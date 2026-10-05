"""
Timeline Clip Auto-Creation Service (ADR 0007)

When a node completes execution and produces a media asset, this service
automatically creates a timeline clip on the appropriate track.

Mapping:
- video node → video track
- voice-cast node → voice track
- audio node (bgm role) → bgm track
- audio node (sfx role) → sfx track
- scene-3d node → camera track (previs camera motion)
- text/script node (subtitle role) → subtitle track
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from app.persistence.models import AssetVersionRow
from app.persistence.timeline_repository import (
    NodeSubtitleCue,
    TimelineRepository,
)
from app.schemas.agent_canvas import CanvasNodeV2

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlannedSubtitleCue:
    """One validated subtitle line parsed from a node output asset."""

    start_seconds: float
    end_seconds: float
    text: str


def parse_subtitle_cue_plan(payload: object) -> tuple[PlannedSubtitleCue, ...] | None:
    """Extract ordered cues from a text/script node output asset.

    Supports two published shapes:
    - canvas script asset: ``{"structured_output": {"subtitleLines":
      [{"startTime", "endTime" (float seconds), "text"}]}}`` (or top-level)
    - provider subtitle plan: ``{"cues": [{"start_time", "end_time"
      ("HH:MM:SS,mmm"), "text"}]}``

    Returns ``None`` when the payload carries neither container so callers
    can fall back to legacy single-clip behaviour; empty recognized plans
    return an empty tuple.
    """
    if not isinstance(payload, dict):
        return None
    structured = payload.get("structured_output")
    lines: list[Any] | None = None
    if isinstance(structured, dict) and isinstance(structured.get("subtitleLines"), list):
        lines = structured["subtitleLines"]
    elif isinstance(payload.get("subtitleLines"), list):
        lines = payload["subtitleLines"]
    elif isinstance(payload.get("cues"), list):
        return _cues_from_srt_plan(payload["cues"])
    if lines is None:
        return None

    cues: list[PlannedSubtitleCue] = []
    for item in lines:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        start = _finite_number(item.get("startTime"))
        end = _finite_number(item.get("endTime"))
        if not text or start is None or end is None or end <= start:
            continue
        cues.append(PlannedSubtitleCue(start_seconds=start, end_seconds=end, text=text))
    cues.sort(key=lambda cue: cue.start_seconds)
    return tuple(cues)


def _cues_from_srt_plan(raw_cues: list[Any]) -> tuple[PlannedSubtitleCue, ...]:
    cues: list[PlannedSubtitleCue] = []
    for item in raw_cues:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        start = _srt_timestamp_seconds(item.get("start_time"))
        end = _srt_timestamp_seconds(item.get("end_time"))
        if not text or start is None or end is None or end <= start:
            continue
        cues.append(PlannedSubtitleCue(start_seconds=start, end_seconds=end, text=text))
    cues.sort(key=lambda cue: cue.start_seconds)
    return tuple(cues)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number else None  # NaN guard
    return None


def _srt_timestamp_seconds(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    text = value.strip().replace(",", ".")
    try:
        hours, minutes, seconds = text.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (ValueError, TypeError):
        return None


@dataclass
class AutoClipContext:
    """Context for auto-creating a timeline clip from a completed node."""

    workflow_id: str
    node_id: str
    node_type: str
    semantic_role: str | None
    output_asset_id: str | None
    output_asset_version_id: str | None
    title: str | None
    duration_hint: float | None = None  # seconds, if known
    #: Where this clip belongs on its track, in seconds. Publish order is not
    #: play order — a director publishing shots out of order should still get a
    #: timeline that plays in shot order — so a caller that knows the shot's
    #: position says so here instead of letting the clip append after whatever
    #: happened to be published last.
    desired_start_time: float | None = None


# Node type → default track type mapping
NODE_TYPE_TO_TRACK: dict[str, str] = {
    "video": "video",
    "voice-cast": "voice",
    "scene-3d": "camera",
}

# Semantic role → track type (for audio nodes that can be bgm or sfx)
ROLE_TO_TRACK: dict[str, str] = {
    "bgm": "bgm",
    "background_music": "bgm",
    "sfx": "sfx",
    "sound_effect": "sfx",
    "subtitle": "subtitle",
    "captions": "subtitle",
}

# Default clip duration when unknown (seconds)
DEFAULT_CLIP_DURATION = 3.0


class TimelineClipAutoCreator:
    """Automatically creates timeline clips when nodes complete."""

    def __init__(
        self,
        repository_factory: Callable[[], TimelineRepository],
        *,
        enabled: bool = True,
        asset_path_resolver: Callable[[str], Path] | None = None,
    ) -> None:
        self._repository_factory = repository_factory
        self._enabled = enabled
        self._asset_path_resolver = asset_path_resolver

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def determine_track_type(self, context: AutoClipContext) -> str | None:
        """Determine which track a node's output should go to."""
        # First check semantic role (for audio nodes that can be bgm/sfx)
        if context.semantic_role:
            role_lower = context.semantic_role.lower()
            if role_lower in ROLE_TO_TRACK:
                return ROLE_TO_TRACK[role_lower]

        # Then check node type
        if context.node_type in NODE_TYPE_TO_TRACK:
            return NODE_TYPE_TO_TRACK[context.node_type]

        # Generic audio → sfx by default
        if context.node_type == "audio":
            return "sfx"

        # Text/script with subtitle-like role
        if context.node_type in {"text", "script"} and context.semantic_role:
            if "subtitle" in context.semantic_role.lower() or "caption" in context.semantic_role.lower():
                return "subtitle"

        return None

    def create_clip_for_node(self, context: AutoClipContext) -> str | None:
        """Create a timeline clip for a completed node. Returns clip_id or None."""
        if not self._enabled:
            return None

        track_type = self.determine_track_type(context)
        if track_type is None:
            logger.debug(
                "No timeline track mapping for node type=%s role=%s, skipping auto-clip",
                context.node_type,
                context.semantic_role,
            )
            return None

        try:
            repo = self._repository_factory()
            try:
                # Get or create timeline for this workflow
                timeline = repo.get_by_workflow_id(context.workflow_id)

                # Find the appropriate track
                track = next(
                    (t for t in timeline.tracks if t.type == track_type),
                    None,
                )
                if track is None:
                    logger.warning(
                        "Track type=%s not found in timeline %s",
                        track_type,
                        timeline.timeline_id,
                    )
                    return None

                if track_type == "subtitle":
                    synced = self._sync_subtitle_clips(
                        repo,
                        timeline_id=timeline.timeline_id,
                        track_id=track.track_id,
                        context=context,
                    )
                    if synced is not None:
                        repo._session.commit()
                        return synced
                    # No readable cue plan: fall back to the single-clip path.

                # Reruns are idempotent: refresh the existing clip in place
                # instead of appending a duplicate shot to the timeline.
                existing_clip = repo.get_latest_node_clip(
                    timeline.timeline_id,
                    context.node_id,
                )

                # Determine duration: explicit hint → asset metadata. On a
                # rerun with unknown duration, keep the arranged clip length
                # rather than snapping back to the 3s default.
                duration = context.duration_hint
                if duration is None and context.output_asset_id:
                    duration = self._resolve_asset_duration(
                        repo,
                        asset_id=context.output_asset_id,
                        asset_version_id=context.output_asset_version_id,
                    )
                if duration is None or duration <= 0:
                    duration = (
                        existing_clip.duration
                        if existing_clip is not None
                        else DEFAULT_CLIP_DURATION
                    )

                # Place (or refresh) the clip. The repository preserves the
                # existing start time / trim / fades / label on rerun.
                clip, created = repo.upsert_auto_clip_for_node(
                    timeline_id=timeline.timeline_id,
                    source_node_id=context.node_id,
                    track_id=track.track_id,
                    duration=duration,
                    asset_id=context.output_asset_id,
                    asset_version_id=context.output_asset_version_id,
                    label=context.title or f"{context.node_type}: {context.node_id[:8]}",
                    # Where the caller wants it. Only meaningful on create:
                    # an existing clip keeps whatever position it already has.
                    desired_start_time=context.desired_start_time,
                )

                action = "created" if created else "updated"
                logger.info(
                    "Auto-%s timeline clip %s on %s track for node %s "
                    "(start=%.1fs, dur=%.1fs)",
                    action,
                    clip.clip_id,
                    track_type,
                    context.node_id,
                    clip.start_time,
                    duration,
                )
                repo._session.commit()
                return clip.clip_id

            except Exception:
                if hasattr(repo, "_session"):
                    repo._session.rollback()
                raise
            finally:
                # Close the session if the repository has one
                if hasattr(repo, "_session"):
                    try:
                        repo._session.close()
                    except Exception:
                        pass
        except Exception as error:
            logger.warning(
                "Failed to auto-create timeline clip for node %s: %s",
                context.node_id,
                error,
                exc_info=True,
            )
            return None

    def _resolve_asset_duration(
        self,
        repo: TimelineRepository,
        *,
        asset_id: str,
        asset_version_id: str | None,
    ) -> float | None:
        """Look up the media duration from the published asset version.

        Prefers the exact published version, otherwise the latest version of
        the asset. Returns None when the asset has no recorded duration
        (e.g. images), so callers can fall back to the default clip length.
        """
        try:
            session = repo._session  # same V2 database as the timeline
            statement = select(AssetVersionRow.duration_seconds).where(
                AssetVersionRow.asset_id == asset_id
            )
            if asset_version_id:
                statement = statement.where(
                    AssetVersionRow.version_id == asset_version_id
                )
            else:
                statement = statement.order_by(
                    AssetVersionRow.version_no.desc()
                )
            duration = session.execute(statement.limit(1)).scalar_one_or_none()
        except Exception as error:
            logger.debug(
                "Could not resolve duration for asset %s: %s", asset_id, error
            )
            return None
        return float(duration) if duration is not None and duration > 0 else None

    def _sync_subtitle_clips(
        self,
        repo: TimelineRepository,
        *,
        timeline_id: str,
        track_id: str,
        context: AutoClipContext,
    ) -> str | None:
        """Reconcile a subtitle node's output asset into one clip per cue.

        Returns the first synced clip id (an empty string when the plan
        legitimately contains no cues), or ``None`` to request legacy
        single-clip fallback (no resolver, missing asset, unreadable file or
        an unrecognized payload shape).
        """
        if self._asset_path_resolver is None or not context.output_asset_id:
            return None
        try:
            asset_path = self._asset_path_resolver(context.output_asset_id)
            payload = json.loads(asset_path.read_text(encoding="utf-8"))
        except Exception as error:
            logger.debug(
                "Subtitle asset %s is not a readable cue plan: %s",
                context.output_asset_id,
                error,
            )
            return None

        planned = parse_subtitle_cue_plan(payload)
        if planned is None:
            logger.debug(
                "Subtitle asset %s has no recognized cue container",
                context.output_asset_id,
            )
            return None

        label = context.title or f"{context.node_type}: {context.node_id[:8]}"
        clips = repo.sync_node_subtitle_clips(
            timeline_id=timeline_id,
            source_node_id=context.node_id,
            track_id=track_id,
            cues=tuple(
                NodeSubtitleCue(
                    start_seconds=cue.start_seconds,
                    end_seconds=cue.end_seconds,
                    text=cue.text,
                )
                for cue in planned
            ),
            asset_id=context.output_asset_id,
            asset_version_id=context.output_asset_version_id,
            label=label,
        )
        logger.info(
            "Synced %d subtitle clip(s) for node %s",
            len(clips),
            context.node_id,
        )
        return clips[0].clip_id if clips else ""

    def create_clip_from_node(
        self,
        node: CanvasNodeV2,
        *,
        output_asset_id: str | None,
        output_asset_version_id: str | None = None,
        duration_hint: float | None = None,
        desired_start_time: float | None = None,
    ) -> str | None:
        """Convenience: create a clip directly from a node object."""
        context = AutoClipContext(
            workflow_id=node.workflow_id,
            node_id=node.node_id,
            node_type=node.node_type,
            semantic_role=node.semantic_role,
            output_asset_id=output_asset_id,
            output_asset_version_id=output_asset_version_id,
            title=node.title,
            duration_hint=duration_hint,
            desired_start_time=desired_start_time,
        )
        return self.create_clip_for_node(context)
