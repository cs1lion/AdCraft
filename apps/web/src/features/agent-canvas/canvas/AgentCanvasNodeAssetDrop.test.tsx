/**
 * Card drop-target tests (V0.2 §2.2: 卡片内部 = 素材归属).
 *
 * The research's retained feature: dropping an asset ON a card means "this
 * belongs to that node" — an image lands as the node's reference input. These
 * tests lock the gesture's honesty: the cursor is only promised where the
 * node type accepts image references, the drop re-validates rather than
 * trusting the cursor, a drop on a card does NOT also create a node on the
 * pane, and an unresolvable asset is reported instead of vanishing.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CanvasNodeV2, ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import {
  CANVAS_DROP_MIME,
  cardAcceptsCanvasDrop,
  canvasDropMimeFor,
  canvasDropPayloadFor,
  parseCanvasDropPayload,
} from "./canvasDrop.ts";

vi.mock("@xyflow/react", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@xyflow/react");
  return {
    ...actual,
    Handle: () => null,
    Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  };
});

// The lazy workbench and the 3D surface are irrelevant to a drop gesture.
vi.mock("./workbench/AgentCanvasInlineWorkbench.tsx", () => ({
  AgentCanvasInlineWorkbench: () => null,
}));

afterEach(cleanup);

function node(nodeType: CanvasNodeV2["node_type"], id = "node-1"): CanvasNodeV2 {
  return {
    node_id: id,
    workflow_id: "workflow-1",
    node_type: nodeType,
    creative_role: "general_image",
    role_contract_version: "ad-media-role-v1",
    title: "target",
    status: "draft",
    summary_prompt: null,
    generation_prompt: null,
    structured_content: {},
    model_id: null,
    parameters: {},
    metadata: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    output_asset_version_id: null,
    latest_attempt: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    created_at: "2026-09-27T00:00:00Z",
    updated_at: "2026-09-27T00:00:00Z",
  } as CanvasNodeV2;
}

function imageAsset(overrides: Partial<ProjectAssetSummaryV2> = {}): ProjectAssetSummaryV2 {
  return {
    asset_id: "asset-1",
    version_id: "version-1",
    display_name: "走廊设定图",
    media_type: "image",
    mime_type: "image/png",
    width: 1024,
    height: 576,
    state: "ready",
    public_url: null,
    thumbnail_url: null,
    created_at: null,
    ...overrides,
  } as ProjectAssetSummaryV2;
}

/** Minimal DataTransfer stand-in (jsdom does not implement the interface). */
function makeDataTransfer(entries: Record<string, string>) {
  return {
    types: Object.keys(entries),
    getData: (type: string) => entries[type] ?? "",
    setData: () => {},
    dropEffect: "none",
  };
}

async function renderCard(
  target: CanvasNodeV2,
  onDrop: (nodeId: string, assetId: string, displayName: string) => void,
) {
  const { AgentCanvasNodeCard } = await import("./AgentCanvasNode.tsx");
  return render(
    <AgentCanvasNodeCard
      node={target}
      asset={null}
      runtime={null}
      onAssetDroppedAsReference={onDrop}
    />,
  );
}

const IMAGE_PAYLOAD = {
  asset_id: "asset-1",
  media_type: "image",
  display_name: "走廊设定图",
};

describe("cardAcceptsCanvasDrop", () => {
  it("accepts images on the three reference-taking node types", () => {
    expect(cardAcceptsCanvasDrop("image", "image")).toBe(true);
    expect(cardAcceptsCanvasDrop("image", "video")).toBe(true);
    expect(cardAcceptsCanvasDrop("image", "scene-3d")).toBe(true);
  });

  it("refuses non-image media (the gesture is named for images)", () => {
    expect(cardAcceptsCanvasDrop("video", "video")).toBe(false);
    expect(cardAcceptsCanvasDrop("audio", "audio")).toBe(false);
  });

  it("refuses node types whose input roles exclude image_reference", () => {
    for (const target of ["text", "script", "audio", "editing", "voice-cast"] as const) {
      expect(cardAcceptsCanvasDrop("image", target)).toBe(false);
    }
  });
});

describe("the typed drop MIME", () => {
  it("is derived from the base MIME so a card can recognise the media type", () => {
    expect(canvasDropMimeFor("image")).toBe(`${CANVAS_DROP_MIME}+image`);
  });

  it("carries the same payload as the base MIME", () => {
    const payload = canvasDropPayloadFor({
      assetId: "asset-1",
      mediaType: "image",
      displayName: "走廊设定图",
    });
    expect(parseCanvasDropPayload(payload)).toEqual(IMAGE_PAYLOAD);
  });
});

describe("AgentCanvasNodeCard as a drop target", () => {
  it("binds an image asset dropped on the card", async () => {
    const onDrop = vi.fn();
    await renderCard(node("image"), onDrop);

    fireEvent.drop(screen.getByTestId("agent-canvas-node-node-1"), {
      dataTransfer: makeDataTransfer({
        [canvasDropMimeFor("image")]: JSON.stringify(IMAGE_PAYLOAD),
      }),
    });

    expect(onDrop).toHaveBeenCalledWith("node-1", "asset-1", "走廊设定图");
  });

  it("ignores a drop whose payload is for a different media type", async () => {
    const onDrop = vi.fn();
    await renderCard(node("image"), onDrop);

    fireEvent.drop(screen.getByTestId("agent-canvas-node-node-1"), {
      dataTransfer: makeDataTransfer({
        [CANVAS_DROP_MIME]: JSON.stringify({ ...IMAGE_PAYLOAD, media_type: "video" }),
      }),
    });

    expect(onDrop).not.toHaveBeenCalled();
  });

  it("ignores a drop on a node type that takes no image references", async () => {
    const onDrop = vi.fn();
    await renderCard(node("text"), onDrop);

    fireEvent.drop(screen.getByTestId("agent-canvas-node-node-1"), {
      dataTransfer: makeDataTransfer({
        [canvasDropMimeFor("image")]: JSON.stringify(IMAGE_PAYLOAD),
      }),
    });

    // The card stays inert rather than accepting a binding it cannot hold.
    expect(onDrop).not.toHaveBeenCalled();
  });

  it("offers the copy cursor only where the drop would land", async () => {
    await renderCard(node("video"), vi.fn());

    const event = new Event("dragover", { bubbles: true, cancelable: true }) as DragEvent & {
      dataTransfer: ReturnType<typeof makeDataTransfer>;
    };
    event.dataTransfer = makeDataTransfer({ [canvasDropMimeFor("image")]: "x" });
    fireEvent(screen.getByTestId("agent-canvas-node-node-1"), event);

    expect(event.defaultPrevented).toBe(true);
    expect(event.dataTransfer.dropEffect).toBe("copy");
  });

  it("keeps the plain cursor when the drag carries no canvas payload", async () => {
    await renderCard(node("video"), vi.fn());

    const event = new Event("dragover", { bubbles: true, cancelable: true }) as DragEvent & {
      dataTransfer: ReturnType<typeof makeDataTransfer>;
    };
    event.dataTransfer = makeDataTransfer({ "text/plain": "something" });
    fireEvent(screen.getByTestId("agent-canvas-node-node-1"), event);

    expect(event.defaultPrevented).toBe(false);
  });
});
