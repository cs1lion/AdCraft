"""Dialogue-driven previs wiring: dialogue -> speech timeline -> lip-sync -> SceneScript.

Chains the pieces the speech track already provides (``speech_orchestration``)
into the one call the scene-3d workbench needs:

    dialogue lines (character, text, optional timing/emotion)
        -> SpeechTimeline (TTS-measured durations, ADR 0003 ``bound`` mode)
        -> LipSyncGenerator.merge_into_scene_script (mouth keyframes that
           inherit each character's existing position/rotation)
        -> re-validated SceneScriptRoot + a queryable summary

Design notes:
- Durations are MEASURED, not guessed: when a real TTS engine is configured the
  measured WAV length drives the timeline; without one, ``SimpleTTSEngine``
  estimates (~8 chars/s Chinese, ~15 chars/s Latin) and the summary says so
  (``duration_source: "estimated"`` vs ``"measured"``) — never silent
  (engineering standard §4).
- Overlaps/gaps are reported, not silently resolved: the caller decides
  whether overlapping dialogue is intentional (a noisy crowd) or an error.
- The merge preserves every non-lip keyframe: lip-sync keyframes only ADD or
  UPDATE the ``action`` field, inheriting position/rotation by forward-hold.
- The merged script re-runs SceneScriptRoot validation (shot/keyframe bounds),
  so a bad merge fails closed instead of reaching the renderer.

See docs/plans/3d-workbench-and-pipeline-completion.md §5.2 (mode B/C) and
docs/plans/blender-mcp-white-model-mode-and-audio-collaboration.md §2.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.speech_orchestration import (
    LipSyncGenerator,
    SimpleTTSEngine,
    SpeechTimeline,
    TTSEngine,
    build_timeline_from_script,
)
from app.services.scene3d.emotion_continuity import check_emotion_continuity
from app.services.scene3d.shot_advisor import advise_shots_from_speech


class DialogueLipSyncError(Exception):
    """Raised when dialogue-driven lip-sync application fails (fail closed)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DialogueLipSyncResult:
    """Merged SceneScript plus the queryable provenance of the operation."""

    scene_script: SceneScriptRoot
    summary: dict[str, Any]


def speech_qa_report(
    *,
    segments: list[Any],
    issues: list[Any],
    speech_bindings: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    measured_durations: list[dict[str, float]],
    audio_path: str | None,
) -> dict[str, object]:
    """Run the ADR 0003 §5 registry over one lip-sync application."""

    from app.services.dialogue.speech_qa_checks import build_speech_qa_registry
    from app.services.dialogue.v2_qa_registry import QaSubject

    subject = QaSubject(
        measured_durations=measured_durations,
        segments=list(segments),
        speech_bindings=speech_bindings,
        shots=shots,
        timeline_issues=[
            {
                "issue_type": issue.issue_type,
                "description": issue.description,
                "segments": list(issue.segments),
            }
            for issue in issues
        ],
        audio_path=audio_path,
    )
    return build_speech_qa_registry().report(subject)


def _normalize_dialogue_lines(dialogue_lines: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not dialogue_lines:
        raise DialogueLipSyncError(
            "dialogue_required",
            "At least one dialogue line is required.",
        )
    normalized: list[dict[str, Any]] = []
    for index, line in enumerate(dialogue_lines):
        if not isinstance(line, dict):
            raise DialogueLipSyncError(
                "dialogue_line_invalid",
                f"dialogue_lines[{index}] must be an object.",
            )
        text = str(line.get("text") or "").strip()
        if not text:
            raise DialogueLipSyncError(
                "dialogue_text_required",
                f"dialogue_lines[{index}].text is required.",
            )
        start_time = line.get("start_time")
        if start_time is not None:
            try:
                start_time = float(start_time)
            except (TypeError, ValueError) as exc:
                raise DialogueLipSyncError(
                    "dialogue_start_time_invalid",
                    f"dialogue_lines[{index}].start_time must be a number.",
                ) from exc
            if start_time < 0:
                raise DialogueLipSyncError(
                    "dialogue_start_time_invalid",
                    f"dialogue_lines[{index}].start_time must be >= 0.",
                )
        entry: dict[str, Any] = {
            "character_id": str(line.get("character_id") or f"char_{index}"),
            "text": text,
            "emotion": line.get("emotion"),
        }
        # Only forward start_time when present: the timeline builder keys on
        # KEY PRESENCE, and an explicit None would crash float(). An explicit
        # end_time rides along (forced alignment produces both).
        if start_time is not None:
            entry["start_time"] = start_time
        end_time = line.get("end_time")
        if end_time is not None and start_time is not None:
            try:
                entry["end_time"] = float(end_time)
            except (TypeError, ValueError):
                pass
        # Word-level timings ride along so the mouth can move WITH the words
        # (V0.2 §14.9). Malformed entries are dropped rather than trusted; the
        # generator falls back to its syllable metronome without them.
        raw_word_timings = line.get("word_timings")
        if isinstance(raw_word_timings, list):
            words: list[dict[str, Any]] = []
            for word in raw_word_timings:
                if not isinstance(word, dict):
                    continue
                word_start = word.get("start")
                word_end = word.get("end")
                if not isinstance(word_start, (int, float)) or not isinstance(
                    word_end, (int, float)
                ):
                    continue
                words.append(
                    {
                        "text": str(word.get("text") or ""),
                        "start": float(word_start),
                        "end": float(word_end),
                    }
                )
            if words:
                entry["word_timings"] = words
        normalized.append(entry)
    return normalized


def _as_scene_script(scene_script: SceneScriptRoot | dict[str, Any]) -> SceneScriptRoot:
    if isinstance(scene_script, SceneScriptRoot):
        return scene_script
    try:
        return SceneScriptRoot.model_validate(scene_script)
    except Exception as exc:
        raise DialogueLipSyncError(
            "scene_script_invalid",
            f"SceneScript failed schema validation: {str(exc)[:300]}",
        ) from exc


def apply_dialogue_lip_sync(
    scene_script: SceneScriptRoot | dict[str, Any],
    dialogue_lines: list[dict[str, Any]] | None,
    *,
    tts_engine: TTSEngine | None = None,
    syllables_per_second: float = 4.0,
    audio_path: str | None = None,
) -> DialogueLipSyncResult:
    """Apply dialogue-driven lip-sync keyframes to a SceneScript.

    Args:
        scene_script: The canonical SceneScript (model or raw dict).
        dialogue_lines: [{character_id, text, start_time?, emotion?}]; lines
            without start_time are appended sequentially after the previous.
        tts_engine: Measured-duration engine (None -> estimated, recorded in
            the summary).
        syllables_per_second: Mouth-open/close alternation density.

    Returns:
        DialogueLipSyncResult with the merged script and a summary.

    Raises:
        DialogueLipSyncError: Fail-closed on invalid input or a merge that
            violates SceneScript invariants.
    """
    script = _as_scene_script(scene_script)
    lines = _normalize_dialogue_lines(dialogue_lines)

    duration_source = "estimated"
    engine: TTSEngine = tts_engine if tts_engine is not None else SimpleTTSEngine()
    if tts_engine is not None:
        duration_source = "measured"

    try:
        timeline: SpeechTimeline = build_timeline_from_script(
            lines,
            frame_rate=script.scene.frame_rate,
            tts_engine=engine,
        )
    except Exception as exc:
        raise DialogueLipSyncError(
            "dialogue_timeline_failed",
            f"Failed to build the speech timeline: {str(exc)[:200]}",
        ) from exc

    # Report (never silently fix) overlap/gap/out-of-range problems.
    issues = timeline.validate(scene_duration=script.scene.duration)
    scene_total_seconds = script.total_frames / script.scene.frame_rate
    beyond_scene = [
        issue
        for issue in issues
        if issue.issue_type == "out_of_bounds"
    ]

    # Fail closed on speakers the scene does not define: merging would create
    # SpeechBindings that SceneScriptRoot._validate_speech_references rejects,
    # and silently dropping the lines would lose dialogue (fail closed, not
    # silent — the error names both the unknown ids and the valid ones).
    scene_character_ids = {character.id for character in script.characters}
    speaking_characters = sorted({segment.character_id for segment in timeline.segments})
    unknown_speakers = [
        character_id for character_id in speaking_characters if character_id not in scene_character_ids
    ]
    if unknown_speakers:
        raise DialogueLipSyncError(
            "dialogue_unknown_speaker",
            f"dialogue_lines reference character(s) {unknown_speakers} not present in the "
            f"SceneScript (available: {sorted(scene_character_ids)}).",
        )

    generator = LipSyncGenerator(
        frame_rate=script.scene.frame_rate,
        syllables_per_second=syllables_per_second,
    )
    try:
        merged = generator.merge_into_scene_script(script, timeline)
    except Exception as exc:
        raise DialogueLipSyncError(
            "lip_sync_merge_failed",
            f"Lip-sync merge failed: {str(exc)[:300]}",
        ) from exc

    # Re-validate: the merge constructs a new SceneScriptRoot (whose
    # validators ran), but assert the invariants that matter downstream so a
    # future refactor of the merge cannot regress them silently.
    for character in merged.characters:
        for keyframe in character.keyframes:
            if keyframe.frame > merged.total_frames:
                raise DialogueLipSyncError(
                    "lip_sync_keyframe_out_of_range",
                    f"Merged lip-sync keyframe for '{character.id}' exceeds the "
                    f"scene's total frames ({merged.total_frames}).",
                )
    # C mode: lines may arrive pre-timed by forced alignment. Say so, so a
    # consumer knows the timeline did not come from TTS measurement or
    # text-length estimation.
    pretimed_lines = sum(
        1
        for line in lines
        if line.get("start_time") is not None and line.get("end_time") is not None
    )
    duration_source = "aligned" if pretimed_lines == len(lines) else duration_source

    summary = {
        "dialogue_line_count": len(lines),
        "pretimed_line_count": pretimed_lines,
        "segment_count": len(timeline.segments),
        "characters_with_speech": speaking_characters,
        "total_speech_seconds": round(timeline.total_duration, 3),
        # Per-line timings: subtitle cues and the timeline must use the SAME
        # boundaries the lip-sync keyframes came from, or the captions drift
        # from the mouths. Additive: existing consumers ignore it.
        "segments": [
            {
                "segment_id": segment.segment_id,
                "character_id": segment.character_id,
                "text": segment.text,
                "start_time": round(segment.start_time, 3),
                "end_time": round(segment.end_time, 3),
                "emotion": segment.emotion,
            }
            for segment in timeline.segments
        ],
        "scene_total_seconds": round(scene_total_seconds, 3),
        "duration_source": duration_source,
        "syllables_per_second": syllables_per_second,
        "lip_sync_action": "talk",
        # Overlaps/gaps are advisory: a crowd scene overlaps on purpose.
        "issues": [
            {
                "issue_type": issue.issue_type,
                "description": issue.description,
                "segments": list(issue.segments),
                "time_start": issue.time_start,
                "time_end": issue.time_end,
            }
            for issue in issues
        ],
        "speech_exceeds_scene": bool(beyond_scene),
        # QA registry (ADR 0003 §5): one report answers "what was checked".
        # Every entry is advisory and queryable; a failed check never silently
        # passes, and an unrunnable one degrades with its reason inside.
        "qa_report": speech_qa_report(
            segments=list(timeline.segments),
            issues=issues,
            speech_bindings=[binding.model_dump(mode="json") for binding in script.speech_bindings],
            shots=[
                {
                    "id": shot.id,
                    "start_seconds": shot.start_frame / (script.scene.frame_rate or 30),
                    "end_seconds": shot.end_frame / (script.scene.frame_rate or 30),
                }
                for shot in script.shots
            ],
            measured_durations=(
                [
                    {
                        "segment_id": segment.segment_id,
                        "measured": segment.end_time - segment.start_time,
                        "estimated": max(0.5, len(segment.text) / 8.0),
                    }
                    for segment in timeline.segments
                ]
                if duration_source == "measured"
                else []
            ),
            audio_path=audio_path,
        ),
        # Shot advisories: "说多久 → 分镜多长". The speech timeline the
        # lip-sync just rode on, read against the shot list — where a cut
        # lands mid-word (offered as the L-cut choice, not a defect), where a
        # single-subject framing holds cross-talk, and where a shot carries no
        # dialogue. Advisory only: the author keeps the editor's chair.
        "shot_advisories": [
            advisory.to_dict()
            for advisory in advise_shots_from_speech(
                shots=list(script.shots),
                segments=list(timeline.segments),
                frame_rate=script.scene.frame_rate,
                scene_duration=scene_total_seconds,
                shot_types={
                    camera.id: camera.shot_type for camera in script.cameras
                },
            )
        ],
        # Emotion continuity (V0.2 §5): the emotion a line carries out of a
        # shot is the state the next shot starts from. A whiplash with no
        # pause to read as intentional gets asked about, never blocked.
        "emotion_advisories": [
            advisory.to_dict()
            for advisory in check_emotion_continuity(
                shots=list(script.shots),
                segments=list(timeline.segments),
                frame_rate=script.scene.frame_rate,
            )
        ],
    }
    return DialogueLipSyncResult(scene_script=merged, summary=summary)
