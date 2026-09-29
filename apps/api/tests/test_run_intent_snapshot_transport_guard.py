"""Run-intent snapshots must survive content fields that merely look secret.

2026-09-29 live (拉片复刻): the replica blueprint's anchor events carry
``start_token_id`` / ``end_token_id``.  The credential-key check matched the
substring "token", rejected the whole snapshot, and every replica run died
with a 500 ("Run intent snapshots cannot contain transport values") before a
single provider call.  An identifier reference is not a secret: the guard is
anchored on credential suffixes, and ``*_id`` keys are exempt.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.schemas.agent_canvas_runtime import (
    NodeRunBindingSnapshotV2,
    NodeRunIntentSnapshotV2,
    _contains_forbidden_transport,
    _is_credential_key,
)

DIGEST = "a" * 64


def _snapshot(**overrides) -> NodeRunIntentSnapshotV2:
    payload = dict(
        snapshot_id="run_intent_1",
        workflow_id="wf_1",
        execution_id="exec_1",
        member_id="member_1",
        node_id="node_1",
        node_revision=1,
        node_type="script",
        creative_role="script",
        role_contract_version="ad-media-role-v2",
        summary_prompt="replica script",
        generation_prompt="# 复刻脚本",
        structured_content_digest=DIGEST,
        model_selection_mode="default",
        snapshot_digest=DIGEST,
        created_at=datetime.now(timezone.utc),
    )
    payload.update(overrides)
    return NodeRunIntentSnapshotV2(**payload)


def test_identifier_keys_that_mention_token_are_not_secrets() -> None:
    assert not _is_credential_key("start_token_id")
    assert not _is_credential_key("end_token_id")
    assert not _is_credential_key("prompt_digest")


def test_credential_key_names_are_still_rejected() -> None:
    for key in (
        "api_key",
        "provider_api_key",
        "token",
        "session_token",
        "auth_token",
        "secret",
        "client_secret",
        "credential",
        "provider_credential",
        "authorization",
        "authorization_header",
    ):
        assert _is_credential_key(key), key


def test_a_replica_anchor_event_snapshot_validates() -> None:
    binding = NodeRunBindingSnapshotV2(
        binding_id="binding_1",
        input_role="text_context",
        order=0,
        source_kind="node_output",
        source_id="node_replica",
        source_structured_content={
            "anchor_events": [
                {
                    "event_id": "b1_caption",
                    "kind": "caption",
                    "beat_id": "b1",
                    "start_token_id": "",
                    "end_token_id": "",
                    "hint": "新文案写到这一段时，此处挂字幕/关键词高亮",
                }
            ]
        },
    )
    snapshot = _snapshot(binding_snapshots=(binding,))
    events = snapshot.binding_snapshots[0].source_structured_content["anchor_events"]
    assert events[0]["start_token_id"] == ""
    assert events[0]["end_token_id"] == ""


def test_credential_keys_in_parameters_still_reject_the_snapshot() -> None:
    for key in ("api_key", "auth_token", "client_secret"):
        with pytest.raises(ValueError, match="transport"):
            _snapshot(requested_parameters={key: "some-value"})


def test_transport_values_are_still_rejected() -> None:
    for value in ("/absolute/path.mp4", "data:audio/mp3;base64,AAAA", "https://x.example/y?x-amz-signature=abc"):
        with pytest.raises(ValueError, match="transport"):
            _snapshot(requested_parameters={"url": value})


def test_plain_content_is_accepted() -> None:
    snapshot = _snapshot(requested_parameters={"aspect_ratio": "16:9", "seconds": 5})
    assert snapshot.requested_parameters["aspect_ratio"] == "16:9"
    assert not _contains_forbidden_transport({"text": "# 复刻脚本"})
