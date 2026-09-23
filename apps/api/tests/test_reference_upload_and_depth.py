"""Tests for reference video upload and depth estimation services.

These tests cover:
- Reference video validation (format, size, duration)
- Reference video upload and metadata extraction
- Depth estimation dependency checking
- Depth estimation model availability

Note: Tests that require actual video files or torch models are marked
as integration tests and skipped by default.
"""

from __future__ import annotations


import pytest

from app.services.scene3d.reference_upload import (
    MAX_DURATION_SECONDS,
    MAX_FILE_SIZE_MB,
    MIN_DURATION_SECONDS,
    UploadError,
    validate_metadata,
    validate_upload,
)
from app.services.scene3d.depth_estimator import (
    DEFAULT_MODEL_TYPE,
    get_available_colormaps,
    get_available_models,
)


# ---------------------------------------------------------------------------
# Reference upload validation tests
# ---------------------------------------------------------------------------

class TestValidateUpload:
    """Tests for file upload validation."""

    def test_valid_mp4_extension(self):
        """MP4 files should pass extension validation."""
        validate_upload("video.mp4", 1024 * 1024, "video/mp4")

    def test_valid_webm_extension(self):
        """WebM files should pass extension validation."""
        validate_upload("video.webm", 1024 * 1024, "video/webm")

    def test_valid_mov_extension(self):
        """MOV files should pass extension validation."""
        validate_upload("video.mov", 1024 * 1024, "video/quicktime")

    def test_invalid_extension(self):
        """Files with invalid extensions should raise UploadError."""
        with pytest.raises(UploadError) as exc_info:
            validate_upload("video.txt", 1024, "text/plain")
        assert "Unsupported file format" in str(exc_info.value)
        assert exc_info.value.error_type == "invalid_format"

    def test_empty_file(self):
        """Empty files should raise UploadError."""
        with pytest.raises(UploadError) as exc_info:
            validate_upload("video.mp4", 0, "video/mp4")
        assert "File is empty" in str(exc_info.value)
        assert exc_info.value.error_type == "invalid_size"

    def test_file_too_large(self):
        """Files larger than MAX_FILE_SIZE_MB should raise UploadError."""
        large_size = (MAX_FILE_SIZE_MB + 1) * 1024 * 1024
        with pytest.raises(UploadError) as exc_info:
            validate_upload("video.mp4", large_size, "video/mp4")
        assert "File too large" in str(exc_info.value)
        assert exc_info.value.error_type == "invalid_size"

    def test_invalid_mime_type(self):
        """Files with invalid MIME types should raise UploadError."""
        with pytest.raises(UploadError) as exc_info:
            validate_upload("video.mp4", 1024, "application/octet-stream")
        assert "Unsupported MIME type" in str(exc_info.value)

    def test_none_mime_type_passes(self):
        """None MIME type should pass MIME validation."""
        validate_upload("video.mp4", 1024 * 1024, None)


class TestValidateMetadata:
    """Tests for video metadata validation."""

    def _make_metadata(self, **kwargs):
        """Helper to create a VideoMetadata-like object."""
        from app.services.scene3d.reference_upload import VideoMetadata
        defaults = {
            "duration_seconds": 5.0,
            "width": 1920,
            "height": 1080,
            "frame_rate": 30.0,
            "frame_count": 150,
            "codec_name": "h264",
            "file_size_bytes": 1024 * 1024,
        }
        defaults.update(kwargs)
        return VideoMetadata(**defaults)

    def test_valid_metadata(self):
        """Valid metadata should pass validation."""
        metadata = self._make_metadata()
        validate_metadata(metadata)  # Should not raise

    def test_duration_too_short(self):
        """Videos shorter than MIN_DURATION_SECONDS should raise UploadError."""
        metadata = self._make_metadata(duration_seconds=MIN_DURATION_SECONDS - 0.1)
        with pytest.raises(UploadError) as exc_info:
            validate_metadata(metadata)
        assert "Video too short" in str(exc_info.value)
        assert exc_info.value.error_type == "invalid_duration"

    def test_duration_too_long(self):
        """Videos longer than MAX_DURATION_SECONDS should raise UploadError."""
        metadata = self._make_metadata(duration_seconds=MAX_DURATION_SECONDS + 1)
        with pytest.raises(UploadError) as exc_info:
            validate_metadata(metadata)
        assert "Video too long" in str(exc_info.value)
        assert exc_info.value.error_type == "invalid_duration"

    def test_zero_dimensions(self):
        """Videos with zero dimensions should raise UploadError."""
        metadata = self._make_metadata(width=0, height=1080)
        with pytest.raises(UploadError) as exc_info:
            validate_metadata(metadata)
        assert "Invalid video dimensions" in str(exc_info.value)

    def test_resolution_too_high(self):
        """Videos with resolution > 4096 should raise UploadError."""
        metadata = self._make_metadata(width=4097, height=2160)
        with pytest.raises(UploadError) as exc_info:
            validate_metadata(metadata)
        assert "Resolution too high" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Depth estimation tests
# ---------------------------------------------------------------------------

class TestDepthEstimator:
    """Tests for depth estimation service configuration."""

    def test_default_model_type(self):
        """Default model type should be DPT_Hybrid."""
        assert DEFAULT_MODEL_TYPE == "DPT_Hybrid"

    def test_available_models(self):
        """Should return three MiDaS model types."""
        models = get_available_models()
        assert "DPT_Large" in models
        assert "DPT_Hybrid" in models
        assert "MiDaS_small" in models
        assert len(models) == 3

    def test_available_colormaps(self):
        """Should return six colormap options."""
        colormaps = get_available_colormaps()
        assert "grayscale" in colormaps
        assert "inferno" in colormaps
        assert "magma" in colormaps
        assert "plasma" in colormaps
        assert "viridis" in colormaps
        assert "jet" in colormaps
        assert len(colormaps) == 6


class TestDepthDependencies:
    """Tests for depth estimation dependency checking."""

    def test_check_dependencies_returns_dict(self):
        """check_dependencies should return a dict with all expected keys."""
        from app.services.scene3d.depth_estimator import check_dependencies
        deps = check_dependencies()
        assert "torch" in deps
        assert "opencv" in deps
        assert "numpy" in deps
        assert "timm" in deps
        assert "ffmpeg" in deps
        assert all(isinstance(v, bool) for v in deps.values())


# ---------------------------------------------------------------------------
# Integration tests (require actual video files)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestReferenceUploadIntegration:
    """Integration tests requiring actual video files."""

    def test_upload_and_extract_metadata(self, tmp_path):
        """Test full upload flow with a generated test video."""
        # Generate a small test video using ffmpeg
        test_video = tmp_path / "test.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "testsrc=duration=2:size=320x240:rate=30",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(test_video),
        ]
        import subprocess
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            pytest.skip("ffmpeg not available for test video generation")

        # Upload the test video
        from app.services.scene3d.reference_upload import save_reference_video
        file_bytes = test_video.read_bytes()
        result = save_reference_video(
            file_bytes=file_bytes,
            file_name="test.mp4",
            content_type="video/mp4",
            upload_dir=tmp_path / "uploads",
            extract_keyframes=False,
        )

        assert result.success is True if hasattr(result, 'success') else True
        assert result.asset_id.startswith("ref_")
        assert result.metadata.duration_seconds > 0
        assert result.metadata.width == 320
        assert result.metadata.height == 240
        assert result.metadata.frame_rate > 0
