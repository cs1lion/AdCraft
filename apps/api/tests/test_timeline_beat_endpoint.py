"""HTTP tests for the clip beat-analysis endpoint (plan 4.4).

The timeline router runs on a minimal FastAPI app with both dependencies
overridden by in-memory fakes, exercising routing/serialization/error codes
without a database or ffmpeg.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v2.endpoints import timeline as timeline_endpoint
from app.persistence.errors import V2PersistenceError
from app.schemas.timeline import TimelineClipV1, TimelineTrackV1, TimelineV1
from app.services.timeline_beat_analysis import BeatAnalysis, BeatAnalysisError

_TS = "2026-09-18T00:00:00+00:00"


def _clip(
    clip_id: str,
    *,
    asset_id: str | None = "asset-bgm",
    track_type: str = "bgm",
) -> TimelineClipV1:
    return TimelineClipV1(
        clip_id=clip_id,
        track_id=f"track-{track_type}",
        start_time=0.0,
        duration=8.0,
        asset_id=asset_id,
        created_at=_TS,
        updated_at=_TS,
    )


def _track(clips: tuple[TimelineClipV1, ...]) -> TimelineTrackV1:
    return TimelineTrackV1(
        track_id="track-bgm",
        timeline_id="timeline-1",
        type="bgm",
        name="BGM",
        clips=clips,
        created_at=_TS,
        updated_at=_TS,
    )


def _timeline(clips: tuple[TimelineClipV1, ...]) -> TimelineV1:
    return TimelineV1(
        timeline_id="timeline-1",
        workflow_id="wf-1",
        duration_seconds=10,
        fps=30,
        subtitle_burn_in=True,
        tracks=(_track(clips),),
        created_at=_TS,
        updated_at=_TS,
    )


class _FakeRepo:
    def __init__(self, timeline: TimelineV1) -> None:
        self._timeline = timeline

    def get_by_workflow_id(self, workflow_id: str) -> TimelineV1:
        return self._timeline


class _FakeTools:
    def __init__(
        self,
        *,
        path: Path | None = Path("bgm.wav"),
        analysis: BeatAnalysis | None = None,
        resolve_error: V2PersistenceError | None = None,
        analysis_error: BeatAnalysisError | None = None,
    ) -> None:
        self._path = path
        self._analysis = analysis or BeatAnalysis(
            bpm=120.0, beats=(0.0, 0.5, 1.0), confidence=0.7
        )
        self._resolve_error = resolve_error
        self._analysis_error = analysis_error
        self.resolved_asset_ids: list[str] = []
        self.analyzed_paths: list[str] = []
        # The endpoint reaches the analyzer as ``tools.analyzer.analyze``.
        self.analyzer = self

    def resolve_asset_path(self, asset_id: str) -> Path:
        self.resolved_asset_ids.append(asset_id)
        if self._resolve_error is not None:
            raise self._resolve_error
        assert self._path is not None
        return self._path

    def analyze(self, path: str) -> BeatAnalysis:
        self.analyzed_paths.append(path)
        if self._analysis_error is not None:
            raise self._analysis_error
        return self._analysis


@pytest.fixture
def client_factory():
    def build(timeline: TimelineV1, tools: _FakeTools) -> TestClient:
        app = FastAPI()
        app.include_router(timeline_endpoint.router)
        app.dependency_overrides[
            timeline_endpoint.get_timeline_repository
        ] = lambda: _FakeRepo(timeline)
        app.dependency_overrides[
            timeline_endpoint.get_beat_analysis_tools
        ] = lambda: tools
        return TestClient(app)

    return build


def test_returns_bpm_and_beats_for_linked_audio_clip(client_factory) -> None:
    tools = _FakeTools()
    client = client_factory(_timeline((_clip("clip-bgm"),)), tools)

    response = client.get("/workflows/wf-1/timeline/clips/clip-bgm/beats")

    assert response.status_code == 200
    assert response.json() == {
        "bpm": 120.0,
        "beats": [0.0, 0.5, 1.0],
        "confidence": 0.7,
    }
    assert tools.resolved_asset_ids == ["asset-bgm"]
    assert tools.analyzed_paths == ["bgm.wav"]


def test_unknown_clip_is_404(client_factory) -> None:
    client = client_factory(_timeline((_clip("clip-bgm"),)), _FakeTools())

    response = client.get("/workflows/wf-1/timeline/clips/missing/beats")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "timeline_clip_not_found"


def test_clip_without_asset_is_409(client_factory) -> None:
    client = client_factory(
        _timeline((_clip("clip-none", asset_id=None),)), _FakeTools()
    )

    response = client.get("/workflows/wf-1/timeline/clips/clip-none/beats")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "beat_analysis_no_asset"


def test_missing_asset_content_maps_to_404(client_factory) -> None:
    tools = _FakeTools(
        resolve_error=V2PersistenceError("asset_not_found", "Asset was not found.")
    )
    client = client_factory(_timeline((_clip("clip-bgm"),)), tools)

    response = client.get("/workflows/wf-1/timeline/clips/clip-bgm/beats")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "asset_not_found"


def test_too_short_audio_maps_to_422(client_factory) -> None:
    tools = _FakeTools(
        analysis_error=BeatAnalysisError(
            "beat_analysis_too_short", "Audio must be at least 2 seconds."
        )
    )
    client = client_factory(_timeline((_clip("clip-bgm"),)), tools)

    response = client.get("/workflows/wf-1/timeline/clips/clip-bgm/beats")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "beat_analysis_too_short"


def test_decoder_failure_maps_to_503(client_factory) -> None:
    tools = _FakeTools(
        analysis_error=BeatAnalysisError(
            "beat_analysis_unavailable", "ffmpeg could not decode the audio asset."
        )
    )
    client = client_factory(_timeline((_clip("clip-bgm"),)), tools)

    response = client.get("/workflows/wf-1/timeline/clips/clip-bgm/beats")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "beat_analysis_unavailable"

