import { describe, expect, it } from "vitest";

import {
  AGENT_CANVAS_VISIBLE_NODE_TYPES,
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
