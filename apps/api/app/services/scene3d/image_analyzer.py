"""Image analyzer: convert user-dropped images into SceneScript.

Single or multiple images -> multimodal LLM analysis -> validated SceneScript.
This is the image counterpart of ``reference_video_analyzer`` (video ->
SceneScript): it powers the "drop an image in, get an editable 3D blockout"
path of the 3D director workbench.

Panorama support: an equirectangular panorama is detected by its ~2:1 aspect
ratio and sliced into six cubic faces (4 horizontal + top + bottom) before
analysis, so the LLM reads undistorted perspective views instead of a
stretched strip. Faces are labelled with their direction so the synthesized
SceneScript keeps a consistent orientation.

The analyzer is model-agnostic: it calls any OpenAI-compatible chat/completions
endpoint that supports image_url content parts (same contract as the video
analyzer). LLM configuration comes from ``LLM_API_KEY`` / ``LLM_BASE_URL``;
when absent the caller gets an ``AnalysisError`` with ``error_type=
"configuration"`` — never a silent failure (engineering standard §4).

See: docs/plans/3d-workbench-and-pipeline-completion.md §3 (Q2).
"""

from __future__ import annotations

import math
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.reference_video_analyzer import (
    _call_multimodal_llm,
    _extract_json_from_response,
    _FRAME_ANALYSIS_SYSTEM_PROMPT,
    _normalize_scene_script_data,
    AnalysisSummary,
    FrameAnalysis,
    FrameCharacter,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_DURATION_SECONDS = 6.0
"""Default scene duration for image-derived blockouts (video models' sweet spot)."""

DEFAULT_FPS = 30
"""Frames per second for image-derived SceneScripts (ADR 0005 convention)."""

MAX_IMAGES = 6
"""Hard cap on user images per call; a panorama consumes this budget alone (6 faces)."""

MAX_FILE_SIZE_MB = 20

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

PANORAMA_MIN_WIDTH = 1024
"""Below this an equirect slice would be too small for the LLM to read."""

PANORAMA_ASPECT_MIN = 1.9
PANORAMA_ASPECT_MAX = 2.1
"""Equirectangular panoramas are 2:1; this band absorbs JPEG/PNG rounding."""

DEFAULT_FACE_SIZE = 512
"""Edge length of each cubemap face sent to the LLM."""

# Cubemap faces in a fixed order; direction labels are passed to the LLM so
# the synthesized SceneScript orients walls/doors consistently across faces.
# Each face is a natural upright 90° view: horizontal faces have +Y up, and
# the direction is what the viewer looks TOWARD (px = looking toward +X).
CUBEMAP_FACES: tuple[tuple[str, str], ...] = (
    ("px", "looking toward +X (from the west side)"),
    ("nx", "looking toward -X (from the east side)"),
    ("pz", "looking toward +Z (scene north/back)"),
    ("nz", "looking toward -Z (scene south/front, toward the default camera)"),
    ("py", "looking straight down from above (+Y); image top is -Z (north)"),
    ("ny", "looking straight up from below (-Y); image top is +Z (south)"),
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PanoramaInfo:
    """Panorama detection result for one image."""

    width: int
    height: int
    is_panorama: bool


@dataclass
class ImageAnalysisResult:
    """Complete result of analyzing reference images."""

    scene_script: SceneScriptRoot
    scene_script_dict: dict[str, Any]
    image_analyses: list[FrameAnalysis]
    summary: AnalysisSummary
    image_paths: list[str]
    analyzed_image_paths: list[str]
    panorama_image_indices: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    user_description: str | None = None


class AnalysisError(Exception):
    """Raised when image analysis fails."""

    def __init__(self, message: str, error_type: str = "analysis"):
        super().__init__(message)
        self.error_type = error_type


# ---------------------------------------------------------------------------
# Lazy imports (mirror the depth estimator: import heavy deps on demand)
# ---------------------------------------------------------------------------

_cv2 = None


def _import_cv2():
    """Lazy import opencv."""
    global _cv2
    if _cv2 is None:
        try:
            import cv2

            _cv2 = cv2
        except ImportError as e:
            raise AnalysisError(
                "OpenCV is not installed. Install with: uv pip install opencv-python",
                error_type="missing_dependency",
            ) from e
    return _cv2


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------


def _build_llm_client():
    """Build an httpx client and return (client, base_url, api_key, model)."""
    import httpx

    from app.core.config import get_settings

    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_base_url:
        raise AnalysisError(
            "LLM not configured: set LLM_API_KEY and LLM_BASE_URL",
            error_type="configuration",
        )
    model = settings.llm_scene_model or settings.llm_front_desk_model
    client = httpx.Client(timeout=120)
    return client, settings.llm_base_url, settings.llm_api_key, model


def _image_to_data_uri(image_path: Path) -> str:
    """Read an image file and return a base64 data URI."""
    import base64

    img_bytes = image_path.read_bytes()
    img_b64 = base64.b64encode(img_bytes).decode()
    ext = image_path.suffix.lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    return f"data:image/{ext};base64,{img_b64}"


# ---------------------------------------------------------------------------
# Panorama detection + equirectangular slicing
# ---------------------------------------------------------------------------


def detect_panorama(image_path: str | Path) -> PanoramaInfo:
    """Detect whether an image is an equirectangular panorama (~2:1 aspect)."""
    cv2 = _import_cv2()
    image = cv2.imread(str(image_path))
    if image is None:
        raise AnalysisError(
            f"Failed to read image: {image_path}",
            error_type="image_read_error",
        )
    height, width = image.shape[:2]
    is_panorama = (
        width >= PANORAMA_MIN_WIDTH
        and height > 0
        and PANORAMA_ASPECT_MIN <= (width / height) <= PANORAMA_ASPECT_MAX
    )
    return PanoramaInfo(width=width, height=height, is_panorama=is_panorama)


def crop_equirect_faces(
    image_path: str | Path,
    output_dir: str | Path,
    face_size: int = DEFAULT_FACE_SIZE,
) -> dict[str, str]:
    """Slice an equirectangular panorama into 6 perspective cubemap faces.

    Pure inverse spherical mapping with bilinear sampling (no ffmpeg needed):
    for each output pixel of each face, compute its 3D direction, project to
    spherical coordinates, and sample the source panorama.

    Returns a mapping of face key (``px``/``nx``/``pz``/``nz``/``py``/``ny``)
    to the saved PNG path.
    """
    cv2 = _import_cv2()
    np = _numpy()
    image = cv2.imread(str(image_path))
    if image is None:
        raise AnalysisError(
            f"Failed to read panorama: {image_path}",
            error_type="image_read_error",
        )
    src_height, src_width = image.shape[:2]

    # Output pixel grid in [-1, 1]; v is +1 at the TOP row so every face has
    # a natural upright orientation (horizontal faces: +Y up).
    u = (np.arange(face_size, dtype=np.float32) + 0.5) / face_size * 2.0 - 1.0
    v = -((np.arange(face_size, dtype=np.float32) + 0.5) / face_size * 2.0 - 1.0)
    uu, vv = np.meshgrid(u, v)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    faces: dict[str, str] = {}
    for face_key, _label in CUBEMAP_FACES:
        # Face direction for each output pixel: f + a*right + b*up, where
        # right/up follow the natural camera orientation for that face and
        # (a, b) = (u, v) with v=+1 at the top of the image:
        #   px: ( 1,  v,  u)   nx: (-1,  v, -u)
        #   pz: (-u,  v,  1)   nz: ( u,  v, -1)
        #   py: (-u,  1, -v)   ny: (-u, -1,  v)
        if face_key == "px":
            dx, dy, dz = np.ones_like(uu), vv, uu
        elif face_key == "nx":
            dx, dy, dz = -np.ones_like(uu), vv, -uu
        elif face_key == "py":
            dx, dy, dz = -uu, np.ones_like(uu), -vv
        elif face_key == "ny":
            dx, dy, dz = -uu, -np.ones_like(uu), vv
        elif face_key == "pz":
            dx, dy, dz = -uu, vv, np.ones_like(uu)
        else:  # nz
            dx, dy, dz = uu, vv, -np.ones_like(uu)

        # Spherical projection onto the equirectangular image.
        lon = np.arctan2(dx, dz)  # [-pi, pi]
        lat = np.arcsin(np.clip(dy / np.sqrt(dx * dx + dy * dy + dz * dz), -1.0, 1.0))

        map_x = ((lon / (2.0 * math.pi)) + 0.5) * src_width
        map_y = (0.5 - lat / math.pi) * src_height
        map_x = np.clip(map_x, 0, src_width - 1).astype(np.float32)
        map_y = np.clip(map_y, 0, src_height - 1).astype(np.float32)

        face = cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
        face_path = output_dir / f"face_{face_key}_{uuid.uuid4().hex[:8]}.png"
        cv2.imwrite(str(face_path), face)
        faces[face_key] = str(face_path)
    return faces


def _numpy():
    import numpy as np

    return np


# ---------------------------------------------------------------------------
# Frame / image analysis
# ---------------------------------------------------------------------------


def _analyze_image(
    *,
    client,
    base_url: str,
    api_key: str,
    model: str,
    image_path: Path,
    image_index: int,
    total_images: int,
    direction_label: str | None = None,
) -> FrameAnalysis:
    """Analyze a single image (or cubemap face) with the multimodal LLM.

    Reuses the video analyzer's frame-analysis contract: one structured JSON
    per image (scene/lighting/camera/characters/props). A ``direction_label``
    is appended for cubemap faces so the synthesizer can orient the blockout.
    """
    user_text = (
        f"This is image {image_index + 1} of {total_images} "
        f"showing the same scene"
        + (f" from the {direction_label}" if direction_label else "")
        + ". Analyze it and output the structured JSON."
    )
    raw = _call_multimodal_llm(
        client=client,
        base_url=base_url,
        api_key=api_key,
        model=model,
        system_prompt=_FRAME_ANALYSIS_SYSTEM_PROMPT,
        user_text=user_text,
        image_path=image_path,
        max_tokens=800,
    )
    data = _extract_json_from_response(raw)

    characters = [
        FrameCharacter(
            description=c.get("description", ""),
            position_hint=c.get("position_hint", ""),
            action=c.get("action", "standing"),
            facing=c.get("facing", ""),
        )
        for c in data.get("characters", [])
    ]

    return FrameAnalysis(
        frame_index=image_index,
        timestamp_seconds=0.0,
        scene_type=data.get("scene_type", "indoor"),
        environment_description=data.get("environment_description", ""),
        lighting=data.get("lighting", "neutral"),
        camera_angle=data.get("camera_angle", "eye-level"),
        shot_size=data.get("shot_size", "wide"),
        camera_motion_hint=data.get("camera_motion_hint", "static"),
        characters=characters,
        props=data.get("props", []),
        notable_elements=data.get("notable_elements", ""),
    )


# ---------------------------------------------------------------------------
# SceneScript synthesis
# ---------------------------------------------------------------------------


_IMAGE_SCENE_SCRIPT_SYSTEM_PROMPT = """You are a 3D previs artist and cinematographer.
Given analysis of one or more images showing the SAME scene, synthesize a valid SceneScript
JSON that recreates the scene's spatial layout as a low-fidelity blockout.

This is a STATIC reconstruction: the images have no motion. Do NOT invent character or
camera movement. Create ONE sensible default camera at eye level (position z ~ 1.5-1.7m)
framing the whole scene (wide/medium), looking at the scene center. Characters get a
SINGLE keyframe at frame 0 placed according to their image position.

SceneScript schema (you MUST output exactly this structure):
{
  "scene": {"name": "descriptive name", "environment": "indoor|outdoor|mixed", "lighting": "warm|cool|neutral|dramatic|soft|hard", "duration": <seconds>, "frame_rate": 30},
  "characters": [
    {"id": "char_id", "type": "lowpoly_human", "character_asset_id": null, "appearance": {"color": "#RRGGBB", "height": 1.7, "scale": 1.0}, "keyframes": [{"frame": 0, "position": [x, y, z], "rotation_y": 0, "action": "stand|talk|walk|sit|gesture"}]}
  ],
  "props": [
    {"id": "prop_id", "type": "round_table|rect_table|chair|stool|lantern|box|crate|vase|weapon|scroll|book|cup", "prop_asset_id": null, "position": [x, y, z], "scale": 1.0, "rotation_y": 0}
  ],
  "environment": [
    {"id": "env_id", "type": "wall|pillar|floor|gable_roof|flat_roof|door|window|stairs|platform|tree|rock|fence|ground", "scene_asset_id": null, "position": [x, y, z], "scale": 1.0, "rotation_y": 0}
  ],
  "cameras": [
    {"id": "cam_id", "shot_type": "wide|medium|closeup|over_shoulder|pov", "keyframes": [{"frame": 0, "position": [x, y, z], "look_at": [x, y, z]}]}
  ],
  "shots": [
    {"id": "shot_id", "camera": "cam_id", "start_frame": 0, "end_frame": <last_frame>, "description": "description of the shot"}
  ],
  "speech_bindings": []
}

Coordinate system: X = right, Y = forward (away from default camera), Z = up. 1 unit = 1 meter.
Characters are ~1.7m tall. Camera look_at should target character heads (~z=1.5).
Use distinct colors for each character (e.g. #E74C3C red, #3498DB blue, #2ECC71 green).
Frame number = seconds * 30. Total frames = duration * 30.
Prioritize ENVIRONMENT objects (walls, floor, doors, pillars) to establish the space,
then large props, then characters. Keep it simple: <=5 characters, <=8 props,
<=8 environment objects, 1 camera, 1 shot.

IMPORTANT: "scale" is ALWAYS a single number (e.g. 1.0, 1.5, 2.0), NEVER an array like [1,1,1].
"position" is ALWAYS a 3-element array [x, y, z]. "rotation_y" is ALWAYS a single number in degrees.
"appearance.scale" is also a single number.

Output ONLY the JSON object. No prose, no explanations, no markdown outside the JSON."""


def _build_image_scene_script_user_prompt(
    analyses: list[tuple[FrameAnalysis, str | None]],
    duration_seconds: float,
    scene_name: str | None,
    user_description: str | None,
) -> str:
    """Build the user prompt for SceneScript synthesis from image analyses."""
    lines = []
    lines.append(f"Target scene duration: {duration_seconds:.1f}s at 30 fps.")
    if scene_name:
        lines.append(f"Scene name: {scene_name}")
    if user_description:
        lines.append(f"User description: {user_description}")
    lines.append("")
    lines.append("=== Image-by-image analysis ===")
    for i, (analysis, direction_label) in enumerate(analyses):
        label = f" [view direction: {direction_label}]" if direction_label else ""
        lines.append(f"--- Image {i + 1}{label} ---")
        lines.append(f"  Scene: {analysis.scene_type}, {analysis.environment_description}")
        lines.append(f"  Lighting: {analysis.lighting}, Camera view: {analysis.camera_angle} {analysis.shot_size}")
        if analysis.characters:
            for j, c in enumerate(analysis.characters):
                lines.append(
                    f"  Character {j + 1}: {c.description} | pos: {c.position_hint} "
                    f"| action: {c.action} | facing: {c.facing}"
                )
        else:
            lines.append("  Characters: none")
        if analysis.props:
            lines.append(f"  Props: {', '.join(analysis.props)}")
        if analysis.notable_elements:
            lines.append(f"  Notable: {analysis.notable_elements}")
        lines.append("")

    lines.append(
        "Based on these views, synthesize ONE SceneScript JSON. When multiple images of the "
        "same scene are provided, reconcile them into a single consistent layout (the same "
        "wall must not appear twice)."
    )
    return "\n".join(lines)


def _synthesize_image_scene_script(
    client,
    base_url: str,
    api_key: str,
    model: str,
    analyses: list[tuple[FrameAnalysis, str | None]],
    duration_seconds: float,
    scene_name: str | None,
    user_description: str | None,
) -> tuple[SceneScriptRoot, dict[str, Any]]:
    """Synthesize a SceneScript from image analyses using the LLM."""
    user_prompt = _build_image_scene_script_user_prompt(
        analyses=analyses,
        duration_seconds=duration_seconds,
        scene_name=scene_name,
        user_description=user_description,
    )
    raw = _call_multimodal_llm(
        client=client,
        base_url=base_url,
        api_key=api_key,
        model=model,
        system_prompt=_IMAGE_SCENE_SCRIPT_SYSTEM_PROMPT,
        user_text=user_prompt,
        image_path=None,  # synthesis is text-only; analyses carry the image content
        max_tokens=2000,
    )
    data = _extract_json_from_response(raw)
    data = _normalize_scene_script_data(data)

    # Enforce the requested duration/shots even when the LLM drifts.
    if isinstance(data.get("scene"), dict):
        data["scene"]["duration"] = duration_seconds
        data["scene"]["frame_rate"] = DEFAULT_FPS
    total_frames = max(1, round(duration_seconds * DEFAULT_FPS))
    if isinstance(data.get("shots"), list) and data["shots"]:
        data["shots"][0]["start_frame"] = 0
        data["shots"][0]["end_frame"] = total_frames - 1
        if len(data["shots"]) > 1:
            # A static image-derived blockout has exactly one shot by contract.
            data["shots"] = data["shots"][:1]

    try:
        scene_script = SceneScriptRoot.model_validate(data)
    except Exception as e:
        raise AnalysisError(
            f"Generated SceneScript failed schema validation: {str(e)[:300]}",
            error_type="schema_validation",
        ) from e

    return scene_script, data


def _build_image_summary(
    analyses: list[FrameAnalysis],
    duration_seconds: float,
) -> AnalysisSummary:
    """Build a human-readable summary from image analyses (no LLM call)."""
    if analyses:
        first = analyses[0]
        scene_overview = f"{first.scene_type} scene: {first.environment_description}"
    else:
        scene_overview = "Unknown scene"

    character_descriptions: list[str] = []
    for analysis in analyses:
        for c in analysis.characters:
            if c.description not in character_descriptions:
                character_descriptions.append(c.description)
    if character_descriptions:
        characters_summary = (
            f"{len(character_descriptions)} distinct character(s): "
            + "; ".join(character_descriptions[:5])
        )
    else:
        characters_summary = "No characters detected"

    return AnalysisSummary(
        scene_overview=scene_overview,
        characters_summary=characters_summary,
        camera_movement_summary="Static scene reconstructed from images (no motion inferred)",
        action_timeline="static blockout",
        inferred_duration_seconds=duration_seconds,
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_image_paths(image_paths: list[str | Path]) -> list[Path]:
    if not image_paths:
        raise AnalysisError("No images provided", error_type="input")
    if len(image_paths) > MAX_IMAGES:
        raise AnalysisError(
            f"Too many images: {len(image_paths)} (max {MAX_IMAGES})",
            error_type="input",
        )
    resolved: list[Path] = []
    for raw in image_paths:
        path = Path(raw)
        if not path.exists():
            raise AnalysisError(f"Image file not found: {path}", error_type="input")
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise AnalysisError(
                f"Unsupported image format '{path.suffix}'. Allowed: "
                + ", ".join(sorted(ALLOWED_EXTENSIONS)),
                error_type="invalid_format",
            )
        if path.stat().st_size == 0:
            raise AnalysisError(f"Image file is empty: {path}", error_type="invalid_size")
        if path.stat().st_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            raise AnalysisError(
                f"Image too large: {path.stat().st_size / (1024 * 1024):.1f} MB (max {MAX_FILE_SIZE_MB} MB)",
                error_type="invalid_size",
            )
        resolved.append(path)
    return resolved


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze_images(
    image_paths: list[str | Path],
    user_description: str | None = None,
    scene_name: str | None = None,
    duration_seconds: float = DEFAULT_DURATION_SECONDS,
    panorama: bool | None = None,
    output_dir: str | Path | None = None,
) -> ImageAnalysisResult:
    """Analyze reference images and generate a SceneScript blockout.

    Args:
        image_paths: 1..MAX_IMAGES image files of the same scene.
        user_description: Optional user description to guide analysis.
        scene_name: Optional name for the generated scene.
        duration_seconds: Scene duration for the static blockout (default 6s).
        panorama: Force panorama slicing on/off; None = auto-detect by aspect.
        output_dir: Where to write cubemap faces. Defaults to a temp dir.

    Returns:
        ImageAnalysisResult with SceneScript, per-image analyses, and summary.

    Raises:
        AnalysisError: If analysis fails at any stage (fail closed, never silent).
    """
    paths = _validate_image_paths(image_paths)
    if duration_seconds <= 0 or duration_seconds > 600:
        raise AnalysisError(
            f"duration_seconds must be in (0, 600], got {duration_seconds}",
            error_type="input",
        )

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="image_analysis_"))
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    panorama_image_indices: list[int] = []

    # Stage 1: preprocessing — detect/slice panoramas into cubemap faces.
    # analyses holds (FrameAnalysis, direction_label) pairs; labels stay None
    # for ordinary images.
    prepared: list[tuple[Path, str | None, int]] = []  # (path, direction_label, image_index)
    for index, path in enumerate(paths):
        info = detect_panorama(path)
        if panorama is None:
            treat_as_panorama = info.is_panorama
        elif panorama:
            # Explicit hint: slicing a non-equirectangular image produces
            # garbage faces, so the hint is ignored with a warning.
            treat_as_panorama = info.is_panorama
            if not info.is_panorama:
                warnings.append(
                    f"panorama_hint_ignored: image {index + 1} "
                    f"({info.width}x{info.height}) does not look equirectangular; analyzed whole"
                )
        else:
            # Explicit opt-out overrides auto-detection (observable, §4).
            treat_as_panorama = False
            if info.is_panorama:
                warnings.append(
                    f"panorama_slicing_disabled_by_hint: image {index + 1} analyzed whole"
                )
        if not treat_as_panorama:
            prepared.append((path, None, index))
            continue

        panorama_image_indices.append(index)
        try:
            faces = crop_equirect_faces(path, output_dir / f"pano_{index}")
            ordered = [faces[key] for key, _ in CUBEMAP_FACES]
            labels = [label for _, label in CUBEMAP_FACES]
            for face_path, label in zip(ordered, labels):
                prepared.append((Path(face_path), label, index))
            warnings.append(
                f"panorama_sliced_to_cubemap: image {index + 1} ({info.width}x{info.height}) "
                f"sliced into {len(ordered)} faces"
            )
        except Exception as e:  # degrade with a warning, never fail closed here
            warnings.append(
                f"panorama_slice_failed: image {index + 1} analyzed whole "
                f"({str(e)[:100]}); stretched edges may reduce quality"
            )
            prepared.append((path, None, index))

    if not prepared:
        raise AnalysisError("No analyzable images after preprocessing", error_type="input")

    # Stage 2+3: analyze each image, then synthesize one SceneScript.
    client, base_url, api_key, model = _build_llm_client()
    try:
        analyses: list[FrameAnalysis] = []
        labels: list[str | None] = []
        for path, direction_label, _index in prepared:
            analyses.append(
                _analyze_image(
                    client=client,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    image_path=path,
                    image_index=len(analyses),
                    total_images=len(prepared),
                    direction_label=direction_label,
                )
            )
            labels.append(direction_label)

        scene_script, scene_script_dict = _synthesize_image_scene_script(
            client=client,
            base_url=base_url,
            api_key=api_key,
            model=model,
            analyses=list(zip(analyses, labels)),
            duration_seconds=duration_seconds,
            scene_name=scene_name,
            user_description=user_description,
        )

        summary = _build_image_summary(analyses, duration_seconds)
    finally:
        client.close()

    return ImageAnalysisResult(
        scene_script=scene_script,
        scene_script_dict=scene_script_dict,
        image_analyses=analyses,
        summary=summary,
        image_paths=[str(p) for p in paths],
        analyzed_image_paths=[str(p) for p, _label, _idx in prepared],
        panorama_image_indices=panorama_image_indices,
        warnings=warnings,
        user_description=user_description,
    )
