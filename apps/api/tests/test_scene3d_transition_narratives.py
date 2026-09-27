"""Tests for the LLM narrative layer of transition proposals (V0.2 §6.2/§15).

Locks the contract that makes an LLM advisory safe to ship:
* the LLM only rewrites narrative prose (operations untouched);
* partial coverage degrades per-proposal (unexplained readings keep their
  rule text);
* any LLM trouble degrades WITH a reported reason (engineering standard §4);
* the parser is fence-tolerant and refuses to invent ids.
"""

from __future__ import annotations

import pytest

from app.schemas.scene_script import SceneCamera, SceneCharacter, SceneShot
from app.services.scene3d.transition_narratives import (
    NarrativePolishUnavailable,
    apply_polished_narratives,
    build_narrative_prompt,
    parse_narrative_response,
    polish_transition_narratives,
)
from app.services.scene3d.transition_proposals import (
    TransitionProposal,
    propose_transitions,
)
from app.services.scene3d.speech_orchestration import SpeechSegment


def _proposals() -> list[TransitionProposal]:
    return propose_transitions(
        shot_a=SceneShot(id="s1", camera="cam1", start_frame=0, end_frame=89),
        shot_b=SceneShot(id="s2", camera="cam1", start_frame=90, end_frame=179),
        characters=[
            SceneCharacter(
                id="lin",
                type="lowpoly_human",
                appearance={"color": "#E74C3C"},
                keyframes=[{"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}],
            )
        ],
        cameras=[
            SceneCamera(
                id="cam1",
                shot_type="wide",
                keyframes=[{"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]}],
            )
        ],
        segments=[
            SpeechSegment(
                segment_id="a",
                character_id="lin",
                text="你终于来了",
                start_time=1.0,
                end_time=3.0,
            )
        ],
        frame_rate=30,
        scene_duration=6,
    )


class TestPrompt:
    def test_the_prompt_carries_the_pair_and_every_reading(self) -> None:
        proposals = _proposals()
        system_prompt, user_text = build_narrative_prompt(
            shot_a_id="s1",
            shot_b_id="s2",
            proposals=proposals,
        )
        assert "导演" in system_prompt
        for proposal in proposals:
            assert proposal.id in user_text
            assert proposal.label in user_text
        assert "s1" in user_text and "s2" in user_text


class TestParse:
    def test_parses_plain_json(self) -> None:
        parsed = parse_narrative_response('{"narratives": {"sound_bridge": "声音先到。"}}')
        assert parsed == {"sound_bridge": "声音先到。"}

    def test_parses_fenced_json(self) -> None:
        parsed = parse_narrative_response(
            '前言\n```json\n{"narratives": {"time_jump": "切在停顿里。"}}\n```\n后记'
        )
        assert parsed == {"time_jump": "切在停顿里。"}

    def test_garbage_yields_an_empty_map(self) -> None:
        assert parse_narrative_response("not json at all") == {}
        assert parse_narrative_response("") == {}

    def test_empty_strings_are_dropped(self) -> None:
        parsed = parse_narrative_response('{"narratives": {"sound_bridge": "   "}}')
        assert parsed == {}


class TestApply:
    def test_only_narratives_change_operations_are_untouched(self) -> None:
        proposals = _proposals()
        before = {proposal.id: proposal.operations for proposal in proposals}
        merged = apply_polished_narratives(
            proposals,
            {"continuous_motion": "人物带过画面切换。"},
        )
        after = {proposal.id: proposal.operations for proposal in merged}
        assert after == before
        by_id = {proposal.id: proposal for proposal in merged}
        assert by_id["continuous_motion"].narrative == "人物带过画面切换。"
        # Uncovered readings keep their rule narrative.
        assert by_id["gaze_closeup"].narrative == proposals[1].narrative

    def test_unknown_ids_are_ignored(self) -> None:
        proposals = _proposals()
        merged = apply_polished_narratives(proposals, {"no_such_reading": "x"})
        assert all(
            merged[index].narrative == proposals[index].narrative
            for index in range(len(proposals))
        )


class TestPolish:
    def test_a_successful_polish_marks_the_source(self) -> None:
        proposals = _proposals()
        result = polish_transition_narratives(
            shot_a_id="s1",
            shot_b_id="s2",
            proposals=proposals,
            llm_call=lambda system, user: '{"narratives": {"sound_bridge": "声音先到，画面后到。"}}',
        )
        assert result.source == "llm"
        assert result.polished_ids == ("sound_bridge",)
        assert result.degraded_reason is None
        by_id = {proposal.id: proposal for proposal in result.proposals}
        assert by_id["sound_bridge"].narrative == "声音先到，画面后到。"

    def test_a_missing_llm_configuration_degrades_with_a_reason(self) -> None:
        proposals = _proposals()

        def unavailable(system: str, user: str) -> str:
            raise NarrativePolishUnavailable("LLM 未配置")

        result = polish_transition_narratives(
            shot_a_id="s1",
            shot_b_id="s2",
            proposals=proposals,
            llm_call=unavailable,
        )
        assert result.source == "rules"
        assert result.degraded_reason == "LLM 未配置"
        assert result.proposals == proposals  # untouched

    def test_unparsable_output_degrades_with_a_reason(self) -> None:
        proposals = _proposals()
        result = polish_transition_narratives(
            shot_a_id="s1",
            shot_b_id="s2",
            proposals=proposals,
            llm_call=lambda system, user: "我不会 JSON",
        )
        assert result.source == "rules"
        assert "JSON" in (result.degraded_reason or "")
        assert result.proposals == proposals

    def test_an_empty_narratives_object_degrades_with_a_reason(self) -> None:
        proposals = _proposals()
        result = polish_transition_narratives(
            shot_a_id="s1",
            shot_b_id="s2",
            proposals=proposals,
            llm_call=lambda system, user: '{"narratives": {}}',
        )
        assert result.source == "rules"
        assert result.degraded_reason
        assert result.proposals == proposals


# ---------------------------------------------------------------------------
# HTTP endpoint: the flag, the polish, and the honest degradation
# ---------------------------------------------------------------------------


def _script_for_endpoint() -> dict[str, object]:
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
        "shots": [
            {"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 89},
            {"id": "s2", "camera": "cam1", "start_frame": 90, "end_frame": 179},
        ],
        "speech_bindings": [],
    }


def test_endpoint_polishes_narratives_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    monkeypatch.setattr(
        "app.services.scene3d.transition_narratives.default_llm_call",
        lambda system, user: '{"narratives": {"sound_bridge": "声音先到，画面后到。"}}',
    )
    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    response = client.post(
        "/scene-3d/transition-proposals",
        json={
            "scene_script": _script_for_endpoint(),
            "shot_a_id": "s1",
            "shot_b_id": "s2",
            "polish_narratives": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["narrative_source"] == "llm"
    by_id = {proposal["id"]: proposal for proposal in body["proposals"]}
    assert by_id["sound_bridge"]["narrative"] == "声音先到，画面后到。"


def test_endpoint_reports_the_degradation_instead_of_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint
    from app.services.scene3d import transition_narratives

    def unavailable(system: str, user: str) -> str:
        raise transition_narratives.NarrativePolishUnavailable("LLM 未配置（测试）")

    monkeypatch.setattr(transition_narratives, "default_llm_call", unavailable)
    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    response = client.post(
        "/scene-3d/transition-proposals",
        json={
            "scene_script": _script_for_endpoint(),
            "shot_a_id": "s1",
            "shot_b_id": "s2",
            "polish_narratives": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # The readings still arrive, on rule narratives, with the reason said.
    assert body["narrative_source"] == "rules"
    assert len(body["proposals"]) == 6
    assert any("LLM 未配置" in warning for warning in body["warnings"])


def test_endpoint_defaults_to_rule_narratives() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint
    from app.services.scene3d import transition_narratives

    called = {"count": 0}

    def counting_call(system: str, user: str) -> str:
        called["count"] += 1
        return "{}"

    # The seam is patched, so a call would be visible: the default must be NO
    # LLM traffic unless the flag asks for it.
    original = transition_narratives.default_llm_call
    transition_narratives.default_llm_call = counting_call
    try:
        app = FastAPI()
        app.include_router(scene_3d_endpoint.router)
        client = TestClient(app)

        response = client.post(
            "/scene-3d/transition-proposals",
            json={
                "scene_script": _script_for_endpoint(),
                "shot_a_id": "s1",
                "shot_b_id": "s2",
            },
        )
    finally:
        transition_narratives.default_llm_call = original

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["narrative_source"] == "rules"
    assert called["count"] == 0


# ---------------------------------------------------------------------------
# Role 2: LLM-proposed readings, validated fail-closed (V0.2 §15 deepening)
# ---------------------------------------------------------------------------

from app.services.scene3d.transition_narratives import (  # noqa: E402
    CAMERA_MOTION_PRESET_IDS,
    CHARACTER_MOTION_PRESET_IDS,
    SceneVocabulary,
    build_proposal_prompt,
    parse_proposed_readings,
    propose_additional_readings,
    validate_proposed_reading,
)


def _vocabulary() -> SceneVocabulary:
    return SceneVocabulary.from_scene(
        shots=[
            SceneShot(id="s1", camera="cam1", start_frame=0, end_frame=89),
            SceneShot(id="s2", camera="cam1", start_frame=90, end_frame=179),
        ],
        characters=[
            SceneCharacter(
                id="lin",
                type="lowpoly_human",
                appearance={"color": "#E74C3C"},
                keyframes=[{"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}],
            )
        ],
        cameras=[
            SceneCamera(
                id="cam1",
                shot_type="wide",
                keyframes=[{"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]}],
            )
        ],
        # The rule catalogue's ids are reserved: an LLM reading may not
        # impersonate one.
        reserved_ids=[
            "continuous_motion",
            "gaze_closeup",
            "sound_bridge",
            "cut_after_line",
            "time_jump",
            "angle_switch",
        ],
    )


def _reading(reading_id: str = "shadow_pass", **overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": reading_id,
        "label": "剪影过渡",
        "narrative": "主体化作剪影，光替它完成转场。",
        "operations": [
            {"kind": "camera_preset", "preset_id": "push_in", "camera_id": "cam1"},
        ],
    }
    payload.update(overrides)
    return payload


class TestPresetVocabularyParity:
    def test_the_vocabulary_matches_the_frontend_catalogues(self) -> None:
        # Parity contract with cameraMotionPresets.ts (8) and
        # characterMotionPresets.ts (4) — the same ids are pinned on the web
        # side by characterMotionPresets.test.ts / cameraMotionPresets.test.ts.
        assert CAMERA_MOTION_PRESET_IDS == {
            "push_in",
            "pull_out",
            "orbit_left",
            "orbit_right",
            "pan_left",
            "pan_right",
            "crane_up",
            "crane_down",
        }
        assert CHARACTER_MOTION_PRESET_IDS == {"walk_to", "turn_to", "approach", "mark_talk"}


class TestProposalPrompt:
    def test_the_prompt_hands_the_llm_the_vocabulary_and_the_scene(self) -> None:
        system_prompt, user_text = build_proposal_prompt(
            shot_a_id="s1",
            shot_b_id="s2",
            vocabulary=_vocabulary(),
            existing_labels=["连续运动"],
        )
        assert "补充规则目录之外" in system_prompt
        assert '"push_in"' in user_text
        assert '"mark_talk"' in user_text
        assert '"cam1"' in user_text
        assert '"s2"' in user_text
        assert "连续运动" in user_text


class TestProposalParsing:
    def test_parses_the_readings_list(self) -> None:
        parsed = parse_proposed_readings('{"readings": [{"id": "a", "label": "b", "narrative": "c"}]}')
        assert parsed == [{"id": "a", "label": "b", "narrative": "c"}]

    def test_parses_fenced_json(self) -> None:
        parsed = parse_proposed_readings('```json\n{"readings": [{"id": "a"}]}\n```')
        assert parsed == [{"id": "a"}]

    def test_garbage_and_emptiness_yield_no_readings(self) -> None:
        assert parse_proposed_readings("不会 JSON") == []
        assert parse_proposed_readings('{"readings": []}') == []


class TestProposalValidation:
    def test_a_well_formed_reading_is_accepted_with_llm_origin(self) -> None:
        proposal, reason = validate_proposed_reading(
            _reading(), _vocabulary(), taken_ids=frozenset()
        )
        assert reason is None
        assert proposal is not None
        assert proposal.id == "shadow_pass"
        assert proposal.origin == "llm"
        assert proposal.feasible is True
        assert proposal.operations[0].preset_id == "push_in"

    def test_an_impersonated_rule_id_is_refused(self) -> None:
        proposal, reason = validate_proposed_reading(
            _reading("sound_bridge"), _vocabulary(), taken_ids=frozenset()
        )
        assert proposal is None
        assert "冲突" in (reason or "")

    def test_a_hallucinated_preset_is_refused(self) -> None:
        proposal, reason = validate_proposed_reading(
            _reading(operations=[{"kind": "camera_preset", "preset_id": "zoom_9000", "camera_id": "cam1"}]),
            _vocabulary(),
            taken_ids=frozenset(),
        )
        assert proposal is None
        assert "zoom_9000" in (reason or "")

    def test_an_unknown_camera_is_refused(self) -> None:
        proposal, reason = validate_proposed_reading(
            _reading(operations=[{"kind": "camera_preset", "preset_id": "push_in", "camera_id": "cam_ghost"}]),
            _vocabulary(),
            taken_ids=frozenset(),
        )
        assert proposal is None
        assert "cam_ghost" in (reason or "")

    def test_a_cut_without_a_timestamp_is_refused(self) -> None:
        proposal, reason = validate_proposed_reading(
            _reading(operations=[{"kind": "cut", "shot_id": "s2"}]),
            _vocabulary(),
            taken_ids=frozenset(),
        )
        assert proposal is None
        assert "at_seconds" in (reason or "")

    def test_a_cut_pointing_at_a_ghost_shot_is_refused(self) -> None:
        proposal, reason = validate_proposed_reading(
            _reading(operations=[{"kind": "cut", "at_seconds": 2.0, "shot_id": "s_ghost"}]),
            _vocabulary(),
            taken_ids=frozenset(),
        )
        assert proposal is None
        assert "s_ghost" in (reason or "")

    def test_a_zero_operation_reading_is_refused(self) -> None:
        proposal, reason = validate_proposed_reading(
            _reading(operations=[]), _vocabulary(), taken_ids=frozenset()
        )
        assert proposal is None
        assert "没有可执行操作" in (reason or "")

    def test_an_unsafe_id_is_refused(self) -> None:
        proposal, reason = validate_proposed_reading(
            _reading("has space"), _vocabulary(), taken_ids=frozenset()
        )
        assert proposal is None
        assert reason

    def test_a_duplicate_id_within_one_response_is_refused(self) -> None:
        proposal, reason = validate_proposed_reading(
            _reading(), _vocabulary(), taken_ids=frozenset({"shadow_pass"})
        )
        assert proposal is None
        assert "重复" in (reason or "")

    def test_character_presets_are_validated_too(self) -> None:
        proposal, reason = validate_proposed_reading(
            _reading(operations=[{"kind": "character_preset", "preset_id": "walk_to", "character_id": "lin"}]),
            _vocabulary(),
            taken_ids=frozenset(),
        )
        assert reason is None
        assert proposal is not None
        assert proposal.operations[0].character_id == "lin"


class TestProposalOrchestration:
    def test_accepted_readings_arrive_with_their_origin(self) -> None:
        result = propose_additional_readings(
            shot_a_id="s1",
            shot_b_id="s2",
            vocabulary=_vocabulary(),
            existing_labels=["连续运动"],
            llm_call=lambda system, user: '{"readings": [{"id": "shadow_pass", "label": "剪影过渡", "narrative": "光替它完成转场。", "operations": [{"kind": "camera_preset", "preset_id": "push_in", "camera_id": "cam1"}]}]}',
        )
        assert result.source == "llm"
        assert [reading.id for reading in result.readings] == ["shadow_pass"]
        assert result.readings[0].origin == "llm"
        assert result.dropped == ()

    def test_a_batch_survives_its_bad_members(self) -> None:
        payload = (
            '{"readings": ['
            '{"id": "good", "label": "好", "narrative": "可行。", "operations": [{"kind": "cut", "at_seconds": 2.0, "shot_id": "s2"}]},'
            '{"id": "bad", "label": "坏", "narrative": "幻觉预设。", "operations": [{"kind": "camera_preset", "preset_id": "nope", "camera_id": "cam1"}]}'
            "]}"
        )
        result = propose_additional_readings(
            shot_a_id="s1",
            shot_b_id="s2",
            vocabulary=_vocabulary(),
            existing_labels=[],
            llm_call=lambda system, user: payload,
        )
        assert [reading.id for reading in result.readings] == ["good"]
        assert len(result.dropped) == 1
        assert "bad" in result.dropped[0]

    def test_an_all_invalid_batch_degrades_with_every_reason(self) -> None:
        payload = '{"readings": [{"id": "bad", "label": "坏", "narrative": "x", "operations": [{"kind": "cut", "shot_id": "s2"}]}]}'
        result = propose_additional_readings(
            shot_a_id="s1",
            shot_b_id="s2",
            vocabulary=_vocabulary(),
            existing_labels=[],
            llm_call=lambda system, user: payload,
        )
        assert result.source == "rules"
        assert result.readings == ()
        assert result.degraded_reason
        assert len(result.dropped) == 1

    def test_an_empty_answer_is_honest_not_failed(self) -> None:
        result = propose_additional_readings(
            shot_a_id="s1",
            shot_b_id="s2",
            vocabulary=_vocabulary(),
            existing_labels=[],
            llm_call=lambda system, user: '{"readings": []}',
        )
        assert result.source == "rules"
        assert result.degraded_reason

    def test_llm_unavailability_degrades_with_a_reason(self) -> None:
        def unavailable(system: str, user: str) -> str:
            raise NarrativePolishUnavailable("LLM 未配置")

        result = propose_additional_readings(
            shot_a_id="s1",
            shot_b_id="s2",
            vocabulary=_vocabulary(),
            existing_labels=[],
            llm_call=unavailable,
        )
        assert result.source == "rules"
        assert result.degraded_reason == "LLM 未配置"
        assert result.readings == ()


def test_endpoint_appends_validated_llm_readings(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint
    from app.services.scene3d import transition_narratives

    monkeypatch.setattr(
        transition_narratives,
        "default_llm_call",
        lambda system, user: (
            '{"readings": [{"id": "shadow_pass", "label": "剪影过渡", '
            '"narrative": "光替它完成转场。", "operations": [{"kind": "camera_preset", '
            '"preset_id": "push_in", "camera_id": "cam1"}]},'
            '{"id": "bad", "label": "坏", "narrative": "幻觉。", '
            '"operations": [{"kind": "camera_preset", "preset_id": "nope", "camera_id": "cam1"}]}]}'
        ),
    )
    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    response = client.post(
        "/scene-3d/transition-proposals",
        json={
            "scene_script": _script_for_endpoint(),
            "shot_a_id": "s1",
            "shot_b_id": "s2",
            "propose_readings": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    by_id = {proposal["id"]: proposal for proposal in body["proposals"]}
    # The valid LLM reading is appended with its origin…
    assert by_id["shadow_pass"]["origin"] == "llm"
    assert by_id["sound_bridge"]["origin"] == "rules"
    # …the invalid one is dropped with its reason said out loud.
    assert "bad" not in by_id
    assert any("bad" in warning for warning in body["warnings"])


class TestMultiRoundMemory:
    """The LLM is told what the author already engaged with (V0.2 §15)."""

    def test_excluded_ids_are_reserved_in_the_vocabulary(self) -> None:
        vocabulary = _vocabulary().with_exclusions(["shadow_pass"])
        assert "shadow_pass" in vocabulary.reserved_ids
        # The rule catalogue's reservations survive the merge.
        assert "sound_bridge" in vocabulary.reserved_ids

    def test_a_repeated_reading_is_dropped_and_named(self) -> None:
        payload = (
            '{"readings": ['
            '{"id": "shadow_pass", "label": "剪影过渡", "narrative": "光替它完成转场。", '
            '"operations": [{"kind": "camera_preset", "preset_id": "push_in", "camera_id": "cam1"}]},'
            '{"id": "new_idea", "label": "新读法", "narrative": "另一条路。", '
            '"operations": [{"kind": "cut", "at_seconds": 2.0, "shot_id": "s2"}]}'
            "]}"
        )
        result = propose_additional_readings(
            shot_a_id="s1",
            shot_b_id="s2",
            vocabulary=_vocabulary(),
            existing_labels=["剪影过渡"],
            exclude_ids=["shadow_pass"],
            llm_call=lambda system, user: payload,
        )
        assert [reading.id for reading in result.readings] == ["new_idea"]
        assert any("shadow_pass" in reason for reason in result.dropped)

    def test_the_engaged_readings_reach_the_prompt(self) -> None:
        seen: dict[str, str] = {}

        def capture(system: str, user: str) -> str:
            seen["user"] = user
            return '{"readings": []}'

        propose_additional_readings(
            shot_a_id="s1",
            shot_b_id="s2",
            vocabulary=_vocabulary(),
            existing_labels=["连续运动", "shadow_pass"],
            exclude_ids=["shadow_pass"],
            llm_call=capture,
        )
        # Both the rule catalogue and the author's engaged ids are context.
        assert "连续运动" in seen["user"]
        assert "shadow_pass" in seen["user"]


def test_endpoint_reserves_the_authors_engaged_readings(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint
    from app.services.scene3d import transition_narratives

    monkeypatch.setattr(
        transition_narratives,
        "default_llm_call",
        lambda system, user: (
            '{"readings": [{"id": "shadow_pass", "label": "剪影过渡", '
            '"narrative": "光替它完成转场。", "operations": [{"kind": "camera_preset", '
            '"preset_id": "push_in", "camera_id": "cam1"}]}]}'
        ),
    )
    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    # Round 2: the author applied shadow_pass last round, so it must not
    # come back — and the endpoint says why the list is shorter.
    response = client.post(
        "/scene-3d/transition-proposals",
        json={
            "scene_script": _script_for_endpoint(),
            "shot_a_id": "s1",
            "shot_b_id": "s2",
            "propose_readings": True,
            "exclude_reading_ids": ["shadow_pass"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "shadow_pass" not in {proposal["id"] for proposal in body["proposals"]}
    assert any("shadow_pass" in warning for warning in body["warnings"])
    # The rule catalogue is untouched by the exclusion (only ids in it stay).
    assert "sound_bridge" in {proposal["id"] for proposal in body["proposals"]}
