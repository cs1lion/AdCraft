"""Tests for LLM advisory narrative proposals (V0.2 §14.3/§14.5, §6.2/§15).

The LLM 提案版 for the shot advisor. The load-bearing property: **every
proposal is validated against the scene's own ids**, so a machine that
imagines a shot that does not exist, or renames a rule finding, is dropped
with a named reason rather than smuggled into the advisory list. Silent
fallbacks are forbidden (engineering standard §4) — every rejection says WHY.
"""

from __future__ import annotations

import json

from app.schemas.scene_script import SceneShot
from app.services.scene3d.advisory_narratives import (
    AdvisoryProposalUnavailable,
    build_advisory_prompt,
    parse_advisory_proposals,
    propose_advisory_narratives,
    validate_proposed_advisory,
)
from app.services.scene3d.shot_advisor import ShotAdvisory


def _shot(shot_id: str, start: int = 0, end: int = 89) -> SceneShot:
    return SceneShot.model_validate(
        {"id": shot_id, "camera": "cam1", "start_frame": start, "end_frame": end}
    )


def _advisory(code: str = "line_crosses_cut", shot_id: str | None = "s1") -> ShotAdvisory:
    return ShotAdvisory(
        code=code,
        shot_id=shot_id,
        message="台词跨切。",
        remedy="移到停顿处。",
        proposal_ids=("sound_bridge",),
    )


SHOTS = [_shot("s1", 0, 89), _shot("s2", 90, 179)]
IDS = {"s1", "s2"}


class TestBuildAdvisoryPrompt:
    def test_includes_shots_segments_and_advisories(self) -> None:
        system, user = build_advisory_prompt(
            shots=SHOTS,
            segments=[],
            advisories=[_advisory()],
        )
        assert "分镜顾问" in system
        assert "JSON" in system
        payload = json.loads(user)
        assert [shot["id"] for shot in payload["shots"]] == ["s1", "s2"]
        assert payload["advisories"][0]["code"] == "line_crosses_cut"

    def test_omits_executable_authority_from_the_prompt(self) -> None:
        """The LLM reads which readings exist; it cannot create one."""

        _, user = build_advisory_prompt(
            shots=SHOTS,
            segments=[],
            advisories=[_advisory()],
        )
        payload = json.loads(user)
        # proposal_ids rides along as text (the LLM knows the remedy's
        # landing) but no operation vocabulary is exposed.
        assert payload["advisories"][0]["proposal_ids"] == ["sound_bridge"]
        assert "operations" not in json.dumps(payload["advisories"][0])


class TestValidateProposedAdvisory:
    def test_accepts_a_well_formed_proposal(self) -> None:
        proposal, reason = validate_proposed_advisory(
            {"advisory_code": "line_crosses_cut", "shot_id": "s2", "suggestion": "把 s2 缩短半秒。"},
            advisories=[_advisory()],
            valid_shot_ids=IDS,
        )
        assert reason is None
        assert proposal is not None
        assert proposal.advisory_code == "line_crosses_cut"
        assert proposal.shot_id == "s2"
        assert proposal.suggestion == "把 s2 缩短半秒。"

    def test_rejects_an_unknown_advisory_code(self) -> None:
        _, reason = validate_proposed_advisory(
            {"advisory_code": "made_up_code", "shot_id": "s2", "suggestion": "x"},
            advisories=[_advisory()],
            valid_shot_ids=IDS,
        )
        assert "不是规则顾问发现的问题" in (reason or "")

    def test_rejects_an_unknown_shot_id(self) -> None:
        """A suggestion about a shot nobody authored is noise."""

        _, reason = validate_proposed_advisory(
            {"advisory_code": "line_crosses_cut", "shot_id": "s99", "suggestion": "x"},
            advisories=[_advisory()],
            valid_shot_ids=IDS,
        )
        assert "不在本场景的镜头列表里" in (reason or "")

    def test_rejects_a_missing_suggestion(self) -> None:
        _, reason = validate_proposed_advisory(
            {"advisory_code": "line_crosses_cut", "shot_id": "s2", "suggestion": "   "},
            advisories=[_advisory()],
            valid_shot_ids=IDS,
        )
        assert "缺少 suggestion" in (reason or "")

    def test_rejects_an_overlong_suggestion(self) -> None:
        _, reason = validate_proposed_advisory(
            {"advisory_code": "line_crosses_cut", "shot_id": "s2", "suggestion": "x" * 501},
            advisories=[_advisory()],
            valid_shot_ids=IDS,
        )
        assert "超过 500 字符" in (reason or "")

    def test_rejects_a_non_object(self) -> None:
        _, reason = validate_proposed_advisory(
            "not a dict",
            advisories=[_advisory()],
            valid_shot_ids=IDS,
        )
        assert reason == "提案不是对象"


class TestParseAdvisoryProposals:
    def test_accepts_valid_proposals(self) -> None:
        accepted, dropped = parse_advisory_proposals(
            text=json.dumps(
                {
                    "proposals": [
                        {"advisory_code": "line_crosses_cut", "shot_id": "s2", "suggestion": "缩短 s2。"},
                        {"advisory_code": "line_crosses_cut", "shot_id": "s1", "suggestion": "延长 s1。"},
                    ]
                }
            ),
            advisories=[_advisory()],
            valid_shot_ids=IDS,
        )
        assert len(accepted) == 2
        assert dropped == []

    def test_drops_each_invalid_proposal_with_a_reason(self) -> None:
        accepted, dropped = parse_advisory_proposals(
            text=json.dumps(
                {
                    "proposals": [
                        {"advisory_code": "line_crosses_cut", "shot_id": "s2", "suggestion": "ok"},
                        {"advisory_code": "ghost", "shot_id": "s1", "suggestion": "bad code"},
                        {"advisory_code": "line_crosses_cut", "shot_id": "s9", "suggestion": "bad shot"},
                        {"advisory_code": "line_crosses_cut", "shot_id": "s1", "suggestion": ""},
                    ]
                }
            ),
            advisories=[_advisory()],
            valid_shot_ids=IDS,
        )
        assert len(accepted) == 1
        assert len(dropped) == 3
        assert "proposals[1]" in dropped[0]
        assert "proposals[2]" in dropped[1]
        assert "proposals[3]" in dropped[2]

    def test_deduplicates_repeated_proposals(self) -> None:
        accepted, dropped = parse_advisory_proposals(
            text=json.dumps(
                {
                    "proposals": [
                        {"advisory_code": "line_crosses_cut", "shot_id": "s2", "suggestion": "first"},
                        {"advisory_code": "line_crosses_cut", "shot_id": "s2", "suggestion": "second"},
                    ]
                }
            ),
            advisories=[_advisory()],
            valid_shot_ids=IDS,
        )
        assert len(accepted) == 1
        assert accepted[0].suggestion == "first"
        assert len(dropped) == 1
        assert "重复" in dropped[0]

    def test_reports_malformed_json_rather_than_falling_back_silently(self) -> None:
        accepted, dropped = parse_advisory_proposals(
            text="not json at all",
            advisories=[_advisory()],
            valid_shot_ids=IDS,
        )
        assert accepted == []
        assert any("不是合法 JSON" in reason for reason in dropped)

    def test_reports_a_missing_proposals_key(self) -> None:
        accepted, dropped = parse_advisory_proposals(
            text=json.dumps({"narratives": {}}),
            advisories=[_advisory()],
            valid_shot_ids=IDS,
        )
        assert accepted == []
        assert any("缺少 proposals 列表" in reason for reason in dropped)

    def test_reports_a_non_list_proposals_value(self) -> None:
        accepted, dropped = parse_advisory_proposals(
            text=json.dumps({"proposals": "nope"}),
            advisories=[_advisory()],
            valid_shot_ids=IDS,
        )
        assert accepted == []
        assert any("缺少 proposals 列表" in reason for reason in dropped)

    def test_an_empty_proposals_list_is_not_an_error(self) -> None:
        """The LLM had nothing to add: that is a valid answer."""

        accepted, dropped = parse_advisory_proposals(
            text=json.dumps({"proposals": []}),
            advisories=[_advisory()],
            valid_shot_ids=IDS,
        )
        assert accepted == []
        assert dropped == []


class TestProposeAdvisoryNarratives:
    """The LLM call layer: same seam discipline as transition_narratives."""

    def test_returns_proposals_when_the_llm_answers(self) -> None:
        def fake_call(system: str, user: str) -> str:
            return json.dumps(
                {
                    "proposals": [
                        {
                            "advisory_code": "line_crosses_cut",
                            "shot_id": "s2",
                            "suggestion": "把 s2 缩短半秒，让 s1 说完。",
                        }
                    ]
                }
            )

        result = propose_advisory_narratives(
            shots=SHOTS,
            segments=[],
            advisories=[_advisory()],
            llm_call=fake_call,
        )
        assert len(result.proposals) == 1
        assert result.proposals[0].suggestion == "把 s2 缩短半秒，让 s1 说完。"
        assert result.degraded_reason is None
        assert result.dropped == ()

    def test_degrades_with_a_reason_when_the_llm_is_unavailable(self) -> None:
        def unavailable_call(system: str, user: str) -> str:
            raise AdvisoryProposalUnavailable("LLM 未配置，保留规则补救语。")

        result = propose_advisory_narratives(
            shots=SHOTS,
            segments=[],
            advisories=[_advisory()],
            llm_call=unavailable_call,
        )
        assert result.proposals == ()
        assert result.degraded_reason == "LLM 未配置，保留规则补救语。"

    def test_degrades_when_the_llm_returns_unusable_json(self) -> None:
        result = propose_advisory_narratives(
            shots=SHOTS,
            segments=[],
            advisories=[_advisory()],
            llm_call=lambda system, user: "garbage",
        )
        assert result.proposals == ()
        assert "不是合法 JSON" in (result.degraded_reason or "")

    def test_reports_dropped_proposals_with_reasons(self) -> None:
        def fake_call(system: str, user: str) -> str:
            return json.dumps(
                {
                    "proposals": [
                        {
                            "advisory_code": "line_crosses_cut",
                            "shot_id": "s2",
                            "suggestion": "good",
                        },
                        {
                            "advisory_code": "ghost",
                            "shot_id": "s1",
                            "suggestion": "bad code",
                        },
                    ]
                }
            )

        result = propose_advisory_narratives(
            shots=SHOTS,
            segments=[],
            advisories=[_advisory()],
            llm_call=fake_call,
        )
        assert len(result.proposals) == 1
        assert len(result.dropped) == 1
        assert "proposals[1]" in result.dropped[0]

    def test_degrades_when_every_proposal_is_dropped(self) -> None:
        def fake_call(system: str, user: str) -> str:
            return json.dumps(
                {"proposals": [{"advisory_code": "ghost", "shot_id": "s1", "suggestion": "x"}]}
            )

        result = propose_advisory_narratives(
            shots=SHOTS,
            segments=[],
            advisories=[_advisory()],
            llm_call=fake_call,
        )
        assert result.proposals == ()
        assert "未返回可用的补充建议" in (result.degraded_reason or "")
        assert len(result.dropped) == 1

    def test_no_advisories_means_no_proposals_no_llm_call(self) -> None:
        """Proposing without a rule finding to build on would be guessing."""

        def exploding_call(system: str, user: str) -> str:
            raise AssertionError("should not be called")

        result = propose_advisory_narratives(
            shots=SHOTS,
            segments=[],
            advisories=[],
            llm_call=exploding_call,
        )
        assert result.proposals == ()
        assert result.degraded_reason is None
        assert result.dropped == ()
