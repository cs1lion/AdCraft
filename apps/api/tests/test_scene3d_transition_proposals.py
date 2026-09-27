"""Tests for transition-intent proposals (Scene A → Scene B).

Locks the contract the V0.2 research asks for: the creator gets several
readings of "how do we get from A to B", each priced honestly (feasible or
why not), each mapped to operations the already-tested motion presets can
execute, and nothing is auto-applied.
"""

from __future__ import annotations

import pytest

from app.schemas.scene_script import SceneCamera, SceneCharacter, SceneShot
from app.services.scene3d.transition_proposals import propose_transitions
from app.services.scene3d.speech_orchestration import SpeechSegment


def _character(character_id: str = "lin") -> SceneCharacter:
    return SceneCharacter(
        id=character_id,
        type="lowpoly_human",
        appearance={"color": "#E74C3C"},
        keyframes=[{"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}],
    )


def _camera(camera_id: str = "cam1") -> SceneCamera:
    return SceneCamera(
        id=camera_id,
        shot_type="wide",
        keyframes=[{"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]}],
    )


def _shot(shot_id: str, start: int, end: int, camera: str = "cam1") -> SceneShot:
    return SceneShot(id=shot_id, camera=camera, start_frame=start, end_frame=end)


class TestProposalCatalogue:
    def test_offers_the_six_readings_in_picker_order(self) -> None:
        proposals = propose_transitions(
            shot_a=_shot("s1", 0, 59),
            shot_b=_shot("s2", 60, 179),
            characters=[_character()],
            cameras=[_camera()],
            segments=[],
            frame_rate=30,
            scene_duration=6,
        )

        assert [proposal.id for proposal in proposals] == [
            "continuous_motion",
            "gaze_closeup",
            "sound_bridge",
            "cut_after_line",
            "time_jump",
            "angle_switch",
        ]
        by_id = {proposal.id: proposal for proposal in proposals}
        assert by_id["continuous_motion"].label == "连续运动"
        assert by_id["gaze_closeup"].label == "视线/特写切换"
        assert by_id["sound_bridge"].label == "声音桥（有意保留）"
        assert by_id["cut_after_line"].label == "说完再切"
        assert by_id["angle_switch"].feasible is True

    def test_every_proposal_serializes_with_its_rationale(self) -> None:
        proposals = propose_transitions(
            shot_a=_shot("s1", 0, 59),
            shot_b=_shot("s2", 60, 179),
            characters=[_character()],
            cameras=[_camera()],
            segments=[],
            frame_rate=30,
            scene_duration=6,
        )

        for proposal in proposals:
            payload = proposal.to_dict()
            assert payload["id"] == proposal.id
            assert payload["label"]
            assert payload["narrative"]
            assert payload["feasible"] is proposal.feasible
            for operation in payload["operations"]:
                assert operation["kind"]
                assert operation["rationale"]


class TestFeasibility:
    def test_continuous_motion_needs_a_character_with_keyframes(self) -> None:
        proposals = propose_transitions(
            shot_a=_shot("s1", 0, 59),
            shot_b=_shot("s2", 60, 179),
            characters=[],  # nobody to block
            cameras=[_camera()],
            segments=[],
            frame_rate=30,
            scene_duration=6,
        )
        proposal = next(p for p in proposals if p.id == "continuous_motion")

        assert proposal.feasible is False
        assert "关键帧" in (proposal.infeasible_reason or "")
        assert proposal.operations == ()

    def test_gaze_closeup_names_the_missing_camera(self) -> None:
        proposals = propose_transitions(
            shot_a=_shot("s1", 0, 59, camera="cam_missing"),
            shot_b=_shot("s2", 60, 179),
            characters=[_character()],
            cameras=[_camera("cam1")],
            segments=[],
            frame_rate=30,
            scene_duration=6,
        )
        proposal = next(p for p in proposals if p.id == "gaze_closeup")

        assert proposal.feasible is False
        assert "cam_missing" in (proposal.infeasible_reason or "")

    def test_time_jump_needs_a_pause_long_enough_to_hide_a_cut(self) -> None:
        # Dialogue runs wall to wall: no pause, no jump.
        proposals = propose_transitions(
            shot_a=_shot("s1", 0, 59),
            shot_b=_shot("s2", 60, 179),
            characters=[_character()],
            cameras=[_camera()],
            segments=[
                SpeechSegment(
                    segment_id="a",
                    character_id="lin",
                    text="第一句",
                    start_time=0.0,
                    end_time=2.5,
                ),
                SpeechSegment(
                    segment_id="b",
                    character_id="lin",
                    text="第二句",
                    start_time=2.6,
                    end_time=4.0,
                ),
                SpeechSegment(
                    segment_id="c",
                    character_id="lin",
                    text="第三句",
                    start_time=4.1,
                    end_time=6.0,
                ),
            ],
            frame_rate=30,
            scene_duration=6,
        )
        proposal = next(p for p in proposals if p.id == "time_jump")

        assert proposal.feasible is False
        assert "停顿" in (proposal.infeasible_reason or "")

    def test_time_jump_becomes_feasible_across_a_real_pause(self) -> None:
        proposals = propose_transitions(
            shot_a=_shot("s1", 0, 89),
            shot_b=_shot("s2", 90, 179),
            characters=[_character()],
            cameras=[_camera()],
            segments=[
                SpeechSegment(
                    segment_id="a",
                    character_id="lin",
                    text="第一句",
                    start_time=0.0,
                    end_time=1.0,
                ),
                SpeechSegment(
                    segment_id="b",
                    character_id="lin",
                    text="第二句",
                    start_time=4.0,
                    end_time=5.0,
                ),
            ],
            frame_rate=30,
            scene_duration=6,
        )
        proposal = next(p for p in proposals if p.id == "time_jump")

        assert proposal.feasible is True
        assert proposal.operations
        # The cut lands INSIDE the pause, not at its edge (the pause is 1–4s).
        cut_at = proposal.operations[0].at_seconds
        assert cut_at is not None and 1.0 <= cut_at <= 4.0


class TestOperationsMapToExecutablePresets:
    def test_continuous_motion_uses_the_walk_and_orbit_presets(self) -> None:
        proposals = propose_transitions(
            shot_a=_shot("s1", 0, 59),
            shot_b=_shot("s2", 60, 179),
            characters=[_character()],
            cameras=[_camera()],
            segments=[],
            frame_rate=30,
            scene_duration=6,
        )
        proposal = next(p for p in proposals if p.id == "continuous_motion")

        kinds = {operation.kind: operation for operation in proposal.operations}
        assert set(kinds) == {"character_preset", "camera_preset"}
        assert kinds["character_preset"].preset_id == "walk_to"
        assert kinds["character_preset"].character_id == "lin"
        assert kinds["camera_preset"].preset_id == "orbit_right"
        assert kinds["camera_preset"].camera_id == "cam1"
        # Both start inside shot A: the movement begins before the cut.
        assert kinds["character_preset"].start_frame == 0
        assert kinds["character_preset"].duration_frames == 45

    def test_gaze_closeup_pushes_in_before_the_cut_and_pans_after(self) -> None:
        proposals = propose_transitions(
            shot_a=_shot("s1", 0, 59),
            shot_b=_shot("s2", 60, 179),
            characters=[_character()],
            cameras=[_camera()],
            segments=[],
            frame_rate=30,
            scene_duration=6,
        )
        proposal = next(p for p in proposals if p.id == "gaze_closeup")

        push, pan = proposal.operations
        assert (push.preset_id, push.camera_id) == ("push_in", "cam1")
        assert push.start_frame < 59  # before the cut
        assert (pan.preset_id, pan.camera_id) == ("pan_right", "cam1")
        assert pan.start_frame == 60  # after the cut

    def test_angle_switch_is_a_placement_not_a_preset(self) -> None:
        proposals = propose_transitions(
            shot_a=_shot("s1", 0, 59),
            shot_b=_shot("s2", 60, 179),
            characters=[_character()],
            cameras=[_camera()],
            segments=[],
            frame_rate=30,
            scene_duration=6,
        )
        proposal = next(p for p in proposals if p.id == "angle_switch")

        assert proposal.operations[0].kind == "camera_place"
        assert proposal.operations[0].camera_id == "cam1"


# ---------------------------------------------------------------------------
# The sound-bridge family: the executable landing of the advisor's remedy
# ---------------------------------------------------------------------------


def _crossing_line(
    start: float, end: float, text: str = "你终于来了"
) -> SpeechSegment:
    return SpeechSegment(
        segment_id="cross",
        character_id="lin",
        text=text,
        start_time=start,
        end_time=end,
    )


class TestSoundBridgeFamily:
    """A line crossing the cut is the advisor's ``line_crosses_cut`` finding.

    These three readings are what its remedy actually offers (keep it as an
    L-cut / postpone the cut / cut in the pause), so they must be feasible
    exactly when a line crosses — and honestly priced when none does.
    """

    def _proposals(self, segments: list[SpeechSegment]) -> dict[str, object]:
        proposals = propose_transitions(
            shot_a=_shot("s1", 0, 89),  # the cut sits at 3.0s
            shot_b=_shot("s2", 90, 179),
            characters=[_character()],
            cameras=[_camera()],
            segments=segments,
            frame_rate=30,
            scene_duration=6,
        )
        return {proposal.id: proposal for proposal in proposals}

    def test_keep_the_cut_is_a_choice_with_zero_operations(self) -> None:
        by_id = self._proposals([_crossing_line(2.6, 3.8)])

        bridge = by_id["sound_bridge"]
        assert bridge.feasible is True
        # Zero operations is the honest price: nothing structural changes,
        # the creator is confirming intent (V0.2 §14.13 声音先到).
        assert bridge.operations == ()
        assert "声音" in bridge.narrative

    def test_postpone_the_cut_moves_it_to_where_the_line_ends(self) -> None:
        by_id = self._proposals([_crossing_line(2.6, 3.8)])

        after = by_id["cut_after_line"]
        assert after.feasible is True
        assert len(after.operations) == 1
        operation = after.operations[0]
        assert operation.kind == "cut"
        assert operation.at_seconds == 3.8
        assert operation.shot_id == "s2"

    def test_the_pause_reading_stays_available_alongside(self) -> None:
        by_id = self._proposals(
            [
                SpeechSegment(
                    segment_id="a",
                    character_id="lin",
                    text="第一句",
                    start_time=0.0,
                    end_time=2.6,
                ),
                _crossing_line(2.6, 3.8),
            ]
        )

        assert by_id["time_jump"].feasible is True

    def test_without_a_crossing_line_the_family_is_infeasible_with_reasons(self) -> None:
        by_id = self._proposals(
            [
                SpeechSegment(
                    segment_id="a",
                    character_id="lin",
                    text="第一句",
                    start_time=0.0,
                    end_time=1.0,
                ),
                SpeechSegment(
                    segment_id="b",
                    character_id="lin",
                    text="第二句",
                    start_time=4.0,
                    end_time=5.0,
                ),
            ]
        )

        for proposal_id in ("sound_bridge", "cut_after_line"):
            proposal = by_id[proposal_id]
            assert proposal.feasible is False, proposal_id
            assert proposal.infeasible_reason
            assert proposal.operations == ()

    def test_without_segments_at_all_the_family_is_infeasible(self) -> None:
        by_id = self._proposals([])

        for proposal_id in ("sound_bridge", "cut_after_line"):
            proposal = by_id[proposal_id]
            assert proposal.feasible is False, proposal_id
            assert proposal.infeasible_reason

    def test_postponing_past_the_shots_own_end_is_refused_loudly(self) -> None:
        # The line runs past the END of shot B: postponing the cut would
        # swallow the whole shot. The reading stays visible, priced honestly.
        by_id = self._proposals([_crossing_line(2.6, 7.5)])

        after = by_id["cut_after_line"]
        assert after.feasible is False
        assert "吃掉" in (after.infeasible_reason or "")
        assert after.operations == ()

    def test_the_earliest_crossing_line_drives_the_readings(self) -> None:
        by_id = self._proposals(
            [_crossing_line(4.2, 5.1, "第二句"), _crossing_line(2.6, 3.8)]
        )

        after = by_id["cut_after_line"]
        assert after.feasible is True
        assert after.operations[0].at_seconds == 3.8  # the 2.6–3.8 line


# ---------------------------------------------------------------------------
# HTTP endpoint (the shot inspector asks for proposals)
# ---------------------------------------------------------------------------

def _script_for_endpoint() -> dict[str, object]:
    return {
        "scene": {"name": "lab", "environment": "indoor", "lighting": "cool", "duration": 6, "frame_rate": 30},
        "characters": [_character().model_dump(mode="json")],
        "props": [],
        "environment": [],
        "cameras": [_camera().model_dump(mode="json")],
        "shots": [
            _shot("s1", 0, 59).model_dump(mode="json"),
            _shot("s2", 60, 179).model_dump(mode="json"),
        ],
        "speech_bindings": [],
    }


def test_endpoint_returns_proposals_and_honors_unknown_shots() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    response = client.post(
        "/scene-3d/transition-proposals",
        json={
            "scene_script": _script_for_endpoint(),
            "shot_a_id": "s1",
            "shot_b_id": "s2",
            "segments": [
                {"segment_id": "a", "character_id": "lin", "text": "第一句", "start_time": 0, "end_time": 1},
                {"segment_id": "b", "character_id": "lin", "text": "第二句", "start_time": 4, "end_time": 5},
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["warnings"] == []
    # With a 1–4s pause the time-jump reading becomes available.
    time_jump = next(p for p in body["proposals"] if p["id"] == "time_jump")
    assert time_jump["feasible"] is True
    assert time_jump["operations"][0]["kind"] == "cut"

    missing = client.post(
        "/scene-3d/transition-proposals",
        json={"scene_script": _script_for_endpoint(), "shot_a_id": "nope", "shot_b_id": "s2"},
    )
    assert missing.status_code == 404


def test_endpoint_offers_the_sound_bridge_family_across_a_crossing_line() -> None:
    """The advisor's remedy, executable: a line crossing the cut makes the
    keep-it (L-cut) and postpone readings available over HTTP."""

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    response = client.post(
        "/scene-3d/transition-proposals",
        json={
            "scene_script": _script_for_endpoint(),
            "shot_a_id": "s1",
            "shot_b_id": "s2",
            # 1.0–3.0s crosses the 2.0s boundary (frame 59/60).
            "segments": [
                {"segment_id": "a", "character_id": "lin", "text": "你终于来了", "start_time": 1.0, "end_time": 3.0},
            ],
        },
    )
    assert response.status_code == 200, response.text
    by_id = {proposal["id"]: proposal for proposal in response.json()["proposals"]}

    assert by_id["sound_bridge"]["feasible"] is True
    assert by_id["sound_bridge"]["operations"] == []
    assert by_id["cut_after_line"]["feasible"] is True
    assert by_id["cut_after_line"]["operations"][0]["at_seconds"] == 3.0


def test_endpoint_survives_malformed_segments() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    # A non-dict segment is rejected by the schema — loud, not silent.
    rejected = client.post(
        "/scene-3d/transition-proposals",
        json={
            "scene_script": _script_for_endpoint(),
            "shot_a_id": "s1",
            "shot_b_id": "s2",
            "segments": ["garbage"],
        },
    )
    assert rejected.status_code == 422

    # A dict-shaped segment with an unusable VALUE degrades in-handler: the
    # entry is skipped, the warning names it, and the proposals still arrive.
    response = client.post(
        "/scene-3d/transition-proposals",
        json={
            "scene_script": _script_for_endpoint(),
            "shot_a_id": "s1",
            "shot_b_id": "s2",
            "segments": [{"text": "x", "start_time": "soon"}],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["warnings"]
    assert len(body["proposals"]) == 6


# ---------------------------------------------------------------------------
# Animatic mux on the render endpoints (V0.2 §14.9 成片侧)
# ---------------------------------------------------------------------------


def _render_script() -> dict[str, object]:
    return {
        "scene": {"name": "lab", "environment": "indoor", "lighting": "cool", "duration": 6, "frame_rate": 30},
        "characters": [
            {
                "id": "lin",
                "type": "lowpoly_human",
                "appearance": {"color": "#E74C3C"},
                "keyframes": [{"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}],
            }
        ],
        "props": [],
        "environment": [],
        "cameras": [
            {"id": "cam1", "shot_type": "wide", "keyframes": [{"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]}]}
        ],
        "shots": [{"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 179}],
        "speech_bindings": [],
    }


def _stub_render_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path, *, mux_success: bool = True) -> list[tuple[str, str, str]]:
    """Stub Blender + ffmpeg so the endpoint can run without either."""

    from dataclasses import dataclass

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    calls: list[tuple[str, str, str]] = []

    @dataclass
    class _Capability:
        state: str = "ready"
        error: str | None = None

    @dataclass
    class _RenderResult:
        success: bool = True
        frame_count: int = 2
        duration_seconds: float = 2.0
        blender_version: str = "Blender 5.2"
        rendered_frames: str = "animation"
        degraded_assets: tuple[str, ...] = ()
        error: str | None = None

    @dataclass
    class _EncodeResult:
        success: bool = True
        output_path: str | None = None
        frame_count: int = 2
        error: str | None = None

    @dataclass
    class _MuxResult:
        success: bool
        output_path: str | None = None
        error: str | None = None

    def _encoder(input_dir: str, output_path: str, fps: int = 30):
        from pathlib import Path

        Path(output_path).write_bytes(b"SILENT")
        return _EncodeResult()

    def _muxer(video_path: str, audio_path: str, output_path: str):
        from pathlib import Path

        calls.append((video_path, audio_path, output_path))
        if mux_success:
            Path(output_path).write_bytes(b"ANIMATIC")
            return _MuxResult(success=True, output_path=output_path)
        return _MuxResult(success=False, error="mux boom")

    monkeypatch.setattr(scene_3d_endpoint, "get_blender_capability", lambda executable=None: _Capability())
    monkeypatch.setattr(scene_3d_endpoint, "render_scene_script", lambda script, frames_dir, **kwargs: _RenderResult())
    monkeypatch.setattr(scene_3d_endpoint, "encode_png_sequence", _encoder)
    monkeypatch.setattr(scene_3d_endpoint, "mux_audio_to_video", _muxer)
    return calls


def test_render_endpoint_muxes_the_bed_into_the_animatic(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    bed = tmp_path / "bed.mp3"
    bed.write_bytes(b"ID3fake")
    calls = _stub_render_pipeline(monkeypatch, tmp_path)

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)
    response = client.post(
        "/scene-3d/render",
        json={"scene_script": _render_script(), "audio_path": str(bed)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["audio_muxed"] is True
    assert body["animatic_video_path"].endswith("previs_animatic.mp4")
    assert body["warnings"] == []
    assert len(calls) == 1
    assert calls[0][1] == str(bed)


def test_render_endpoint_reports_a_failed_mux_without_failing_the_render(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    bed = tmp_path / "bed.mp3"
    bed.write_bytes(b"ID3fake")
    _stub_render_pipeline(monkeypatch, tmp_path, mux_success=False)

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)
    response = client.post(
        "/scene-3d/render",
        json={"scene_script": _render_script(), "audio_path": str(bed)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # The silent previs still ships; the reason is reported.
    assert body["success"] is True
    assert body["audio_muxed"] is False
    assert body["animatic_video_path"] is None
    assert any("混入失败" in warning for warning in body["warnings"])


def test_render_endpoint_reports_a_missing_bed_instead_of_failing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    _stub_render_pipeline(monkeypatch, tmp_path)

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)
    response = client.post(
        "/scene-3d/render",
        json={
            "scene_script": _render_script(),
            "audio_path": str(tmp_path / "nope.mp3"),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["audio_muxed"] is False
    assert any("音频床不可用" in warning for warning in body["warnings"])


def test_render_endpoint_without_a_bed_renders_silently(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    calls = _stub_render_pipeline(monkeypatch, tmp_path)

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)
    response = client.post(
        "/scene-3d/render", json={"scene_script": _render_script()}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["audio_muxed"] is False
    assert body["animatic_video_path"] is None
    assert calls == []  # no mux attempted when no bed was offered


def _shot_with_intent(*, shot_id: str, start: int, end: int, intent: str | None) -> dict[str, object]:
    shot = _shot(shot_id, start, end).model_dump(mode="json")
    if intent is not None:
        shot["transition_intent"] = intent
    return shot


def _declared_intent(client, payload: dict[str, object]) -> dict[str, object]:
    response = client.post("/scene-3d/transition-proposals", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["intent_audit"]


class TestDeclaredIntentAudit:
    """V0.2 §13 第 5 问: once the relation is recorded it must be checkable.

    A declaration outlives the timeline it was made against — the author
    re-times the dialogue or moves the cut, and the label keeps saying
    "声音桥" while the scene says otherwise. Nothing else would notice.
    """

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

        app = FastAPI()
        app.include_router(scene_3d_endpoint.router)
        return TestClient(app)

    def _script(self, *, intent: str | None) -> dict[str, object]:
        return {
            "scene": {
                "name": "lab",
                "environment": "indoor",
                "lighting": "cool",
                "duration": 6,
                "frame_rate": 30,
            },
            "characters": [_character().model_dump(mode="json")],
            "props": [],
            "environment": [],
            "cameras": [_camera().model_dump(mode="json")],
            "shots": [
                _shot("s1", 0, 59).model_dump(mode="json"),
                _shot_with_intent(shot_id="s2", start=60, end=179, intent=intent),
            ],
            "speech_bindings": [],
        }

    def test_nothing_declared_is_not_a_defect(self) -> None:
        audit = _declared_intent(
            self._client(),
            {
                "scene_script": self._script(intent=None),
                "shot_a_id": "s1",
                "shot_b_id": "s2",
            },
        )
        assert audit["declared"] is None
        assert audit["holds"] is None

    def test_a_declared_reading_that_still_holds_is_confirmed(self) -> None:
        # continuous_motion only needs a keyframed character: it holds here.
        audit = _declared_intent(
            self._client(),
            {
                "scene_script": self._script(intent="continuous_motion"),
                "shot_a_id": "s1",
                "shot_b_id": "s2",
            },
        )
        assert audit["declared"] == "continuous_motion"
        assert audit["holds"] is True
        assert audit["label"] == "连续运动"
        assert audit["reason"] is None

    def test_a_declared_reading_the_scene_can_no_longer_pay_for_is_flagged(self) -> None:
        # gaze_closeup is feasible with the lab camera, so an INFEASIBLE
        # declaration needs a reading the scene cannot pay for: with no
        # speech crossing the cut, 声音桥 is exactly that.
        audit = _declared_intent(
            self._client(),
            {
                "scene_script": self._script(intent="sound_bridge"),
                "shot_a_id": "s1",
                "shot_b_id": "s2",
            },
        )
        assert audit["holds"] is False
        assert audit["reason"]
        assert audit["remedy"]

    def test_a_reading_that_left_the_catalogue_is_flagged_with_the_reason(self) -> None:
        audit = _declared_intent(
            self._client(),
            {
                "scene_script": self._script(intent="llm_overhead_match_cut"),
                "shot_a_id": "s1",
                "shot_b_id": "s2",
            },
        )
        assert audit["declared"] == "llm_overhead_match_cut"
        assert audit["holds"] is False
        assert "不在当前这一对的读法目录里" in audit["reason"]

    def test_the_boundary_between_the_pair_and_its_purpose(self) -> None:
        """The audit is computed for the shot B the caller named — never for
        the first shot in the script (a first shot has no entry)."""
        script = self._script(intent="continuous_motion")
        audit = _declared_intent(
            self._client(),
            {"scene_script": script, "shot_a_id": "s2", "shot_b_id": "s1"},
        )
        # s1 declares nothing: asking about it must not inherit s2's answer.
        assert audit["declared"] is None
