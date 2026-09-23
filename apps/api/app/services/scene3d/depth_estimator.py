"""Depth map estimation service for white-model (白模) extraction.

Uses MiDaS (Monocular Depth Estimation) to convert uploaded videos into
depth-map "white model" videos that can be used as 3D previs references.

The depth map visualizes spatial structure: closer objects are brighter,
farther objects are darker. This gives video models a sense of 3D space
and camera movement without requiring actual 3D geometry.

Models:
- DPT_Large: Highest quality, slowest (~2-5 fps on CPU)
- DPT_Hybrid: Good balance of quality and speed
- MiDaS_small: Fastest, lower quality (good for real-time preview)

Dependencies: torch, timm, opencv-python, numpy
Install: uv pip install torch timm opencv-python numpy
"""

from __future__ import annotations

import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MODEL_TYPE = "DPT_Hybrid"  # "DPT_Large" | "DPT_Hybrid" | "MiDaS_small"
DEFAULT_OUTPUT_WIDTH = 960
DEFAULT_OUTPUT_HEIGHT = 540
DEFAULT_FPS = 30

# Colormap options for depth visualization
COLORMAP_GRAYSCALE = "grayscale"
COLORMAP_INFERNO = "inferno"
COLORMAP_MAGMA = "magma"
COLORMAP_PLASMA = "plasma"
COLORMAP_VIRIDIS = "viridis"
COLORMAP_JET = "jet"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class DepthEstimationResult:
    """Result of a depth estimation operation."""
    asset_id: str
    input_video_path: str
    output_video_path: str
    output_width: int
    output_height: int
    frame_count: int
    duration_seconds: float
    fps: float
    model_type: str
    colormap: str
    keyframes_dir: Optional[str] = None
    keyframe_count: int = 0
    processing_time_seconds: float = 0.0


class DepthEstimationError(Exception):
    """Raised when depth estimation fails."""
    def __init__(self, message: str, error_type: str = "estimation_error"):
        super().__init__(message)
        self.error_type = error_type


# ---------------------------------------------------------------------------
# Lazy imports (torch is heavy, only import when needed)
# ---------------------------------------------------------------------------

_torch = None
_cv2 = None
_np = None
_model_cache = {}
_transform_cache = {}


def _import_torch():
    """Lazy import torch."""
    global _torch
    if _torch is None:
        try:
            import torch
            _torch = torch
        except ImportError as e:
            raise DepthEstimationError(
                "PyTorch is not installed. Install with: uv pip install torch",
                error_type="missing_dependency",
            ) from e
    return _torch


def _import_cv2():
    """Lazy import opencv."""
    global _cv2
    if _cv2 is None:
        try:
            import cv2
            _cv2 = cv2
        except ImportError as e:
            raise DepthEstimationError(
                "OpenCV is not installed. Install with: uv pip install opencv-python",
                error_type="missing_dependency",
            ) from e
    return _cv2


def _import_np():
    """Lazy import numpy."""
    global _np
    if _np is None:
        try:
            import numpy as np
            _np = np
        except ImportError as e:
            raise DepthEstimationError(
                "NumPy is not installed. Install with: uv pip install numpy",
                error_type="missing_dependency",
            ) from e
    return _np


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def load_midas_model(model_type: str = DEFAULT_MODEL_TYPE):
    """Load a MiDaS model and its transform.

    Models are cached in memory for reuse.
    """
    if model_type in _model_cache:
        return _model_cache[model_type], _transform_cache[model_type]

    torch = _import_torch()

    try:
        model = torch.hub.load("intel-isl/MiDaS", model_type)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device)
        model.eval()

        midas_transforms = torch.hub.load("intel-isl/MiDaS", "transforms")
        if model_type in ("DPT_Large", "DPT_Hybrid"):
            transform = midas_transforms.dpt_transform
        else:
            transform = midas_transforms.small_transform

        _model_cache[model_type] = model
        _transform_cache[model_type] = transform
        return model, transform
    except Exception as e:
        raise DepthEstimationError(
            f"Failed to load MiDaS model '{model_type}': {str(e)[:200]}",
            error_type="model_load_error",
        ) from e


# ---------------------------------------------------------------------------
# Depth estimation
# ---------------------------------------------------------------------------

def estimate_depth_frame(
    frame,
    model,
    transform,
    device,
    colormap: str = COLORMAP_GRAYSCALE,
):
    """Estimate depth for a single frame and return a colorized depth map.

    Args:
        frame: BGR image (numpy array, HxWx3)
        model: Loaded MiDaS model
        transform: MiDaS transform function
        device: torch device
        colormap: Colormap name for visualization

    Returns:
        Colorized depth map (BGR image, same size as input)
    """
    torch = _import_torch()
    np = _import_np()
    cv2 = _import_cv2()

    # Convert BGR to RGB
    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # Apply transform
    input_batch = transform(img_rgb).to(device)

    # Run inference
    with torch.no_grad():
        prediction = model(input_batch)
        prediction = torch.nn.functional.interpolate(
            prediction.unsqueeze(1),
            size=img_rgb.shape[:2],
            mode="bicubic",
            align_corners=False,
        ).squeeze()

    depth = prediction.cpu().numpy()

    # Normalize depth to 0-255
    depth_min = depth.min()
    depth_max = depth.max()
    if depth_max - depth_min > 1e-6:
        depth_normalized = (depth - depth_min) / (depth_max - depth_min)
    else:
        depth_normalized = np.zeros_like(depth)
    depth_uint8 = (depth_normalized * 255).astype(np.uint8)

    # Apply colormap
    if colormap == COLORMAP_GRAYSCALE:
        depth_color = cv2.cvtColor(depth_uint8, cv2.COLOR_GRAY2BGR)
    else:
        colormap_map = {
            COLORMAP_INFERNO: cv2.COLORMAP_INFERNO,
            COLORMAP_MAGMA: cv2.COLORMAP_MAGMA,
            COLORMAP_PLASMA: cv2.COLORMAP_PLASMA,
            COLORMAP_VIRIDIS: cv2.COLORMAP_VIRIDIS,
            COLORMAP_JET: cv2.COLORMAP_JET,
        }
        cv_colormap = colormap_map.get(colormap, cv2.COLORMAP_INFERNO)
        depth_color = cv2.applyColorMap(depth_uint8, cv_colormap)

    return depth_color


# ---------------------------------------------------------------------------
# Video processing
# ---------------------------------------------------------------------------

def extract_depth_from_video(
    input_video_path: str | Path,
    output_dir: Optional[str | Path] = None,
    model_type: str = DEFAULT_MODEL_TYPE,
    colormap: str = COLORMAP_GRAYSCALE,
    output_width: int = DEFAULT_OUTPUT_WIDTH,
    output_height: int = DEFAULT_OUTPUT_HEIGHT,
    extract_keyframes: bool = True,
    num_keyframes: int = 5,
    max_frames: Optional[int] = None,
) -> DepthEstimationResult:
    """Extract depth map (white model) from a video.

    Args:
        input_video_path: Path to input video file
        output_dir: Directory to save output. Defaults to temp dir.
        model_type: MiDaS model type
        colormap: Colormap for depth visualization
        output_width: Output video width
        output_height: Output video height
        extract_keyframes: Whether to extract keyframes from output
        num_keyframes: Number of keyframes to extract
        max_frames: Maximum number of frames to process (None = all)

    Returns:
        DepthEstimationResult with output paths and metadata

    Raises:
        DepthEstimationError: If processing fails
    """
    import time
    cv2 = _import_cv2()
    torch = _import_torch()

    input_path = Path(input_video_path)
    if not input_path.exists():
        raise DepthEstimationError(
            f"Input video not found: {input_path}",
            error_type="file_not_found",
        )

    # Setup output directory
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="depth_estimation_"))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    asset_id = f"depth_{uuid.uuid4().hex[:12]}"
    output_video_path = output_dir / f"{asset_id}.mp4"

    # Load model
    model, transform = load_midas_model(model_type)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Open input video
    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        raise DepthEstimationError(
            f"Failed to open input video: {input_path}",
            error_type="video_open_error",
        )

    input_fps = cap.get(cv2.CAP_PROP_FPS) or DEFAULT_FPS
    input_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    input_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    input_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if max_frames is not None:
        input_frame_count = min(input_frame_count, max_frames)

    # Setup output video writer
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(
        str(output_video_path),
        fourcc,
        input_fps,
        (output_width, output_height),
    )

    if not out.isOpened():
        cap.release()
        raise DepthEstimationError(
            "Failed to create output video writer",
            error_type="video_writer_error",
        )

    # Process frames
    start_time = time.time()
    frame_idx = 0
    keyframe_timestamps = []

    try:
        while frame_idx < input_frame_count:
            ret, frame = cap.read()
            if not ret:
                break

            # Resize input if needed (for performance)
            if input_width > 1280 or input_height > 720:
                scale = min(1280 / input_width, 720 / input_height)
                frame = cv2.resize(
                    frame,
                    (int(input_width * scale), int(input_height * scale)),
                )

            # Estimate depth
            depth_frame = estimate_depth_frame(
                frame, model, transform, device, colormap
            )

            # Resize to output dimensions
            depth_frame = cv2.resize(depth_frame, (output_width, output_height))

            # Write to output
            out.write(depth_frame)

            # Record keyframe timestamps
            if extract_keyframes and input_frame_count > 0:
                keyframe_frame = int((num_keyframes - 1) * frame_idx / max(1, input_frame_count - 1))
                if frame_idx == keyframe_frame or frame_idx == 0 or frame_idx == input_frame_count - 1:
                    keyframe_timestamps.append(frame_idx)

            frame_idx += 1

    finally:
        cap.release()
        out.release()

    processing_time = time.time() - start_time

    # Extract keyframes from output video
    keyframes_dir = None
    keyframe_count = 0
    if extract_keyframes and frame_idx > 0:
        keyframes_dir = output_dir / f"{asset_id}_keyframes"
        keyframes_dir.mkdir(parents=True, exist_ok=True)

        for i, frame_num in enumerate(keyframe_timestamps[:num_keyframes]):
            kf_path = keyframes_dir / f"keyframe_{i:02d}.png"
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(frame_num / input_fps),
                "-i", str(output_video_path),
                "-vframes", "1",
                "-q:v", "2",
                str(kf_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and kf_path.exists():
                keyframe_count += 1

    duration_seconds = frame_idx / input_fps if input_fps > 0 else 0

    return DepthEstimationResult(
        asset_id=asset_id,
        input_video_path=str(input_path),
        output_video_path=str(output_video_path),
        output_width=output_width,
        output_height=output_height,
        frame_count=frame_idx,
        duration_seconds=duration_seconds,
        fps=input_fps,
        model_type=model_type,
        colormap=colormap,
        keyframes_dir=str(keyframes_dir) if keyframes_dir else None,
        keyframe_count=keyframe_count,
        processing_time_seconds=processing_time,
    )


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def check_dependencies() -> dict[str, bool]:
    """Check if required dependencies are installed.

    Returns a dict with dependency names and availability.
    """
    result = {
        "torch": False,
        "opencv": False,
        "numpy": False,
        "timm": False,
        "ffmpeg": False,
    }

    try:
        import torch  # noqa: F401
        result["torch"] = True
    except ImportError:
        pass

    try:
        import cv2  # noqa: F401
        result["opencv"] = True
    except ImportError:
        pass

    try:
        import numpy  # noqa: F401
        result["numpy"] = True
    except ImportError:
        pass

    try:
        import timm  # noqa: F401
        result["timm"] = True
    except ImportError:
        pass

    try:
        result_ = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        result["ffmpeg"] = result_.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return result


def get_available_models() -> list[str]:
    """Return list of available MiDaS model types."""
    return ["DPT_Large", "DPT_Hybrid", "MiDaS_small"]


def get_available_colormaps() -> list[str]:
    """Return list of available depth colormaps."""
    return [
        COLORMAP_GRAYSCALE,
        COLORMAP_INFERNO,
        COLORMAP_MAGMA,
        COLORMAP_PLASMA,
        COLORMAP_VIRIDIS,
        COLORMAP_JET,
    ]
