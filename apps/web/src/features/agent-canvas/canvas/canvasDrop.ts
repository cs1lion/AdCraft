/**
 * Canvas drop payload — the drag half of V0.2 §2.1.
 *
 * The research's retained feature #1 is "拖拽作为第一语言: 素材 → 拖到画布:
 * 创建镜头". The creation HALF already exists in the backend
 * (``source_asset_id`` + ``validate_asset_backed_node``: an asset-backed
 * node's type must equal the asset's media type — image/video/audio). What
 * was missing was the gesture: the asset browser emitted a TIMELINE-only
 * payload, and the canvas pane had no drop surface at all, so dragging an
 * asset onto the canvas did precisely nothing.
 *
 * This module is the contract between the two halves: a custom MIME (drop
 * handlers read it by ``dataTransfer.types``, never the debug mirror), a
 * tolerant parser (a malformed payload must not throw inside a drop event),
 * and the media→node-type mapping that mirrors the backend's rule exactly.
 */

import type {
  AgentCanvasAssetMediaTypeV2,
  CanvasNodeCreateRequestV2,
  CanvasNodeTypeV2,
  CanvasPositionV2,
} from "../../../types-v2.ts";
import { assetBackedCanvasNodeRequest } from "../model/nodeDefaults.ts";

export const CANVAS_DROP_MIME = "application/x-adcraft-canvas-drop";

/**
 * The per-media-type MIME for CARD drops (V0.2 §2.2: 卡片内部 = 素材归属).
 *
 * A drag carries both this typed MIME and the base one: the pane reads the
 * base MIME to create a node; a card reads the typed MIME to bind the asset
 * as its reference input. The typed form exists because ``dragover`` may
 * only inspect ``dataTransfer.types`` — the payload is unreadable until the
 * drop — so the media type has to be part of the type list for the cursor
 * to be honest before the release.
 */
export function canvasDropMimeFor(mediaType: string): string {
  return `${CANVAS_DROP_MIME}+${mediaType}`;
}

/**
 * Node types that accept an image reference (mirrors the connection policy's
 * image → image/video/scene-3d rules, and the page's existing
 * ``addReferences`` guard that rejects editing cards).
 */
export const IMAGE_REFERENCE_TARGET_TYPES: readonly CanvasNodeTypeV2[] = [
  "image",
  "video",
  "scene-3d",
];

export interface CanvasDropAsset {
  assetId: string;
  mediaType: AgentCanvasAssetMediaTypeV2;
  displayName: string;
}

export interface CanvasDropPayload {
  asset_id: string;
  media_type: AgentCanvasAssetMediaTypeV2;
  display_name: string;
}

/** The payload an asset browser card puts on the drag. */
export function canvasDropPayloadFor(asset: CanvasDropAsset): string {
  return JSON.stringify({
    asset_id: asset.assetId,
    media_type: asset.mediaType,
    display_name: asset.displayName,
  } satisfies CanvasDropPayload);
}

/**
 * Parse a drop payload. Returns null for anything unusable — a drop event
 * must degrade to "nothing happens", never throw inside React's event loop.
 */
export function parseCanvasDropPayload(raw: string | null): CanvasDropPayload | null {
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const record = parsed as Record<string, unknown>;
  const assetId = record.asset_id;
  const mediaType = record.media_type;
  if (typeof assetId !== "string" || !assetId.trim()) return null;
  if (mediaType !== "image" && mediaType !== "video" && mediaType !== "audio") {
    return null;
  }
  const displayName = record.display_name;
  return {
    asset_id: assetId,
    media_type: mediaType,
    display_name: typeof displayName === "string" ? displayName : assetId,
  };
}

/**
 * The node type an asset-backed node must use. Mirrors the backend's
 * ``validate_asset_backed_node`` exactly: the media type IS the node type
 * for the three backable kinds; anything else has no canvas home.
 */
export function canvasNodeTypeForMedia(
  mediaType: AgentCanvasAssetMediaTypeV2,
): CanvasNodeTypeV2 | null {
  if (mediaType === "image" || mediaType === "video" || mediaType === "audio") {
    return mediaType;
  }
  return null;
}
/**
 * The whole drop decision as one pure function: a parsed payload plus a drop
 * position becomes the create request (or null when the asset has no canvas
 * home). The pane handler is then a thin adapter, and this is what the tests
 * lock — mounting ReactFlow to test a mapping would be ceremony.
 */
export function canvasDropCreateRequest(
  payload: CanvasDropPayload,
  position: CanvasPositionV2,
): CanvasNodeCreateRequestV2 | null {
  const nodeType = canvasNodeTypeForMedia(payload.media_type);
  if (!nodeType) return null;
  return assetBackedCanvasNodeRequest(
    {
      assetId: payload.asset_id,
      mediaType: payload.media_type,
      displayName: payload.display_name,
    },
    position,
  );
}

/**
 * Whether an asset dropped on a CARD belongs there (V0.2 §2.2: 卡片内部 =
 * 素材归属). Only images are nameable for this gesture — the research's own
 * row is "图片 → 拖到图片/Scene：作为参考图或素材" — and only the node types
 * whose input roles include ``image_reference`` accept them.
 */
export function cardAcceptsCanvasDrop(
  mediaType: AgentCanvasAssetMediaTypeV2,
  targetNodeType: CanvasNodeTypeV2,
): boolean {
  return (
    mediaType === "image"
    && IMAGE_REFERENCE_TARGET_TYPES.includes(targetNodeType)
  );
}

// ---------------------------------------------------------------------------
// The drop INTENT: what a card drop means depends on WHAT was dropped
// ---------------------------------------------------------------------------

/**
 * What an asset dropped on a card does there (V0.2 §2.1):
 *
 * - 人物 → 拖到镜头：成为该镜头的角色 — a character asset landing on the
 *   scene-3d card JOINS THE CAST (a SceneCharacter bound to that asset);
 * - 图片 → 拖到图片/Scene：作为参考图 — any other image becomes the node's
 *   reference input.
 *
 * The semantic type is read off the workflow's asset list (the payload
 * cannot carry it: `dragover` cannot read the payload at all). `null` means
 * the card accepts nothing of that kind.
 */
export type CanvasCardDropIntent = "image_reference" | "add_character";

export function canvasCardDropIntent(
  mediaType: AgentCanvasAssetMediaTypeV2,
  targetNodeType: CanvasNodeTypeV2,
  semanticType: string | null | undefined,
): CanvasCardDropIntent | null {
  if (mediaType !== "image") return null;
  if (!IMAGE_REFERENCE_TARGET_TYPES.includes(targetNodeType)) return null;
  if (targetNodeType === "scene-3d" && (semanticType ?? "").startsWith("character_")) {
    return "add_character";
  }
  return "image_reference";
}
