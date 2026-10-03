"""One frame-based plan for replica picture, authored captions and selected sound.

Reference transcript word windows are intentionally never consumed: newly generated
pictures are not a measured target speech performance.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.schemas.workflow_v2 import (
    WorkflowV2Timeline,
    WorkflowV2TimelineAudioControls,
    WorkflowV2TimelineClip,
    WorkflowV2TimelineTrack,
)
from app.services.creation.film_assembly import AssemblyPlanV1


class ReplicaAudioPlacementV1(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    role: Literal["voice", "bgm", "sfx"]
    asset_id: str = Field(min_length=1)
    asset_version_id: str = Field(min_length=1)
    start_seconds: float = Field(default=0, ge=0)
    duration_seconds: float = Field(gt=0)
    trim_start_seconds: float = Field(default=0, ge=0)
    volume: float = Field(default=1, ge=0, le=1)
    fade_in_seconds: float = Field(default=0, ge=0)
    fade_out_seconds: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_fades(self):
        if self.fade_in_seconds + self.fade_out_seconds > self.duration_seconds:
            raise ValueError("audio fades cannot exceed duration")
        return self


@dataclass(frozen=True)
class ReplicaCompositionPlanV1:
    timeline: WorkflowV2Timeline
    plan_hash: str
    warnings: tuple[str, ...]
    owner_id: str


def plan_replica_composition(
    assembly: AssemblyPlanV1,
    *,
    replica_node_id: str,
    blueprint: ReplicaBlueprintContentV2,
    include_captions: bool = True,
    audio_clips: list[ReplicaAudioPlacementV1] | None = None,
    source_audio_policy: Literal["mute", "preserve"] = "mute",
    fps: int = 30,
    ducking: bool = False,
) -> ReplicaCompositionPlanV1:
    if fps < 1 or fps > 120:
        raise ValueError("fps must be between 1 and 120")
    owner = f"replica-plan:{replica_node_id}"
    tracks = [WorkflowV2TimelineTrack(track_id="replica_video", track_type="video", order=1)]
    clips: list[WorkflowV2TimelineClip] = []
    cursor = 0
    warnings: list[str] = []
    for index, placement in enumerate(assembly.placements):
        if not placement.asset_version_id:
            raise ValueError(f"missing version for shot {placement.source_node_id}")
        frames = max(1, round(placement.duration * fps))
        duration = round(frames / fps, 3)
        start = round(cursor / fps, 3)
        shot_index = placement.source_shot_index or index + 1
        source_shot = next((shot for shot in blueprint.shots if shot.index == shot_index), None)
        metadata = {
            "owner_id": owner,
            "source_node_id": placement.source_node_id,
            "source_shot_index": shot_index,
        }
        clips.append(
            WorkflowV2TimelineClip(
                clip_id=f"{owner}:video:{placement.source_node_id}",
                track_id="replica_video",
                clip_type="video",
                source_asset_id=placement.asset_id,
                source_version_id=placement.asset_version_id,
                start_time=start,
                duration=duration,
                audio=WorkflowV2TimelineAudioControls(muted=source_audio_policy == "mute"),
                metadata=metadata,
            )
        )
        if include_captions and source_shot is not None:
            text = source_shot.on_screen_text.strip()
            if text:
                clips.append(
                    WorkflowV2TimelineClip(
                        clip_id=f"{owner}:caption:{placement.source_node_id}",
                        track_id="replica_subtitle",
                        clip_type="subtitle",
                        start_time=start,
                        duration=duration,
                        text=text,
                        metadata={
                            **metadata,
                            "timing_quality": "authored_shot",
                            "not_speech_aligned": True,
                        },
                    )
                )
        cursor += frames
    if not cursor:
        raise ValueError("composition requires at least one shot")
    total = round(cursor / fps, 3)
    if any(clip.clip_type == "subtitle" for clip in clips):
        tracks.append(
            WorkflowV2TimelineTrack(track_id="replica_subtitle", track_type="subtitle", order=2)
        )
        warnings.append("captions_authored_shot_timing_not_word_aligned")
    for index, audio in enumerate(audio_clips or []):
        start = round(round(audio.start_seconds * fps) / fps, 3)
        duration = round(round(audio.duration_seconds * fps) / fps, 3)
        if duration <= 0 or start + duration > total + 0.001:
            raise ValueError("audio placement must fit the picture program")
        track_id = f"replica_{audio.role}"
        if not any(track.track_id == track_id for track in tracks):
            tracks.append(
                WorkflowV2TimelineTrack(
                    track_id=track_id,
                    track_type="audio",
                    order=len(tracks) + 1,
                    metadata={"audio_role": audio.role},
                )
            )
        clips.append(
            WorkflowV2TimelineClip(
                clip_id=f"{owner}:audio:{index}",
                track_id=track_id,
                clip_type="audio",
                source_asset_id=audio.asset_id,
                source_version_id=audio.asset_version_id,
                start_time=start,
                duration=duration,
                trim_in=audio.trim_start_seconds,
                audio=WorkflowV2TimelineAudioControls(
                    volume=audio.volume,
                    fade_in_seconds=audio.fade_in_seconds,
                    fade_out_seconds=audio.fade_out_seconds,
                ),
                metadata={"owner_id": owner, "audio_role": audio.role},
            )
        )
    timeline = WorkflowV2Timeline(
        timeline_id=f"replica-composition:{replica_node_id}",
        duration_seconds=total,
        aspect_ratio=blueprint.aspect or "16:9",
        fps=fps,
        tracks=tracks,
        clips=clips,
        metadata={
            "source": "replica_composition",
            "requires_timeline_editor": True,
            "resolution_source": "replica_composition",
            "edit_mode": "system_default",
            "owner_id": owner,
            "source_audio_policy": source_audio_policy,
            "warnings": warnings,
            "ducking": {
                "enabled": ducking,
                "threshold_db": -30,
                "ratio": 12,
                "attack_ms": 50,
                "release_ms": 250,
            },
        },
    )
    encoded = json.dumps(timeline.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    plan_hash = "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()
    timeline.metadata["replica_composition_plan_hash"] = plan_hash
    return ReplicaCompositionPlanV1(timeline, plan_hash, tuple(warnings), owner)
