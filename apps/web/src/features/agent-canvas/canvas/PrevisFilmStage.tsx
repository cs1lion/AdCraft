/**
 * PrevisFilmStage — the 成片预演 viewport.
 *
 * The reference framework's film mode plays ONE continuous reel laid out on a
 * real time axis: the shots in order, each as its published previs clip, so the
 * author watches pacing rather than a 3D editor. Until now this viewport showed
 * the live 3D preview widened, which is a different thing — one is a scrub-able
 * scene, the other is the film.
 *
 * The time axis is the TIMELINE's video track, not an evenly spaced list of
 * shots. The two disagree, and disagreeing in a specific direction: a shot
 * published out of order is placed by the timeline at its shot's start, so the
 * reel reads in play order regardless of publish order. Reading the track (as
 * opposed to recomputing positions from the shots) also means what the author
 * sees here is what the Editing node will assemble — one source of truth, the
 * same one the timeline panel uses.
 *
 * Missing shots stay visible as gaps on the axis rather than being dropped:
 * "three of five shots have footage" is information, not a blemish to hide.
 *
 * The stage resolves its own clip URLs from the project asset list. That is a
 * fetch the rest of the 3D panel does not need, so keeping it here means the
 * editor stays a presenter of shots/labels while the reel stays playable.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { SceneCamera, SceneShot } from "../../../types/scene-script";
import type { PublishedPrevisClipEntryV2 } from "../../../types-v2.ts";
import { useAgentCanvasAssets } from "../assets/useAgentCanvasAssets.ts";
import { getTimeline } from "../timeline/timelineApi.ts";
import type { TimelineClipV1 } from "../timeline/timelineTypes.ts";
import { mediaAssetContentPath } from "../../../workflow/mediaPreview.ts";
import { cameraLabel } from "./shotLabels.ts";

/** Pixels per second on the reel's time axis — the timeline panel's own scale,
 *  so a shot that is 3s wide here is 3s wide there. */
const PIXELS_PER_SECOND = 40;

export interface PrevisFilmStageProps {
  /** Owning workflow, used to resolve clip asset URLs and read the timeline. */
  workflowId: string | null;
  /** The scene's shots, in timeline order. */
  shots: readonly SceneShot[];
  /** The scene's cameras; labels come from here, not from shot text. */
  cameras: readonly SceneCamera[];
  /** Clips published from those shots. */
  clips: readonly PublishedPrevisClipEntryV2[];
  /** The scene's frame rate, for placing shots the timeline has no clip for. */
  frameRate: number;
  /**
   * Seek the SceneScript playhead into a shot, so the 3D view underneath stays
   * on the same cut the reel is showing.
   */
  onSeekFrame?: (frame: number) => void;
}

interface ReelEntry {
  shot: SceneShot;
  label: string;
  /** Resolvable URL, or null when the shot has no playable clip. */
  url: string | null;
  /** True when the lineage exists but the bytes are still resolving. */
  resolving: boolean;
  /**
   * Where this shot sits on the reel, in seconds. The timeline's video-track
   * clip position when the shot has one; otherwise the shot's own start, so a
   * gap still occupies its real place on the axis.
   */
  startSeconds: number;
  /** The timeline clip backing this shot, when it reached the track. */
  timelineClip: TimelineClipV1 | null;
}

/** Read the timeline's video track. Null on any failure: the stage can still
 *  play from the published clips, it just loses the assembled positions. */
function useVideoTrack(workflowId: string | null): TimelineClipV1[] | null {
  const [clips, setClips] = useState<TimelineClipV1[] | null>(null);

  useEffect(() => {
    if (!workflowId) {
      setClips(null);
      return;
    }
    let cancelled = false;
    getTimeline(workflowId)
      .then((timeline) => {
        if (cancelled) return;
        const track = timeline.tracks.find((item) => item.type === "video");
        setClips(track ? [...track.clips] : []);
      })
      .catch(() => {
        // A missing or unreadable timeline must not blank the reel: the clips
        // are still playable, we just fall back to shot order.
        if (!cancelled) setClips(null);
      });
    return () => {
      cancelled = true;
    };
  }, [workflowId]);

  return clips;
}

export function PrevisFilmStage({
  workflowId,
  shots,
  cameras,
  clips,
  frameRate,
  onSeekFrame,
}: PrevisFilmStageProps) {
  const playerRef = useRef<HTMLVideoElement>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const trackClips = useVideoTrack(workflowId);

  const assets = useAgentCanvasAssets({
    // The editor's workflowId is nullable; the hook treats undefined as
    // "not loadable" and `enabled` already guards that case, so the coercion
    // happens once here rather than leaking null into the hook's contract.
    workflowId: workflowId ?? undefined,
    scope: "project",
    mediaType: "video",
    enabled: Boolean(workflowId),
  });

  const clipByShotId = useMemo(() => {
    const map = new Map<string, PublishedPrevisClipEntryV2>();
    for (const clip of clips) if (!map.has(clip.shot_id)) map.set(clip.shot_id, clip);
    return map;
  }, [clips]);

  // The reel is every shot, in order, whether or not it has a clip: a missing
  // clip is information the author needs, not a gap to paper over.
  const reel = useMemo<ReelEntry[]>(() => {
    const assetById = new Map<string, string>();
    for (const item of assets.items) {
      const asset = item.projectAsset;
      if (asset) assetById.set(asset.asset_id, mediaAssetContentPath(asset));
    }
    // The timeline clip for a published shot is found through the lineage the
    // publisher writes: its clip node is the timeline clip's source node.
    const clipByNodeId = new Map<string, TimelineClipV1>();
    for (const clip of trackClips ?? []) {
      if (clip.source_node_id) clipByNodeId.set(clip.source_node_id, clip);
    }
    const cameraById = new Map(
      cameras.map((camera, position) => [camera.id, { camera, position }]),
    );
    return [...shots]
      .sort((left, right) => left.start_frame - right.start_frame)
      .map((shot) => {
        const clip = clipByShotId.get(shot.id) ?? null;
        const url = clip ? assetById.get(clip.clip_asset_id) ?? null : null;
        const match = cameraById.get(shot.camera);
        // A shot pointing at a camera that is no longer in the script must not
        // borrow another camera's name: that would relabel the cut exactly
        // where the author needs to see something is wrong.
        const label = match ? cameraLabel(match.camera, match.position) : shot.camera;
        const timelineClip = clip ? clipByNodeId.get(clip.node_id) ?? null : null;
        const startSeconds = timelineClip
          ? timelineClip.start_time
          : // No timeline clip yet (not published, or the track could not be
            // read): fall back to the shot's own start so the axis keeps its
            // real shape instead of packing everything against zero.
            shot.start_frame / frameRate;
        return {
          shot,
          label,
          url: url || null,
          resolving: Boolean(clip) && !url,
          startSeconds,
          timelineClip,
        };
      });
  }, [shots, cameras, clipByShotId, assets.items, trackClips, frameRate]);

  const playableCount = reel.filter((entry) => entry.url).length;
  const safeIndex = Math.min(Math.max(index, 0), Math.max(reel.length - 1, 0));
  const current = reel[safeIndex] ?? null;
  const totalSeconds = reel.reduce(
    (max, entry) => Math.max(max, entry.startSeconds + (entry.timelineClip?.duration ?? 0)),
    0,
  );

  // Keep the 3D preview underneath on the same cut as the reel. Seeking only
  // when the cut changes — not on every parent render — so dragging the reel
  // does not fight the playhead.
  useEffect(() => {
    if (!current) return;
    onSeekFrame?.(current.shot.start_frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.shot.id]);

  const advance = useCallback(() => {
    setIndex((value) => {
      const next = value + 1;
      if (next >= reel.length) {
        setPlaying(false);
        return value;
      }
      return next;
    });
  }, [reel.length]);

  const togglePlay = useCallback(() => {
    const player = playerRef.current;
    if (!player) return;
    if (player.paused) {
      // `play()` is not guaranteed to return a promise (jsdom returns
      // undefined), so guard the shape rather than assuming it.
      const started = player.play() as Promise<void> | undefined;
      if (started && typeof started.catch === "function") started.catch(() => undefined);
      setPlaying(true);
    } else {
      player.pause();
      setPlaying(false);
    }
  }, []);

  if (!current) {
    return (
      <div className="previs-film" data-testid="previs-film" data-state="empty">
        <p className="previs-film__empty">这个场景还没有分镜。</p>
      </div>
    );
  }

  const gaps = reel.filter((entry) => !entry.url);

  return (
    <div className="previs-film" data-testid="previs-film" data-state="ready">
      <div className="previs-film__stage">
        {current.url ? (
          <video
            ref={playerRef}
            className="previs-film__video"
            data-testid="previs-film-video"
            src={current.url}
            playsInline
            preload="metadata"
            onEnded={advance}
          />
        ) : (
          <div className="previs-film__placeholder" data-testid="previs-film-placeholder">
            <p>
              这一镜还没有发布预演片段
              {current.resolving ? "（血缘已在，素材解析中）" : ""}
              。
            </p>
          </div>
        )}

        <header className="previs-film__hud">
          <span className="previs-film__hud-title" data-testid="previs-film-title">
            {current.label}
          </span>
          <span className="previs-film__hud-count" data-testid="previs-film-count">
            {safeIndex + 1}/{reel.length} · 可播 {playableCount}
          </span>
        </header>

        <div className="previs-film__transport">
          <button
            type="button"
            data-testid="previs-film-play"
            aria-label={playing ? "暂停成片预演" : "播放成片预演"}
            aria-pressed={playing}
            onClick={togglePlay}
          >
            {playing ? "❚❚" : "▶"}
          </button>
          <button
            type="button"
            data-testid="previs-film-prev"
            aria-label="上一镜"
            disabled={safeIndex === 0}
            onClick={() => {
              setPlaying(false);
              setIndex((value) => Math.max(0, value - 1));
            }}
          >
            ⏮
          </button>
          <button
            type="button"
            data-testid="previs-film-next"
            aria-label="下一镜"
            disabled={safeIndex >= reel.length - 1}
            onClick={() => {
              setPlaying(false);
              setIndex((value) => Math.min(reel.length - 1, value + 1));
            }}
          >
            ⏭
          </button>
        </div>
      </div>

      {/* The reel is a TIME AXIS, not an evenly spaced list: each shot's width
          and offset come from the timeline, so what the author reads here is
          what the Editing node will assemble. Missing shots keep their place on
          the axis as empty gaps rather than being packed out. */}
      <ol
        className="previs-film__reel previs-film__reel--timeline"
        data-testid="previs-film-reel"
        data-total-seconds={totalSeconds.toFixed(2)}
        style={{ width: Math.max(totalSeconds * PIXELS_PER_SECOND, 240) }}
      >
        {reel.map((entry, position) => (
          <li
            key={entry.shot.id}
            className="previs-film__reel-item"
            data-active={position === safeIndex ? "true" : "false"}
            data-has-clip={entry.url ? "true" : "false"}
            data-on-timeline={entry.timelineClip ? "true" : "false"}
            style={{
              position: "absolute",
              left: entry.startSeconds * PIXELS_PER_SECOND,
              // The timeline knows the real width; a shot without one keeps a
              // one-frame sliver rather than disappearing.
              width: Math.max(
                (entry.timelineClip?.duration ?? 0) * PIXELS_PER_SECOND,
                6,
              ),
            }}
          >
            <button
              type="button"
              onClick={() => {
                setPlaying(false);
                setIndex(position);
              }}
              aria-label={`跳到 ${entry.label}`}
              aria-current={position === safeIndex}
              title={`${entry.label} · ${entry.startSeconds.toFixed(1)}s`}
            >
              <span className="previs-film__reel-label">{entry.label}</span>
              <span className="previs-film__reel-state">
                {entry.url ? "●" : entry.resolving ? "◐" : "○"}
              </span>
            </button>
          </li>
        ))}
      </ol>

      {gaps.length > 0 && (
        <p className="previs-film__notice" data-testid="previs-film-notice">
          {gaps.length} 个镜头还没有预演片段；成片预演会跳过它们。
        </p>
      )}
    </div>
  );
}

export default PrevisFilmStage;
