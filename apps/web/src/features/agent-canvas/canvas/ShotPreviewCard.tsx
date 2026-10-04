/**
 * ShotPreviewCard — the 机位 video card that floats over the 3D viewport.
 *
 * This is the piece that makes the 3D↔video relation visible rather than
 * merely stored. The chain already exists in the backend (see
 * docs/plans/scene3d-shot-preview-bridge.md):
 *
 *   SceneShot.camera ──► SceneCamera          (机位 ↔ 分镜段)
 *   published_previs_clips.shot_id ──► clip_asset_id   (分镜段 → 视频片段)
 *
 * and `StoryboardPanel` shows it as a table. What it does not do is put the
 * rendered clip next to the shot it came from, which is the one thing the
 * reference framework does: a card titled `机位01 | 双人全景` playing that
 * shot's footage, floating at the viewport's bottom-left.
 *
 * The card is deliberately presentational: it is told which shot, which clip
 * and which asset, and it decides only how to say "there is nothing to play
 * yet". Resolving the clip for the active shot, and offering the publish
 * action, belong to the caller — the panel that owns the API.
 */

import { useRef } from "react";

import type { SceneShot } from "../../../types/scene-script";
import type { ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import type { PublishedPrevisClipEntryV2 } from "../../../types-v2.ts";
import { mediaAssetContentPath, mediaAssetPosterPath } from "../../../workflow/mediaPreview.ts";
import { useAgentCanvasVideoPoster } from "./useAgentCanvasVideoPoster.ts";
import { formatTimecode, shotDurationSeconds } from "./shotLabels.ts";

export interface ShotPreviewCardProps {
  /** Human label for the shot, e.g. "机位01 | 双人全景" (see shotLabels). */
  label: string | null;
  /** The shot being previewed; drives the duration readout. */
  shot: SceneShot | null;
  /** Frame rate of the owning script, for frames → seconds. */
  frameRate: number;
  /** The clip published from this shot, when the scene has one. */
  clip: PublishedPrevisClipEntryV2 | null;
  /** Asset-library row the clip resolves to. Null while it is still loading. */
  asset?: ProjectAssetSummaryV2 | null;
  /** True while the playhead is inside this shot. */
  active: boolean;
  /** Offered when the shot has no published clip yet. */
  onPublish?: () => void;
  /** True while a publish request for this shot is in flight. */
  publishing?: boolean;
}

export function ShotPreviewCard({
  label,
  shot,
  frameRate,
  clip,
  asset,
  active,
  onPublish,
  publishing = false,
}: ShotPreviewCardProps) {
  const playerRef = useRef<HTMLVideoElement>(null);
  const posterUrl = useAgentCanvasVideoPoster(asset, playerRef);
  const mediaUrl = asset ? mediaAssetContentPath(asset) : null;
  const poster = asset ? mediaAssetPosterPath(asset) || posterUrl || undefined : undefined;
  const duration = shot ? shotDurationSeconds(shot, frameRate) : null;

  return (
    <section
      className="shot-preview-card"
      data-active={active ? "true" : "false"}
      data-testid="shot-preview-card"
      aria-label={label ?? "机位预览"}
    >
      <header className="shot-preview-card__header">
        <span className="shot-preview-card__icon" aria-hidden="true">
          📹
        </span>
        <span className="shot-preview-card__title" data-testid="shot-preview-card-title">
          {label ?? "机位未命名"}
        </span>
        {duration !== null && (
          <span className="shot-preview-card__duration" data-testid="shot-preview-card-duration">
            {formatTimecode(duration)}
          </span>
        )}
      </header>

      <div className="shot-preview-card__stage">
        {mediaUrl ? (
          <video
            ref={playerRef}
            className="shot-preview-card__video"
            data-testid="shot-preview-card-video"
            src={mediaUrl}
            poster={poster}
            controls
            playsInline
            preload="metadata"
          />
        ) : (
          <div className="shot-preview-card__empty" data-testid="shot-preview-card-empty">
            {clip ? (
              // A clip whose asset has not resolved yet: the lineage is there,
              // the bytes are not. Saying "still loading" is honest; pretending
              // there is no clip would invite a duplicate publish.
              <p className="shot-preview-card__hint">预演片段解析中…</p>
            ) : (
              <>
                <p className="shot-preview-card__hint">这一镜还没有发布预演片段。</p>
                {onPublish && (
                  <button
                    type="button"
                    className="shot-preview-card__publish"
                    data-testid="shot-preview-card-publish"
                    onClick={onPublish}
                    disabled={publishing || !shot}
                  >
                    {publishing ? "发布中…" : `发布${label ?? "此镜"}`}
                  </button>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

export default ShotPreviewCard;
