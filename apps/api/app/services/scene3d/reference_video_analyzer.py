"""Reference video analyzer: convert user-uploaded video into SceneScript.

Uses a multimodal LLM to analyze extracted keyframes (scene, characters,
actions, camera, props), then synthesizes a valid SceneScript JSON that can
be rendered by the Blender previs pipeline.

This implements the "upload reference video -> 3D previs" path:
  user video -> extract frames -> multimodal LLM analysis -> SceneScript -> Blender render

The analyzer is model-agnostic: it calls any OpenAI-compatible chat/completions
endpoint that supports image_url content parts (verified with agnes-3.0-flash).

See: docs/adr/0005-3d-low-fidelity-previs.md (reference video as previs source)
"""

from __future__ import annotations

import base64
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.reference_upload import (
    VideoMetadata,
    extract_keyframes_from_video,
    extract_metadata,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_NUM_FRAMES = 6
"""Number of evenly-spaced frames to extract and analyze."""

DEFAULT_LLM_TIMEOUT_SECONDS = 120
"""Per-call timeout for LLM requests."""

DEFAULT_MAX_TOKENS_FRAME_ANALYSIS = 800
DEFAULT_MAX_TOKENS_SCENE_SCRIPT = 2000


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameCharacter:
    """A character detected in one frame."""
    description: str
    position_hint: str  # e.g. "left foreground", "center", "right background"
    action: str  # e.g. "walking", "sitting", "standing", "gesturing"
    facing: str  # e.g. "toward camera", "away", "left"


@dataclass(frozen=True)
class FrameAnalysis:
    """Structured analysis of a single video frame."""
    frame_index: int
    timestamp_seconds: float
    scene_type: str  # indoor / outdoor / mixed
    environment_description: str
    lighting: str  # warm / cool / neutral / dramatic / soft / hard
    camera_angle: str  # high-angle / eye-level / low-angle
    shot_size: str  # wide / medium / closeup / over_shoulder / pov
    camera_motion_hint: str  # static / pushing_in / pulling_out / tracking / orbiting
    characters: list[FrameCharacter]
    props: list[str]
    notable_elements: str


@dataclass(frozen=True)
class AnalysisSummary:
    """Human-readable summary of the full video analysis."""
    scene_overview: str
    characters_summary: str
    camera_movement_summary: str
    action_timeline: str
    inferred_duration_seconds: float


@dataclass(frozen=True)
class ReferenceVideoAnalysisResult:
    """Complete result of analyzing a reference video."""
    scene_script: SceneScriptRoot
    scene_script_dict: dict[str, Any]
    frame_analyses: list[FrameAnalysis]
    summary: AnalysisSummary
    video_metadata: VideoMetadata
    num_frames_analyzed: int
    user_description: str | None = None


class AnalysisError(Exception):
    """Raised when reference video analysis fails."""
    def __init__(self, message: str, error_type: str = "analysis"):
        super().__init__(message)
        self.error_type = error_type


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------


def _build_llm_client() -> tuple[httpx.Client, str, str, str]:
    """Build an httpx client and return (client, base_url, api_key, model)."""
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_base_url:
        raise AnalysisError(
            "LLM not configured: set LLM_API_KEY and LLM_BASE_URL",
            error_type="configuration",
        )
    model = settings.llm_scene_model or settings.llm_front_desk_model
    client = httpx.Client(timeout=DEFAULT_LLM_TIMEOUT_SECONDS)
    return client, settings.llm_base_url, settings.llm_api_key, model


def _image_to_data_uri(image_path: Path) -> str:
    """Read an image file and return a base64 data URI."""
    img_bytes = image_path.read_bytes()
    img_b64 = base64.b64encode(img_bytes).decode()
    ext = image_path.suffix.lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    return f"data:image/{ext};base64,{img_b64}"


def _call_multimodal_llm(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_text: str,
    image_path: Path | None = None,
    max_tokens: int = 1000,
    extra_payload: dict[str, Any] | None = None,
) -> str:
    """Call a multimodal LLM with optional image input. Returns text content.

    ``extra_payload``: 额外的请求体选项（OpenAI 兼容参数，如
    ``reasoning_effort``）——推理型模型默认会把 max_tokens 花在思考上，
    导致 content 为空；调用方按需降推理档位。
    """
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    if image_path is not None:
        content.append({
            "type": "image_url",
            "image_url": {"url": _image_to_data_uri(image_path)},
        })

    resp = client.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            **(extra_payload or {}),
        },
    )
    if resp.status_code != 200:
        raise AnalysisError(
            f"LLM call failed ({resp.status_code}): {resp.text[:200]}",
            error_type="llm_error",
        )
    data = resp.json()
    if "choices" not in data or not data["choices"]:
        raise AnalysisError(
            f"LLM returned no choices: {json.dumps(data, ensure_ascii=False)[:200]}",
            error_type="llm_error",
        )
    text = data["choices"][0]["message"]["content"] or ""
    if not text.strip():
        # 推理型模型可能把预算花光在思考上（content 为空）：显式失败并提示
        raise AnalysisError(
            "LLM returned empty content (reasoning consumed the token budget; "
            "lower reasoning_effort or raise max_tokens)",
            error_type="llm_error",
        )
    return text


def _extract_json_from_response(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM response text (handles markdown code fences)."""
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try to find JSON in markdown code fence
    for fence in ("```json", "```"):
        if fence in text:
            start = text.find(fence) + len(fence)
            end = text.find("```", start)
            if end > start:
                candidate = text[start:end].strip()
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
    # Try to find first { and last }
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        candidate = text[brace_start:brace_end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    raise AnalysisError(
        f"Failed to extract JSON from LLM response: {text[:200]}",
        error_type="json_parse",
    )


# ---------------------------------------------------------------------------
# Frame analysis
# ---------------------------------------------------------------------------

_FRAME_ANALYSIS_SYSTEM_PROMPT = """You are a professional cinematographer and 3D previs artist.
Analyze a single frame from a reference video and describe it in structured JSON.
Be precise and objective. Describe what you actually see, not what you imagine.

IMPORTANT: This may be a 3D low-fidelity previs (previsualization) video where characters
are represented as simple colored geometric shapes — typically a colored cube/box for the body
and a sphere for the head. If you see colored geometric shapes that could represent human figures
(e.g. a colored box with a sphere on top, or two colored shapes moving together), identify them
as characters even if they look abstract. Describe their color, position, and apparent action.

Also note: this may be a real video with actual people. Identify people normally in that case.

Output ONLY a JSON object with these fields:
{
  "scene_type": "indoor|outdoor|mixed",
  "environment_description": "brief description of the space and key architectural elements",
  "lighting": "warm|cool|neutral|dramatic|soft|hard",
  "camera_angle": "high-angle|eye-level|low-angle",
  "shot_size": "wide|medium|closeup|over_shoulder|pov",
  "camera_motion_hint": "static|pushing_in|pulling_out|tracking_left|tracking_right|tracking_forward|orbiting",
  "characters": [
    {"description": "what the person looks like / is wearing", "position_hint": "left foreground|center|right background|etc", "action": "walking|sitting|standing|gesturing|running|entering|exiting", "facing": "toward camera|away|left|right"}
  ],
  "props": ["list of notable objects: table, chair, door, lamp, etc"],
  "notable_elements": "anything else important: door opening, dramatic lighting, spatial depth, etc"
}

If there are no characters, return an empty array. If unsure, make your best guess.
Do not include any text outside the JSON object."""


def _analyze_frame(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    model: str,
    image_path: Path,
    frame_index: int,
    timestamp_seconds: float,
    total_frames: int,
) -> FrameAnalysis:
    """Analyze a single frame using the multimodal LLM."""
    user_text = (
        f"This is frame {frame_index + 1} of {total_frames} "
        f"(timestamp {timestamp_seconds:.2f}s) from a reference video. "
        f"Analyze this frame and output the structured JSON."
    )
    raw = _call_multimodal_llm(
        client=client,
        base_url=base_url,
        api_key=api_key,
        model=model,
        system_prompt=_FRAME_ANALYSIS_SYSTEM_PROMPT,
        user_text=user_text,
        image_path=image_path,
        max_tokens=DEFAULT_MAX_TOKENS_FRAME_ANALYSIS,
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
        frame_index=frame_index,
        timestamp_seconds=timestamp_seconds,
        scene_type=data.get("scene_type", "indoor"),
        environment_description=data.get("environment_description", ""),
        lighting=data.get("lighting", "neutral"),
        camera_angle=data.get("camera_angle", "eye-level"),
        shot_size=data.get("shot_size", "medium"),
        camera_motion_hint=data.get("camera_motion_hint", "static"),
        characters=characters,
        props=data.get("props", []),
        notable_elements=data.get("notable_elements", ""),
    )


# ---------------------------------------------------------------------------
# SceneScript synthesis
# ---------------------------------------------------------------------------

_SCENE_SCRIPT_SYSTEM_PROMPT = """You are a 3D previs artist and cinematographer.
Given frame-by-frame analysis of a reference video, synthesize a valid SceneScript JSON
that recreates the scene's spatial layout, character blocking, camera movement, and timing.

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
    {"id": "shot_id", "camera": "cam_id", "start_frame": 0, "end_frame": <last_frame>, "description": "Chinese description of the shot"}
  ],
  "speech_bindings": []
}

Coordinate system: X = right, Y = forward (away from default camera), Z = up. 1 unit = 1 meter.
Characters are ~1.7m tall. Camera look_at should target character heads (~z=1.5).
Use distinct colors for each character (e.g. #E74C3C red, #3498DB blue, #2ECC71 green).
Moving characters need >=2 keyframes. Camera movement needs >=2 keyframes.
Frame number = seconds * 30. Total frames = duration * 30.
Keep it simple: <=5 characters, <=8 props, <=5 environment objects, 1 camera, 1 shot.

IMPORTANT: "scale" is ALWAYS a single number (e.g. 1.0, 1.5, 2.0), NEVER an array like [1,1,1].
"position" is ALWAYS a 3-element array [x, y, z]. "rotation_y" is ALWAYS a single number in degrees.
"appearance.scale" is also a single number.

Output ONLY the JSON object. No prose, no explanations, no markdown outside the JSON."""


def _build_scene_script_user_prompt(
    frame_analyses: list[FrameAnalysis],
    video_metadata: VideoMetadata,
    user_description: str | None,
) -> str:
    """Build the user prompt for SceneScript synthesis from frame analyses."""
    lines = []
    lines.append(f"Video duration: {video_metadata.duration_seconds:.2f}s")
    lines.append(f"Video resolution: {video_metadata.width}x{video_metadata.height}")
    lines.append(f"Frame rate: {video_metadata.frame_rate:.1f} fps")
    lines.append(f"Frames analyzed: {len(frame_analyses)}")
    lines.append("")

    if user_description:
        lines.append(f"User description: {user_description}")
        lines.append("")

    lines.append("=== Frame-by-frame analysis ===")
    for fa in frame_analyses:
        lines.append(f"--- Frame {fa.frame_index + 1} (t={fa.timestamp_seconds:.2f}s) ---")
        lines.append(f"  Scene: {fa.scene_type}, {fa.environment_description}")
        lines.append(f"  Lighting: {fa.lighting}, Camera: {fa.camera_angle} {fa.shot_size}, Motion: {fa.camera_motion_hint}")
        if fa.characters:
            for i, c in enumerate(fa.characters):
                lines.append(f"  Character {i+1}: {c.description} | pos: {c.position_hint} | action: {c.action} | facing: {c.facing}")
        else:
            lines.append("  Characters: none")
        if fa.props:
            lines.append(f"  Props: {', '.join(fa.props)}")
        if fa.notable_elements:
            lines.append(f"  Notable: {fa.notable_elements}")
        lines.append("")

    lines.append("Based on this analysis, synthesize a SceneScript JSON that recreates the scene.")
    lines.append("Infer character movement trajectories from position changes across frames.")
    lines.append("Infer camera movement from camera_motion_hint and shot_size changes across frames.")
    lines.append("Use the video duration for scene.duration.")
    return "\n".join(lines)


def _synthesize_scene_script(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    model: str,
    frame_analyses: list[FrameAnalysis],
    video_metadata: VideoMetadata,
    user_description: str | None,
) -> tuple[SceneScriptRoot, dict[str, Any]]:
    """Synthesize a SceneScript from frame analyses using the LLM."""
    user_prompt = _build_scene_script_user_prompt(
        frame_analyses=frame_analyses,
        video_metadata=video_metadata,
        user_description=user_description,
    )
    raw = _call_multimodal_llm(
        client=client,
        base_url=base_url,
        api_key=api_key,
        model=model,
        system_prompt=_SCENE_SCRIPT_SYSTEM_PROMPT,
        user_text=user_prompt,
        image_path=None,  # No image for synthesis; frame analyses are text
        max_tokens=DEFAULT_MAX_TOKENS_SCENE_SCRIPT,
    )
    data = _extract_json_from_response(raw)

    # Normalize LLM output (e.g. scale arrays -> single numbers)
    data = _normalize_scene_script_data(data)

    # Validate against schema
    try:
        scene_script = SceneScriptRoot.model_validate(data)
    except Exception as e:
        raise AnalysisError(
            f"Generated SceneScript failed schema validation: {str(e)[:300]}",
            error_type="schema_validation",
        ) from e

    return scene_script, data


def _normalize_scene_script_data(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize LLM-generated SceneScript data to match schema expectations.

    Fixes common LLM mistakes:
    - scale as array [1,1,1] -> single number 1.0
    - appearance.scale as array -> single number
    - rotation_y as array -> single number (first element)
    - position as object -> array [x,y,z]
    """
    def _to_float(value: Any, default: float = 1.0) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, (list, tuple)) and len(value) > 0:
            # If array, use average of non-zero elements, or first element
            nums = [v for v in value if isinstance(v, (int, float))]
            if nums:
                return sum(nums) / len(nums)
        return default

    # Normalize characters
    for char in data.get("characters", []):
        if "appearance" in char and isinstance(char["appearance"], dict):
            char["appearance"]["scale"] = _to_float(char["appearance"].get("scale", 1.0))
            char["appearance"]["height"] = _to_float(char["appearance"].get("height", 1.7), 1.7)
        for kf in char.get("keyframes", []):
            if isinstance(kf.get("rotation_y"), (list, tuple)):
                kf["rotation_y"] = _to_float(kf["rotation_y"], 0.0)

    # Normalize props
    for prop in data.get("props", []):
        prop["scale"] = _to_float(prop.get("scale", 1.0))
        if isinstance(prop.get("rotation_y"), (list, tuple)):
            prop["rotation_y"] = _to_float(prop["rotation_y"], 0.0)

    # Normalize environment
    for env in data.get("environment", []):
        env["scale"] = _to_float(env.get("scale", 1.0))
        if isinstance(env.get("rotation_y"), (list, tuple)):
            env["rotation_y"] = _to_float(env["rotation_y"], 0.0)

    return data


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------


def _build_summary(
    frame_analyses: list[FrameAnalysis],
    video_metadata: VideoMetadata,
) -> AnalysisSummary:
    """Build a human-readable summary from frame analyses (no LLM call)."""
    # Scene overview
    if frame_analyses:
        first = frame_analyses[0]
        scene_overview = f"{first.scene_type} scene: {first.environment_description}"
    else:
        scene_overview = "Unknown scene"

    # Characters summary
    all_char_descriptions: list[str] = []
    for fa in frame_analyses:
        for c in fa.characters:
            if c.description not in all_char_descriptions:
                all_char_descriptions.append(c.description)
    if all_char_descriptions:
        characters_summary = f"{len(all_char_descriptions)} distinct character(s): " + "; ".join(all_char_descriptions[:5])
    else:
        characters_summary = "No characters detected"

    # Camera movement summary
    motions = [fa.camera_motion_hint for fa in frame_analyses if fa.camera_motion_hint != "static"]
    if motions:
        # Count most common
        from collections import Counter
        most_common = Counter(motions).most_common(1)[0][0]
        camera_movement_summary = f"Camera primarily {most_common.replace('_', ' ')} across {len(motions)} of {len(frame_analyses)} frames"
    else:
        camera_movement_summary = "Camera appears mostly static"

    # Action timeline
    timeline_parts = []
    for fa in frame_analyses:
        actions = [c.action for c in fa.characters]
        action_str = ", ".join(set(actions)) if actions else "no character action"
        timeline_parts.append(f"t={fa.timestamp_seconds:.1f}s: {action_str}")
    action_timeline = " | ".join(timeline_parts)

    return AnalysisSummary(
        scene_overview=scene_overview,
        characters_summary=characters_summary,
        camera_movement_summary=camera_movement_summary,
        action_timeline=action_timeline,
        inferred_duration_seconds=video_metadata.duration_seconds,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze_reference_video(
    video_path: str | Path,
    num_frames: int = DEFAULT_NUM_FRAMES,
    user_description: str | None = None,
    output_dir: str | Path | None = None,
) -> ReferenceVideoAnalysisResult:
    """Analyze a reference video and generate a SceneScript.

    Args:
        video_path: Path to the uploaded video file.
        num_frames: Number of evenly-spaced frames to extract and analyze.
        user_description: Optional user-provided description to guide analysis.
        output_dir: Directory to save extracted frames. Defaults to temp dir.

    Returns:
        ReferenceVideoAnalysisResult with SceneScript, frame analyses, and summary.

    Raises:
        AnalysisError: If analysis fails at any stage.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise AnalysisError(f"Video file not found: {video_path}", error_type="input")

    # Extract metadata
    try:
        video_metadata = extract_metadata(video_path)
    except Exception as e:
        raise AnalysisError(f"Failed to extract video metadata: {e}", error_type="metadata") from e

    # Extract frames
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="ref_video_frames_"))
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        frame_paths = extract_keyframes_from_video(
            video_path=video_path,
            output_dir=output_dir,
            num_keyframes=num_frames,
        )
    except Exception as e:
        raise AnalysisError(f"Failed to extract frames: {e}", error_type="frame_extraction") from e

    if not frame_paths:
        raise AnalysisError("No frames extracted from video", error_type="frame_extraction")

    # Calculate timestamps for each frame
    duration = video_metadata.duration_seconds
    timestamps = [
        (duration * i) / (len(frame_paths) - 1) if len(frame_paths) > 1 else 0
        for i in range(len(frame_paths))
    ]

    # Build LLM client
    client, base_url, api_key, model = _build_llm_client()

    try:
        # Analyze each frame
        frame_analyses: list[FrameAnalysis] = []
        for i, (frame_path, ts) in enumerate(zip(frame_paths, timestamps)):
            fa = _analyze_frame(
                client=client,
                base_url=base_url,
                api_key=api_key,
                model=model,
                image_path=Path(frame_path),
                frame_index=i,
                timestamp_seconds=ts,
                total_frames=len(frame_paths),
            )
            frame_analyses.append(fa)

        # Synthesize SceneScript
        scene_script, scene_script_dict = _synthesize_scene_script(
            client=client,
            base_url=base_url,
            api_key=api_key,
            model=model,
            frame_analyses=frame_analyses,
            video_metadata=video_metadata,
            user_description=user_description,
        )

        # Build summary
        summary = _build_summary(frame_analyses, video_metadata)

        return ReferenceVideoAnalysisResult(
            scene_script=scene_script,
            scene_script_dict=scene_script_dict,
            frame_analyses=frame_analyses,
            summary=summary,
            video_metadata=video_metadata,
            num_frames_analyzed=len(frame_analyses),
            user_description=user_description,
        )

    finally:
        client.close()
