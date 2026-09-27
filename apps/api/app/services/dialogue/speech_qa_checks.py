"""The speech track's phase-1 QA checks (ADR 0003 §1.13 / §5).

Every entry here is an automated pre-commit check that needs no LLM: measured
durations compared against the estimate, bound-mode speech compared against
its shot, the timeline's own consistency, and the loudness probe against the
speech target. Each returns a structured outcome and degrades WITH a reason
when it cannot run — a skipped check never reports itself as a pass.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from app.services.dialogue.v2_qa_registry import (
    QA_FAIL,
    QA_PASS,
    QA_WARN,
    QaCheck,
    QaOutcome,
    QaRegistry,
    QaSubject,
)

# A measured duration this far from the text-length estimate is worth a look
# (either the engine heard something else, or the text does not match).
DURATION_SANITY_RATIO_RANGE = (0.5, 2.0)
# Integrated loudness target for a speech bed (LUFS) and its tolerance.
SPEECH_LOUDNESS_TARGET_LUFS = -16.0
SPEECH_LOUDNESS_TOLERANCE_LU = 2.0
# A bed measuring below this is not a quiet take, it is NO take: committing it
# would poison the downstream alignment and lip-sync (and the final mix would
# carry a silent voice). That is a FAIL, not a warning (ADR 0003 §5: failure
# blocks the commit).
SPEECH_LOUDNESS_FAIL_FLOOR_LUFS = -60.0


class SpeechDurationSanityCheck(QaCheck):
    """Measured TTS durations vs the text-length estimate (per line)."""

    name = "speech_duration_sanity"
    version = "1"

    def run(self, subject: QaSubject) -> QaOutcome:
        low, high = DURATION_SANITY_RATIO_RANGE
        outliers: list[dict[str, object]] = []
        for entry in subject.measured_durations:
            measured = entry.get("measured")
            estimated = entry.get("estimated")
            if not measured or not estimated or estimated <= 0:
                continue
            ratio = measured / estimated
            if ratio < low or ratio > high:
                outliers.append(
                    {
                        "segment_id": entry.get("segment_id"),
                        "measured": round(measured, 3),
                        "estimated": round(estimated, 3),
                        "ratio": round(ratio, 3),
                    }
                )
        if not outliers:
            return QaOutcome(
                check=self.name,
                status=QA_PASS,
                reason="实测时长与文本估算一致。"
                if subject.measured_durations
                else "本轮没有实测时长（估算模式），不适用。",
                details={"checked": len(subject.measured_durations)},
            )
        return QaOutcome(
            check=self.name,
            status=QA_WARN,
            reason=f"{len(outliers)} 句实测时长与估算偏差超出 [{low}, {high}]，"
            "可能是文本与录音不一致，或引擎听错了内容。",
            details={"outliers": outliers},
        )


class BoundSpeechVsShotDurationCheck(QaCheck):
    """In ``bound`` mode, speech must fit the shot it drives."""

    name = "bound_speech_vs_shot_duration"
    version = "1"

    def run(self, subject: QaSubject) -> QaOutcome:
        bound_characters = {
            str(binding.get("character"))
            for binding in subject.speech_bindings
            if str(binding.get("mode", "free")) == "bound"
        }
        if not bound_characters:
            return QaOutcome(
                check=self.name,
                status=QA_PASS,
                reason="没有 bound 模式的语音绑定，不适用。",
                details={"bound_characters": []},
            )
        shots = [
            shot for shot in subject.shots if isinstance(shot.get("id"), str)
        ]
        overruns: list[dict[str, object]] = []
        for segment in subject.segments:
            character_id = getattr(segment, "character_id", None)
            if character_id not in bound_characters:
                continue
            for shot in shots:
                start = shot.get("start_seconds")
                end = shot.get("end_seconds")
                if not isinstance(start, (int, float)) or not isinstance(
                    end, (int, float)
                ):
                    continue
                if segment.start_time < end - 1e-6 and segment.end_time > end + 1e-6:
                    overruns.append(
                        {
                            "segment_id": segment.segment_id,
                            "shot_id": shot["id"],
                            "speech_end": round(segment.end_time, 3),
                            "shot_end": round(float(end), 3),
                        }
                    )
        if not overruns:
            return QaOutcome(
                check=self.name,
                status=QA_PASS,
                reason="bound 模式的台词都收在其镜头时长内。",
                details={"bound_characters": sorted(bound_characters)},
            )
        return QaOutcome(
            check=self.name,
            status=QA_WARN,
            reason=f"{len(overruns)} 处 bound 台词超出所属镜头时长："
            "语音会拉着镜头超时，或镜头把话切断。",
            details={"overruns": overruns},
        )


class SpeechTimelineConsistencyCheck(QaCheck):
    """The speech timeline's own findings, as a registered entry.

    The timeline already computes overlap/gap/out-of-bounds findings; the ADR's
    point is that they belong IN the registry rather than beside it, so one
    report answers "what was checked".
    """

    name = "speech_timeline_consistency"
    version = "1"

    def run(self, subject: QaSubject) -> QaOutcome:
        issues = list(subject.timeline_issues)
        if not issues:
            return QaOutcome(
                check=self.name,
                status=QA_PASS,
                reason="语音时间线没有重叠、越界或空文本问题。",
                details={"issues": []},
            )
        return QaOutcome(
            check=self.name,
            status=QA_WARN,
            reason=f"语音时间线有 {len(issues)} 处问题（重叠/越界/空文本）。",
            details={"issues": issues},
        )


class LoudnessTargetCheck(QaCheck):
    """Integrated loudness of the speech bed against the target.

    The real ebur128 probe. When ffmpeg is absent the check degrades to ``warn``
    WITH the reason — it must not report a pass it did not measure.
    """

    name = "speech_loudness_target"
    version = "1"

    def __init__(self, ffmpeg_path: str = "ffmpeg") -> None:
        self._ffmpeg = ffmpeg_path

    def run(self, subject: QaSubject) -> QaOutcome:
        if not subject.audio_path:
            return QaOutcome(
                check=self.name,
                status=QA_WARN,
                reason="没有提供音频床，跳过响度测量（未测量 ≠ 通过）。",
                details={"audio_path": None},
            )
        if shutil.which(self._ffmpeg) is None:
            return QaOutcome(
                check=self.name,
                status=QA_WARN,
                reason="ffmpeg 不在 PATH 上，跳过响度测量（未测量 ≠ 通过）。",
                details={"audio_path": subject.audio_path},
            )
        command = [
            self._ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            subject.audio_path,
            "-filter_complex",
            "ebur128",
            "-f",
            "null",
            "-",
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=120
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return QaOutcome(
                check=self.name,
                status=QA_WARN,
                reason=f"响度测量失败：{error}",
                details={"audio_path": subject.audio_path},
            )
        integrated = _parse_integrated_loudness(result.stderr or "")
        if integrated is None:
            return QaOutcome(
                check=self.name,
                status=QA_WARN,
                reason="无法从 ffmpeg 输出解析整体响度，跳过判定（未测量 ≠ 通过）。",
                details={"audio_path": subject.audio_path},
            )
        if integrated < SPEECH_LOUDNESS_FAIL_FLOOR_LUFS:
            return QaOutcome(
                check=self.name,
                status=QA_FAIL,
                reason=(
                    f"整体响度仅 {integrated:.1f} LUFS，低于 "
                    f"{SPEECH_LOUDNESS_FAIL_FLOOR_LUFS:.0f} LUFS：这一轨几乎是静音，"
                    "不是一次可以提交的录音。"
                ),
                details={
                    "integrated_lufs": round(integrated, 2),
                    "fail_floor_lufs": SPEECH_LOUDNESS_FAIL_FLOOR_LUFS,
                },
            )
        deviation = integrated - SPEECH_LOUDNESS_TARGET_LUFS
        if abs(deviation) <= SPEECH_LOUDNESS_TOLERANCE_LU:
            return QaOutcome(
                check=self.name,
                status=QA_PASS,
                reason=(
                    f"整体响度 {integrated:.1f} LUFS，在目标 "
                    f"{SPEECH_LOUDNESS_TARGET_LUFS:.0f} ± "
                    f"{SPEECH_LOUDNESS_TOLERANCE_LU:.0f} LU 内。"
                ),
                details={
                    "integrated_lufs": round(integrated, 2),
                    "target_lufs": SPEECH_LOUDNESS_TARGET_LUFS,
                },
            )
        return QaOutcome(
            check=self.name,
            status=QA_WARN,
            reason=(
                f"整体响度 {integrated:.1f} LUFS，偏离目标 "
                f"{SPEECH_LOUDNESS_TARGET_LUFS:.0f} LUFS "
                f"{deviation:+.1f} LU（容差 ±{SPEECH_LOUDNESS_TOLERANCE_LU:.0f}）。"
            ),
            details={
                "integrated_lufs": round(integrated, 2),
                "target_lufs": SPEECH_LOUDNESS_TARGET_LUFS,
                "deviation_lu": round(deviation, 2),
            },
        )


def _parse_integrated_loudness(stderr: str) -> float | None:
    """The ``I:`` line of ebur128's summary block."""

    for line in reversed(stderr.splitlines()):
        fields = [part.strip() for part in line.split()]
        if len(fields) >= 2 and fields[0] == "I:":
            try:
                return float(fields[1])
            except ValueError:
                return None
    return None


def build_speech_qa_registry(*, ffmpeg_path: str = "ffmpeg") -> QaRegistry:
    """The phase-1 registry in its documented order."""

    registry = QaRegistry()
    registry.register(SpeechDurationSanityCheck())
    registry.register(BoundSpeechVsShotDurationCheck())
    registry.register(SpeechTimelineConsistencyCheck())
    registry.register(LoudnessTargetCheck(ffmpeg_path))
    return registry


def loudness_summary_json(stderr: str) -> str:
    """Debug helper: the ebur128 summary block (used by tests)."""

    return json.dumps({"stderr_tail": stderr[-400:]}, ensure_ascii=False)
