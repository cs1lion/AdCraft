"""Tests for timeline-window reference slicing (ADR 0008 P1).

Locks: no-window pass-through, video/audio slicing with the provider input
rewritten to a data URL, images never sliced, unresolvable sources and slice
failures degrading to the whole asset WITH warnings (never silent), and the
executor wiring (the report rides on the context; a resolver failure never
blocks generation).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.seedance_inputs import SeedanceDeliveredMediaInputV1
from app.services.timeline_media_slice import MediaSliceResult
from app.services.timeline_window_slicer import slice_references_to_window


def _reference(media_type: str, asset_id: str = "asset_1") -> SeedanceDeliveredMediaInputV1:
    return SeedanceDeliveredMediaInputV1(
        binding_id=f"bnd_{asset_id}",
        asset_id=asset_id,
        version_id="ver_1",
        media_type=media_type,  # type: ignore[arg-type]
        input_role="video_reference" if media_type == "video" else "audio_reference",
        source_semantic_role="scene",
        required=True,
        display_order=0,
        provider_input_type="video_url" if media_type == "video" else "audio_url",
        provider_input_value="https://provider.example/whole.mp4",
        checksum="abc",
        byte_count=1000,
    )


@pytest.fixture
def fake_slice(tmp_path, monkeypatch):
    """A fake slice_media that writes a small file and reports success."""

    state = {"calls": [], "fail": False}

    def fake(
        source_path,
        *,
        start_time,
        duration,
        output_dir,
        workflow_id,
        kind,
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
    ):
        state["calls"].append(
            {
                "source": str(source_path),
                "start_time": start_time,
                "duration": duration,
                "kind": kind,
            }
        )
        if state["fail"]:
            return MediaSliceResult(
                path=None, sliced=False, warnings=["slice_ffmpeg_failed: boom"],
                start_time=start_time, duration=duration,
            )
        out = Path(output_dir) / "slices" / workflow_id / f"slice_{kind}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"sliced-bytes")
        return MediaSliceResult(
            path=out, sliced=True, warnings=[],
            start_time=start_time, duration=duration,
        )

    monkeypatch.setattr(
        "app.services.timeline_window_slicer.slice_media_to_window", fake
    )
    return state


def _resolver(mapping: dict[str, Path | None]):
    return lambda asset_id, version_id: mapping.get(asset_id)


def test_no_window_passes_everything_through(tmp_path, fake_slice) -> None:
    refs = [_reference("video"), _reference("audio")]
    out, report = slice_references_to_window(
        refs,
        window=None,
        workflow_id="wf-1",
        output_dir=tmp_path / "out",
        resolve_local_path=_resolver({"asset_1": Path("x.mp4")}),
    )
    assert out == refs  # untouched
    assert report.skipped[0]["reason"] == "no_timeline_window"
    assert fake_slice["calls"] == []


def test_video_and_audio_references_are_sliced(tmp_path, fake_slice) -> None:
    refs = [_reference("video", "asset_v"), _reference("audio", "asset_a")]
    out, report = slice_references_to_window(
        refs,
        window=(3.0, 2.0),
        workflow_id="wf-1",
        output_dir=tmp_path / "out",
        resolve_local_path=_resolver(
            {"asset_v": Path("whole.mp4"), "asset_a": Path("whole.mp3")}
        ),
    )

    # Both slice calls carried the window.
    assert [call["kind"] for call in fake_slice["calls"]] == ["video", "audio"]
    assert all(call["start_time"] == 3.0 and call["duration"] == 2.0 for call in fake_slice["calls"])

    # The provider input is rewritten to the slice's data URL.
    for reference in out:
        assert reference.provider_input_value.startswith("data:")
        assert "sliced-bytes" not in reference.provider_input_value  # base64, not raw
        assert reference.byte_count == len(b"sliced-bytes")
    assert len(report.sliced) == 2
    assert report.warnings == []


def test_images_are_never_sliced(tmp_path, fake_slice) -> None:
    refs = [_reference("image", "asset_i")]
    out, report = slice_references_to_window(
        refs,
        window=(1.0, 2.0),
        workflow_id="wf-1",
        output_dir=tmp_path / "out",
        resolve_local_path=_resolver({"asset_i": Path("still.png")}),
    )
    assert out == refs
    assert report.skipped[0]["reason"] == "not_sliceable_media_type"
    assert fake_slice["calls"] == []


def test_unresolvable_source_keeps_whole_asset_with_warning(tmp_path, fake_slice) -> None:
    refs = [_reference("video", "asset_missing")]
    out, report = slice_references_to_window(
        refs,
        window=(1.0, 2.0),
        workflow_id="wf-1",
        output_dir=tmp_path / "out",
        resolve_local_path=_resolver({}),
    )
    assert out == refs  # degraded to the whole asset
    assert report.skipped[0]["reason"] == "source_unresolved"
    assert any("timeline_slice_source_unresolved" in w for w in report.warnings)


def test_slice_failure_keeps_whole_asset_with_warning(tmp_path, fake_slice) -> None:
    fake_slice["fail"] = True
    refs = [_reference("video", "asset_v")]
    out, report = slice_references_to_window(
        refs,
        window=(1.0, 2.0),
        workflow_id="wf-1",
        output_dir=tmp_path / "out",
        resolve_local_path=_resolver({"asset_v": Path("whole.mp4")}),
    )
    assert out == refs  # the original reference survives
    assert report.skipped[0]["reason"] == "slice_failed"
    assert any("slice_ffmpeg_failed" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# Executor wiring
# ---------------------------------------------------------------------------


def _executor(tmp_path, resolver):
    from app.services.agent_canvas_node_execution import MediaNodeExecutor

    return MediaNodeExecutor(
        provider=None,  # type: ignore[arg-type]
        data_dir=tmp_path / "data",
        settings=_settings(tmp_path),
        timeline_window_resolver=resolver,
    )


def _settings(tmp_path):
    from app.core.config import Settings

    return Settings(
        agent_runtime_mode="fake",
        media_mode="mock",
        media_data_dir=tmp_path / "data",
        stepfun_api_key="k",
    )


def _node(node_type: str = "video"):
    from app.schemas.agent_canvas import CanvasNodeV2

    return CanvasNodeV2.model_validate(
        {
            "node_id": "node-video-1",
            "workflow_id": "wf-1",
            "node_type": node_type,
            "creative_role": "general_video",
            "role_contract_version": "ad-media-role-v1",
            "title": "video node",
            "status": "draft",
            "summary_prompt": None,
            "generation_prompt": "a shot",
            "structured_content": {},
            "parameters": {},
            "prompt_context_snapshot_id": None,
            "output_asset_id": None,
            "position": {"x": 0, "y": 0},
            "revision": 1,
            "error": None,
            "created_at": "2026-09-26T00:00:00Z",
            "updated_at": "2026-09-26T00:00:00Z",
        }
    )


def test_executor_slicing_uses_the_resolver_window(tmp_path, fake_slice) -> None:
    executor = _executor(tmp_path, lambda node: (5.0, 2.5))
    executor._resolve_reference_local_path = lambda asset_id, version_id: Path("whole.mp4")

    refs, report = executor._slice_references_to_window(
        _node(), (_reference("video", "asset_v"),)
    )

    assert fake_slice["calls"][0]["start_time"] == 5.0
    assert fake_slice["calls"][0]["duration"] == 2.5
    assert refs[0].provider_input_value.startswith("data:")
    assert report.window == (5.0, 2.5)


def test_executor_slicing_noop_without_window(tmp_path, fake_slice) -> None:
    executor = _executor(tmp_path, lambda node: None)
    executor._resolve_reference_local_path = lambda asset_id, version_id: Path("whole.mp4")

    refs, report = executor._slice_references_to_window(
        _node(), (_reference("video", "asset_v"),)
    )
    assert refs[0].provider_input_value == "https://provider.example/whole.mp4"
    assert fake_slice["calls"] == []
    assert report.window is None


def test_executor_slicing_resolver_failure_never_blocks(tmp_path, fake_slice) -> None:
    def boom(node):
        raise RuntimeError("timeline db unavailable")

    executor = _executor(tmp_path, boom)
    executor._resolve_reference_local_path = lambda asset_id, version_id: Path("whole.mp4")

    refs, report = executor._slice_references_to_window(
        _node(), (_reference("video", "asset_v"),)
    )
    # Generation proceeds unsliced; the resolver failure is swallowed here.
    assert refs[0].provider_input_value == "https://provider.example/whole.mp4"
    assert fake_slice["calls"] == []


def test_a_voice_cast_bed_reference_is_sliced_to_the_shot_window(
    tmp_path, fake_slice
) -> None:
    """The dialogue-driven convergence (ADR 0008 + the audio plan).

    A voice-cast bed bound to a video node reaches the provider as an
    audio_url reference; the shot's timeline window slices it to the spoken
    span, so the video model sees THIS shot's dialogue, not the whole
    conversation. The same boundaries the mouths animate on."""

    executor = _executor(tmp_path, lambda node: (12.0, 3.0))
    executor._resolve_reference_local_path = lambda asset_id, version_id: Path("bed.mp3")

    refs, report = executor._slice_references_to_window(
        _node(), (_reference("audio", "bed_asset"),)
    )

    assert fake_slice["calls"][0]["start_time"] == 12.0
    assert fake_slice["calls"][0]["duration"] == 3.0
    # Delivered as a sliced audio reference (data URL), still typed audio.
    assert refs[0].provider_input_value.startswith("data:")
    assert refs[0].media_type == "audio"
    assert refs[0].provider_input_type == "audio_url"
    assert len(report.sliced) == 1
    assert report.sliced[0]["asset_id"] == "bed_asset"
