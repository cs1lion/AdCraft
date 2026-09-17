/**
 * Global Timeline Panel (ADR 0007)
 *
 * A collapsible panel at the bottom of the canvas that shows all tracks
 * (video / voice / bgm / sfx / camera / subtitle) and their clips on a
 * time-axis. This is the orchestration layer above nodes.
 *
 * Phase 2 additions:
 * - Audio track controls (mute + volume) for voice/bgm/sfx tracks
 * - Selected-clip inspector (precise timing / trim / fade / label edits)
 * - Auto-ducking settings popover persisted on the timeline
 * - Observable renderer degradation: capability probe + post-export banner,
 *   so missing sidechaincompress is never a silent fallback
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type {
  TimelineAudioDegradationEventV1,
  TimelineClipV1,
  TimelineDuckingConfigV1,
  TimelineTrackTypeV1,
  TimelineTrackV1,
  TimelineV1,
} from "./timelineTypes.ts";
import {
  AUDIO_DUCKING_UNAVAILABLE,
  deleteClip,
  getMediaToolchainCapabilities,
  getTimeline,
  listLatestAudioDegradations,
  updateClip,
  updateTimeline,
  updateTrack,
} from "./timelineApi.ts";

const TRACK_COLORS: Record<TimelineTrackTypeV1, string> = {
  video: "#4f8cff",
  voice: "#52c41a",
  bgm: "#faad14",
  sfx: "#722ed1",
  camera: "#13c2c2",
  subtitle: "#f5222d",
};

const TRACK_ICONS: Record<TimelineTrackTypeV1, string> = {
  video: "🎬",
  voice: "🎙️",
  bgm: "🎵",
  sfx: "🔊",
  camera: "📷",
  subtitle: "💬",
};

const AUDIO_ROLES: ReadonlySet<TimelineTrackTypeV1> = new Set(["voice", "bgm", "sfx"]);

/** Renderer-side defaults — duplicated on purpose so the timeline chunk has
 *  no import dependency on the editing manifest package. */
const DUCKING_DEFAULTS: TimelineDuckingConfigV1 = {
  enabled: true,
  threshold_db: -30.0,
  ratio: 12.0,
  attack_ms: 50,
  release_ms: 250,
  makeup_gain_db: 0.0,
};

const DUCKING_LIMITS = {
  threshold_db: { min: -80, max: -10, step: 1 },
  ratio: { min: 1.5, max: 60, step: 0.5 },
  attack_ms: { min: 0, max: 2000, step: 10 },
  release_ms: { min: 0, max: 5000, step: 50 },
  makeup_gain_db: { min: 0, max: 24, step: 0.5 },
} as const;

const DEGRADATION_POLL_MS = 15_000;

interface GlobalTimelinePanelProps {
  workflowId: string;
  onClipClick?: (clip: TimelineClipV1) => void;
  onTrackClick?: (track: TimelineTrackV1) => void;
}

const PIXELS_PER_SECOND = 40;
const TRACK_HEIGHT = 48;
const TRACK_LABEL_WIDTH = 150;

interface DuckingFormState {
  enabled: boolean;
  threshold_db: string;
  ratio: string;
  attack_ms: string;
  release_ms: string;
  makeup_gain_db: string;
}

interface ClipInspectorDraft {
  clipId: string;
  start_time: string;
  duration: string;
  source_start: string;
  source_duration: string;
  fade_in: string;
  fade_out: string;
  label: string;
}

function duckingToForm(config: TimelineDuckingConfigV1 | null | undefined): DuckingFormState {
  const source = config ?? DUCKING_DEFAULTS;
  return {
    enabled: source.enabled,
    threshold_db: String(source.threshold_db),
    ratio: String(source.ratio),
    attack_ms: String(source.attack_ms),
    release_ms: String(source.release_ms),
    makeup_gain_db: String(source.makeup_gain_db),
  };
}

function _parseOptionalNonNegative(raw: string): number | null | "invalid" {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  if (!Number.isFinite(value) || value < 0) return "invalid";
  return value;
}

export function GlobalTimelinePanel({
  workflowId,
  onClipClick,
  onTrackClick,
}: GlobalTimelinePanelProps) {
  const [timeline, setTimeline] = useState<TimelineV1 | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [dragInteraction, setDragInteraction] = useState<{
    clipId: string;
    mode: "move" | "resize-left" | "resize-right";
    pointerStartX: number;
    origStartTime: number;
    origDuration: number;
  } | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const playbackRef = useRef<number | null>(null);
  const dragMovedRef = useRef(false);

  // Audio track control state
  const [savingTrackId, setSavingTrackId] = useState<string | null>(null);

  // Clip inspector state
  const [inspectorDraft, setInspectorDraft] = useState<ClipInspectorDraft | null>(null);
  const [inspectorSaving, setInspectorSaving] = useState(false);
  const [inspectorError, setInspectorError] = useState<string | null>(null);

  // Ducking UI state
  const [duckingOpen, setDuckingOpen] = useState(false);
  const [duckingForm, setDuckingForm] = useState<DuckingFormState>(() =>
    duckingToForm(null),
  );
  const [duckingSaving, setDuckingSaving] = useState(false);
  const [duckingError, setDuckingError] = useState<string | null>(null);

  // Renderer capability probe (single source of truth lives server-side).
  const [capability, setCapability] = useState<{
    phase: "loading" | "ready" | "error";
    audioDucking: boolean;
  }>({ phase: "loading", audioDucking: false });

  // Latest observable renderer degradation for this workflow.
  const [degradation, setDegradation] = useState<TimelineAudioDegradationEventV1 | null>(
    null,
  );
  const [dismissedDegradationSeq, setDismissedDegradationSeq] = useState<number | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTimeline(workflowId)
      .then((data) => {
        if (!cancelled) {
          setTimeline(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load timeline");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [workflowId]);

  // Probe the renderer once: drives the proactive ducking warning.
  useEffect(() => {
    let cancelled = false;
    getMediaToolchainCapabilities()
      .then((snapshot) => {
        if (!cancelled) {
          setCapability({
            phase: "ready",
            audioDucking: Boolean(snapshot.feature_flags?.audio_ducking),
          });
        }
      })
      .catch(() => {
        if (!cancelled) setCapability({ phase: "error", audioDucking: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Poll for post-export audio degradations so fallback is never silent.
  useEffect(() => {
    if (collapsed) return;
    let cancelled = false;
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const events = await listLatestAudioDegradations(workflowId, controller.signal);
        if (!cancelled && events.length > 0) {
          setDegradation(events.reduce((latest, event) =>
            event.seq > latest.seq ? event : latest,
          ));
        }
      } catch (err) {
        if (!cancelled && !(err instanceof DOMException && err.name === "AbortError")) {
          // Banner is best-effort; never block the timeline on event fetches.
          console.warn("Failed to load audio degradation events", err);
        }
      }
    };
    void refresh();
    const interval = window.setInterval(() => void refresh(), DEGRADATION_POLL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(interval);
    };
  }, [workflowId, collapsed]);

  const totalDuration = useMemo(() => {
    if (!timeline) return 30;
    const maxClipEnd = Math.max(
      0,
      ...timeline.tracks.flatMap((track) =>
        track.clips.map((clip) => clip.start_time + clip.duration),
      ),
    );
    return Math.max(timeline.duration_seconds, maxClipEnd, 10);
  }, [timeline]);

  const sortedTracks = useMemo(() => {
    if (!timeline) return [];
    return [...timeline.tracks].sort((a, b) => a.display_order - b.display_order);
  }, [timeline]);

  const audioRoleClips = useMemo(() => {
    const counts = { voice: 0, bgm: 0, sfx: 0 } as Record<string, number>;
    for (const track of timeline?.tracks ?? []) {
      if (AUDIO_ROLES.has(track.type)) counts[track.type] += track.clips.length;
    }
    return counts;
  }, [timeline]);

  const duckingAvailable = audioRoleClips.voice > 0 && audioRoleClips.bgm > 0;

  // Playback loop
  useEffect(() => {
    if (!isPlaying) {
      if (playbackRef.current) {
        cancelAnimationFrame(playbackRef.current);
        playbackRef.current = null;
      }
      return;
    }
    let lastTime = performance.now();
    const tick = (now: number) => {
      const delta = (now - lastTime) / 1000;
      lastTime = now;
      setCurrentTime((prev) => {
        const next = prev + delta;
        if (next >= totalDuration) {
          setIsPlaying(false);
          return totalDuration;
        }
        return next;
      });
      playbackRef.current = requestAnimationFrame(tick);
    };
    playbackRef.current = requestAnimationFrame(tick);
    return () => {
      if (playbackRef.current) {
        cancelAnimationFrame(playbackRef.current);
      }
    };
  }, [isPlaying, totalDuration]);

  const togglePlay = () => {
    if (currentTime >= totalDuration) {
      setCurrentTime(0);
    }
    setIsPlaying((p) => !p);
  };

  const seekTo = (time: number) => {
    setCurrentTime(Math.max(0, Math.min(time, totalDuration)));
  };

  const stepFrame = (direction: number) => {
    const fps = timeline?.fps || 30;
    const frameTime = 1 / fps;
    seekTo(currentTime + direction * frameTime);
  };

  const resyncTimeline = async () => {
    try {
      setTimeline(await getTimeline(workflowId));
    } catch (resyncError) {
      console.error("Failed to resync timeline:", resyncError);
    }
  };

  // --- Audio track controls ---

  const persistTrackPatch = async (
    track: TimelineTrackV1,
    patch: Partial<Pick<TimelineTrackV1, "muted" | "volume">>,
  ) => {
    if (savingTrackId) return;
    setSavingTrackId(track.track_id);
    setTimeline((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        tracks: prev.tracks.map((candidate) =>
          candidate.track_id === track.track_id
            ? { ...candidate, ...patch }
            : candidate,
        ),
      };
    });
    try {
      await updateTrack(workflowId, track.track_id, patch);
    } catch (err) {
      console.error("Failed to persist track control change:", err);
      await resyncTimeline();
    } finally {
      setSavingTrackId(null);
    }
  };

  // --- Clip drag ---

  const beginClipDrag = (
    e: React.MouseEvent,
    clip: TimelineClipV1,
    track: TimelineTrackV1,
    mode: "move" | "resize-left" | "resize-right",
  ) => {
    if (track.locked) return;
    e.stopPropagation();
    e.preventDefault();
    dragMovedRef.current = false;
    setDragInteraction({
      clipId: clip.clip_id,
      mode,
      pointerStartX: e.clientX,
      origStartTime: clip.start_time,
      origDuration: clip.duration,
    });
  };

  const handleContainerMouseMove = (e: React.MouseEvent) => {
    if (!dragInteraction || !timeline) return;
    if (Math.abs(e.clientX - dragInteraction.pointerStartX) > 4) {
      dragMovedRef.current = true;
    }
    const fps = timeline.fps || 30;
    const frame = 1 / fps;
    const snapToFrame = (value: number) =>
      Math.max(0, Math.round(value * fps) / fps);
    const delta =
      (e.clientX - dragInteraction.pointerStartX) / PIXELS_PER_SECOND;

    let nextStart = dragInteraction.origStartTime;
    let nextDuration = dragInteraction.origDuration;

    if (dragInteraction.mode === "move") {
      nextStart = snapToFrame(dragInteraction.origStartTime + delta);
    } else if (dragInteraction.mode === "resize-left") {
      const bounded = Math.min(
        dragInteraction.origStartTime + delta,
        dragInteraction.origStartTime + dragInteraction.origDuration - frame,
      );
      nextStart = snapToFrame(bounded);
      nextDuration = Math.max(
        frame,
        dragInteraction.origDuration -
          (nextStart - dragInteraction.origStartTime),
      );
    } else {
      nextDuration = Math.max(
        frame,
        snapToFrame(dragInteraction.origDuration + delta),
      );
    }

    const interactionId = dragInteraction.clipId;
    setTimeline((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        tracks: prev.tracks.map((track) => ({
          ...track,
          clips: track.clips.map((clip) =>
            clip.clip_id === interactionId
              ? { ...clip, start_time: nextStart, duration: nextDuration }
              : clip,
          ),
        })),
      };
    });
  };

  const finishClipDrag = async () => {
    const interaction = dragInteraction;
    if (!interaction) return;
    setDragInteraction(null);
    const draggedClip = timeline?.tracks
      .flatMap((track) => track.clips)
      .find((clip) => clip.clip_id === interaction.clipId);
    if (!draggedClip) return;

    const startChanged =
      Math.abs(draggedClip.start_time - interaction.origStartTime) > 1e-6;
    const durationChanged =
      Math.abs(draggedClip.duration - interaction.origDuration) > 1e-6;
    if (!startChanged && !durationChanged) return;

    try {
      await updateClip(workflowId, interaction.clipId, {
        start_time: draggedClip.start_time,
        duration: draggedClip.duration,
      });
    } catch (err) {
      console.error("Failed to persist clip drag:", err);
      // Resync local state with the server after a rejected write
      await resyncTimeline();
    }
  };

  const handleClipClick = (clip: TimelineClipV1) => {
    // A click that follows a drag must not toggle selection
    if (dragMovedRef.current) {
      dragMovedRef.current = false;
      return;
    }
    setSelectedClipId(clip.clip_id === selectedClipId ? null : clip.clip_id);
    onClipClick?.(clip);
  };

  const selectedClip = useMemo(() => {
    if (!selectedClipId || !timeline) return null;
    for (const track of timeline.tracks) {
      const found = track.clips.find((c) => c.clip_id === selectedClipId);
      if (found) return { clip: found, track };
    }
    return null;
  }, [selectedClipId, timeline]);

  // Hydrate the inspector draft from the current selection.
  useEffect(() => {
    setInspectorError(null);
    if (!selectedClip) {
      setInspectorDraft(null);
      return;
    }
    const { clip } = selectedClip;
    setInspectorDraft({
      clipId: clip.clip_id,
      start_time: String(clip.start_time),
      duration: String(clip.duration),
      source_start: String(clip.source_start ?? 0),
      source_duration: clip.source_duration == null ? "" : String(clip.source_duration),
      fade_in: clip.fade_in == null ? "" : String(clip.fade_in),
      fade_out: clip.fade_out == null ? "" : String(clip.fade_out),
      label: clip.label ?? "",
    });
  }, [selectedClip]);

  // --- Clip inspector persistence ---

  const patchInspector = (patch: Partial<ClipInspectorDraft>) => {
    setInspectorDraft((current) => (current ? { ...current, ...patch } : current));
  };

  const saveInspector = async () => {
    if (!inspectorDraft || !selectedClip) return;
    const draft = inspectorDraft;

    const startTime = Number(draft.start_time);
    const duration = Number(draft.duration);
    const sourceStart = Number(draft.source_start || "0");
    if (!Number.isFinite(startTime) || startTime < 0) {
      setInspectorError("Start time must be a non-negative number of seconds.");
      return;
    }
    if (!Number.isFinite(duration) || duration <= 0) {
      setInspectorError("Duration must be greater than 0 seconds.");
      return;
    }
    if (!Number.isFinite(sourceStart) || sourceStart < 0) {
      setInspectorError("Source in-point must be a non-negative number of seconds.");
      return;
    }
    const sourceDuration = _parseOptionalNonNegative(draft.source_duration);
    if (sourceDuration === "invalid") {
      setInspectorError("Source length must be a non-negative number (or empty).");
      return;
    }
    const fadeIn = _parseOptionalNonNegative(draft.fade_in);
    if (fadeIn === "invalid") {
      setInspectorError("Fade in must be a non-negative number of seconds.");
      return;
    }
    const fadeOut = _parseOptionalNonNegative(draft.fade_out);
    if (fadeOut === "invalid") {
      setInspectorError("Fade out must be a non-negative number of seconds.");
      return;
    }

    setInspectorSaving(true);
    setInspectorError(null);
    try {
      const updated = await updateClip(workflowId, draft.clipId, {
        start_time: startTime,
        duration,
        source_start: sourceStart,
        source_duration: sourceDuration,
        fade_in: AUDIO_ROLES.has(selectedClip.track.type) ? fadeIn : undefined,
        fade_out: AUDIO_ROLES.has(selectedClip.track.type) ? fadeOut : undefined,
        label: draft.label.trim() ? draft.label.trim() : null,
      });
      setTimeline((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          tracks: prev.tracks.map((track) => ({
            ...track,
            clips: track.clips.map((clip) =>
              clip.clip_id === updated.clip_id ? updated : clip,
            ),
          })),
        };
      });
    } catch (err) {
      console.error("Failed to persist clip inspector edits:", err);
      setInspectorError(
        err instanceof Error ? err.message : "Failed to save clip edits.",
      );
      await resyncTimeline();
    } finally {
      setInspectorSaving(false);
    }
  };

  const removeSelectedClip = async () => {
    if (!selectedClip) return;
    const { clip } = selectedClip;
    setInspectorSaving(true);
    setInspectorError(null);
    try {
      await deleteClip(workflowId, clip.clip_id);
      setSelectedClipId(null);
      await resyncTimeline();
    } catch (err) {
      console.error("Failed to delete clip:", err);
      setInspectorError(err instanceof Error ? err.message : "Failed to delete clip.");
    } finally {
      setInspectorSaving(false);
    }
  };

  // --- Ducking settings ---

  const openDucking = () => {
    setDuckingForm(duckingToForm(timeline?.ducking ?? null));
    setDuckingError(null);
    setDuckingOpen(true);
  };

  const saveDucking = async (resetToAuto = false) => {
    if (!timeline) return;
    setDuckingSaving(true);
    setDuckingError(null);
    try {
      let payload: TimelineDuckingConfigV1 | null;
      if (resetToAuto) {
        payload = null;
      } else {
        const threshold = Number(duckingForm.threshold_db);
        const ratio = Number(duckingForm.ratio);
        const attack = Number(duckingForm.attack_ms);
        const release = Number(duckingForm.release_ms);
        const makeup = Number(duckingForm.makeup_gain_db);
        const inRange = (value: number, bounds: { min: number; max: number }) =>
          Number.isFinite(value) && value >= bounds.min && value <= bounds.max;
        if (
          !inRange(threshold, DUCKING_LIMITS.threshold_db)
          || !inRange(ratio, { ...DUCKING_LIMITS.ratio, min: 1.01 })
          || !inRange(attack, DUCKING_LIMITS.attack_ms)
          || !inRange(release, DUCKING_LIMITS.release_ms)
          || !inRange(makeup, DUCKING_LIMITS.makeup_gain_db)
        ) {
          setDuckingError("One or more ducking parameters are outside their valid range.");
          setDuckingSaving(false);
          return;
        }
        payload = {
          enabled: duckingForm.enabled,
          threshold_db: threshold,
          ratio,
          attack_ms: Math.round(attack),
          release_ms: Math.round(release),
          makeup_gain_db: makeup,
        };
      }
      const updated = await updateTimeline(workflowId, { ducking: payload });
      setTimeline((prev) => (prev ? { ...prev, ducking: updated.ducking ?? null } : prev));
      setDuckingOpen(false);
    } catch (err) {
      console.error("Failed to persist ducking settings:", err);
      setDuckingError(err instanceof Error ? err.message : "Failed to save ducking settings.");
    } finally {
      setDuckingSaving(false);
    }
  };

  const duckingStateLabel = useMemo(() => {
    if (!timeline?.ducking) return "Auto";
    return timeline.ducking.enabled ? "On" : "Off";
  }, [timeline]);

  const visibleDegradation =
    degradation && degradation.seq !== dismissedDegradationSeq ? degradation : null;

  if (collapsed) {
    return (
      <div
        role="button"
        tabIndex={0}
        aria-label="Expand timeline panel"
        style={{
          borderTop: "1px solid #333333",
          background: "#141414",
          padding: "8px 16px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          cursor: "pointer",
        }}
        onClick={() => setCollapsed(false)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setCollapsed(false);
          }
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 13 }}>
          🎬 Timeline {timeline ? `(${timeline.tracks.length} tracks)` : ""}
        </span>
        <span style={{ fontSize: 12, color: "#cccccc" }}>Click to expand</span>
      </div>
    );
  }

  const smallBtnStyle: React.CSSProperties = {
    border: "1px solid #444",
    background: "#2a2a2a",
    color: "#ccc",
    cursor: "pointer",
    fontSize: 11,
    padding: "2px 5px",
    borderRadius: 3,
  };

  return (
    <div
      style={{
        borderTop: "1px solid #333333",
        background: "#141414",
        display: "flex",
        flexDirection: "column",
        height: 280,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "8px 16px",
          borderBottom: "1px solid #333333",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          background: "#1e1e1e",
          position: "relative",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontWeight: 600, fontSize: 13 }}>🎬 Timeline</span>
          {timeline && (
            <span style={{ fontSize: 12, color: "#cccccc" }}>
              {totalDuration.toFixed(1)}s · {timeline.fps}fps ·{" "}
              {timeline.tracks.reduce((sum, t) => sum + t.clips.length, 0)} clips
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <button
            onClick={stepFrame.bind(null, -1)}
            title="Prev frame"
            style={smallBtnStyle}
          >
            ⏮
          </button>
          <button
            onClick={togglePlay}
            title={isPlaying ? "Pause" : "Play"}
            style={{
              ...smallBtnStyle,
              background: isPlaying ? "#1a5fb4" : "#2a2a2a",
              color: "#fff",
              fontSize: 13,
              padding: "2px 8px",
              minWidth: 28,
            }}
          >
            {isPlaying ? "⏸" : "▶"}
          </button>
          <button onClick={() => stepFrame(1)} title="Next frame" style={smallBtnStyle}>
            ⏭
          </button>
          <span
            style={{
              fontSize: 10,
              color: "#888",
              fontFamily: "monospace",
              minWidth: 45,
              textAlign: "center",
            }}
          >
            {currentTime.toFixed(2)}s
          </span>
          <button
            onClick={openDucking}
            title="Auto-ducking settings (lower BGM while voice plays)"
            aria-haspopup="dialog"
            aria-expanded={duckingOpen}
            data-testid="timeline-ducking-button"
            style={{
              ...smallBtnStyle,
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              borderColor:
                timeline?.ducking?.enabled && capability.phase === "ready" && !capability.audioDucking
                  ? "#d48806"
                  : "#444",
            }}
          >
            <span
              aria-hidden
              style={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: !duckingAvailable
                  ? "#666"
                  : capability.phase === "ready" && !capability.audioDucking
                    ? "#faad14"
                    : timeline?.ducking?.enabled === false
                      ? "#888"
                      : "#52c41a",
              }}
            />
            🦆 Ducking · {duckingStateLabel}
          </button>
          <button
            onClick={() => setCollapsed(true)}
            style={{
              border: "none",
              background: "none",
              cursor: "pointer",
              fontSize: 14,
              color: "#888",
              padding: "4px 6px",
            }}
          >
            ▼
          </button>
        </div>

        {/* Ducking popover */}
        {duckingOpen && (
          <>
            {/* Click-away layer (aria-hidden: keyboard dismissal lives in the popover's Close button) */}
            <div
              aria-hidden
              style={{ position: "fixed", inset: 0, zIndex: 40 }}
              onClick={() => setDuckingOpen(false)}
            />
            <div
              role="dialog"
              aria-label="Auto-ducking settings"
              data-testid="timeline-ducking-popover"
              style={{
                position: "absolute",
                top: "100%",
                right: 36,
                marginTop: 4,
                width: 300,
                zIndex: 41,
                background: "#242424",
                border: "1px solid #444",
                borderRadius: 6,
                boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
                padding: 12,
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 8,
                }}
              >
                <strong style={{ fontSize: 12 }}>Auto-ducking (sidechain)</strong>
                <button
                  onClick={() => setDuckingOpen(false)}
                  style={{ border: "none", background: "none", color: "#999", cursor: "pointer" }}
                  aria-label="Close ducking settings"
                >
                  ✕
                </button>
              </div>

              {!duckingAvailable && (
                <div
                  style={{
                    fontSize: 11,
                    color: "#d48806",
                    background: "rgba(250,173,20,0.1)",
                    border: "1px solid rgba(250,173,20,0.3)",
                    borderRadius: 4,
                    padding: "6px 8px",
                    marginBottom: 8,
                  }}
                >
                  Add at least one Voice and one BGM clip: ducking is applied only
                  while both roles are present in the export.
                </div>
              )}

              {capability.phase === "ready" && !capability.audioDucking && (
                <div
                  role="status"
                  data-testid="timeline-ducking-unsupported"
                  style={{
                    fontSize: 11,
                    color: "#faad14",
                    background: "rgba(250,173,20,0.12)",
                    border: "1px solid rgba(250,173,20,0.35)",
                    borderRadius: 4,
                    padding: "6px 8px",
                    marginBottom: 8,
                  }}
                >
                  This renderer has no <code>sidechaincompress</code> filter. Exports
                  will fall back to a static-volume mix and the run is flagged with an
                  audible-degradation event.
                </div>
              )}

              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 12,
                  marginBottom: 8,
                }}
              >
                <input
                  type="checkbox"
                  checked={duckingForm.enabled}
                  onChange={(event) =>
                    setDuckingForm((current) => ({
                      ...current,
                      enabled: event.currentTarget.checked,
                    }))
                  }
                />
                Enable auto-ducking
              </label>

              <fieldset
                disabled={!duckingForm.enabled}
                style={{ border: "none", padding: 0, margin: 0, opacity: duckingForm.enabled ? 1 : 0.55 }}
              >
                {(
                  [
                    ["threshold_db", "Threshold (dB)"],
                    ["ratio", "Ratio"],
                    ["attack_ms", "Attack (ms)"],
                    ["release_ms", "Release (ms)"],
                    ["makeup_gain_db", "Make-up gain (dB)"],
                  ] as const
                ).map(([field, labelText]) => (
                  <div
                    key={field}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 6,
                    }}
                  >
                    <span style={{ fontSize: 11, width: 118, color: "#cccccc" }}>
                      {labelText}
                    </span>
                    <input
                      type="range"
                      aria-label={labelText}
                      min={DUCKING_LIMITS[field].min}
                      max={DUCKING_LIMITS[field].max}
                      step={DUCKING_LIMITS[field].step}
                      value={Number(duckingForm[field]) || 0}
                      onChange={(event) =>
                        patchDuckingField(field, event.currentTarget.value)
                      }
                      style={{ flex: 1 }}
                    />
                    <input
                      type="number"
                      aria-label={`${labelText} value`}
                      min={DUCKING_LIMITS[field].min}
                      max={DUCKING_LIMITS[field].max}
                      step={DUCKING_LIMITS[field].step}
                      value={duckingForm[field]}
                      onChange={(event) =>
                        patchDuckingField(field, event.currentTarget.value)
                      }
                      style={{
                        width: 64,
                        fontSize: 11,
                        background: "#1a1a1a",
                        color: "#eee",
                        border: "1px solid #444",
                        borderRadius: 3,
                        padding: "2px 4px",
                      }}
                    />
                  </div>
                ))}
              </fieldset>

              {timeline?.ducking == null && (
                <div style={{ fontSize: 10, color: "#888", marginBottom: 8 }}>
                  No saved override — renderer defaults are in use (Auto).
                </div>
              )}

              {duckingError && (
                <div style={{ fontSize: 11, color: "#f5222d", marginBottom: 8 }}>
                  {duckingError}
                </div>
              )}

              <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                <button
                  onClick={() => void saveDucking(true)}
                  disabled={duckingSaving || timeline?.ducking == null}
                  style={{ ...smallBtnStyle, fontSize: 11 }}
                  title="Clear the override and let the renderer choose defaults"
                >
                  Reset to Auto
                </button>
                <button
                  onClick={() => void saveDucking(false)}
                  disabled={duckingSaving}
                  data-testid="timeline-ducking-save"
                  style={{
                    ...smallBtnStyle,
                    background: "#1a5fb4",
                    borderColor: "#1a5fb4",
                    color: "#fff",
                    fontSize: 11,
                  }}
                >
                  {duckingSaving ? "Saving…" : "Save"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Observable degradation banner */}
      {visibleDegradation && (
        <div
          role="status"
          data-testid="timeline-audio-degradation-banner"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "6px 16px",
            background: "rgba(250,173,20,0.12)",
            borderBottom: "1px solid rgba(250,173,20,0.35)",
            fontSize: 11,
            color: "#ffd591",
          }}
        >
          <span aria-hidden>⚠</span>
          <span style={{ flex: 1 }}>
            Last export
            {visibleDegradation.payload?.export_id
              ? ` (${String(visibleDegradation.payload.export_id).slice(-12)})`
              : ""}{" "}
            could not apply auto-ducking
            {visibleDegradation.payload?.degradations?.includes(
              AUDIO_DUCKING_UNAVAILABLE,
            )
              ? ": this renderer lacks the sidechaincompress filter, so a static-volume mix was used."
              : `: ${(visibleDegradation.payload?.degradations ?? []).join(", ") || "audio mixing was degraded"}.`}
          </span>
          <button
            onClick={() => setDismissedDegradationSeq(visibleDegradation.seq)}
            aria-label="Dismiss degradation notice"
            style={{ border: "none", background: "none", color: "#ffd591", cursor: "pointer" }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Content */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- Scroll surface only hosts drag move/up listeners; clips own the keyboard-accessible actions. */}
      <div
        style={{ flex: 1, overflow: "auto", position: "relative" }}
        onMouseMove={handleContainerMouseMove}
        onMouseUp={() => void finishClipDrag()}
        onMouseLeave={() => void finishClipDrag()}
      >
        {loading && (
          <div style={{ padding: 24, textAlign: "center", color: "#cccccc" }}>
            Loading timeline...
          </div>
        )}
        {error && (
          <div style={{ padding: 24, textAlign: "center", color: "#f5222d" }}>
            {error}
          </div>
        )}
        {!loading && !error && timeline && (
          <div
            style={{
              minWidth: TRACK_LABEL_WIDTH + totalDuration * PIXELS_PER_SECOND + 40,
            }}
          >
            {/* Time ruler */}
            <div
              style={{
                position: "sticky",
                top: 0,
                background: "#252525",
                borderBottom: "1px solid #333333",
                height: 24,
                display: "flex",
                zIndex: 2,
              }}
            >
              <div style={{ width: TRACK_LABEL_WIDTH, flexShrink: 0 }} />
              <div style={{ position: "relative", flex: 1 }}>
                {Array.from({ length: Math.ceil(totalDuration) + 1 }).map((_, i) => (
                  <div
                    key={i}
                    style={{
                      position: "absolute",
                      left: i * PIXELS_PER_SECOND,
                      top: 0,
                      bottom: 0,
                      borderLeft:
                        i % 5 === 0 ? "1px solid #555555" : "1px solid #2a2a2a",
                      display: "flex",
                      alignItems: "center",
                      paddingLeft: 4,
                      fontSize: 10,
                      color: i % 5 === 0 ? "#666666aaa" : "#666666",
                    }}
                  >
                    {i}s
                  </div>
                ))}
              </div>
            </div>

            {/* Tracks */}
            {sortedTracks.map((track) => {
              const isAudioRole = AUDIO_ROLES.has(track.type);
              return (
                <div
                  key={track.track_id}
                  role="button"
                  tabIndex={0}
                  aria-label={`${track.name} track`}
                  style={{
                    display: "flex",
                    borderBottom: "1px solid #2a2a2a",
                    height: TRACK_HEIGHT,
                    cursor: onTrackClick ? "pointer" : "default",
                  }}
                  onClick={() => onTrackClick?.(track)}
                  onKeyDown={(e) => {
                    if (
                      onTrackClick &&
                      (e.key === "Enter" || e.key === " ")
                    ) {
                      e.preventDefault();
                      onTrackClick(track);
                    }
                  }}
                >
                  {/* Track label */}
                  {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events -- Label surface only swallows bubbled clicks so track-level selection does not fire from its own mute/volume controls; the row owns keyboard handling. */}
                  <div
                    style={{
                      width: TRACK_LABEL_WIDTH,
                      flexShrink: 0,
                      padding: "2px 8px",
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "center",
                      gap: 2,
                      borderRight: "1px solid #333333",
                      background: track.muted ? "#2a2a2a" : "#1e1e1e",
                      opacity: track.muted ? 0.65 : 1,
                    }}
                    onClick={(event) => event.stopPropagation()}
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                        minWidth: 0,
                      }}
                    >
                      <span style={{ fontSize: 12 }}>{TRACK_ICONS[track.type]}</span>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 500,
                          color: "#cccccc",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {track.name}
                      </span>
                      {track.locked && (
                        <span style={{ fontSize: 9, color: "#999999" }}>🔒</span>
                      )}
                    </div>
                    {isAudioRole && (
                      <div
                        style={{ display: "flex", alignItems: "center", gap: 4 }}
                      >
                        <button
                          type="button"
                          aria-label={track.muted ? `Unmute ${track.name}` : `Mute ${track.name}`}
                          aria-pressed={track.muted}
                          disabled={track.locked || savingTrackId === track.track_id}
                          title={track.muted ? "Unmute track" : "Mute track"}
                          onClick={() =>
                            void persistTrackPatch(track, { muted: !track.muted })
                          }
                          style={{
                            border: "none",
                            background: "none",
                            cursor: track.locked ? "not-allowed" : "pointer",
                            fontSize: 11,
                            padding: 0,
                            lineHeight: 1,
                            opacity: track.muted ? 0.7 : 1,
                          }}
                        >
                          {track.muted ? "🔇" : "🔊"}
                        </button>
                        <input
                          type="range"
                          min={0}
                          max={1}
                          step={0.05}
                          value={track.volume}
                          disabled={
                            track.muted
                            || track.locked
                            || savingTrackId === track.track_id
                          }
                          aria-label={`${track.name} track volume`}
                          title={`Track volume ${Math.round(track.volume * 100)}%`}
                          onChange={(event) =>
                            void persistTrackPatch(track, {
                              volume: Number(event.currentTarget.value),
                            })
                          }
                          style={{ flex: 1, minWidth: 0, padding: 0 }}
                        />
                        <span
                          style={{
                            fontSize: 9,
                            color: "#999",
                            fontFamily: "monospace",
                            width: 26,
                            textAlign: "right",
                          }}
                        >
                          {Math.round(track.volume * 100)}
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Track content */}
                  <div style={{ position: "relative", flex: 1, background: "#1a1a1a" }}>
                    {/* Playhead line */}
                    <div
                      style={{
                        position: "absolute",
                        left: currentTime * PIXELS_PER_SECOND,
                        top: 0,
                        bottom: 0,
                        width: 1,
                        background: "rgba(255,68,68,0.5)",
                        zIndex: 3,
                        pointerEvents: "none",
                      }}
                    />
                    {/* Grid lines */}
                    {Array.from({ length: Math.ceil(totalDuration) + 1 }).map(
                      (_, i) => (
                        <div
                          key={i}
                          style={{
                            position: "absolute",
                            left: i * PIXELS_PER_SECOND,
                            top: 0,
                            bottom: 0,
                            borderLeft:
                              i % 5 === 0
                                ? "1px solid #2a2a2a"
                                : "1px solid #222222",
                          }}
                        />
                      ),
                    )}

                    {/* Clips */}
                    {track.clips.map((clip) => {
                      const isSelected = clip.clip_id === selectedClipId;
                      return (
                        <div
                          key={clip.clip_id}
                          role="button"
                          tabIndex={0}
                          aria-label={
                            clip.label ||
                            `Clip from ${clip.start_time.toFixed(2)} seconds, ${clip.duration.toFixed(2)} seconds long`
                          }
                          onClick={(e) => {
                            e.stopPropagation();
                            handleClipClick(clip);
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              handleClipClick(clip);
                            }
                          }}
                          style={{
                            position: "absolute",
                            left: clip.start_time * PIXELS_PER_SECOND,
                            top: 6,
                            width: Math.max(
                              clip.duration * PIXELS_PER_SECOND,
                              20,
                            ),
                            height: TRACK_HEIGHT - 12,
                            background: clip.color || TRACK_COLORS[track.type],
                            borderRadius: 4,
                            border: isSelected
                              ? "2px solid #1890ff"
                              : "1px solid rgba(0,0,0,0.1)",
                            boxShadow: isSelected
                              ? "0 0 0 2px rgba(24,144,255,0.2)"
                              : "none",
                            cursor: track.locked
                              ? "default"
                              : dragInteraction?.clipId === clip.clip_id
                                  && dragInteraction.mode === "move"
                                ? "grabbing"
                                : "grab",
                            overflow: "hidden",
                            display: "flex",
                            alignItems: "center",
                            padding: "0 6px",
                            transition:
                              dragInteraction?.clipId === clip.clip_id
                                ? "none"
                                : "box-shadow 0.15s",
                            opacity: track.muted ? 0.55 : 1,
                          }}
                          onMouseDown={(e) => beginClipDrag(e, clip, track, "move")}
                          title={
                            clip.label ||
                            `Clip: ${clip.start_time.toFixed(2)}s - ${(
                              clip.start_time + clip.duration
                            ).toFixed(2)}s`
                          }
                        >
                          {/* Left trim handle */}
                          {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- Pointer-only trim affordance; precise numeric trimming is available via the selected-clip editor. */}
                          <div
                            onMouseDown={(e) =>
                              beginClipDrag(e, clip, track, "resize-left")
                            }
                            title={track.locked ? "Track locked" : "Trim start"}
                            style={{
                              position: "absolute",
                              left: 0,
                              top: 0,
                              bottom: 0,
                              width: 6,
                              cursor: track.locked ? "not-allowed" : "ew-resize",
                              background:
                                "linear-gradient(to right, rgba(0,0,0,0.25), transparent)",
                              zIndex: 1,
                            }}
                          />
                          <span
                            style={{
                              fontSize: 11,
                              color: "#1e1e1e",
                              whiteSpace: "nowrap",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              textShadow: "0 1px 2px rgba(0,0,0,0.3)",
                            }}
                          >
                            {clip.label || `${clip.duration.toFixed(2)}s`}
                          </span>
                          {/* Right trim handle */}
                          {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- Pointer-only trim affordance; precise numeric trimming is available via the selected-clip editor. */}
                          <div
                            onMouseDown={(e) =>
                              beginClipDrag(e, clip, track, "resize-right")
                            }
                            title={track.locked ? "Track locked" : "Trim end"}
                            style={{
                              position: "absolute",
                              right: 0,
                              top: 0,
                              bottom: 0,
                              width: 6,
                              cursor: track.locked ? "not-allowed" : "ew-resize",
                              background:
                                "linear-gradient(to left, rgba(0,0,0,0.25), transparent)",
                              zIndex: 1,
                            }}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Selected clip inspector */}
      {selectedClip && inspectorDraft && (
        <SelectedClipInspector
          track={selectedClip.track}
          draft={inspectorDraft}
          saving={inspectorSaving}
          errorMessage={inspectorError}
          onChange={patchInspector}
          onSave={() => void saveInspector()}
          onDelete={() => void removeSelectedClip()}
          onClose={() => setSelectedClipId(null)}
        />
      )}

      {/* Footer hint */}
      {!loading && !error && timeline && (
        <div
          style={{
            padding: "4px 16px",
            borderTop: "1px solid #333333",
            background: "#1e1e1e",
            fontSize: 11,
            color: "#999999",
            display: "flex",
            justifyContent: "space-between",
          }}
        >
          {selectedClip ? (
            <span style={{ color: "#4f8cff" }}>
              ✓ {selectedClip.clip.label || "Clip"} · {selectedClip.track.type} ·{" "}
              {selectedClip.clip.start_time.toFixed(1)}s-
              {selectedClip.clip.duration.toFixed(1)}s
              {selectedClip.clip.bound_character_id
                ? ` · 👤 ${selectedClip.clip.bound_character_id.substring(0, 12)}`
                : ""}
            </span>
          ) : (
            <span>
              Click a clip to select · Tracks:{" "}
              {sortedTracks.map((t) => t.name).join(", ")}
            </span>
          )}
          <span>ADR 0007 Timeline Orchestration</span>
        </div>
      )}
    </div>
  );

  function patchDuckingField(field: keyof Omit<DuckingFormState, "enabled">, value: string) {
    setDuckingForm((current) => ({ ...current, [field]: value }));
  }
}

interface SelectedClipInspectorProps {
  track: TimelineTrackV1;
  draft: ClipInspectorDraft;
  saving: boolean;
  errorMessage: string | null;
  onChange: (patch: Partial<ClipInspectorDraft>) => void;
  onSave: () => void;
  onDelete: () => void;
  onClose: () => void;
}

function SelectedClipInspector({
  track,
  draft,
  saving,
  errorMessage,
  onChange,
  onSave,
  onDelete,
  onClose,
}: SelectedClipInspectorProps) {
  const isAudio = AUDIO_ROLES.has(track.type);
  const disabled = track.locked || saving;

  const numberInputStyle: React.CSSProperties = {
    width: 64,
    fontSize: 11,
    background: "#1a1a1a",
    color: "#eee",
    border: "1px solid #444",
    borderRadius: 3,
    padding: "2px 4px",
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 10,
    color: "#999",
    display: "flex",
    flexDirection: "column",
    gap: 1,
  };

  return (
    <div
      role="region"
      aria-label="Selected clip properties"
      data-testid="timeline-clip-inspector"
      style={{
        borderTop: "1px solid #333",
        background: "#1b1b1b",
        padding: "6px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: "#ccc" }}>
          {TRACK_ICONS[track.type]} {track.name} clip
        </span>
        <label style={labelStyle}>
          Start (s)
          <input
            type="number"
            min={0}
            step={0.1}
            value={draft.start_time}
            disabled={disabled}
            aria-label="Clip start time in seconds"
            onChange={(event) => onChange({ start_time: event.currentTarget.value })}
            style={numberInputStyle}
          />
        </label>
        <label style={labelStyle}>
          Duration (s)
          <input
            type="number"
            min={0.05}
            step={0.1}
            value={draft.duration}
            disabled={disabled}
            aria-label="Clip duration in seconds"
            onChange={(event) => onChange({ duration: event.currentTarget.value })}
            style={numberInputStyle}
          />
        </label>
        <label style={labelStyle}>
          Source in (s)
          <input
            type="number"
            min={0}
            step={0.1}
            value={draft.source_start}
            disabled={disabled}
            aria-label="Source trim in-point in seconds"
            onChange={(event) => onChange({ source_start: event.currentTarget.value })}
            style={numberInputStyle}
          />
        </label>
        <label style={labelStyle}>
          Source length (s)
          <input
            type="number"
            min={0}
            step={0.1}
            placeholder="auto"
            value={draft.source_duration}
            disabled={disabled}
            aria-label="Source trim length in seconds"
            title="Leave empty to use the clip duration"
            onChange={(event) => onChange({ source_duration: event.currentTarget.value })}
            style={numberInputStyle}
          />
        </label>
        {isAudio && (
          <>
            <label style={labelStyle}>
              Fade in (s)
              <input
                type="number"
                min={0}
                step={0.05}
                placeholder="none"
                value={draft.fade_in}
                disabled={disabled}
                aria-label="Fade in duration in seconds"
                onChange={(event) => onChange({ fade_in: event.currentTarget.value })}
                style={numberInputStyle}
              />
            </label>
            <label style={labelStyle}>
              Fade out (s)
              <input
                type="number"
                min={0}
                step={0.05}
                placeholder="none"
                value={draft.fade_out}
                disabled={disabled}
                aria-label="Fade out duration in seconds"
                onChange={(event) => onChange({ fade_out: event.currentTarget.value })}
                style={numberInputStyle}
              />
            </label>
          </>
        )}
        <label style={{ ...labelStyle, flex: 1, minWidth: 120 }}>
          Label
          <input
            type="text"
            maxLength={200}
            value={draft.label}
            disabled={disabled}
            aria-label="Clip label"
            onChange={(event) => onChange({ label: event.currentTarget.value })}
            style={{ ...numberInputStyle, width: "100%" }}
          />
        </label>
        <div style={{ display: "flex", gap: 6, alignItems: "flex-end" }}>
          <button
            onClick={onSave}
            disabled={disabled}
            data-testid="timeline-inspector-save"
            style={{
              border: "1px solid #1a5fb4",
              background: "#1a5fb4",
              color: "#fff",
              borderRadius: 3,
              fontSize: 11,
              padding: "3px 10px",
              cursor: disabled ? "not-allowed" : "pointer",
            }}
          >
            {saving ? "Saving…" : "Apply"}
          </button>
          <button
            onClick={onDelete}
            disabled={disabled}
            data-testid="timeline-inspector-delete"
            style={{
              border: "1px solid #a8071a",
              background: "transparent",
              color: "#ff7875",
              borderRadius: 3,
              fontSize: 11,
              padding: "3px 10px",
              cursor: disabled ? "not-allowed" : "pointer",
            }}
          >
            Delete
          </button>
          <button
            onClick={onClose}
            aria-label="Close clip properties"
            style={{
              border: "none",
              background: "none",
              color: "#999",
              cursor: "pointer",
              fontSize: 12,
              padding: "3px 4px",
            }}
          >
            ✕
          </button>
        </div>
      </div>
      {errorMessage && (
        <div style={{ fontSize: 11, color: "#f5222d" }} role="alert">
          {errorMessage}
        </div>
      )}
    </div>
  );
}
