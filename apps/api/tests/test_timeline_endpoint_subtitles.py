"""HTTP tests for timeline subtitle export and burn-in PATCH (Phase 3.3).

The timeline router is mounted on a minimal FastAPI app with the repository
dependency overridden by an in-memory fake, so these tests exercise routing,
serialization and response headers without a database.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v2.endpoints import timeline as timeline_endpoint
from app.schemas.timeline import (
    TimelineClipV1,
    TimelineTrackV1,
    TimelineV1,
)

_TS = "2026-09-18T00:00:00+00:00"


def _clip(
    clip_id: str,
    *,
    track_id: str = "track-subtitle",
    start_time: float,
    duration: float,
    text: str | None,
) -> TimelineClipV1:
    return TimelineClipV1(
        clip_id=clip_id,
        track_id=track_id,
        start_time=start_time,
        duration=duration,
        subtitle_text=text,
        created_at=_TS,
        updated_at=_TS,
    )


def _track(
    track_type: str,
    clips: tuple[TimelineClipV1, ...],
    *,
    muted: bool = False,
) -> TimelineTrackV1:
    return TimelineTrackV1(
        track_id=f"track-{track_type}",
        timeline_id="timeline-1",
        type=track_type,
        name=track_type,
        muted=muted,
        clips=clips,
        created_at=_TS,
        updated_at=_TS,
    )


class _FakeTimelineRepository:
    def __init__(self, timeline: TimelineV1) -> None:
        self._timeline = timeline
        self.update_timeline_calls: list[dict[str, Any]] = []

    def get_by_workflow_id(self, workflow_id: str) -> TimelineV1:
        return self._timeline

    def update_timeline(
        self, timeline_id: str, **kwargs: Any
    ) -> TimelineV1:
        self.update_timeline_calls.append({"timeline_id": timeline_id, **kwargs})
        updates = {
            key: value
            for key, value in kwargs.items()
            if value is not None and key in {"duration_seconds", "fps", "subtitle_burn_in"}
        }
        return self._timeline.model_copy(update=updates)


@pytest.fixture
def client_factory():
    def build(
        timeline: TimelineV1,
    ) -> tuple[TestClient, _FakeTimelineRepository]:
        fake_repo = _FakeTimelineRepository(timeline)
        app = FastAPI()
        app.include_router(timeline_endpoint.router)
        app.dependency_overrides[
            timeline_endpoint.get_timeline_repository
        ] = lambda: fake_repo
        return TestClient(app), fake_repo

    return build


@pytest.fixture
def client(
    request: pytest.FixtureRequest,
    client_factory,
) -> TestClient:
    test_client, _ = client_factory(request.param)
    return test_client


_SUBTITLE_TIMELINE = TimelineV1(
    timeline_id="timeline-1",
    workflow_id="wf-1",
    duration_seconds=10.0,
    fps=30,
    tracks=(
        _track(
            "subtitle",
            (
                _clip("c2", start_time=4.0, duration=1.0, text="Later line"),
                _clip("c1", start_time=0.0, duration=1.5, text="Hello\nworld"),
                _clip("c-empty", start_time=2.0, duration=1.0, text="   "),
            ),
        ),
    ),
    created_at=_TS,
    updated_at=_TS,
)


_WITH_SUBTITLES = pytest.mark.parametrize(
    "client", [_SUBTITLE_TIMELINE], indirect=True
)


class TestSubtitleExport:
    @_WITH_SUBTITLES
    def test_srt_download_is_sorted_sidecar(self, client: TestClient) -> None:
        response = client.get("/workflows/wf-1/timeline/subtitles?format=srt")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-subrip; charset=utf-8"
        assert (
            response.headers["content-disposition"]
            == 'attachment; filename="subtitles.srt"'
        )
        body = response.text
        # Empty/whitespace cues are dropped and cues are ordered by start.
        assert body.index("Hello") < body.index("Later line")
        assert "00:00:00,000 --> 00:00:01,500" in body
        assert "c-empty" not in body
        assert body.startswith("1\n")

    @_WITH_SUBTITLES
    def test_srt_is_the_default_format(self, client: TestClient) -> None:
        response = client.get("/workflows/wf-1/timeline/subtitles")
        assert response.status_code == 200
        assert response.headers["content-disposition"] == (
            'attachment; filename="subtitles.srt"'
        )

    @_WITH_SUBTITLES
    def test_ass_download_contains_styles(self, client: TestClient) -> None:
        response = client.get("/workflows/wf-1/timeline/subtitles?format=ass")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/x-ass; charset=utf-8"
        assert response.headers["content-disposition"] == (
            'attachment; filename="subtitles.ass"'
        )
        assert "[Script Info]" in response.text
        assert "[Events]" in response.text

    @_WITH_SUBTITLES
    def test_unknown_format_rejected(self, client: TestClient) -> None:
        response = client.get("/workflows/wf-1/timeline/subtitles?format=vtt")
        assert response.status_code == 422

    def test_muted_subtitle_track_excluded_from_export(self, client_factory) -> None:
        muted_timeline = TimelineV1(
            timeline_id="timeline-1",
            workflow_id="wf-1",
            duration_seconds=10.0,
            fps=30,
            tracks=(
                _track(
                    "subtitle",
                    (_clip("c1", start_time=0.0, duration=1.0, text="Hidden"),),
                    muted=True,
                ),
            ),
            created_at=_TS,
            updated_at=_TS,
        )
        muted_client, _ = client_factory(muted_timeline)

        response = muted_client.get(
            "/workflows/wf-1/timeline/subtitles?format=srt"
        )
        assert response.status_code == 200
        assert response.text == ""


def test_burn_in_false_is_forwarded_to_repository(client_factory) -> None:
    client, fake_repo = client_factory(_SUBTITLE_TIMELINE)
    response = client.patch(
        "/workflows/wf-1/timeline",
        json={"subtitle_burn_in": False},
    )

    assert response.status_code == 200
    assert response.json()["subtitle_burn_in"] is False
    assert fake_repo.update_timeline_calls == [
        {
            "timeline_id": "timeline-1",
            "duration_seconds": None,
            "fps": None,
            "subtitle_burn_in": False,
        }
    ]
