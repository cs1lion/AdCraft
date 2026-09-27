/**
 * LocalEngineWorkbench scene-3d integration tests.
 *
 * The 3D editor is mocked (its own tests cover the inspector); this file
 * locks the workbench contract: the editor appears only for scene-3d nodes
 * that carry a SceneScript, the hint appears otherwise, and 保存场景 PATCHes
 * the node with structured_content MERGED (narration must survive), never
 * replaced.
 */

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import type { CanvasNodeV2 } from "../../../types-v2.ts";
import type { SceneScriptRoot } from "../../../types/scene-script";

type EditorProbe = {
  sceneScript?: SceneScriptRoot;
  dirty?: boolean;
  /** §13 第 4 问: the continuity findings, parsed off the node's key. */
  blockingContinuity?: readonly { code: string; boundary: string; message: string }[];
  /** §13 第 4 问: the declared reading reconciled with those findings. */
  consistency?: { passed: boolean; issues: readonly { code: string; severity: string }[] };
  onSelectionChange?: (ref: unknown) => void;
  transitionIntentNotes?: readonly {
    code: string;
    severity: string;
    shot_id: string;
    reading_id: string | null;
    message: string;
    remedy: string;
  }[];
  onChange?: (next: SceneScriptRoot) => void;
  onSave?: () => void;
  onRevert?: () => void;
  dialogueLines?: readonly {
    character_id: string;
    text: string;
    start_time: number;
  }[];
};

const editorProps = vi.hoisted(() => ({}) as EditorProbe);
vi.mock("../canvas/SceneScript3DEditor.tsx", () => ({
  SceneScript3DEditor: (props: {
    sceneScript: SceneScriptRoot;
    dirty?: boolean;
    onChange: (next: SceneScriptRoot) => void;
    onSave: () => void;
    onRevert: () => void;
    error?: string | null;
  }) => {
    Object.assign(editorProps, props);
    return (
      <div>
        <button type="button" onClick={() => props.onChange({ ...props.sceneScript, scene: { ...props.sceneScript.scene, name: "edited" } })}>
          make-dirty
        </button>
        <button type="button" disabled={!props.dirty} onClick={props.onSave}>
          editor-save
        </button>
        <button type="button" onClick={props.onRevert}>
          editor-revert
        </button>
        {props.error ? <span>{props.error}</span> : null}
      </div>
    );
  },
}));

vi.mock("../canvas/SceneScript3DPreview.tsx", () => ({
  SceneScript3DPreview: () => null,
}));

import { LocalEngineWorkbench } from "./LocalEngineWorkbench.tsx";

function sceneScript(): SceneScriptRoot {
  return {
    scene: { name: "地下研究所 B2", environment: "indoor", lighting: "cool", duration: 6, frame_rate: 30 },
    characters: [
      {
        id: "char_a",
        type: "lowpoly_human",
        appearance: { color: "#E74C3C", height: 1.7, scale: 1 },
        keyframes: [{ frame: 0, position: [0, 0, 0], rotation_y: 90, action: "stand" }],
      },
    ],
    props: [],
    environment: [],
    cameras: [
      {
        id: "cam1",
        shot_type: "wide",
        keyframes: [{ frame: 0, position: [8, -10, 5], look_at: [0, 0, 1] }],
      },
    ],
    shots: [{ id: "shot1", camera: "cam1", start_frame: 0, end_frame: 179, description: "wide" }],
    speech_bindings: [],
  };
}

function makeOutputAsset() {
  return {
    asset_id: "asset_audio_1",
    version_id: "ver_audio_1",
    project_id: "proj-1",
    workflow_id: "workflow-1",
    media_type: "audio",
    source_type: "generated",
    semantic_type: null,
    display_name: "生成的音频床",
    mime_type: "audio/mpeg",
    status: "ready",
    size_bytes: 20000,
    storage_key: "k",
    preview_url: null,
    media_url: null,
    width: null,
    height: null,
    duration_seconds: 12.5,
    checksum: "c",
  };
}

function makeNode(overrides: Partial<CanvasNodeV2> = {}): CanvasNodeV2 {
  return {
    node_id: "scene-node",
    workflow_id: "workflow-1",
    node_type: "scene-3d",
    creative_role: "scene_3d_previs",
    role_contract_version: "ad-media-role-v1",
    title: "scene node",
    status: "ready",
    summary_prompt: null,
    generation_prompt: "a corridor",
    structured_content: { scene_script: sceneScript(), narration: "低沉的风声" },
    model_id: null,
    parameters: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    prompt_preparation: null,
    created_at: "2026-09-25T00:00:00Z",
    updated_at: "2026-09-25T00:00:00Z",
    ...overrides,
  } as CanvasNodeV2;
}

const draft = {
  pending: false,
  prompt: "a corridor",
  setPrompt: vi.fn(),
  run: vi.fn(),
};

afterEach(() => {
  cleanup();
});

// The probe accumulates across renders; reset it so later tests assert on
// their own render, not the previous one's captured props.
function resetEditorProbe() {
  for (const key of Object.keys(editorProps)) {
    delete editorProps[key as keyof EditorProbe];
  }
}

async function renderWorkbench(node: CanvasNodeV2, patchNode = vi.fn().mockResolvedValue(undefined)) {
  resetEditorProbe();
  const utils = render(
    <LocalEngineWorkbench node={node} draft={draft} patchNode={patchNode} />,
  );
  return { patchNode, ...utils };
}

/** The editor is lazy-loaded (three.js stays in an async chunk): await its mount. */
async function editorMounted() {
  await screen.findByRole("button", { name: "editor-save" });
}

describe("LocalEngineWorkbench scene-3d editing", () => {
  it("renders the 3D editor for a scene-3d node carrying a SceneScript", async () => {
    renderWorkbench(makeNode());
    await editorMounted();
    expect(editorProps.sceneScript?.scene.name).toBe("地下研究所 B2");
    expect(screen.getByRole("button", { name: "editor-save" })).toBeTruthy();
  });

  it("parses the continuity findings and the declared-reading notes (§13 第 4 问)", async () => {
    renderWorkbench(
      makeNode({
        structured_content: {
          scene_script: sceneScript(),
          scene3d_blocking_continuity: [
            {
              code: "facing_flip",
              severity: "warning",
              subject: "char_a",
              boundary: "shot1→shot2",
              message: "转身 170°。",
              remedy: "补一个转身关键帧。",
            },
          ],
          scene3d_transition_intent: [
            {
              code: "transition_intent_explains_continuity",
              severity: "info",
              shot_id: "shot2",
              reading_id: "time_jump",
              message: "变化是读法的一部分。",
              remedy: "无需处理。",
            },
          ],
        },
      }),
    );
    await editorMounted();
    expect(editorProps.blockingContinuity).toEqual([
      {
        code: "facing_flip",
        severity: "warning",
        subject: "char_a",
        boundary: "shot1→shot2",
        message: "转身 170°。",
        remedy: "补一个转身关键帧。",
      },
    ]);
    expect(editorProps.transitionIntentNotes?.[0].code).toBe(
      "transition_intent_explains_continuity",
    );
  });

  it("parses the consistency report the executor publishes (§12 核心问题)", async () => {
    renderWorkbench(
      makeNode({
        structured_content: {
          scene_script: sceneScript(),
          scene3d_consistency: {
            passed: false,
            error_count: 1,
            warning_count: 0,
            issues: [
              {
                code: "character_unbound",
                severity: "error",
                subject: "char_a",
                message: "Character 'char_a' has no bound character asset.",
                remedy: "Bind a character asset.",
              },
            ],
          },
        },
      }),
    );
    await editorMounted();
    expect(editorProps.consistency?.passed).toBe(false);
    expect(editorProps.consistency?.issues[0].code).toBe("character_unbound");
  });

  it("passes nothing when the node carries neither key", async () => {
    renderWorkbench(makeNode());
    await editorMounted();
    expect(editorProps.blockingContinuity).toBeNull();
    expect(editorProps.transitionIntentNotes).toBeNull();
  });

  it("shows the guidance hint when the node has no SceneScript yet", async () => {
    renderWorkbench(makeNode({ structured_content: {} }));
    expect(screen.getByText(/运行节点生成 SceneScript/)).toBeTruthy();
    expect(editorProps.sceneScript).toBeUndefined();
  });

  it("does not render the editor for voice-cast nodes", async () => {
    renderWorkbench(makeNode({ node_type: "voice-cast", creative_role: "voice_cast" }));
    expect(screen.queryByRole("button", { name: "editor-save" })).toBeNull();
    expect(screen.queryByText(/运行节点生成 SceneScript/)).toBeNull();
  });

  it("does not render the editor without a patchNode capability", async () => {
    render(<LocalEngineWorkbench node={makeNode()} draft={draft} />);
    expect(screen.queryByRole("button", { name: "editor-save" })).toBeNull();
  });

  it("PATCHes merged structured_content on save (narration survives)", async () => {
    const { patchNode } = await renderWorkbench(makeNode());
    await editorMounted();
    // Save is gated on dirty: make an edit first.
    fireEvent.click(screen.getByRole("button", { name: "make-dirty" }));
    fireEvent.click(screen.getByRole("button", { name: "editor-save" }));

    expect(patchNode).toHaveBeenCalledTimes(1);
    const [nodeId, patch] = patchNode.mock.calls[0];
    expect(nodeId).toBe("scene-node");
    // The merge: narration preserved, scene_script replaced with the draft.
    expect(patch.structured_content.narration).toBe("低沉的风声");
    expect(patch.structured_content.scene_script.scene.name).toBe("edited");
    // The persisted node is never mutated in place.
    expect(makeNode().structured_content.scene_script.scene.name).toBe("地下研究所 B2");
  });

  it("surfaces a save error and keeps the draft for retry", async () => {
    const patchNode = vi.fn().mockRejectedValue(new Error("版本冲突"));
    renderWorkbench(makeNode(), patchNode);
    await editorMounted();
    fireEvent.click(screen.getByRole("button", { name: "make-dirty" }));
    fireEvent.click(screen.getByRole("button", { name: "editor-save" }));

    await vi.waitFor(() => {
      expect(screen.getByText("版本冲突")).toBeTruthy();
    });
    // The editor is still mounted with the edited draft (not reverted).
    expect(editorProps.sceneScript?.scene.name).toBe("edited");
  });
});


describe("LocalEngineWorkbench — bed preview", () => {
  it("renders the generated audio bed for a voice-cast node with output", async () => {
    const node = makeNode({
      node_type: "voice-cast",
      creative_role: "voice_cast",
      output_asset_id: "asset_audio_1",
      status: "ready",
    });
    render(
      <LocalEngineWorkbench
        node={node}
        draft={draft}
        outputAsset={makeOutputAsset() as never}
      />,
    );
    // The audio player renders (AgentCanvasAudioPlayer's contract: the title
    // is the node's prompt excerpt) with the asset's content endpoint.
    // (The prompt text also appears in the composer textarea, so query the
    // player's title node rather than by text.)
    await waitFor(() => {
      expect(
        document.querySelector(".agent-canvas-audio-player__title")?.textContent,
      ).toBe("a corridor");
    });
    expect(document.querySelector("audio")?.getAttribute("src")).toBe(
      "/api/v2/assets/asset_audio_1/content?v=ver_audio_1",
    );
  });

  it("renders no player before the node has produced media", () => {
    const node = makeNode({ node_type: "voice-cast", creative_role: "voice_cast" });
    render(<LocalEngineWorkbench node={node} draft={draft} outputAsset={null} />);
    // Without an output asset the player section is absent entirely.
    expect(document.querySelector(".local-engine-workbench__output")).toBeNull();
  });

  it("does not preview output on scene-3d nodes (the canvas owns that surface)", () => {
    render(
      <LocalEngineWorkbench
        node={makeNode()}
        draft={draft}
        outputAsset={makeOutputAsset() as never}
      />,
    );
    // The scene-3d editor renders, but no audio player surface exists.
    expect(document.querySelector(".local-engine-workbench__output")).toBeNull();
  });
});


describe("LocalEngineWorkbench — white-model mode entry", () => {
  it("shows the mode toggle off by default and explains the off state", () => {
    renderWorkbench(makeNode());
    const toggle = screen.getByLabelText("白模设计模式") as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    expect(screen.getByText(/开启后，运行节点按操作批次生成场景/)).toBeTruthy();
  });

  it("reflects a stored white_model flag and the on-state explanation", () => {
    const node = makeNode();
    node.structured_content = { ...node.structured_content, white_model: true };
    renderWorkbench(node);
    expect((screen.getByLabelText("白模设计模式") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/描述经 agent 转为操作批次/)).toBeTruthy();
  });

  it("toggling PATCHes the merged structured content (white_model flips)", async () => {
    const patchNode = vi.fn().mockResolvedValue(undefined);
    render(<LocalEngineWorkbench node={makeNode()} draft={draft} patchNode={patchNode} />);

    fireEvent.click(screen.getByLabelText("白模设计模式"));

    await waitFor(() => {
      expect(patchNode).toHaveBeenCalledTimes(1);
    });
    const [nodeId, patch] = patchNode.mock.calls[0];
    expect(nodeId).toBe("scene-node");
    expect(patch.structured_content.white_model).toBe(true);
    // Merge, never replace: the scene script survives the mode switch.
    expect(patch.structured_content.scene_script).toBeDefined();
  });
});


describe("LocalEngineWorkbench — white-model op log", () => {
  it("renders the agent's op log when the node carries a report", async () => {
    const node = makeNode();
    node.structured_content = {
      ...node.structured_content,
      white_model: true,
      white_model_report: {
        operation_count: 2,
        applied: [
          { index: 0, op: "add_environment", target: "env_1" },
          { index: 1, op: "add_character", target: "char_1" },
        ],
        mcp_results: [],
      },
    };
    render(<LocalEngineWorkbench node={node} draft={draft} patchNode={vi.fn()} />);

    const log = await screen.findByTestId("white-model-op-log");
    expect(log.textContent).toContain("2/2 个操作");
    expect(log.textContent).toContain("添加环境");
  });

  it("renders no op log for a plain scene-3d node", () => {
    render(<LocalEngineWorkbench node={makeNode()} draft={draft} patchNode={vi.fn()} />);
    expect(screen.queryByTestId("white-model-op-log")).toBeNull();
  });
});


describe("LocalEngineWorkbench — image intake entry", () => {
  it("renders the image intake for scene-3d nodes", () => {
    render(<LocalEngineWorkbench node={makeNode()} draft={draft} patchNode={vi.fn()} />);
    expect(screen.getByText("🖼 从图片生成场景")).toBeTruthy();
  });

  it("does not render the image intake for voice-cast nodes", () => {
    const node = makeNode({ node_type: "voice-cast", creative_role: "voice_cast" });
    render(<LocalEngineWorkbench node={node} draft={draft} patchNode={vi.fn()} />);
    expect(screen.queryByText("🖼 从图片生成场景")).toBeNull();
  });
});


describe("LocalEngineWorkbench — full-screen director workbench", () => {
  it("toggles into the full-screen portal and back", async () => {
    render(<LocalEngineWorkbench node={makeNode()} draft={draft} patchNode={vi.fn()} />);
    expect(screen.queryByTestId("scene-3d-workbench-fullscreen")).toBeNull();

    fireEvent.click(screen.getByText("⤢ 全屏导演台"));
    // The portal content lands on document.body, outside the panel.
    expect(screen.getByTestId("scene-3d-workbench-fullscreen")).toBeTruthy();

    fireEvent.click(screen.getByText("⤡ 退出全屏"));
    expect(screen.queryByTestId("scene-3d-workbench-fullscreen")).toBeNull();
  });

  it("Escape collapses the full-screen workbench", () => {
    render(<LocalEngineWorkbench node={makeNode()} draft={draft} patchNode={vi.fn()} />);
    fireEvent.click(screen.getByText("⤢ 全屏导演台"));
    expect(screen.getByTestId("scene-3d-workbench-fullscreen")).toBeTruthy();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("scene-3d-workbench-fullscreen")).toBeNull();
  });
});


describe("LocalEngineWorkbench — dialogue lip-sync entry", () => {
  it("renders the lip-sync panel with the scene's characters", () => {
    render(<LocalEngineWorkbench node={makeNode()} draft={draft} patchNode={vi.fn()} />);
    const panel = screen.getByTestId("dialogue-lipsync");
    expect(panel).toBeTruthy();
    // The scene's character is offered as a speaker.
    expect(screen.getByLabelText("第 1 行说话人")).toBeTruthy();
  });

  it("hides the panel for voice-cast nodes", () => {
    const node = makeNode({ node_type: "voice-cast", creative_role: "voice_cast" });
    render(<LocalEngineWorkbench node={node} draft={draft} patchNode={vi.fn()} />);
    expect(screen.queryByTestId("dialogue-lipsync")).toBeNull();
  });

  it("seeds the lip-sync panel from the C-mode alignment handoff", () => {
    render(
      <LocalEngineWorkbench
        node={makeNode()}
        draft={draft}
        patchNode={vi.fn()}
        alignedSpeechLines={[
          {
            segment_id: "seg_0",
            character_id: "char_a",
            text: "门是锁着的。",
            start_time: 1.25,
            end_time: 3.4,
            confidence: 0.91,
            align_source: "whisperx",
          },
        ]}
      />,
    );
    // The measured start time lands in the seed row — the lip-sync service
    // must not re-estimate it (the alignment IS the measurement).
    const startInput = screen.getByLabelText("第 1 行开始 (s，可空)") as HTMLInputElement;
    expect(startInput.value).toBe("1.25");
    const textInput = screen.getByLabelText("第 1 行台词") as HTMLInputElement;
    expect(textInput.value).toBe("门是锁着的。");
    const speakerInput = screen.getByLabelText("第 1 行说话人") as HTMLSelectElement;
    expect(speakerInput.value).toBe("char_a");
  });
});

describe("LocalEngineWorkbench — durable dialogue lines", () => {
  it("seeds the lip-sync panel from the node and PATCHes edits back", async () => {
    const patchNode = vi.fn().mockResolvedValue(undefined);
    const node = makeNode();
    node.structured_content = {
      scene_script: sceneScript(),
      dialogue_lines: [
        { character_id: "char_a", text: "就是这里。", start_time: 1.5, emotion: null },
      ],
    };
    render(<LocalEngineWorkbench node={node} draft={draft} patchNode={patchNode} />);

    // Seeded from the node's stored lines.
    expect((screen.getByLabelText("第 1 行台词") as HTMLInputElement).value).toBe("就是这里。");
    expect((screen.getByLabelText("第 1 行开始 (s，可空)") as HTMLInputElement).value).toBe("1.5");

    fireEvent.change(screen.getByLabelText("第 1 行台词"), {
      target: { value: "就是这里，信号源在墙后面。" },
    });

    await waitFor(
      () => {
        expect(patchNode).toHaveBeenCalled();
      },
      { timeout: 2000 },
    );
    const [nodeId, payload, options] = patchNode.mock.calls[0];
    expect(nodeId).toBe("scene-node");
    // Merge, never replace: the scene script survives the dialogue patch.
    expect((payload.structured_content as Record<string, unknown>).scene_script).toBeTruthy();
    expect((payload.structured_content as Record<string, unknown>).dialogue_lines).toEqual([
      { character_id: "char_a", text: "就是这里，信号源在墙后面。", start_time: 1.5, emotion: null },
    ]);
    expect((options as { coalesce?: boolean }).coalesce).toBe(true);
  });
});

describe("LocalEngineWorkbench — viewport speech overlay wiring", () => {
  it("hands the persisted dialogue lines to the 3D editor for the overlay", () => {
    const node = makeNode();
    node.structured_content = {
      scene_script: sceneScript(),
      dialogue_lines: [
        { character_id: "char_a", text: "就是这里。", start_time: 0.5, emotion: null },
        { character_id: "char_b", text: "", start_time: 1, emotion: null }, // dropped: no text
        { character_id: "char_a", text: "下一句。", start_time: null, emotion: null }, // dropped: unaligned
      ],
    };
    render(<LocalEngineWorkbench node={node} draft={draft} patchNode={vi.fn()} />);

    // Only lines with text AND a start time can drive the overlay.
    expect(editorProps.dialogueLines).toEqual([
      { character_id: "char_a", text: "就是这里。", start_time: 0.5 },
    ]);
  });
});

describe("LocalEngineWorkbench — the pointer meets the language (§8.2)", () => {
  /** The mocked editor calls onSelectionChange with whatever we hand it. */
  function pointAt(ref: { kind: string; id: string }) {
    act(() => {
      editorProps.onSelectionChange?.(ref as never);
    });
  }

  it("names what “这个” means once something is pointed at", async () => {
    renderWorkbench(makeNode());
    await editorMounted();
    expect(screen.queryByTestId("workbench-pointer")).toBeNull();

    pointAt({ kind: "character", id: "char_a" });

    const chip = screen.getByTestId("workbench-pointer");
    expect(chip.textContent).toContain("角色 char_a");
    expect(chip.textContent).toContain("指的就是它");
  });

  it("writes the pointer into the prompt visibly, not silently", async () => {
    const draftWithPrompt = {
      ...draft,
      prompt: "把这个改成短发",
      setPrompt: vi.fn(),
    };
    render(
      <LocalEngineWorkbench node={makeNode()} draft={draftWithPrompt} patchNode={vi.fn()} />,
    );
    await editorMounted();
    pointAt({ kind: "character", id: "char_a" });

    fireEvent.click(screen.getByTestId("workbench-pointer-write"));

    expect(draftWithPrompt.setPrompt).toHaveBeenCalledWith(
      "把这个改成短发 【指向：角色 char_a】",
    );
  });

  it("starts the prompt with the token when the prompt is empty", async () => {
    const draftEmpty = { ...draft, prompt: "", setPrompt: vi.fn() };
    render(<LocalEngineWorkbench node={makeNode()} draft={draftEmpty} patchNode={vi.fn()} />);
    await editorMounted();
    pointAt({ kind: "prop", id: "crate1" });
    fireEvent.click(screen.getByTestId("workbench-pointer-write"));
    expect(draftEmpty.setPrompt).toHaveBeenCalledWith("【指向：道具 crate1】");
  });

  it("clears the chip when the pointer goes away", async () => {
    renderWorkbench(makeNode());
    await editorMounted();
    pointAt({ kind: "character", id: "char_a" });
    expect(screen.getByTestId("workbench-pointer")).toBeTruthy();
    pointAt(null as never);
    expect(screen.queryByTestId("workbench-pointer")).toBeNull();
  });
});

describe("LocalEngineWorkbench — speaker/character map wiring", () => {
  it("passes the bed roles' character_id map to the alignment panel", async () => {
    const onLinesAligned = vi.fn();
    const node = makeNode({
      node_type: "voice-cast",
      creative_role: "voice_cast",
      structured_content: {
        audio_bed: {
          roles: [{ name: "林澈", description: "低沉男声", character_id: "char_a" }],
          scripts: [{ speaker: "林澈", text: "门是锁着的。" }],
        },
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          align_source: "whisperx",
          segments: [
            {
              segment_id: "seg_0",
              character_id: "林澈",
              text: "门是锁着的。",
              start_time: 0,
              end_time: 1.2,
              confidence: 0.9,
              align_source: "whisperx",
            },
          ],
          low_confidence_ids: [],
        }),
      }),
    );
    render(
      <LocalEngineWorkbench
        node={node}
        draft={draft}
        patchNode={vi.fn()}
        outputAsset={{ asset_id: "asset-bed-1", media_type: "audio", title: "bed" } as never}
        onLinesAligned={onLinesAligned}
      />,
    );
    fireEvent.click(screen.getByText("🎯 台词对齐"));

    await waitFor(() => {
      expect(onLinesAligned).toHaveBeenCalledTimes(1);
    });
    // The panel mapped the bed speaker onto the scene character id before
    // handing it up: the scene-side editor receives a selectable speaker.
    expect(
      (onLinesAligned.mock.calls[0][0] as { character_id: string }[])[0].character_id,
    ).toBe("char_a");
    // The alignment row stays faithful to the bed and shows the mapping chip
    // (query the chip itself: the speaker name also appears in the bed editor).
    const chip = document.querySelector(".dialogue-alignment__who-mapped");
    expect(chip?.textContent).toContain("char_a");
  });
});

describe("LocalEngineWorkbench — voice-cast alignment handoff", () => {
  it("reports aligned lines up via onLinesAligned", async () => {
    const onLinesAligned = vi.fn();
    const node = makeNode({
      node_type: "voice-cast",
      creative_role: "voice_cast",
      structured_content: {
        audio_bed: {
          roles: [{ name: "林澈" }],
          scripts: [{ speaker: "林澈", text: "门是锁着的。" }],
        },
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          align_source: "whisperx",
          segments: [
            {
              segment_id: "seg_0",
              character_id: "林澈",
              text: "门是锁着的。",
              start_time: 0,
              end_time: 1.2,
              confidence: 0.9,
              align_source: "whisperx",
            },
          ],
          low_confidence_ids: [],
        }),
      }),
    );
    render(
      <LocalEngineWorkbench
        node={node}
        draft={draft}
        patchNode={vi.fn()}
        outputAsset={{
          asset_id: "asset-bed-1",
          media_type: "audio",
          title: "bed",
          duration_seconds: 4,
        } as never}
        onLinesAligned={onLinesAligned}
      />,
    );
    fireEvent.click(screen.getByText("🎯 台词对齐"));
    await waitFor(() => {
      expect(onLinesAligned).toHaveBeenCalledTimes(1);
    });
    const handed = onLinesAligned.mock.calls[0][0];
    expect(
      (handed as { character_id: string }[]).map((line) => line.character_id),
    ).toEqual(["林澈"]);
  });
});

