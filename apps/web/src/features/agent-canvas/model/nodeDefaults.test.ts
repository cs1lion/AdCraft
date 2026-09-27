import { describe, expect, it } from "vitest";

import {
  AGENT_CANVAS_VISIBLE_NODE_TYPES,
  assetBackedCanvasNodeRequest,
  createDefaultCanvasNodeRequest,
  sourceAssetSemanticRole,
  sourceAssetStructuredContent,
} from "./nodeDefaults.ts";

describe("Agent Canvas node defaults", () => {
  it("exposes all eight canonical authoring node types", () => {
    // This list is what decides which nodes can carry a binding edge at all:
    // ``toAgentCanvasFlowEdges`` filters on it, so a type missing here is a type
    // whose edges silently stop rendering -- which is what happened to the
    // 3D previs, the one node whose only possible edge is the previs -> video
    // link that grounds the film.
    expect(AGENT_CANVAS_VISIBLE_NODE_TYPES).toEqual([
      "text",
      "script",
      "image",
      "video",
      "audio",
      "editing",
      "scene-3d",
      "voice-cast",
    ]);
  });

  it.each([
    ["text", "general_text"],
    ["script", "script"],
    ["image", "general_image"],
    ["video", "general_video"],
    ["audio", "bgm"],
    ["editing", "editing"],
    ["scene-3d", "scene_3d_previs"],
    ["voice-cast", "voice_cast"],
  ] as const)("uses the frozen creative role for %s nodes", (nodeType, creativeRole) => {
    expect(createDefaultCanvasNodeRequest(nodeType, { x: 10, y: 20 })).toMatchObject({
      node_type: nodeType,
      creative_role: creativeRole,
      role_contract_version: "ad-media-role-v2",
      position: { x: 10, y: 20 },
    });
  });

  it("uses uploaded roles for source media nodes", () => {
    expect(sourceAssetSemanticRole("image")).toBe("general_image");
    expect(sourceAssetSemanticRole("video")).toBe("general_video");
    expect(sourceAssetSemanticRole("audio")).toBe("general_audio");
  });

  it("provides a valid BGM contract for blank and imported audio nodes", () => {
    expect(createDefaultCanvasNodeRequest("audio", { x: 0, y: 0 }).structured_content)
      .toMatchObject({
        duration_seconds: 30,
        instrumental_only: true,
        no_vocals: true,
      });
    expect(sourceAssetStructuredContent("audio", "Imported score", 18)).toMatchObject({
      music_summary: "Imported score",
      duration_seconds: 18,
    });
  });

  it.each(["text", "script", "image", "video", "audio"] as const)(
    "creates an empty %s without an empty-string generation prompt",
    (nodeType) => {
      const request = createDefaultCanvasNodeRequest(nodeType, { x: 0, y: 0 });

      expect(request.generation_prompt).not.toBe("");
      expect(request.generation_prompt ?? null).toBeNull();
    },
  );

});

  it("builds the create request for an asset dropped on the canvas", () => {
    // V0.2 §2.1: the drop's payload becomes an asset-backed create. The node
    // type IS the media type (the backend's validate_asset_backed_node rule);
    // the asset rides as source_asset_id so the node is grounded in the
    // library item the author dragged.
    const request = assetBackedCanvasNodeRequest(
      {
        assetId: "asset-9",
        mediaType: "video",
        displayName: "赌场入口",
      },
      { x: 42, y: 17 },
    );
    expect(request.node_type).toBe("video");
    expect(request.creative_role).toBe("general_video");
    expect(request.title).toBe("赌场入口");
    expect(request.source_asset_id).toBe("asset-9");
    expect(request.position).toEqual({ x: 42, y: 17 });
  });

  it("gives a dropped audio asset the BGM contract it needs", () => {
    const request = assetBackedCanvasNodeRequest(
      { assetId: "asset-a", mediaType: "audio", displayName: "导入配乐" },
      { x: 0, y: 0 },
    );
    expect(request.node_type).toBe("audio");
    expect(request.structured_content).toMatchObject({
      music_summary: "导入配乐",
      duration_seconds: 30,
    });
  });

