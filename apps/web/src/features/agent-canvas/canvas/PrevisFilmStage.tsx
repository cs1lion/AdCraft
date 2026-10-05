/**
 * PrevisFilmStage — the 成片预演 viewport.
 *
 * The reference framework's film mode plays ONE continuous reel: the shots in
 * order, each as its published previs clip, so the author watches pacing
 * rather than a 3D editor. Until now this viewport showed the live 3D preview
 * widened, which is a different thing — one is a scrub-able scene, the other
 * is the film.
 *
 * Honest about the data model: the "film" is the ordered list of clips
 * published from this scene's shots (`published_previs_clips`), NOT a single
 * pre-assembled video. So the stage is a sequence player — it plays one clip,
 * then the next — and it names the shots that have no clip yet instead of
 * silently skipping them.
 *
 * The stage resolves its own clip URLs from the project asset list. That is a
 * fetch the rest of the 3D panel does not need, so keeping it here means the
 * editor stays a presenter of shots/labels while the reel stays playable.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { SceneCamera, SceneShot } from "../../../types/scene-script";
import type { PublishedPrevisClipEntryV2 } from "../../../types-v2.ts";
import { useAgentCanvasAssets } from "../assets/useAgentCanvasAssets.ts";
import { mediaAssetContentPath } from "../../../workflow/mediaPreview.ts";
import { cameraLabel } from "./shotLabels.ts";

export interface PrevisFilmStageProps {
  /** Owning workflow, used to resolve clip asset URLs. */
  workflowId: string | null;
  /** The scene's shots, in timeline order. */
  shots: readonly SceneShot[];
  /** The scene's cameras; labels come from here, not from shot text. */
  cameras: readonly SceneCamera[];
  /** Clips published from those shots. */
  clips: readonly PublishedPrevisClipEntryV2[];
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
}

export function PrevisFilmStage({
  workflowId,
  shots,
  cameras,
  clips,
  onSeekFrame,
}: PrevisFilmStageProps) {
  const playerRef = useRef<HTMLVideoElement>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);

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
    const cameraById = new Map(cameras.map((camera, position) => [camera.id, { camera, position }]));
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
        return {
          shot,
          label,
          url: url || null,
          resolving: Boolean(clip) && !url,
        };
      });
  }, [shots, cameras, clipByShotId, assets.items]);

  const playableCount = reel.filter((entry) => entry.url).length;
  const safeIndex = Math.min(Math.max(index, 0), Math.max(reel.length - 1, 0));
  const current = reel[safeIndex] ?? null;

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

      {/* The reel strip: every shot, its clip state at a glance. Missing clips
          stay visible as gaps rather than being dropped, so "three of five
          shots have footage" is readable without counting. */}
      <ol className="previs-film__reel" data-testid="previs-film-reel">
        {reel.map((entry, position) => (
          <li
            key={entry.shot.id}
            className="previs-film__reel-item"
            data-active={position === safeIndex ? "true" : "false"}
            data-has-clip={entry.url ? "true" : "false"}
          >
            <button
              type="button"
              onClick={() => {
                setPlaying(false);
                setIndex(position);
              }}
              aria-label={`跳到 ${entry.label}`}
              aria-current={position === safeIndex}
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
