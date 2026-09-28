"""Endpoint tests for the LLM advisory proposal layer (V0.2 §14.3/§14.5).

The shot advisor was rule-only; the audit table asked for the LLM 提案版.
These tests lock the endpoint contract: ``propose_advisories`` is opt-in,
the response always carries the rule findings (the LLM adds, never replaces),
and an unusable LLM degrades with a reported reason — never silent (§4).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import scene_3d as scene_3d_endpoint


def _scene_script() -> dict:
    """A scene whose dialogue crosses the s1→s2 cut at frame 60 (2s).

    The crossing is what produces a rule advisory to build on; without it
    the LLM layer has nothing to propose against and returns early.
    """

    return {
        "scene": {
            "name": "lab",
            "environment": "indoor",
            "lighting": "cool",
            "duration": 6.0,
            "frame_rate": 30,
        },
        "characters": [
            {
                "id": "lin",
                "type": "lowpoly_human",
                "character_asset_id": "asset-1",
                "appearance": {"color": "#E74C3C"},
                "keyframes": [
                    {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}
                ],
            }
        ],
        "props": [],
        "environment": [],
        "cameras": [
            {
                "id": "cam1",
                "shot_type": "wide",
                "keyframes": [{"frame": 0, "position": [3, -4, 2], "look_at": [0, 0, 1]}],
            },
            {
                "id": "cam2",
                "shot_type": "closeup",
                "keyframes": [{"frame": 60, "position": [1, -2, 2], "look_at": [0, 0, 1]}],
            },
        ],
        "shots": [
            {"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 59},
            {"id": "s2", "camera": "cam2", "start_frame": 60, "end_frame": 179},
        ],
        "speech_bindings": [],
    }


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    return TestClient(app)


def _request(**overrides) -> dict:
    payload = {
        "scene_script": _scene_script(),
        "dialogue_lines": [
            # Starts at 1.5s and runs past the 2s cut: a line crossing a cut.
            {
                "character_id": "lin",
                "text": "就是这里信号源在墙后面别出声我们时间不多了",
                "start_time": 1.5,
            }
        ],
        "syllables_per_second": 4.0,
    }
    payload.update(overrides)
    return payload


class TestAdvisoryProposalsOptIn:
    def test_off_by_default(self) -> None:
        response = _client().post("/scene-3d/dialogue-lipsync", json=_request())
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is True
        # No LLM call: the summary carries the rule advisories only.
        assert "advisory_proposals" not in body["summary"]
        assert body["summary"]["shot_advisories"]

    def test_proposals_key_appears_when_enabled(self) -> None:
        response = _client().post(
            "/scene-3d/dialogue-lipsync", json=_request(propose_advisories=True)
        )
        assert response.status_code == 200, response.text
        body = response.json()
        proposed = body["summary"]["advisory_proposals"]
        # Shape is stable whether or not the LLM produced anything.
        assert "proposals" in proposed
        assert "dropped" in proposed
        assert "degraded_reason" in proposed

    def test_rule_findings_survive_when_proposals_land(self) -> None:
        """The LLM adds; it never replaces the rule findings."""

        response = _client().post(
            "/scene-3d/dialogue-lipsync", json=_request(propose_advisories=True)
        )
        body = response.json()
        assert body["summary"]["shot_advisories"]
        assert body["summary"]["advisory_proposals"]

    def test_degrades_reported_not_silent(self) -> None:
        """An unusable LLM leaves the rule remedies standing WITH a reason."""

        response = _client().post(
            "/scene-3d/dialogue-lipsync", json=_request(propose_advisories=True)
        )
        body = response.json()
        proposed = body["summary"]["advisory_proposals"]
        # Either the LLM produced something, or the reason says why not —
        # the summary is never quietly empty.
        assert proposed["proposals"] or proposed["degraded_reason"]
