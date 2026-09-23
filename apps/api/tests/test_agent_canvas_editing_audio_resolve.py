"""Resolver tests: timeline audio entries resolve like BGM and never fail export."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from app.schemas.agent_canvas import ProjectAssetSummaryV2
from app.schemas.agent_canvas_editing import (
    EditingAudioEntryV2,
    EditingDuckingConfigV2,
    EditingManifestV2,
    EditingVideoEntryV2,
)
from app.services.agent_canvas_editing import EditingInputResolver


def _asset(asset_id: str, media_type: str) -> ProjectAssetSummaryV2:
    return ProjectAssetSummaryV2(
        asset_id=asset_id,
        media_type=media_type,
        source_type="generated",
        display_name=asset_id,
        mime_type="video/mp4" if media_type == "video" else "audio/wav",
        status="ready",
        checksum=f"sha256-{asset_id}",
        duration_seconds=6.0,
    )


class _Workflows:
    def __init__(self) -> None:
        self.workflow = SimpleNamespace(
            workflow_id="wf-1",
            project_id="proj-1",
            bindings=(),
            nodes=(),
        )

    def get_workflow(self, _workflow_id: str):
        return self.workflow


def _resolver(tmp_path: Path, *, missing_asset: bool = False) -> EditingInputResolver:
    files = {
        "v1": tmp_path / "v1.mp4",
        "a1": tmp_path / "a1.wav",
    }
    files["v1"].write_bytes(b"video")
    if not missing_asset:
        files["a1"].write_bytes(b"audio")

    def asset_resolver(asset_id: str) -> ProjectAssetSummaryV2:
        if asset_id == "v1":
            return _asset("v1", "video")
        if asset_id == "a1":
            return _asset("a1", "audio")
        raise LookupError(asset_id)

    def path_resolver(asset_id: str) -> Path:
        return files.get(asset_id, tmp_path / f"{asset_id}.missing")

    return EditingInputResolver(_Workflows(), asset_resolver, path_resolver)


class TestAudioEntryResolution:
    def test_ready_audio_entries_resolve_and_carry_ducking(self, tmp_path: Path) -> None:
        manifest = EditingManifestV2(
            video_entries=(EditingVideoEntryV2(asset_id="v1", timeline_start_seconds=0.0),),
            audio_entries=(
                EditingAudioEntryV2(
                    asset_id="a1",
                    role="voice",
                    timeline_start_seconds=1.0,
                    trim_end_seconds=3.0,
                ),
            ),
            ducking=EditingDuckingConfigV2(threshold_db=-35.0),
            timeline_duration_seconds=6.0,
        )

        resolved = _resolver(tmp_path).resolve("wf-1", "node-1", manifest)

        assert len(resolved.videos) == 1
        assert len(resolved.audios) == 1
        assert resolved.audios[0].asset.asset_id == "a1"
        assert resolved.audios[0].audio_entry is not None
        assert resolved.audios[0].audio_entry.role == "voice"
        assert resolved.ducking is not None
        assert resolved.ducking.threshold_db == -35.0
        assert resolved.skipped == ()

    def test_missing_audio_files_skip_without_killing_export(self, tmp_path: Path) -> None:
        manifest = EditingManifestV2(
            video_entries=(EditingVideoEntryV2(asset_id="v1", timeline_start_seconds=0.0),),
            audio_entries=(
                EditingAudioEntryV2(asset_id="a1", role="voice", trim_end_seconds=3.0),
                EditingAudioEntryV2(asset_id="a2", role="sfx", trim_end_seconds=3.0),
            ),
            timeline_duration_seconds=6.0,
        )

        resolved = _resolver(tmp_path, missing_asset=True).resolve("wf-1", "node-1", manifest)

        assert len(resolved.videos) == 1
        assert resolved.audios == ()
        assert {item.reference_id for item in resolved.skipped} == {"a1", "a2"}
        assert all(item.reason == "source_media_invalid" for item in resolved.skipped)

    def test_wrong_media_type_audio_entry_is_skipped(self, tmp_path: Path) -> None:
        def asset_resolver(asset_id: str) -> ProjectAssetSummaryV2:
            if asset_id == "v1":
                return _asset("v1", "video")
            return _asset("a1", "video")  # audio entry points at a video asset

        resolver = EditingInputResolver(
            _Workflows(),
            asset_resolver,
            lambda asset_id: tmp_path / f"{asset_id}.bin",
        )
        (tmp_path / "v1.bin").write_bytes(b"v")
        (tmp_path / "a1.bin").write_bytes(b"a")

        manifest = EditingManifestV2(
            video_entries=(EditingVideoEntryV2(asset_id="v1", timeline_start_seconds=0.0),),
            audio_entries=(EditingAudioEntryV2(asset_id="a1", role="bgm", trim_end_seconds=2.0),),
            timeline_duration_seconds=6.0,
        )

        resolved = resolver.resolve("wf-1", "node-1", manifest)

        assert resolved.audios == ()
        assert len(resolved.skipped) == 1
        assert resolved.skipped[0].reference_id == "a1"
        assert resolved.skipped[0].reason == "source_media_invalid"
