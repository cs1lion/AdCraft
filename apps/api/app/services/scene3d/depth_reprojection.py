"""2.5D depth-reprojection orbit renderer (the panorama's first-tier path).

Back-projects an image (plus its depth map) onto a depth-displaced point
cloud, then renders an orbiting virtual camera — the classic "2.5D photo"
move. This is the honest middle tier of the design doc's three-tier answer
(§2.2 of the plan): richer than feeding a flat image to the video model,
cheaper and faster than a full 3D rebuild, and every limitation is visible:

- single-view depth has holes at disocclusions — they are filled with
  edge-aware inpainting and the per-frame hole fraction is REPORTED, never
  silently presented as geometry;
- parallax is bounded by the sweep: ±20° by default, because that is where
  single-image depth stays believable. The caller can ask for more; the
  renderer says how much was holes.

The renderer is pure numpy/cv2 + the project's existing MP4 encoder — no
new dependency, no Blender, no GPU.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.scene3d.depth_estimator import (
    DepthEstimationError,
    _import_cv2,
    estimate_depth_from_image,
)

DEFAULT_NUM_FRAMES = 60
DEFAULT_FPS = 30
DEFAULT_SWEEP_DEGREES = 40.0  # total sweep, ±20° around the forward axis
DEFAULT_ELEVATION_DEGREES = 6.0  # camera rises slightly over the sweep
DEFAULT_DEPTH_NEAR = 0.6  # meters, closest surface
DEFAULT_DEPTH_FAR = 5.0  # meters, farthest surface
DEFAULT_FOV_DEGREES = 60.0
HOLE_WARNING_THRESHOLD = 0.15  # report when >15% of a frame was inpainted


@dataclass
class OrbitRenderResult:
    """Outcome of an orbit render."""

    success: bool
    frames_dir: str | None = None
    frame_count: int = 0
    video_path: str | None = None
    keyframe_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    max_hole_fraction: float = 0.0
    error: str | None = None


def _load_depth_map(depth_path: str | Path) -> Any:
    cv2 = _import_cv2()
    depth = cv2.imread(str(depth_path), cv2.IMREAD_GRAYSCALE)
    if depth is None:
        raise DepthEstimationError(
            f"Failed to read depth map: {depth_path}", error_type="image_read_error"
        )
    return depth.astype("float32") / 255.0


def _look_at_rotation(eye: Any, target: Any, up_hint: Any) -> Any:
    """Camera-world rotation (world -> camera) for a look-at camera.

    Rows are the camera axes in the OpenCV convention: the camera looks down
    its own +Z and its +Y points DOWN (image rows). So the second row is the
    NEGATED world up — writing the up vector there vertically flips the
    frame. ``right = cross(forward, up)``; the other cross order mirrors.
    """

    import numpy as np

    forward = target - eye
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, up_hint)
    right = right / (np.linalg.norm(right) + 1e-9)
    camera_down = -np.cross(right, forward)  # OpenCV: camera +Y is down
    rotation = np.stack([right, camera_down, forward], axis=0)
    return rotation


def render_depth_orbit(
    image_path: str | Path,
    depth_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    *,
    num_frames: int = DEFAULT_NUM_FRAMES,
    fps: int = DEFAULT_FPS,
    sweep_degrees: float = DEFAULT_SWEEP_DEGREES,
    elevation_degrees: float = DEFAULT_ELEVATION_DEGREES,
    depth_near: float = DEFAULT_DEPTH_NEAR,
    depth_far: float = DEFAULT_DEPTH_FAR,
    fov_degrees: float = DEFAULT_FOV_DEGREES,
    encode_video: bool = True,
    depth_model_type: str = "DPT_Hybrid",
) -> OrbitRenderResult:
    """Render an orbiting virtual camera over an image + depth pair.

    Args:
        image_path: The source image (typically a panorama crop or photo).
        depth_path: Grayscale depth map (near=bright). When omitted, MiDaS
            estimates it from the image (needs torch).
        num_frames: Frames in the orbit.
        sweep_degrees: Total horizontal sweep.
        elevation_degrees: Vertical rise across the sweep.
        depth_near/far: Metric range the normalized depth maps onto.
        encode_video: Encode the PNG sequence to MP4 (needs ffmpeg).
    """

    import math

    import numpy as np

    cv2 = _import_cv2()

    image = cv2.imread(str(image_path))
    if image is None:
        raise DepthEstimationError(
            f"Failed to read image: {image_path}", error_type="image_read_error"
        )
    height, width = image.shape[:2]

    depth_source = depth_path
    temp_depth_dir: Path | None = None
    if depth_source is None:
        temp_depth_dir = Path(__import__("tempfile").mkdtemp(prefix="orbit_depth_"))
        try:
            depth_result = estimate_depth_from_image(
                image_path, output_dir=temp_depth_dir, model_type=depth_model_type
            )
            depth_source = depth_result.output_video_path
        except DepthEstimationError:
            raise
        except Exception as exc:  # noqa: BLE001 - coded fail-closed.
            raise DepthEstimationError(
                f"Depth estimation for the orbit failed: {str(exc)[:200]}",
                error_type="depth_estimation_failed",
            ) from exc
    depth = _load_depth_map(depth_source)
    if depth.shape[:2] != (height, width):
        depth = cv2.resize(depth, (width, height), interpolation=cv2.INTER_LINEAR)

    # --- Back-project to a point cloud --------------------------------------
    z = depth_near + depth * (depth_far - depth_near)
    fov_x = math.radians(fov_degrees)
    focal = (width / 2.0) / math.tan(fov_x / 2.0)
    cx, cy = width / 2.0, height / 2.0

    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype="float32"), np.arange(height, dtype="float32")
    )
    points = np.stack(
        [
            (grid_x - cx) / focal * z,
            (grid_y - cy) / focal * z,
            z,
        ],
        axis=-1,
    ).reshape(-1, 3)
    colors = image.reshape(-1, 3).astype("float32")

    # The focal point: the cloud point behind the image center. The camera
    # orbits around it on the sphere through the ORIGINAL camera position
    # (the origin), so at sweep angle 0 the warp is the identity and the
    # focal point keeps its exact projected size across the sweep.
    center_index = (height // 2) * width + (width // 2)
    focal_point = points[center_index].copy()
    radius = max(0.8, float(np.linalg.norm(focal_point)))  # == distance origin->focal point

    if output_dir is None:
        output_dir = Path(__import__("tempfile").mkdtemp(prefix="depth_orbit_"))
    else:
        output_dir = Path(output_dir)
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    sweep = math.radians(sweep_degrees)
    elevation = math.radians(elevation_degrees)
    # World up is -Y (the back-projection's Y axis points down with image rows).
    up_hint = np.array([0.0, -1.0, 0.0], dtype="float32")
    keyframe_indices = (
        {0, num_frames // 2, num_frames - 1} if num_frames > 2 else {0}
    )
    warnings: list[str] = []
    max_hole_fraction = 0.0

    for frame_index in range(num_frames):
        t = num_frames - 1 if num_frames == 1 else frame_index / (num_frames - 1)
        angle = -sweep / 2.0 + sweep * t
        elevation_now = -elevation / 2.0 + elevation * t

        # Orbit on the sphere of radius `radius` around the focal point,
        # starting at the original camera (the origin) when angle == 0.
        eye = focal_point + radius * np.array(
            [
                math.sin(angle) * math.cos(elevation_now),
                -math.sin(elevation_now),
                -math.cos(angle) * math.cos(elevation_now),
            ],
            dtype="float32",
        )
        rotation = _look_at_rotation(eye, focal_point, up_hint)

        camera_points = (points - eye) @ rotation.T
        depth_cam = camera_points[:, 2]
        valid = depth_cam > 0.1

        uv = np.stack(
            [
                focal * camera_points[:, 0] / np.maximum(depth_cam, 1e-6) + cx,
                focal * camera_points[:, 1] / np.maximum(depth_cam, 1e-6) + cy,
            ],
            axis=-1,
        )

        frame = np.zeros((height, width, 3), dtype="float32")
        mask = np.zeros((height, width), dtype="uint8")

        sel = np.where(valid)[0]
        if sel.size:
            ui = np.round(uv[sel, 0]).astype(int)
            vi = np.round(uv[sel, 1]).astype(int)
            inb = (ui >= 0) & (ui < width) & (vi >= 0) & (vi < height)
            sel = sel[inb]
            ui = ui[inb]
            vi = vi[inb]
            # Far-to-near splat: nearer points overwrite (a z-buffer by sort).
            order = np.argsort(-depth_cam[sel])
            sel = sel[order]
            ui = ui[order]
            vi = vi[order]
            frame[vi, ui] = colors[sel]
            mask[vi, ui] = 255

        hole_fraction = 1.0 - float(mask.mean() / 255.0)
        max_hole_fraction = max(max_hole_fraction, hole_fraction)
        if hole_fraction > HOLE_WARNING_THRESHOLD:
            warnings.append(
                f"frame {frame_index}: {hole_fraction:.0%} disocclusion filled by inpainting"
            )

        if hole_fraction > 0:
            frame_u8 = np.clip(frame, 0, 255).astype("uint8")
            fill_mask = 255 - mask
            frame_u8 = cv2.inpaint(frame_u8, fill_mask, 3, cv2.INPAINT_TELEA)
        else:
            frame_u8 = np.clip(frame, 0, 255).astype("uint8")

        frame_path = frames_dir / f"frame_{frame_index:04d}.png"
        cv2.imwrite(str(frame_path), frame_u8)
        del frame, frame_u8, camera_points, uv
        if frame_index in keyframe_indices:
            # keyframes are written once more under a stable name for review
            keyframe_path = frames_dir / f"keyframe_{frame_index:04d}.png"
            keyframe_path.write_bytes(frame_path.read_bytes())

    result = OrbitRenderResult(
        success=True,
        frames_dir=str(frames_dir),
        frame_count=num_frames,
        warnings=warnings,
        max_hole_fraction=max_hole_fraction,
    )

    if encode_video:
        from app.services.scene3d.encoder import encode_png_sequence

        video_path = output_dir / "orbit.mp4"
        encoded = encode_png_sequence(str(frames_dir), str(video_path), fps=fps)
        if getattr(encoded, "success", False):
            result.video_path = str(video_path)
        else:
            result.warnings.append(
                f"orbit video could not be encoded: {getattr(encoded, 'error', 'unknown')}"
            )
    return result
