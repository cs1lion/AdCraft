/**
 * Voice-cast node drag-source tests (ADR 0007 drag-in + the audio plan).
 *
 * A bed is ONE take with every speaker mixed in, so the timeline clip it
 * produces is deliberately NOT bound to a single character — the speaker
 * names travel in the clip LABEL, which is the director-phase intent signal
 * for a multi-speaker bed.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CanvasNodeV2, ProjectAssetSummaryV2 } from "../../../types-v2.ts";
import { AgentCanvasAudioPlayer } from "./AgentCanvasAudioPlayer.tsx";
import { AgentCanvasNodeCard } from "./AgentCanvasNode.tsx";
import {
  TIMELINE_DROP_MIME,
  parseTimelineDrop,
} from "../timeline/timelineDropPayload.ts";

vi.mock("./AgentCanvasAudioPlayer.tsx", () => ({
  AgentCanvasAudioPlayer: () => <div data-testid="audio-player" />,
}));

// The card renders inside React Flow; stub the surface provider the way the
// node's own suite does.
vi.mock("@xyflow/react", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@xyflow/react");
  return {
    ...actual,
    Handle: () => null,
    Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  };
});

void AgentCanvasAudioPlayer;

afterEach(cleanup);

function voiceCastNode(overrides: Partial<CanvasNodeV2> = {}): CanvasNodeV2 {
  return {
    node_id: "voice-node",
    workflow_id: "workflow-1",
    node_type: "voice-cast",
    creative_role: "voice_cast",
    role_contract_version: "ad-media-role-v1",
    title: "voice cast",
    status: "ready",
    summary_prompt: null,
    generation_prompt: "dialogue",
    structured_content: {
      audio_bed: {
        roles: [{ name: "林澈", description: "低沉男声" }],
        scripts: [
          { speaker: "林澈", text: "就是这里。" },
          { speaker: "苏晴", text: "（抢话）等一下——" },
        ],
      },
    },
    model_id: null,
    parameters: {},
    metadata: {},
    prompt_context_snapshot_id: null,
    output_asset_id: "bed-asset",
    output_asset_version_id: "bed-asset-version",
    latest_attempt: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    created_at: "2026-09-26T00:00:00Z",
    updated_at: "2026-09-26T00:00:00Z",
    ...overrides,
  } as CanvasNodeV2;
}

function renderCard(node: CanvasNodeV2, asset?: ProjectAssetSummaryV2 | null) {
  return render(
    <AgentCanvasNodeCard
      node={node}
      asset={asset ?? null}
      runtime={null}
      selected={false}
    />,
  );
}

function startDrag(element: HTMLElement) {
  const data: Record<string, string> = {};
  const event = new Event("dragstart", { bubbles: true }) as DragEvent & {
    dataTransfer: { setData: (key: string, value: string) => void; effectAllowed: string };
  };
  event.dataTransfer = {
    setData: (key: string, value: string) => {
      data[key] = value;
    },
    effectAllowed: "",
  };
  fireEvent(element, event);
  return data;
}

describe("AgentCanvasNodeCard — voice-cast drag source", () => {
  it("drags the finished bed onto the voice track with its speaker names", () => {
    renderCard(voiceCastNode());
    const source = screen.getByTestId("voice-cast-drag-source-voice-node");
    const data = startDrag(source);

    const payload = parseTimelineDrop(data[TIMELINE_DROP_MIME]);
    expect(payload).not.toBeNull();
    expect(payload?.kind).toBe("asset");
    expect(payload?.media_type).toBe("audio");
    expect(payload?.asset_id).toBe("bed-asset");
    expect(payload?.source_node_id).toBe("voice-node");
    // One take, many speakers: the names ride in the label, and the clip
    // stays unbound (a single bound_character_id would be a lie).
    expect(payload?.label).toBe("音频床 · 林澈 / 苏晴");
  });

  it("is not draggable before the bed exists", () => {
    renderCard(voiceCastNode({ output_asset_id: null }));
    // The inert card renders the plain player, not a drag source.
    expect(screen.queryByTestId("voice-cast-drag-source-voice-node")).toBeNull();
    expect(screen.getByTestId("audio-player")).toBeTruthy();
  });

  it("falls back to the node title when the bed has no speakers", () => {
    renderCard(
      voiceCastNode({
        structured_content: {
          audio_bed: { scripts: [{ text: "[环境音，通风管道低频嗡鸣]" }] },
        },
      }),
    );
    const data = startDrag(screen.getByTestId("voice-cast-drag-source-voice-node"));

    const payload = parseTimelineDrop(data[TIMELINE_DROP_MIME]);
    expect(payload?.label).toBe("voice cast");
  });
});
