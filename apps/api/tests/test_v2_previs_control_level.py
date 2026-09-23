"""Unit tests: previs_control_level degradation marker on the executor video path.

Mutation check (engineering standard §3): these tests lock the ADR 0005 §4a
contract — a previs-guided video run's provider payload carries a
`previs_control_level` marker, and the result metadata surfaces it
queryably; unknown levels fail closed to text_only.
"""

import pytest

from app.services.v2_provider_executor import (
    _previs_control_level_from_payload,
    _provider_asset_metadata,
)


class TestPrevisControlLevelFromPayload:
    def test_non_previs_payload_has_no_marker(self) -> None:
        # A plain storyboard video run carries no previs bundle → no marker.
        assert _previs_control_level_from_payload({"provider_prompt": "a cat"}) is None

    def test_previs_bundle_yields_level(self) -> None:
        # ADR 0005 §4: "full" additionally requires the model's catalog
        # capability fingerprint to accept at least one control pass.
        payload = {
            "provider_prompt": "teahouse",
            "scene3d_prompt_bundle": {"reference_mode": "video"},
            "previs_control_signals_available": True,
            "previs_control_signal_support": {"depth": True, "normal": True, "flow": False},
        }
        assert _previs_control_level_from_payload(payload) == "full"

    def test_video_without_signals_degrades_to_video_only(self) -> None:
        payload = {"scene3d_prompt_bundle": {"reference_mode": "video"}}
        assert _previs_control_level_from_payload(payload) == "video_only"

    def test_keyframes_maps_to_images_only(self) -> None:
        payload = {"scene3d_prompt_bundle": {"reference_mode": "keyframes"}}
        assert _previs_control_level_from_payload(payload) == "images_only"

    def test_unknown_mode_fails_closed_to_text_only(self) -> None:
        # Mutation: a misspelled reference_mode must never report control.
        payload = {"scene3d_prompt_bundle": {"reference_mode": "bogus"}}
        assert _previs_control_level_from_payload(payload) == "text_only"

    def test_control_signals_from_bundle_capabilities(self) -> None:
        payload = {
            "scene3d_prompt_bundle": {
                "reference_mode": "video",
                "model_capabilities": {"control_signals_available": True},
            },
        }
        # Fingerprint (ADR 0005 §4) defaults to False when unstamped, so a
        # video run without the catalog capability stays at video_only.
        assert _previs_control_level_from_payload(payload) == "video_only"

    def test_video_full_requires_control_signals_and_fingerprint(self) -> None:
        payload = {
            "scene3d_prompt_bundle": {"reference_mode": "video"},
            "previs_control_signals_available": True,
            "previs_control_signal_support": {"depth": True, "normal": True, "flow": False},
        }
        assert _previs_control_level_from_payload(payload) == "full"

    def test_video_full_blocked_when_model_rejects_all_signals(self) -> None:
        # A model that consumes reference video but ignores every control
        # pass must not report "full" (mutation: drop all fingerprint flags).
        payload = {
            "scene3d_prompt_bundle": {"reference_mode": "video"},
            "previs_control_signals_available": True,
            "previs_control_signal_support": {"depth": False, "normal": False, "flow": False},
        }
        assert _previs_control_level_from_payload(payload) == "video_only"

    def test_fingerprint_absent_stays_video_only(self) -> None:
        # Conservative default: no fingerprint stamped → signals not accepted.
        payload = {
            "scene3d_prompt_bundle": {"reference_mode": "video"},
            "previs_control_signals_available": True,
        }
        assert _previs_control_level_from_payload(payload) == "video_only"

    def test_fingerprint_accepts_dict_or_bool(self) -> None:
        payload = {
            "scene3d_prompt_bundle": {"reference_mode": "video"},
            "previs_control_signals_available": True,
            "previs_control_signal_support": True,
        }
        assert _previs_control_level_from_payload(payload) == "full"


class TestPrevisLevelInResultMetadata:
    def test_known_level_surfaces_in_metadata(self) -> None:
        payload = {"previs_control_level": "images_only"}
        metadata = _provider_asset_metadata({"status": "succeeded"}, payload)
        assert metadata["previs_control_level"] == "images_only"

    def test_unknown_level_fails_closed_with_code(self) -> None:
        payload = {
            "previs_control_level": "super_full",
            "previs_control_level_reason": "should surface",
        }
        metadata = _provider_asset_metadata({"status": "succeeded"}, payload)
        assert metadata["previs_control_level"] == "text_only"
        assert metadata["previs_control_level_code"] == "previs_control_level_unknown"
        assert metadata["previs_control_level_reason"] == "should surface"

    def test_reason_carried_for_known_level(self) -> None:
        payload = {
            "previs_control_level": "full",
            "previs_control_level_reason": "reason text",
        }
        metadata = _provider_asset_metadata({}, payload)
        assert metadata["previs_control_level"] == "full"
        assert metadata["previs_control_level_reason"] == "reason text"

    def test_non_previs_video_result_has_no_marker(self) -> None:
        metadata = _provider_asset_metadata({}, {"provider_prompt": "no previs"})
        assert "previs_control_level" not in metadata


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
