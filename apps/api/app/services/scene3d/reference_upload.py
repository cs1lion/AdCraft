"""Reference video upload service.

Handles uploading user-provided reference videos for video model
conditioning. Validates format, size, duration, and extracts metadata
(resolution, frame rate, frame count).

Reference videos can be used as an alternative to Blender-rendered 3D
previs videos. The video model (e.g. Agnes Video V2.0) can consume either:
  - a reference video (if supported), or
  - keyframe images extracted from the reference video (fallback)
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_MB = 100
# 60s 与拉片拆解（replica teardown）的时长上界对齐：参考片上传是拉片复刻的
# 共用入口，15-30s 的广告片必须传得上来；3D 读片成本由抽帧数决定而非时长。
MAX_DURATION_SECONDS = 60
MIN_DURATION_SECONDS = 0.5
ALLOWED_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v"}
ALLOWED_MIME_TYPES = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-m4v",
}

DEFAULT_UPLOAD_DIR = Path("uploads/reference_videos")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class VideoMetadata:
    """Extracted metadata from an uploaded video."""
    duration_seconds: float
    width: int
    height: int
    frame_rate: float
    frame_count: int
    codec_name: str
    file_size_bytes: int


@dataclass
class UploadResult:
    """Result of a reference video upload."""
    asset_id: str
    file_path: str
    file_name: str
    file_size_bytes: int
    metadata: VideoMetadata
    keyframes_dir: Optional[str] = None
    keyframe_count: int = 0


class UploadError(Exception):
    """Raised when a reference video upload fails validation."""
    def __init__(self, message: str, error_type: str = "validation"):
        super().__init__(message)
        self.error_type = error_type


# ---------------------------------------------------------------------------
# FFprobe integration
# ---------------------------------------------------------------------------

def _run_ffprobe(file_path: Path) -> dict:
    """Run ffprobe on a video file and return parsed JSON output."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise UploadError(
            f"ffprobe failed: {result.stderr[:200]}",
            error_type="ffprobe_error",
        )
    return json.loads(result.stdout)


def extract_metadata(file_path: Path) -> VideoMetadata:
    """Extract video metadata using ffprobe."""
    probe = _run_ffprobe(file_path)

    # Find the first video stream
    video_stream = None
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break

    if not video_stream:
        raise UploadError(
            "No video stream found in the file",
            error_type="invalid_format",
        )

    # Parse frame rate (e.g. "30/1" or "30000/1001")
    frame_rate_str = video_stream.get("r_frame_rate", "30/1")
    if "/" in frame_rate_str:
        num, den = frame_rate_str.split("/")
        frame_rate = float(num) / float(den) if float(den) != 0 else 30.0
    else:
        frame_rate = float(frame_rate_str)

    # Duration from format or stream
    duration_str = probe.get("format", {}).get("duration")
    if duration_str:
        duration = float(duration_str)
    else:
        duration = float(video_stream.get("duration", 0))

    # Frame count
    frame_count = int(video_stream.get("nb_frames", 0))
    if frame_count == 0 and duration > 0 and frame_rate > 0:
        frame_count = int(duration * frame_rate)

    file_size = file_path.stat().st_size

    return VideoMetadata(
        duration_seconds=duration,
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        frame_rate=frame_rate,
        frame_count=frame_count,
        codec_name=video_stream.get("codec_name", "unknown"),
        file_size_bytes=file_size,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_upload(
    file_name: str,
    file_size: int,
    content_type: Optional[str] = None,
) -> None:
    """Validate an uploaded file before processing.

    Raises UploadError with a descriptive message if validation fails.
    """
    # Check extension
    ext = Path(file_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadError(
            f"Unsupported file format '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            error_type="invalid_format",
        )

    # Check MIME type (if provided)
    if content_type and content_type not in ALLOWED_MIME_TYPES:
        raise UploadError(
            f"Unsupported MIME type '{content_type}'. Allowed: {', '.join(sorted(ALLOWED_MIME_TYPES))}",
            error_type="invalid_format",
        )

    # Check file size
    if file_size == 0:
        raise UploadError("File is empty", error_type="invalid_size")

    if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise UploadError(
            f"File too large: {file_size / (1024*1024):.1f} MB. Maximum: {MAX_FILE_SIZE_MB} MB",
            error_type="invalid_size",
        )


def validate_metadata(metadata: VideoMetadata) -> None:
    """Validate extracted video metadata.

    Raises UploadError if the video doesn't meet requirements.
    """
    if metadata.duration_seconds < MIN_DURATION_SECONDS:
        raise UploadError(
            f"Video too short: {metadata.duration_seconds:.2f}s. Minimum: {MIN_DURATION_SECONDS}s",
            error_type="invalid_duration",
        )

    if metadata.duration_seconds > MAX_DURATION_SECONDS:
        raise UploadError(
            f"Video too long: {metadata.duration_seconds:.2f}s. Maximum: {MAX_DURATION_SECONDS}s",
            error_type="invalid_duration",
        )

    if metadata.width == 0 or metadata.height == 0:
        raise UploadError(
            "Invalid video dimensions",
            error_type="invalid_dimensions",
        )

    if metadata.width > 4096 or metadata.height > 4096:
        raise UploadError(
            f"Resolution too high: {metadata.width}x{metadata.height}. Maximum: 4096x4096",
            error_type="invalid_dimensions",
        )


# ---------------------------------------------------------------------------
# Keyframe extraction
# ---------------------------------------------------------------------------

def extract_keyframes_from_video(
    video_path: Path,
    output_dir: Path,
    num_keyframes: int = 5,
) -> list[str]:
    """Extract evenly-spaced keyframes from a video using ffmpeg.

    Returns a list of output file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get video duration
    metadata = extract_metadata(video_path)
    duration = metadata.duration_seconds

    keyframe_paths = []
    for i in range(num_keyframes):
        timestamp = (duration * i) / (num_keyframes - 1) if num_keyframes > 1 else 0
        output_path = output_dir / f"keyframe_{i:02d}.png"

        cmd = [
            "ffmpeg",
            "-y",
            "-ss", f"{timestamp:.3f}",
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(output_path),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and output_path.exists():
            keyframe_paths.append(str(output_path))

    return keyframe_paths


# ---------------------------------------------------------------------------
# Main upload handler
# ---------------------------------------------------------------------------

def save_reference_video(
    file_bytes: bytes,
    file_name: str,
    content_type: Optional[str] = None,
    upload_dir: Optional[Path] = None,
    extract_keyframes: bool = True,
    num_keyframes: int = 5,
) -> UploadResult:
    """Save and validate an uploaded reference video.

    Args:
        file_bytes: Raw file content from the upload.
        file_name: Original file name.
        content_type: MIME type from the upload request.
        upload_dir: Directory to save the video. Defaults to uploads/reference_videos.
        extract_keyframes: Whether to extract keyframes from the video.
        num_keyframes: Number of keyframes to extract.

    Returns:
        UploadResult with asset_id, file path, metadata, and keyframe info.

    Raises:
        UploadError: If validation or processing fails.
    """
    # Validate upload
    validate_upload(file_name, len(file_bytes), content_type)

    # Setup output directory
    if upload_dir is None:
        upload_dir = DEFAULT_UPLOAD_DIR
    upload_dir = Path(upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Generate asset ID and safe file name
    asset_id = f"ref_{uuid.uuid4().hex[:12]}"
    ext = Path(file_name).suffix.lower()
    safe_file_name = f"{asset_id}{ext}"
    file_path = upload_dir / safe_file_name

    # Save file
    file_path.write_bytes(file_bytes)

    try:
        # Extract and validate metadata
        metadata = extract_metadata(file_path)
        validate_metadata(metadata)

        # Extract keyframes (optional)
        keyframes_dir = None
        keyframe_count = 0
        if extract_keyframes:
            kf_dir = upload_dir / f"{asset_id}_keyframes"
            kf_paths = extract_keyframes_from_video(
                file_path, kf_dir, num_keyframes
            )
            if kf_paths:
                keyframes_dir = str(kf_dir)
                keyframe_count = len(kf_paths)

        return UploadResult(
            asset_id=asset_id,
            file_path=str(file_path),
            file_name=safe_file_name,
            file_size_bytes=metadata.file_size_bytes,
            metadata=metadata,
            keyframes_dir=keyframes_dir,
            keyframe_count=keyframe_count,
        )

    except UploadError:
        # Clean up on validation failure
        if file_path.exists():
            file_path.unlink()
        raise
    except Exception as e:
        # Clean up on unexpected error
        if file_path.exists():
            file_path.unlink()
        raise UploadError(
            f"Failed to process video: {str(e)[:200]}",
            error_type="processing_error",
        ) from e


def get_reference_video_path(asset_id: str, upload_dir: Optional[Path] = None) -> Optional[Path]:
    """Look up a reference video by asset_id.

    Returns the file path if found, None otherwise.
    """
    if upload_dir is None:
        upload_dir = DEFAULT_UPLOAD_DIR
    upload_dir = Path(upload_dir)

    # Search for files matching the asset_id prefix
    for ext in ALLOWED_EXTENSIONS:
        candidate = upload_dir / f"{asset_id}{ext}"
        if candidate.exists():
            return candidate

    return None


def list_reference_videos(upload_dir: Optional[Path] = None) -> list[dict]:
    """List all uploaded reference videos with basic metadata.

    Returns a list of dicts with asset_id, file_name, file_size, and upload time.
    """
    if upload_dir is None:
        upload_dir = DEFAULT_UPLOAD_DIR
    upload_dir = Path(upload_dir)

    if not upload_dir.exists():
        return []

    results = []
    for file_path in upload_dir.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in ALLOWED_EXTENSIONS:
            stat = file_path.stat()
            results.append({
                "asset_id": file_path.stem,
                "file_name": file_path.name,
                "file_size_bytes": stat.st_size,
                "upload_time": stat.st_mtime,
            })

    return results
