"""Video segment duration policy, and the segment download that never happened.

Two defects are pinned here, both found while cutting the "玫瑰与白桦" 3D previs
into a final film.

**The duration policy was a fiction.** The app enforced ``{5, 10}`` as the only
legal single-task lengths, while the provider's own descriptor declares a
continuous 1-15s range. Worse, the policy existed in *two* independent copies:

* ``workflow_node_media_generators._video_item_duration`` -- ``10 if d > 5 else 5``
* ``workflow_shot_bindings._video_item_duration`` -- the same expression, pasted

The second copy is the one that runs for a ``storyboard_video`` node, so
repairing only the first would have left every 7s beat rewritten to 10s on the
wire -- a segment that was correct on disk and wrong in the request.  Both now
clamp to the provider descriptor, and the equality test below is what stops the
two from drifting apart again.

**Polled segments were never downloaded.** ``segment-1.json`` for the canvas run
came back with ``local_path: null`` and ``download_status: "skipped"``, so
``segment_is_ready()`` was permanently False and the final composition waited
forever.  The download has to be reachable from the poll path, not just from the
submit path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.services.media_tasks import MediaTaskService
from app.services.workflow_node_media_generators import (
    _video_item_duration as generator_item_duration,
)
from app.services.workflow_shot_bindings import (
    _video_item_duration as binding_item_duration,
    build_storyboard_video_binding_plan,
)
from app.services.v2_provider_recovery import (
    PROVIDER_RECOVERABLE_RATE_LIMIT,
    V2ProviderRecoveryContext,
    V2ProviderRecoveryPolicy,
    _provider_retry_delay_seconds,
)
from app.core.config import Settings
from app.schemas.workflow_v2 import V2ProviderResult
from app.tools.media_provider_protocol import (
    SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS,
    SEEDANCE_MIN_SINGLE_TASK_DURATION_SECONDS,
    SEEDANCE_PREFERRED_SEGMENT_SECONDS,
    SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS,
)
from app.tools.seedance_adapter import (
    _normalized_segment_durations,
    _scene_prompts_are_valid_segments,
)

# Durations the previs actually asked for, taken from
# e2e_output/rose/stills/_manifest.json.  Every one of these was silently being
# turned into 5 or 10 before the fix.
PREVIS_SEGMENT_DURATIONS = [7, 7, 6, 6, 6, 6, 6, 6, 8, 7, 7, 6, 6, 6, 8, 7, 7, 7, 6, 6, 6, 6]


class TestDurationPolicy:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (1, 1),
            (3, 3),
            (6, 6),
            (7, 7),
            (8, 8),
            (12, 12),
            (15, 15),
            (1.0, 1),
            (7.4, 7),
            ("8", 8),
            # Below the declared floor and above the declared ceiling.
            (0, SEEDANCE_MIN_SINGLE_TASK_DURATION_SECONDS),
            (-5, SEEDANCE_MIN_SINGLE_TASK_DURATION_SECONDS),
            (16, SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS),
            (99, SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS),
            # Unparseable input falls back, it does not raise into a node.
            (None, 5),
            ("", 5),
            ("not-a-duration", 5),
            (object(), 5),
        ],
    )
    def test_generator_clamp(self, raw: Any, expected: int) -> None:
        assert generator_item_duration(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (1, 1),
            (6, 6),
            (7, 7),
            (8, 8),
            (12, 12),
            (15, 15),
            (0, SEEDANCE_MIN_SINGLE_TASK_DURATION_SECONDS),
            (99, SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS),
            (None, 5),
            ("not-a-duration", 5),
        ],
    )
    def test_binding_clamp(self, raw: Any, expected: int) -> None:
        assert binding_item_duration(raw) == expected

    @pytest.mark.parametrize(
        "raw", [1, 5, 6, 7, 8, 10, 12, 15, 0, 99, None, "7", "not-a-duration"]
    )
    def test_the_two_clamps_cannot_drift_apart(self, raw: Any) -> None:
        # The whole point of the bug: two copies that agreed on the wrong rule
        # were still two copies.  If someone reintroduces a snap in either file,
        # these stop matching and this fails.
        assert generator_item_duration(raw) == binding_item_duration(raw)

    def test_every_previs_duration_survives_untouched(self) -> None:
        # The regression in one line: cutting a 20s previs into 7/7/6/6 must not
        # arrive at the provider as 10/10/10/10.
        for duration in PREVIS_SEGMENT_DURATIONS:
            assert generator_item_duration(duration) == duration
            assert binding_item_duration(duration) == duration

    def test_the_seven_eight_band_is_reachable(self) -> None:
        # The model's quality band had to be reinstated, not merely widened.
        assert 7 in {generator_item_duration(7), generator_item_duration("7")}
        assert generator_item_duration(8) == 8

    def test_accepted_values_are_all_in_the_provider_descriptor(self) -> None:
        for duration in range(-5, 25):
            clamped = generator_item_duration(duration)
            assert SEEDANCE_MIN_SINGLE_TASK_DURATION_SECONDS <= clamped
            assert clamped <= SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS
            assert clamped in SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS


class TestSegmentSplitting:
    @pytest.mark.parametrize("total", [1, 2, 3, 5, 6, 7, 8, 9, 12, 13, 15, 18, 20, 25, 26])
    def test_split_sums_exactly_and_stays_legal(self, total: int) -> None:
        segments = _normalized_segment_durations(total)
        assert segments, "a non-empty split is always required"
        assert sum(segments) == total
        for duration in segments:
            assert duration in SEEDANCE_SINGLE_TASK_DURATIONS_SECONDS
            assert duration <= SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS

    @pytest.mark.parametrize("total", [7, 15, 16, 17, 18, 20, 22, 24, 25, 26, 31])
    def test_split_never_enters_the_nine_to_twelve_band(self, total: int) -> None:
        # 9-12s is *allowed* by the provider but sits outside the 7-8s quality
        # band, so the splitter targets 8 and stays at or below it.  Going the
        # other way -- a 20s shot split as [13, 7] -- would be legal on the wire
        # and visibly worse on screen.
        segments = _normalized_segment_durations(total)
        assert max(segments) <= SEEDANCE_PREFERRED_SEGMENT_SECONDS

    @pytest.mark.parametrize("total", [8, 16, 24, 32])
    def test_a_multiple_of_eight_splits_cleanly(self, total: int) -> None:
        assert _normalized_segment_durations(total) == [8] * (total // 8)

    @pytest.mark.parametrize("total", range(1, 9))
    def test_a_short_shot_is_a_single_segment(self, total: int) -> None:
        assert _normalized_segment_durations(total) == [total]

    def test_non_multiple_of_five_is_no_longer_rejected(self) -> None:
        # Every previs shot in the rose workflow is 20.04s / 18.04s / ... -- none
        # is a multiple of five.  The old rule raised for all of them.
        for total in (18, 20, 21, 22, 23, 24, 26, 31):
            assert sum(_normalized_segment_durations(total)) == total

    def test_too_short_still_raises_a_clear_error(self) -> None:
        with pytest.raises(ValueError, match="at least"):
            _normalized_segment_durations(0)

    def test_resulting_split_is_a_valid_scene_prompt_set(self) -> None:
        for total in (20, 18, 15, 25):
            durations = _normalized_segment_durations(total)
            scene_prompts = [
                {"duration_seconds": length, "shot_id": f"shot_{i}"}
                for i, length in enumerate(durations, start=1)
            ]
            assert _scene_prompts_are_valid_segments(scene_prompts, total) is True

    def test_scene_prompt_set_that_sums_wrong_is_rejected(self) -> None:
        assert _scene_prompts_are_valid_segments(
            [{"duration_seconds": 7}, {"duration_seconds": 7}], 20
        ) is False

    def test_scene_prompt_set_outside_the_descriptor_is_rejected(self) -> None:
        assert _scene_prompts_are_valid_segments(
            [{"duration_seconds": 99}, {"duration_seconds": 1}], 100
        ) is False


class TestStoryboardVideoBindingPlan:
    def _context(self, shots: list[dict[str, Any]]) -> dict[str, Any]:
        # The router reads ``storyboard.shots``; a bare list under ``storyboard``
        # is ignored and the shots are re-derived from the prompt instead.
        return {
            "storyboard": {"shots": shots},
            "provider_prompt": "a rose given back to the sea",
        }

    def _run(self, durations: list[int]) -> list[int]:
        shots = [
            {
                "order": index,
                "shot_id": f"shot_{index:03d}",
                "shot_type": "custom",
                "prompt": f"beat {index}",
                "duration_seconds": duration,
            }
            for index, duration in enumerate(durations, start=1)
        ]
        plan = build_storyboard_video_binding_plan(self._context(shots), [])
        assert plan.get("error") is None, plan.get("error")
        return [shot["duration_seconds"] for shot in plan["shots"]]

    @pytest.mark.parametrize(
        "input_durations",
        [
            [7, 7, 6, 6],
            [6, 6, 6, 6],
            [8, 7, 7],
            [12, 8],
            [5, 15],
        ],
    )
    def test_shot_durations_are_not_snapped_to_five_or_ten(
        self, input_durations: list[int]
    ) -> None:
        assert self._run(input_durations) == input_durations

    def test_the_full_previs_cut_survives_end_to_end(self) -> None:
        # 22 beats, the exact cut recorded in the manifest.
        planned = self._run(PREVIS_SEGMENT_DURATIONS)
        assert planned == PREVIS_SEGMENT_DURATIONS
        assert 5 not in set(planned)
        assert set(planned) == {6, 7, 8}

    def test_out_of_range_shot_durations_are_clamped_not_rejected(self) -> None:
        # 99 is clamped to the descriptor ceiling rather than rejected, so one
        # bad LLM number fails a segment instead of the whole node.
        planned = self._run([12, 99, 7])
        assert planned == [12, SEEDANCE_MAX_SINGLE_TASK_DURATION_SECONDS, 7]

    def test_a_zero_duration_falls_back_before_the_clamp_sees_it(self) -> None:
        # Documented quirk, not the bug under test: the legacy normalizer reads
        # ``duration_seconds or durationSeconds``, so an explicit 0 falls through
        # to its 5s default and never reaches the clamp.  A 5s segment is still
        # legal, so this costs nothing -- but it is not a clamp.
        assert self._run([0, 7])[0] == 5


class TestRateLimitRetryWaitsAFullWindow:
    def _result(self, code: str) -> V2ProviderResult:
        return V2ProviderResult(
            status="failed",  # type: ignore[arg-type]
            media_type="video",
            error_code=code,
            error_message="Too Many Requests",
        )

    def _policy(self, *, rpm: int = 10, max_delay: float = 12.0) -> V2ProviderRecoveryPolicy:
        return V2ProviderRecoveryPolicy(
            Settings(
                provider_requests_per_minute=rpm,
                provider_transient_retry_max_delay_seconds=max_delay,
                provider_transient_retry_base_delay_seconds=0.5,
            )
        )

    def _decide(self, policy: V2ProviderRecoveryPolicy, code: str, used: int):
        return policy.decide(
            self._result(code),
            V2ProviderRecoveryContext(
                workflow_id="wf_test",
                node_id="node-video",
                item_id="item-1",
                slot_id="slot-1",
                slot_type="scene",
                media_type="video",
            ),
            retry_attempts_used=used,
        )

    def test_rate_limit_waits_the_whole_rpm_window(self) -> None:
        # 10 rpm => one slot every 6s.  The old 0.5s/2.0s backoff retried into a
        # closed window, got rejected again, and burned the attempt budget.
        decision = self._decide(self._policy(), "provider_rate_limited", 0)
        assert decision.retry_allowed is True
        assert decision.retry_delay_seconds == pytest.approx(6.0)

    def test_rate_limit_delay_scales_with_the_configured_rpm(self) -> None:
        assert self._decide(self._policy(rpm=6), "provider_rate_limited", 0).retry_delay_seconds == (
            pytest.approx(10.0)
        )
        assert self._decide(
            self._policy(rpm=30), "provider_rate_limited", 0
        ).retry_delay_seconds == pytest.approx(2.0)

    def test_transient_failure_does_not_wait_a_rate_window(self) -> None:
        # A 503 is an outage, not a window: waiting a full 6s for it would waste
        # time without changing the outcome.
        decision = self._decide(
            self._policy(), "provider_temporary_unavailable", 1
        )
        assert decision.retry_delay_seconds < 6.0

    def test_non_recoverable_code_has_no_delay(self) -> None:
        assert (
            _provider_retry_delay_seconds("provider_request_failed", 0, 6.0, 0.5, 12.0)
            == 0.0
        )

    def test_delay_is_capped_by_configured_max(self) -> None:
        delay = _provider_retry_delay_seconds(
            PROVIDER_RECOVERABLE_RATE_LIMIT, 5, 6.0, 0.5, 12.0
        )
        assert 0 < delay <= 12.0


class _DownloadingProvider:
    """A provider whose poll returns a URL, so a download is actually possible."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def retrieve_storyboard_video_task(self, task_id, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"task_id": task_id, **kwargs})
        return {
            "task_id": task_id,
            "status": "completed",
            "download_status": "downloaded",
            "local_path": "videos/wf_test/segments/segment-1.mp4",
            "url": "https://example.invalid/segment-1.mp4",
        }


def _manager(provider: _DownloadingProvider) -> MediaTaskService:
    return MediaTaskService(Settings(), media_provider=provider)  # type: ignore[arg-type]


class TestSegmentDownloadIsReachableFromPoll:
    def test_polling_a_segment_passes_download_media_through(self) -> None:
        # This is the shape of the bug that produced
        # download_status="skipped", local_path=null: the poll path existed but
        # never asked for the bytes, so the segment file could never become
        # ready and the final composition waited forever.
        provider = _DownloadingProvider()
        manager = _manager(provider)
        refreshed = manager.download_completed_segment(
            "wf_test",
            {"task_id": "task_1", "order": 1, "duration_seconds": 7},
            download_media=True,
        )
        assert provider.calls, "the provider must actually be consulted"
        assert provider.calls[0]["download_media"] is True
        assert refreshed["download_status"] == "downloaded"
        assert refreshed["local_path"] == "videos/wf_test/segments/segment-1.mp4"

    def test_segment_without_a_task_id_is_a_no_op(self) -> None:
        provider = _DownloadingProvider()
        manager = _manager(provider)
        segment = {"order": 1, "local_path": None}
        assert (
            manager.download_completed_segment("wf_test", segment, download_media=True)
            is segment
        )
        assert provider.calls == []

    def test_a_downloaded_segment_with_a_missing_file_is_not_ready(self, tmp_path: Path) -> None:
        # download_status alone is not readiness; the bytes have to exist.
        from app.services.workflow_media_segments import segment_is_ready

        segment_dir = tmp_path / "videos" / "wf_test" / "segments"
        segment_dir.mkdir(parents=True)
        (segment_dir / "segment-1.json").write_text(
            json.dumps(
                {
                    "order": 1,
                    "download_status": "downloaded",
                    "local_path": "videos/wf_test/segments/segment-1.mp4",
                }
            ),
            encoding="utf-8",
        )
        assert segment_is_ready(
            tmp_path,
            {
                "download_status": "downloaded",
                "local_path": "videos/wf_test/segments/segment-1.mp4",
            },
        ) is False

    def test_a_downloaded_segment_with_a_real_file_is_ready(self, tmp_path: Path) -> None:
        from app.services.workflow_media_segments import segment_is_ready

        video = tmp_path / "videos" / "wf_test" / "segments" / "segment-1.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        assert segment_is_ready(
            tmp_path,
            {
                "download_status": "downloaded",
                "local_path": "videos/wf_test/segments/segment-1.mp4",
            },
        ) is True

    def test_a_skipped_segment_is_never_ready(self, tmp_path: Path) -> None:
        # The exact state the canvas run left behind.
        from app.services.workflow_media_segments import segment_is_ready

        assert segment_is_ready(
            tmp_path, {"download_status": "skipped", "local_path": None}
        ) is False
