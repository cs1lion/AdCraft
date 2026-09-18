"""Tests for Timeline persistence and node -> clip auto-creation (ADR 0007).

Covers:
- TimelineRepository CRUD and default timeline auto-creation
- TimelineClipAutoCreator track mapping, append ordering and asset-duration
  backfill from asset_versions.duration_seconds
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.persistence.database import V2Database, create_v2_database
from app.persistence.errors import V2PersistenceError
from app.persistence.models import (
    AssetRow,
    AssetVersionRow,
    AgentCanvasWorkflowRow,
    ProjectRow,
)
from app.persistence.timeline_repository import TimelineRepository
from app.schemas.timeline import TimelineDuckingConfigV1
from app.services.timeline_clip_auto_creator import (
    AutoClipContext,
    TimelineClipAutoCreator,
)

pytestmark = pytest.mark.integration


_WORKFLOW_ID = "wf_timeline_test"
_PROJECT_ID = "proj_timeline_test"


@pytest.fixture
def database(v2_media_data_dir: Path) -> V2Database:
    db = create_v2_database(v2_media_data_dir)
    try:
        yield db
    finally:
        db.dispose()


def _seed_workflow(db: V2Database, workflow_id: str = _WORKFLOW_ID) -> None:
    with db.session_factory() as session:
        session.add(
            ProjectRow(
                project_id=_PROJECT_ID,
                name="Timeline Test Project",
                created_at="2026-09-17T00:00:00+00:00",
                updated_at="2026-09-17T00:00:00+00:00",
            )
        )
        session.flush()
        session.add(
            AgentCanvasWorkflowRow(
                workflow_id=workflow_id,
                project_id=_PROJECT_ID,
                created_at="2026-09-17T00:00:00+00:00",
                updated_at="2026-09-17T00:00:00+00:00",
            )
        )
        session.commit()


def _seed_asset(
    db: V2Database,
    *,
    asset_id: str,
    media_type: str,
    duration_seconds: float | None,
) -> None:
    with db.session_factory() as session:
        session.add(
            AssetRow(
                asset_id=asset_id,
                media_type=media_type,
                source_type="generated",
                display_name=f"Asset {asset_id}",
                created_at="2026-09-17T00:00:00+00:00",
                updated_at="2026-09-17T00:00:00+00:00",
            )
        )
        session.flush()
        session.add(
            AssetVersionRow(
                version_id=f"{asset_id}_v1",
                asset_id=asset_id,
                version_no=1,
                storage_key=f"media/{asset_id}.bin",
                sha256=f"sha256-{asset_id}",
                size_bytes=1024,
                mime_type=(
                    "audio/wav"
                    if media_type == "audio"
                    else "video/mp4"
                    if media_type == "video"
                    else "image/png"
                ),
                duration_seconds=duration_seconds,
                metadata_json="{}",
                created_at="2026-09-17T00:00:00+00:00",
            )
        )
        session.commit()


# ---------------------------------------------------------------------------
# TimelineRepository
# ---------------------------------------------------------------------------


class TestTimelineRepository:
    def test_get_auto_creates_six_ordered_tracks(self, database: V2Database) -> None:
        _seed_workflow(database)
        with database.session_factory() as session:
            repo = TimelineRepository(session)
            timeline = repo.get_by_workflow_id(_WORKFLOW_ID)

        assert timeline.workflow_id == _WORKFLOW_ID
        assert timeline.fps == 30
        assert [track.type for track in timeline.tracks] == [
            "video",
            "voice",
            "bgm",
            "sfx",
            "camera",
            "subtitle",
        ]

    def test_get_is_idempotent(self, database: V2Database) -> None:
        _seed_workflow(database)
        with database.session_factory() as session:
            first = TimelineRepository(session).get_by_workflow_id(_WORKFLOW_ID)
            first_id = first.timeline_id
            session.commit()
        with database.session_factory() as session:
            second = TimelineRepository(session).get_by_workflow_id(_WORKFLOW_ID)

        assert second.timeline_id == first_id
        assert len(second.tracks) == 6

    def test_add_clip_appends_and_extends_timeline_duration(
        self, database: V2Database
    ) -> None:
        _seed_workflow(database)
        with database.session_factory() as session:
            repo = TimelineRepository(session)
            timeline = repo.get_by_workflow_id(_WORKFLOW_ID)
            video_track = next(t for t in timeline.tracks if t.type == "video")

            first = repo.add_clip(
                track_id=video_track.track_id,
                start_time=0.0,
                duration=2.0,
                asset_id="asset_first",
                source_node_id="node_first",
            )
            second = repo.add_clip(
                track_id=video_track.track_id,
                start_time=repo.get_next_start_time_for_track(video_track.track_id),
                duration=5.0,
                asset_id="asset_second",
                source_node_id="node_second",
            )
            refreshed = repo.get_by_id(timeline.timeline_id)
            session.commit()

        assert first.start_time == 0.0
        assert second.start_time == 2.0
        assert refreshed.duration_seconds == 7.0
        video_clips = [
            c for t in refreshed.tracks if t.type == "video" for c in t.clips
        ]
        assert [c.source_node_id for c in video_clips] == [
            "node_first",
            "node_second",
        ]

    def test_update_move_and_delete_clip(self, database: V2Database) -> None:
        _seed_workflow(database)
        with database.session_factory() as session:
            repo = TimelineRepository(session)
            timeline = repo.get_by_workflow_id(_WORKFLOW_ID)
            video_track = next(t for t in timeline.tracks if t.type == "video")
            voice_track = next(t for t in timeline.tracks if t.type == "voice")
            clip = repo.add_clip(
                track_id=video_track.track_id,
                start_time=0.0,
                duration=3.0,
            )

            updated = repo.update_clip(
                clip.clip_id,
                start_time=1.5,
                duration=2.0,
                transition_in_type="fade",
                transition_in_duration=0.25,
            )
            moved = repo.move_clip(
                clip.clip_id,
                new_track_id=voice_track.track_id,
                new_start_time=4.0,
            )
            assert updated.transition_in_type == "fade"
            assert moved.track_id == voice_track.track_id
            assert moved.start_time == 4.0

            repo.delete_clip(clip.clip_id)
            assert repo.get_clips_for_track(voice_track.track_id) == []
            session.commit()

    def test_move_clip_rejects_unknown_or_foreign_track(self, database: V2Database) -> None:
        _seed_workflow(database)
        with database.session_factory() as session:
            repo = TimelineRepository(session)
            session.add(
                ProjectRow(
                    project_id="proj_timeline_test_other",
                    name="Timeline Test Project Other",
                    created_at="2026-09-17T00:00:00+00:00",
                    updated_at="2026-09-17T00:00:00+00:00",
                )
            )
            session.flush()
            session.add(
                AgentCanvasWorkflowRow(
                    workflow_id="wf_timeline_test_other",
                    project_id="proj_timeline_test_other",
                    created_at="2026-09-17T00:00:00+00:00",
                    updated_at="2026-09-17T00:00:00+00:00",
                )
            )
            session.flush()
            timeline = repo.get_by_workflow_id(_WORKFLOW_ID)
            video_track = next(t for t in timeline.tracks if t.type == "video")
            voice_track = next(t for t in timeline.tracks if t.type == "voice")
            clip = repo.add_clip(
                track_id=video_track.track_id,
                start_time=0.0,
                duration=3.0,
            )

            # A track id from another timeline must not accept the clip.
            other = repo.get_by_workflow_id("wf_timeline_test_other")
            other_video = next(t for t in other.tracks if t.type == "video")
            with pytest.raises(V2PersistenceError) as foreign_exc:
                repo.move_clip(
                    clip.clip_id,
                    new_track_id=other_video.track_id,
                    new_start_time=1.0,
                )
            assert foreign_exc.value.code == "timeline_track_not_found"

            # A completely made-up track id is rejected the same way.
            with pytest.raises(V2PersistenceError) as missing_exc:
                repo.move_clip(
                    clip.clip_id,
                    new_track_id="track_does_not_exist",
                    new_start_time=1.0,
                )
            assert missing_exc.value.code == "timeline_track_not_found"

            # Failed moves leave the clip on its original track and time.
            untouched = repo.get_clip(clip.clip_id)
            assert untouched.track_id == video_track.track_id
            assert untouched.start_time == pytest.approx(0.0)

            # A same-timeline cross-track move still succeeds.
            moved = repo.move_clip(
                clip.clip_id,
                new_track_id=voice_track.track_id,
                new_start_time=2.0,
            )
            assert moved.track_id == voice_track.track_id
            assert moved.start_time == pytest.approx(2.0)
            session.commit()

    def test_update_clip_explicit_null_clears_nullable_fields(
        self, database: V2Database
    ) -> None:
        _seed_workflow(database)
        with database.session_factory() as session:
            repo = TimelineRepository(session)
            timeline = repo.get_by_workflow_id(_WORKFLOW_ID)
            voice_track = next(t for t in timeline.tracks if t.type == "voice")
            clip = repo.add_clip(
                track_id=voice_track.track_id,
                start_time=0.0,
                duration=3.0,
                source_duration=2.5,
                fade_in=0.2,
                fade_out=0.3,
                label="Original label",
                color="#ff0000",
            )

            # Explicit None must clear the stored columns.
            cleared = repo.update_clip(
                clip.clip_id,
                fade_in=None,
                source_duration=None,
                label=None,
            )
            assert cleared.fade_in is None
            assert cleared.source_duration is None
            assert cleared.label is None
            # Fields not forwarded remain untouched.
            assert cleared.fade_out == pytest.approx(0.3)
            assert cleared.color == "#ff0000"

            # A subsequent update that omits the cleared fields keeps them NULL
            # and can still set a previously-cleared field again.
            relabeled = repo.update_clip(clip.clip_id, start_time=1.0, label="New label")
            assert relabeled.start_time == pytest.approx(1.0)
            assert relabeled.fade_in is None
            assert relabeled.source_duration is None
            assert relabeled.label == "New label"
            session.commit()

        with database.session_factory() as session:
            reloaded = TimelineRepository(session).get_clip(clip.clip_id)
        assert reloaded.fade_in is None
        assert reloaded.source_duration is None
        assert reloaded.label == "New label"
        assert reloaded.fade_out == pytest.approx(0.3)

    def test_update_clip_relinks_and_unlinks_source_node(
        self, database: V2Database
    ) -> None:
        _seed_workflow(database)
        with database.session_factory() as session:
            repo = TimelineRepository(session)
            timeline = repo.get_by_workflow_id(_WORKFLOW_ID)
            video_track = next(t for t in timeline.tracks if t.type == "video")
            # A manual clip starts life without a source node.
            clip = repo.add_clip(
                track_id=video_track.track_id,
                start_time=0.0,
                duration=3.0,
                label="Manual shot",
            )
            assert clip.source_node_id is None

            # Promote the clip: link it to a freshly created canvas node.
            linked = repo.update_clip(clip.clip_id, source_node_id="node_new_video")
            assert linked.source_node_id == "node_new_video"
            # Arrangement fields must survive the relink.
            assert linked.start_time == pytest.approx(0.0)
            assert linked.label == "Manual shot"

            # Unrelated positional updates must not sever the link.
            moved = repo.update_clip(clip.clip_id, start_time=4.0)
            assert moved.source_node_id == "node_new_video"
            assert moved.start_time == pytest.approx(4.0)

            # Explicit None unlinks (manual clip again).
            unlinked = repo.update_clip(clip.clip_id, source_node_id=None)
            assert unlinked.source_node_id is None
            assert unlinked.start_time == pytest.approx(4.0)
            session.commit()

        with database.session_factory() as session:
            reloaded = TimelineRepository(session).get_clip(clip.clip_id)
        assert reloaded.source_node_id is None

    def test_ducking_defaults_to_auto_none(self, database: V2Database) -> None:
        _seed_workflow(database)
        with database.session_factory() as session:
            timeline = TimelineRepository(session).get_by_workflow_id(_WORKFLOW_ID)

        assert timeline.ducking is None

    def test_ducking_settings_round_trip_and_explicit_reset(
        self, database: V2Database
    ) -> None:
        _seed_workflow(database)
        with database.session_factory() as session:
            repo = TimelineRepository(session)
            timeline = repo.get_by_workflow_id(_WORKFLOW_ID)

            configured = repo.update_timeline(
                timeline.timeline_id,
                ducking=TimelineDuckingConfigV1(
                    threshold_db=-22.0,
                    ratio=6.0,
                    attack_ms=30,
                    release_ms=350,
                    makeup_gain_db=2.0,
                ),
            )
            assert configured.ducking == TimelineDuckingConfigV1(
                threshold_db=-22.0,
                ratio=6.0,
                attack_ms=30,
                release_ms=350,
                makeup_gain_db=2.0,
            )

            # Omitting ducking on a later metadata PATCH must not clobber it.
            untouched = repo.update_timeline(timeline.timeline_id, fps=24)
            assert untouched.fps == 24
            assert untouched.ducking is not None
            assert untouched.ducking.threshold_db == -22.0

            # Explicit null resets to auto.
            reset = repo.update_timeline(timeline.timeline_id, ducking=None)
            assert reset.ducking is None
            session.commit()

        with database.session_factory() as session:
            reloaded = TimelineRepository(session).get_by_workflow_id(_WORKFLOW_ID)
        assert reloaded.fps == 24
        assert reloaded.ducking is None


# ---------------------------------------------------------------------------
# TimelineClipAutoCreator
# ---------------------------------------------------------------------------


def _make_creator(db: V2Database) -> TimelineClipAutoCreator:
    return TimelineClipAutoCreator(
        repository_factory=lambda: TimelineRepository(db.session_factory()),
        enabled=True,
    )


class TestTimelineClipAutoCreator:
    def test_track_type_mapping(self) -> None:
        creator = TimelineClipAutoCreator(
            repository_factory=lambda: None, enabled=True
        )

        def track_for(node_type: str, semantic_role: str | None = None) -> str | None:
            return creator.determine_track_type(
                AutoClipContext(
                    workflow_id="wf",
                    node_id="node",
                    node_type=node_type,
                    semantic_role=semantic_role,
                    output_asset_id=None,
                    output_asset_version_id=None,
                    title=None,
                )
            )

        assert track_for("video") == "video"
        assert track_for("voice-cast") == "voice"
        assert track_for("scene-3d") == "camera"
        assert track_for("audio", "bgm") == "bgm"
        assert track_for("audio", "sfx") == "sfx"
        assert track_for("audio") == "sfx"
        assert track_for("text") is None

    def test_voice_cast_clip_backfilled_from_asset_duration(
        self, database: V2Database
    ) -> None:
        _seed_workflow(database)
        _seed_asset(
            database,
            asset_id="asset_voice_1",
            media_type="audio",
            duration_seconds=4.25,
        )
        creator = _make_creator(database)

        clip_id = creator.create_clip_for_node(
            AutoClipContext(
                workflow_id=_WORKFLOW_ID,
                node_id="node_voice_1",
                node_type="voice-cast",
                semantic_role=None,
                output_asset_id="asset_voice_1",
                output_asset_version_id="asset_voice_1_v1",
                title="Character A line",
            )
        )

        assert clip_id is not None
        with database.session_factory() as session:
            timeline = TimelineRepository(session).get_by_workflow_id(_WORKFLOW_ID)
        voice_track = next(t for t in timeline.tracks if t.type == "voice")
        assert len(voice_track.clips) == 1
        clip = voice_track.clips[0]
        assert clip.clip_id == clip_id
        assert clip.duration == pytest.approx(4.25)
        assert clip.source_node_id == "node_voice_1"
        assert clip.asset_version_id == "asset_voice_1_v1"
        assert clip.label == "Character A line"

    def test_video_clip_appends_after_existing_with_real_duration(
        self, database: V2Database
    ) -> None:
        _seed_workflow(database)
        _seed_asset(
            database,
            asset_id="asset_video_1",
            media_type="video",
            duration_seconds=5.5,
        )
        with database.session_factory() as session:
            repo = TimelineRepository(session)
            timeline = repo.get_by_workflow_id(_WORKFLOW_ID)
            video_track = next(t for t in timeline.tracks if t.type == "video")
            repo.add_clip(
                track_id=video_track.track_id,
                start_time=0.0,
                duration=3.0,
            )
            session.commit()

        clip_id = _make_creator(database).create_clip_for_node(
            AutoClipContext(
                workflow_id=_WORKFLOW_ID,
                node_id="node_video_1",
                node_type="video",
                semantic_role=None,
                output_asset_id="asset_video_1",
                output_asset_version_id=None,
                title=None,
            )
        )

        with database.session_factory() as session:
            timeline = TimelineRepository(session).get_by_workflow_id(_WORKFLOW_ID)
        video_clips = [
            c for t in timeline.tracks if t.type == "video" for c in t.clips
        ]
        created = next(c for c in video_clips if c.clip_id == clip_id)
        assert created.start_time == pytest.approx(3.0)
        assert created.duration == pytest.approx(5.5)

    def test_asset_without_duration_falls_back_to_default(
        self, database: V2Database
    ) -> None:
        _seed_workflow(database)
        # A video asset whose provider never recorded a duration (e.g. legacy
        # rows) must fall back to the default clip length instead of failing.
        _seed_asset(
            database,
            asset_id="asset_video_unknown",
            media_type="video",
            duration_seconds=None,
        )

        clip_id = _make_creator(database).create_clip_for_node(
            AutoClipContext(
                workflow_id=_WORKFLOW_ID,
                node_id="node_video_unknown",
                node_type="video",
                semantic_role=None,
                output_asset_id="asset_video_unknown",
                output_asset_version_id=None,
                title=None,
            )
        )

        assert clip_id is not None
        with database.session_factory() as session:
            timeline = TimelineRepository(session).get_by_workflow_id(_WORKFLOW_ID)
        video_track = next(t for t in timeline.tracks if t.type == "video")
        assert video_track.clips[0].duration == pytest.approx(3.0)

    def test_unmapped_node_type_creates_nothing(self, database: V2Database) -> None:
        _seed_workflow(database)
        result = _make_creator(database).create_clip_for_node(
            AutoClipContext(
                workflow_id=_WORKFLOW_ID,
                node_id="node_text_1",
                node_type="text",
                semantic_role=None,
                output_asset_id=None,
                output_asset_version_id=None,
                title=None,
            )
        )
        assert result is None
        with database.session_factory() as session:
            timeline = TimelineRepository(session).get_by_workflow_id(_WORKFLOW_ID)
        assert all(track.clips == () for track in timeline.tracks)

    def test_node_rerun_refreshes_clip_without_duplicating(
        self, database: V2Database
    ) -> None:
        _seed_workflow(database)
        _seed_asset(
            database,
            asset_id="asset_rerun",
            media_type="video",
            duration_seconds=5.5,
        )
        creator = _make_creator(database)
        context = AutoClipContext(
            workflow_id=_WORKFLOW_ID,
            node_id="node_rerun",
            node_type="video",
            semantic_role=None,
            output_asset_id="asset_rerun",
            output_asset_version_id="asset_rerun_v1",
            title="Shot 1",
        )
        clip_id = creator.create_clip_for_node(context)
        assert clip_id is not None

        # The user arranges the clip (moves it, renames it) after generation.
        with database.session_factory() as session:
            TimelineRepository(session).update_clip(
                clip_id,
                start_time=10.0,
                label="My renamed shot",
            )
            session.commit()

        # Node rerun publishes a new 8s version under the same node.
        with database.session_factory() as session:
            session.add(
                AssetVersionRow(
                    version_id="asset_rerun_v2",
                    asset_id="asset_rerun",
                    version_no=2,
                    storage_key="media/asset_rerun_v2.bin",
                    sha256="sha256-asset_rerun-v2",
                    size_bytes=2048,
                    mime_type="video/mp4",
                    duration_seconds=8.0,
                    metadata_json="{}",
                    created_at="2026-09-18T00:00:00+00:00",
                )
            )
            session.commit()

        second_id = creator.create_clip_for_node(
            AutoClipContext(
                workflow_id=_WORKFLOW_ID,
                node_id="node_rerun",
                node_type="video",
                semantic_role=None,
                output_asset_id="asset_rerun",
                output_asset_version_id="asset_rerun_v2",
                title="Shot 1 regenerated",
            )
        )

        assert second_id == clip_id
        with database.session_factory() as session:
            timeline = TimelineRepository(session).get_by_workflow_id(_WORKFLOW_ID)
        video_track = next(t for t in timeline.tracks if t.type == "video")
        assert len(video_track.clips) == 1
        clip = video_track.clips[0]
        # Refreshed asset pointers + duration ...
        assert clip.asset_version_id == "asset_rerun_v2"
        assert clip.duration == pytest.approx(8.0)
        # ... but the user's arrangement is preserved.
        assert clip.start_time == pytest.approx(10.0)
        assert clip.label == "My renamed shot"
        assert timeline.duration_seconds == pytest.approx(18.0)

    def test_rerun_with_unknown_duration_keeps_arranged_length(
        self, database: V2Database
    ) -> None:
        _seed_workflow(database)
        _seed_asset(
            database,
            asset_id="asset_known",
            media_type="video",
            duration_seconds=5.5,
        )
        _seed_asset(
            database,
            asset_id="asset_no_duration",
            media_type="video",
            duration_seconds=None,
        )
        creator = _make_creator(database)

        creator.create_clip_for_node(
            AutoClipContext(
                workflow_id=_WORKFLOW_ID,
                node_id="node_dur",
                node_type="video",
                semantic_role=None,
                output_asset_id="asset_known",
                output_asset_version_id="asset_known_v1",
                title=None,
            )
        )
        # Rerun resolves to an asset version without recorded duration.
        creator.create_clip_for_node(
            AutoClipContext(
                workflow_id=_WORKFLOW_ID,
                node_id="node_dur",
                node_type="video",
                semantic_role=None,
                output_asset_id="asset_no_duration",
                output_asset_version_id="asset_no_duration_v1",
                title=None,
            )
        )

        with database.session_factory() as session:
            timeline = TimelineRepository(session).get_by_workflow_id(_WORKFLOW_ID)
        video_track = next(t for t in timeline.tracks if t.type == "video")
        assert len(video_track.clips) == 1
        clip = video_track.clips[0]
        assert clip.asset_id == "asset_no_duration"
        assert clip.duration == pytest.approx(5.5)

    def test_distinct_nodes_create_distinct_appended_clips(
        self, database: V2Database
    ) -> None:
        _seed_workflow(database)
        _seed_asset(
            database,
            asset_id="asset_a",
            media_type="video",
            duration_seconds=5.5,
        )
        _seed_asset(
            database,
            asset_id="asset_b",
            media_type="video",
            duration_seconds=4.0,
        )
        creator = _make_creator(database)

        creator.create_clip_for_node(
            AutoClipContext(
                workflow_id=_WORKFLOW_ID,
                node_id="node_a",
                node_type="video",
                semantic_role=None,
                output_asset_id="asset_a",
                output_asset_version_id="asset_a_v1",
                title=None,
            )
        )
        creator.create_clip_for_node(
            AutoClipContext(
                workflow_id=_WORKFLOW_ID,
                node_id="node_b",
                node_type="video",
                semantic_role=None,
                output_asset_id="asset_b",
                output_asset_version_id="asset_b_v1",
                title=None,
            )
        )

        with database.session_factory() as session:
            timeline = TimelineRepository(session).get_by_workflow_id(_WORKFLOW_ID)
        video_track = next(t for t in timeline.tracks if t.type == "video")
        assert [c.source_node_id for c in video_track.clips] == [
            "node_a",
            "node_b",
        ]
        assert [c.start_time for c in video_track.clips] == [
            pytest.approx(0.0),
            pytest.approx(5.5),
        ]


# ---------------------------------------------------------------------------
# Node-clip upsert timeline scoping
# ---------------------------------------------------------------------------


_WORKFLOW_ID_2 = "wf_timeline_test_2"
_PROJECT_ID_2 = "proj_timeline_test_2"


class TestNodeClipUpsertScoping:
    def test_upsert_is_scoped_per_timeline(self, database: V2Database) -> None:
        _seed_workflow(database)
        with database.session_factory() as session:
            session.add(
                ProjectRow(
                    project_id=_PROJECT_ID_2,
                    name="Timeline Test Project 2",
                    created_at="2026-09-17T00:00:00+00:00",
                    updated_at="2026-09-17T00:00:00+00:00",
                )
            )
            session.flush()
            session.add(
                AgentCanvasWorkflowRow(
                    workflow_id=_WORKFLOW_ID_2,
                    project_id=_PROJECT_ID_2,
                    created_at="2026-09-17T00:00:00+00:00",
                    updated_at="2026-09-17T00:00:00+00:00",
                )
            )
            session.commit()

        with database.session_factory() as session:
            repo = TimelineRepository(session)
            timeline_1 = repo.get_by_workflow_id(_WORKFLOW_ID)
            timeline_2 = repo.get_by_workflow_id(_WORKFLOW_ID_2)
            video_1 = next(t for t in timeline_1.tracks if t.type == "video")
            video_2 = next(t for t in timeline_2.tracks if t.type == "video")

            clip_1, created_1 = repo.upsert_auto_clip_for_node(
                timeline_id=timeline_1.timeline_id,
                source_node_id="node_shared",
                track_id=video_1.track_id,
                duration=2.0,
                asset_id="asset_1",
                asset_version_id=None,
                label="A",
            )
            clip_2, created_2 = repo.upsert_auto_clip_for_node(
                timeline_id=timeline_2.timeline_id,
                source_node_id="node_shared",
                track_id=video_2.track_id,
                duration=3.0,
                asset_id="asset_2",
                asset_version_id=None,
                label="B",
            )
            refreshed, created_3 = repo.upsert_auto_clip_for_node(
                timeline_id=timeline_1.timeline_id,
                source_node_id="node_shared",
                track_id=video_1.track_id,
                duration=9.0,
                asset_id="asset_1_new",
                asset_version_id=None,
                label="A replaced",
            )
            session.commit()

        assert created_1 is True
        assert created_2 is True
        assert created_3 is False
        assert clip_1.clip_id != clip_2.clip_id
        assert refreshed.clip_id == clip_1.clip_id
        assert refreshed.duration == pytest.approx(9.0)

        with database.session_factory() as session:
            repo = TimelineRepository(session)
            timeline_1 = repo.get_by_workflow_id(_WORKFLOW_ID)
            timeline_2 = repo.get_by_workflow_id(_WORKFLOW_ID_2)
            latest_1 = repo.get_latest_node_clip(
                timeline_1.timeline_id, "node_shared"
            )
            latest_2 = repo.get_latest_node_clip(
                timeline_2.timeline_id, "node_shared"
            )
            video_1 = next(t for t in timeline_1.tracks if t.type == "video")
            video_2 = next(t for t in timeline_2.tracks if t.type == "video")

        assert latest_1 is not None and latest_1.clip_id == clip_1.clip_id
        assert latest_2 is not None and latest_2.clip_id == clip_2.clip_id
        assert len(video_1.clips) == 1
        assert len(video_2.clips) == 1

    def test_promoted_manual_clip_is_upserted_in_place(
        self, database: V2Database
    ) -> None:
        """A manual clip linked to a new node is refreshed, not duplicated."""
        _seed_workflow(database)
        with database.session_factory() as session:
            repo = TimelineRepository(session)
            timeline = repo.get_by_workflow_id(_WORKFLOW_ID)
            video_track = next(t for t in timeline.tracks if t.type == "video")
            manual = repo.add_clip(
                track_id=video_track.track_id,
                start_time=6.0,
                duration=3.0,
                label="Manual slot",
            )
            repo.update_clip(manual.clip_id, source_node_id="node_promoted")

            refreshed, created = repo.upsert_auto_clip_for_node(
                timeline_id=timeline.timeline_id,
                source_node_id="node_promoted",
                track_id=video_track.track_id,
                duration=4.5,
                asset_id="asset_generated",
                asset_version_id=None,
                label="Generated label that must not win",
            )
            session.commit()

        assert created is False
        assert refreshed.clip_id == manual.clip_id
        # New media pointers/duration land on the existing clip...
        assert refreshed.asset_id == "asset_generated"
        assert refreshed.duration == pytest.approx(4.5)
        # ...while the user's arrangement (start time, label) is preserved.
        assert refreshed.start_time == pytest.approx(6.0)
        assert refreshed.label == "Manual slot"

        with database.session_factory() as session:
            video_track = next(
                t
                for t in TimelineRepository(session).get_by_workflow_id(
                    _WORKFLOW_ID
                ).tracks
                if t.type == "video"
            )
        assert len(video_track.clips) == 1
