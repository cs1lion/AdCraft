"""Automatic speech-driven lip-sync for scene-3d execution.

When a SceneScript carries speech bindings (character → speech audio), this
service resolves each referenced speech asset to its local audio file, probes
its MEASURED duration, lays the segments on a per-character speech timeline,
and merges lip-sync keyframes into the script — so a voice-cast node bound
upstream makes its characters' mouths move in the previs render without any
manual panel step. This is the execution-side half of the dialogue-driven
chain (the workbench's DialogueLipSyncPanel is the manual half).

Degradation is queryable, never silent (engineering standard §4):
- an unresolvable or unreadable speech asset leaves THAT character
  un-animated and is named in the warnings — no fake timing is invented for
  audio we could not hear;
- a script that already carries talk keyframes is left untouched, so a rerun
  never double-applies;
- the result's ``duration_source`` says "measured" only when every applied
  segment's duration came from a real probe.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.speech_alignment import probe_audio_duration_seconds
from app.services.scene3d.speech_orchestration import (
    LipSyncGenerator,
    SpeechSegment,
    SpeechTimeline,
)

SEGMENT_GAP_SECONDS = 0.2
"""Silence between consecutive lines of one character (build_timeline convention)."""

SPEECH_ASSET_PREFIX = "speech_audio:"


@dataclass
class AutoLipSyncResult:
    """Outcome of the automatic lip-sync pass."""

    scene_script: SceneScriptRoot
    applied: bool
    duration_source: str  # "measured" | "mixed" | "estimated" | "none"
    segment_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "applied": self.applied,
            "duration_source": self.duration_source,
            "segment_count": self.segment_count,
            "warnings": list(self.warnings),
        }


def speech_asset_ref(speech_asset: str) -> str:
    """Strip the ``speech_audio:`` prefix from a binding's asset reference."""

    if speech_asset.startswith(SPEECH_ASSET_PREFIX):
        return speech_asset[len(SPEECH_ASSET_PREFIX) :]
    return speech_asset


def _has_talk_keyframes(scene_script: SceneScriptRoot) -> bool:
    return any(
        keyframe.action == "talk"
        for character in scene_script.characters
        for keyframe in character.keyframes
    )


def apply_speech_bound_lip_sync(
    scene_script: SceneScriptRoot,
    *,
    asset_resolver: Callable[[str], Path | None],
) -> AutoLipSyncResult:
    """Apply lip-sync driven by the script's speech bindings.

    Args:
        scene_script: The SceneScript to (possibly) animate.
        asset_resolver: Maps a speech asset ref (prefix already stripped) to a
            local audio file, or None when it cannot be resolved.

    Returns:
        AutoLipSyncResult; ``scene_script`` is the input script when nothing
        was applied (identity — no needless re-render churn).
    """

    bindings = scene_script.speech_bindings
    if not bindings:
        return AutoLipSyncResult(scene_script, applied=False, duration_source="none")

    if _has_talk_keyframes(scene_script):
        return AutoLipSyncResult(
            scene_script,
            applied=False,
            duration_source="none",
            warnings=[
                "lip_sync_already_present: the script already carries talk keyframes; "
                "left untouched (rerun idempotence)"
            ],
        )

    warnings: list[str] = []
    timeline = SpeechTimeline()
    cursors: dict[str, float] = {}
    measured_count = 0
    skipped_count = 0

    for index, binding in enumerate(bindings):
        character_id = binding.character
        asset_ref = speech_asset_ref(binding.speech_asset)
        path = asset_resolver(asset_ref)
        if path is None:
            skipped_count += 1
            warnings.append(
                f"speech_asset_unresolved: {asset_ref} (character '{character_id}') "
                "left un-animated"
            )
            continue
        duration = probe_audio_duration_seconds(str(path))
        if duration is None or duration <= 0:
            skipped_count += 1
            warnings.append(
                f"speech_audio_unreadable: {asset_ref} (character '{character_id}') "
                "left un-animated"
            )
            continue
        measured_count += 1
        start = cursors.get(character_id, 0.0)
        end = start + duration
        cursors[character_id] = end + SEGMENT_GAP_SECONDS
        timeline.add(
            SpeechSegment(
                segment_id=f"seg_{index:03d}",
                character_id=character_id,
                text="",
                start_time=start,
                end_time=end,
            )
        )

    if not timeline.segments:
        return AutoLipSyncResult(
            scene_script,
            applied=False,
            duration_source="none",
            warnings=warnings,
        )

    generator = LipSyncGenerator(frame_rate=scene_script.scene.frame_rate)
    merged = generator.merge_into_scene_script(scene_script, timeline)
    applied = _has_talk_keyframes(merged)
    # "measured" only when every APPLIED segment was probed AND no binding
    # was skipped: a partially animated scene is "mixed", not "measured".
    duration_source = (
        "measured"
        if measured_count == len(timeline.segments) and skipped_count == 0
        else "mixed"
        if measured_count > 0
        else "estimated"
    )
    return AutoLipSyncResult(
        scene_script=merged,
        applied=applied,
        duration_source=duration_source,
        segment_count=len(timeline.segments),
        warnings=warnings,
    )
