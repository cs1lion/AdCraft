"""Publication contracts use isolated local files, not Blender or provider calls."""

from __future__ import annotations

import pytest

from app.services.scene3d.render_publication import publish_render_video

pytestmark = pytest.mark.integration


def test_publishes_known_job_output_and_reuses_static_media_path(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    source = job / "previs.mp4"
    source.write_bytes(b"test-video")
    root = tmp_path / "media"
    kwargs = dict(
        media_root=root,
        job_id="job-1",
        output_dir=str(job),
        video_path=str(source),
        filename="previs.mp4",
    )
    assert publish_render_video(**kwargs) == "/media/scene3d/job-1/previs.mp4"
    assert (root / "scene3d/job-1/previs.mp4").read_bytes() == b"test-video"
    assert publish_render_video(**kwargs) == "/media/scene3d/job-1/previs.mp4"


@pytest.mark.parametrize(
    "job_id,filename", [("../escape", "previs.mp4"), ("job-1", "../escape.mp4")]
)
def test_rejects_uncontrolled_publication_names(tmp_path, job_id, filename):
    with pytest.raises(ValueError):
        publish_render_video(
            media_root=tmp_path,
            job_id=job_id,
            output_dir=str(tmp_path),
            video_path=str(tmp_path / "video.mp4"),
            filename=filename,
        )


def test_rejects_output_outside_the_owned_job_directory(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    source = tmp_path / "other.mp4"
    source.write_bytes(b"private")
    with pytest.raises(ValueError, match="outside"):
        publish_render_video(
            media_root=tmp_path / "media",
            job_id="job-1",
            output_dir=str(job),
            video_path=str(source),
            filename="previs.mp4",
        )
    assert not (tmp_path / "media").exists()


def test_missing_video_is_explicitly_unpublished(tmp_path):
    assert (
        publish_render_video(
            media_root=tmp_path,
            job_id="job-1",
            output_dir=str(tmp_path),
            video_path=None,
            filename="previs.mp4",
        )
        is None
    )
