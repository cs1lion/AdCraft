/**
 * canvasDrop tests (V0.2 §2.1: 素材 → 拖到画布 → 创建镜头).
 *
 * The contract between the asset browser's drag and the canvas pane's drop:
 * round-trip the payload, refuse anything malformed (a drop event must never
 * throw), and map media type → node type exactly as the backend's
 * ``validate_asset_backed_node`` does (the node type IS the media type).
 */

import { describe, expect, it } from "vitest";

import {
  CANVAS_DROP_MIME,
  canvasCardDropIntent,
  canvasDropCreateRequest,
  canvasDropMimeFor,
  canvasDropPayloadFor,
  canvasNodeTypeForMedia,
  cardAcceptsCanvasDrop,
  parseCanvasDropPayload,
} from "./canvasDrop.ts";

function payload(overrides: Record<string, unknown> = {}) {
  return JSON.stringify({
    asset_id: "asset-1",
    media_type: "image",
    display_name: "走廊设定图",
    ...overrides,
  });
}

describe("canvasDropPayloadFor / parseCanvasDropPayload", () => {
  it("round-trips a well-formed payload", () => {
    const raw = canvasDropPayloadFor({
      assetId: "asset-1",
      mediaType: "video",
      displayName: "赌场入口",
    });
    expect(parseCanvasDropPayload(raw)).toEqual({
      asset_id: "asset-1",
      media_type: "video",
      display_name: "赌场入口",
    });
  });

  it("refuses malformed JSON instead of throwing inside a drop", () => {
    expect(parseCanvasDropPayload("not json")).toBeNull();
    expect(parseCanvasDropPayload(null)).toBeNull();
    expect(parseCanvasDropPayload("")).toBeNull();
  });

  it("refuses a payload without an asset id", () => {
    expect(parseCanvasDropPayload(payload({ asset_id: "" }))).toBeNull();
    expect(parseCanvasDropPayload(payload({ asset_id: 42 }))).toBeNull();
  });

  it("refuses a media type the backend will not back a node with", () => {
    expect(parseCanvasDropPayload(payload({ media_type: "document" }))).toBeNull();
    expect(parseCanvasDropPayload(payload({ media_type: null }))).toBeNull();
  });

  it("falls back to the asset id when the display name is unusable", () => {
    const parsed = parseCanvasDropPayload(payload({ display_name: 42 }));
    expect(parsed?.display_name).toBe("asset-1");
  });

  it("exposes a custom MIME the pane checks in dragover", () => {
    expect(CANVAS_DROP_MIME.startsWith("application/x-adcraft-")).toBe(true);
  });
});

describe("canvasNodeTypeForMedia", () => {
  it("maps the three backable kinds to themselves (the backend's rule)", () => {
    expect(canvasNodeTypeForMedia("image")).toBe("image");
    expect(canvasNodeTypeForMedia("video")).toBe("video");
    expect(canvasNodeTypeForMedia("audio")).toBe("audio");
  });

  it("has no canvas home for anything else", () => {
    expect(canvasNodeTypeForMedia("document" as never)).toBeNull();
  });
});

describe("canvasDropCreateRequest", () => {
  it("turns a parsed payload into the asset-backed create request", () => {
    const payload = parseCanvasDropPayload(
      canvasDropPayloadFor({
        assetId: "asset-1",
        mediaType: "image",
        displayName: "走廊设定图",
      }),
    );
    expect(payload).not.toBeNull();
    const request = canvasDropCreateRequest(payload!, { x: 10, y: 20 });
    expect(request).not.toBeNull();
    expect(request?.node_type).toBe("image");
    expect(request?.source_asset_id).toBe("asset-1");
    expect(request?.title).toBe("走廊设定图");
    expect(request?.position).toEqual({ x: 10, y: 20 });
  });

  it("returns null for a media type with no canvas home", () => {
    const payload = {
      asset_id: "asset-1",
      media_type: "document" as never,
      display_name: "x",
    };
    expect(canvasDropCreateRequest(payload, { x: 0, y: 0 })).toBeNull();
  });
});

describe("card drops (V0.2 §2.2: 卡片内部 = 素材归属)", () => {
  it("only images are nameable for the card gesture", () => {
    expect(cardAcceptsCanvasDrop("image", "scene-3d")).toBe(true);
    expect(cardAcceptsCanvasDrop("video", "video")).toBe(false);
    expect(cardAcceptsCanvasDrop("audio", "audio")).toBe(false);
  });

  it("only reference-taking node types accept an image", () => {
    expect(cardAcceptsCanvasDrop("image", "image")).toBe(true);
    expect(cardAcceptsCanvasDrop("image", "video")).toBe(true);
    expect(cardAcceptsCanvasDrop("image", "editing")).toBe(false);
    expect(cardAcceptsCanvasDrop("image", "voice-cast")).toBe(false);
  });

  it("derives the typed MIME a card recognises in dragover", () => {
    expect(canvasDropMimeFor("image")).toBe(`${CANVAS_DROP_MIME}+image`);
  });
});

describe("canvasCardDropIntent (V0.2 §2.1: 图片 → 参考 / 人物 → 角色)", () => {
  it("sends a character asset dropped on the previs card into the cast", () => {
    expect(canvasCardDropIntent("image", "scene-3d", "character_identity_master")).toBe(
      "add_character",
    );
    expect(canvasCardDropIntent("image", "scene-3d", "character_turnaround")).toBe(
      "add_character",
    );
  });

  it("keeps any other image a reference input", () => {
    expect(canvasCardDropIntent("image", "scene-3d", "scene_design_board")).toBe(
      "image_reference",
    );
    expect(canvasCardDropIntent("image", "scene-3d", null)).toBe("image_reference");
    expect(canvasCardDropIntent("image", "video", "character_identity_master")).toBe(
      "image_reference",
    );
    expect(canvasCardDropIntent("image", "image", null)).toBe("image_reference");
  });

  it("refuses what no card takes", () => {
    expect(canvasCardDropIntent("video", "video", null)).toBeNull();
    expect(canvasCardDropIntent("audio", "audio", null)).toBeNull();
    expect(canvasCardDropIntent("image", "editing", "character_identity_master")).toBeNull();
    expect(canvasCardDropIntent("image", "text", null)).toBeNull();
  });
});
