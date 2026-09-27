/**
 * DialogueLipSyncPanel tests — the scene side of 台词驱动.
 *
 * Locks: the empty-scene guard, the apply contract (draft script + lines to
 * /scene-3d/dialogue-lipsync), the draft replacement (the returned script
 * becomes the scene), the summary display (measured vs estimated), and the
 * unknown-speaker fail-closed surface.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import { DialogueLipSyncPanel } from "./DialogueLipSyncPanel.tsx";

const publishMock = vi.hoisted(() => vi.fn());
const bumpMock = vi.hoisted(() => vi.fn());
vi.mock("../timeline/publishSubtitleCues.ts", () => ({
  publishSubtitleCues: publishMock,
}));
vi.mock("../timeline/timelineMutationRefresh.ts", () => ({
  bumpTimelineMutationRefresh: bumpMock,
}));

function scene(): SceneScriptRoot {
  return {
    scene: { name: "lab", environment: "indoor", lighting: "cool", duration: 9, frame_rate: 30 },
    characters: [
      {
        id: "lin",
        type: "lowpoly_human",
        appearance: { color: "#E74C3C" },
        keyframes: [{ frame: 0, position: [0.8, 0, 0], rotation_y: 160, action: "stand" }],
      },
      {
        id: "su",
        type: "lowpoly_human",
        appearance: { color: "#3498DB" },
        keyframes: [{ frame: 0, position: [-0.9, 0, 0], rotation_y: 20, action: "stand" }],
      },
    ],
    props: [],
    environment: [],
    cameras: [
      { id: "cam1", shot_type: "wide", keyframes: [{ frame: 0, position: [5, -6, 2.6], look_at: [0, 0, 1.2] }] },
    ],
    shots: [{ id: "shot1", camera: "cam1", start_frame: 0, end_frame: 269, description: "wide" }],
    speech_bindings: [],
  };
}

/** A lip-synced scene: lin now has talk keyframes (what the backend returns). */
function lipSyncedScene(): SceneScriptRoot {
  const script = scene();
  script.characters[0].keyframes = [
    { frame: 0, position: [0.8, 0, 0], rotation_y: 160, action: "talk" },
    { frame: 39, position: [0.8, 0, 0], rotation_y: 160, action: "stand" },
  ];
  script.speech_bindings = [
    { character: "lin", speech_asset: "speech_audio:seg_000", mode: "bound" },
  ];
  return script;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(cleanup);

describe("DialogueLipSyncPanel", () => {
  it("explains itself when the scene has no characters", () => {
    const empty = scene();
    empty.characters = [];
    render(
      <DialogueLipSyncPanel
        sceneScript={empty}
        characterIds={[]}
        onSceneScriptApplied={vi.fn()}
      />,
    );
    expect(screen.getByText(/先在左侧托盘添加角色/)).toBeTruthy();
  });

  it("applies lip-sync and hands the new scene back as the draft", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => ({
        success: true,
        scene_script: lipSyncedScene(),
        summary: { segment_count: 2, duration_source: "estimated", issues: [] },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const onApplied = vi.fn();
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        onSceneScriptApplied={onApplied}
      />,
    );

    fireEvent.change(screen.getByLabelText("第 1 行台词"), {
      target: { value: "就是这里，信号源在墙后面。" },
    });
    fireEvent.change(screen.getByLabelText("第 1 行说话人"), {
      target: { value: "lin" },
    });
    fireEvent.click(screen.getByText("👄 应用唇形到场景"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/scene-3d/dialogue-lipsync");
    const body = JSON.parse((options as RequestInit).body as string);
    expect(body.scene_script.scene.name).toBe("lab");
    expect(body.dialogue_lines[0].character_id).toBe("lin");
    expect(body.dialogue_lines[0].text).toContain("信号源");

    // The returned scene becomes the draft — the speaker now has talk frames.
    await waitFor(() => {
      expect(onApplied).toHaveBeenCalledTimes(1);
    });
    const applied = onApplied.mock.calls[0][0] as SceneScriptRoot;
    const actions = applied.characters[0].keyframes.map((kf) => kf.action);
    expect(actions).toContain("talk");
    // Summary names the duration source honestly.
    expect(screen.getByTestId("dialogue-lipsync-summary").textContent).toContain("文本估算");
  });

  it("keeps an explicit start_time editable so alignment can be nudged", () => {
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        initialLines={[
          { character_id: "lin", text: "门是锁着的。", start_time: 1.25, emotion: null },
        ]}
        onSceneScriptApplied={vi.fn()}
      />,
    );
    const start = screen.getByLabelText("第 1 行开始 (s，可空)") as HTMLInputElement;
    expect(start.value).toBe("1.25"); // the alignment's measured value
    fireEvent.change(start, { target: { value: "2.5" } });
    expect((screen.getByLabelText("第 1 行开始 (s，可空)") as HTMLInputElement).value).toBe("2.5");
  });

  it("clears the start time back to null (falls back to duration estimate)", () => {
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        initialLines={[
          { character_id: "lin", text: "门是锁着的。", start_time: 1.25, emotion: null },
        ]}
        onSceneScriptApplied={vi.fn()}
      />,
    );
    const start = screen.getByLabelText("第 1 行开始 (s，可空)") as HTMLInputElement;
    fireEvent.change(start, { target: { value: "" } });
    expect((screen.getByLabelText("第 1 行开始 (s，可空)") as HTMLInputElement).value).toBe("");
  });

  it("disables apply without any dialogue", () => {
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        onSceneScriptApplied={vi.fn()}
      />,
    );
    expect((screen.getByText("👄 应用唇形到场景") as HTMLButtonElement).disabled).toBe(true);
  });

  it("surfaces an unknown-speaker rejection (fail closed)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 400,
        json: async () => ({
          detail: {
            error: "dialogue_lines reference character(s) ['ghost'] not present in the SceneScript (available: ['lin', 'su']).",
            error_code: "dialogue_unknown_speaker",
          },
        }),
      }),
    );
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        onSceneScriptApplied={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("第 1 行台词"), { target: { value: "有人吗" } });
    // The panel only offers scene characters, so simulate the backend rejection.
    fireEvent.click(screen.getByText("👄 应用唇形到场景"));

    await waitFor(() => {
      expect(screen.getByText(/reference character/)).toBeTruthy();
    });
  });
});

describe("DialogueLipSyncPanel — advisory → transition picker wire (V0.2 §15)", () => {
  const advisories = [
    {
      code: "line_crosses_cut",
      shot_id: "shot1",
      message: "台词跨过镜头 shot1 的剪切点。",
      remedy: "有意保留就是 L-cut；或把剪切点移到停顿里。",
      proposal_ids: ["sound_bridge", "cut_after_line", "time_jump"],
    },
    {
      code: "shot_without_speech",
      shot_id: "shot2",
      message: "镜头 shot2 没有任何台词。",
      remedy: "空镜可以保留。",
      proposal_ids: [],
    },
  ];

  /** The emotion-continuity family (V0.2 §5) arrives as its own summary key. */
  const emotionAdvisories = [
    {
      code: "emotion_whiplash",
      shot_id: "shot1",
      message: "镜头 shot1 的剪切点 3.0s 处情绪从「恐惧」直接切到「狂喜」。",
      remedy: "有意的情绪转折请忽略；否则留出停顿或先给反应镜头。",
    },
  ];

  function renderWith(overrides: { onOpenTransitions?: (shotId: string) => void } = {}) {
    const summary = {
      segment_count: 2,
      duration_source: "estimated",
      shot_advisories: advisories,
      emotion_advisories: emotionAdvisories,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        json: async () => ({ success: true, scene_script: scene(), summary }),
      }),
    );
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        onSceneScriptApplied={vi.fn()}
        {...overrides}
      />,
    );
    fireEvent.change(screen.getByLabelText("第 1 行台词"), {
      target: { value: "就是这里，信号源在墙后面。" },
    });
    fireEvent.change(screen.getByLabelText("第 1 行说话人"), { target: { value: "lin" } });
    fireEvent.click(screen.getByText("👄 应用唇形到场景"));
  }

  it("offers a jump to the picker only where the remedy is executable", async () => {
    const onOpenTransitions = vi.fn();
    renderWith({ onOpenTransitions });

    await waitFor(() => {
      expect(screen.getByTestId("dialogue-shot-advisories")).toBeTruthy();
    });
    // The crossing finding names the readings that execute its remedy…
    const jump = screen.getByTestId("dialogue-advisory-transitions-0") as HTMLButtonElement;
    expect(jump.textContent).toContain("看看怎么接");
    // …the no-speech finding has no cut remedy, so no dead link.
    expect(screen.queryByTestId("dialogue-advisory-transitions-1")).toBeNull();

    fireEvent.click(jump);
    expect(onOpenTransitions).toHaveBeenCalledWith("shot1");
  });

  it("renders emotion-continuity findings with their own label and no jump", async () => {
    const onOpenTransitions = vi.fn();
    renderWith({ onOpenTransitions });

    await waitFor(() => {
      expect(screen.getByTestId("dialogue-shot-advisories")).toBeTruthy();
    });
    // V0.2 §5 情绪维度: a different family, its own code label.
    expect(screen.getByText("情绪跨切突变")).toBeTruthy();
    expect(screen.getByText(/直接切到「狂喜」/)).toBeTruthy();
    // The remedy is a question, not a cut move: no jump-to-picker button.
    expect(screen.queryByTestId("dialogue-advisory-transitions-2")).toBeNull();
    expect(onOpenTransitions).not.toHaveBeenCalled();
  });

  it("keeps the advisories prose-only without a jump handler", async () => {
    renderWith();

    await waitFor(() => {
      expect(screen.getByTestId("dialogue-shot-advisories")).toBeTruthy();
    });
    expect(screen.queryByTestId("dialogue-advisory-transitions-0")).toBeNull();
    // The remedy itself still renders — the wire is additive, not a swap.
    expect(screen.getByText(/有意保留就是 L-cut/)).toBeTruthy();
  });

  it("lifts the measured segments so the picker prices against the same timeline", async () => {
    const segments = [
      { segment_id: "s0", character_id: "lin", text: "第一句。", start_time: 0.5, end_time: 2 },
      { segment_id: "s1", character_id: "su", text: "第二句。", start_time: 3, end_time: 4 },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        json: async () => ({
          success: true,
          scene_script: scene(),
          summary: { segment_count: 2, duration_source: "aligned", segments },
        }),
      }),
    );
    const onSegmentsApplied = vi.fn();
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        onSceneScriptApplied={vi.fn()}
        onSegmentsApplied={onSegmentsApplied}
      />,
    );
    fireEvent.change(screen.getByLabelText("第 1 行台词"), { target: { value: "第一句。" } });
    fireEvent.change(screen.getByLabelText("第 1 行说话人"), { target: { value: "lin" } });
    fireEvent.click(screen.getByText("👄 应用唇形到场景"));

    await waitFor(() => {
      expect(onSegmentsApplied).toHaveBeenCalledTimes(1);
    });
    // The picker gets the boundaries the mouths rode on, verbatim.
    expect(onSegmentsApplied).toHaveBeenCalledWith(segments);
  });
});

describe("DialogueLipSyncPanel — reorder & delivery (V0.2 §14.7 结构层/表演层)", () => {
  function renderRows() {
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        initialLines={[
          { character_id: "lin", text: "第一句。", start_time: 0.5, emotion: null },
          { character_id: "su", text: "第二句。", start_time: 2.0, emotion: null },
        ]}
        onSceneScriptApplied={vi.fn()}
      />,
    );
  }

  it("swaps a line with its neighbour (the row order IS the timeline order)", () => {
    renderRows();

    fireEvent.click(screen.getByLabelText("第 1 行下移"));

    // The rows exchanged places: the second speaker now leads.
    const speakers = screen.getAllByLabelText(/行说话人/) as HTMLSelectElement[];
    expect(speakers[0].value).toBe("su");
    expect(speakers[1].value).toBe("lin");
    expect(
      (screen.getByLabelText("第 1 行台词") as HTMLInputElement).value,
    ).toBe("第二句。");
  });

  it("refuses to reorder past either end", () => {
    renderRows();

    expect((screen.getByLabelText("第 1 行上移") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("第 2 行下移") as HTMLButtonElement).disabled).toBe(true);
  });

  it("carries the delivery into the apply body (the engine and the emotion check read it)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => ({
        success: true,
        scene_script: scene(),
        summary: { segment_count: 1, duration_source: "estimated", segments: [] },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin"]}
        initialLines={[
          { character_id: "lin", text: "别出声。", start_time: null, emotion: null },
        ]}
        onSceneScriptApplied={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("第 1 行语气"), {
      target: { value: "压低、克制" },
    });
    fireEvent.click(screen.getByText("👄 应用唇形到场景"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    // The delivery reaches the backend: the TTS engine takes it as an
    // argument and the emotion-continuity check reads it off the segment.
    expect(body.dialogue_lines[0].emotion).toBe("压低、克制");
  });
});

describe("DialogueLipSyncPanel — QA registry report (ADR 0003 §5)", () => {
  const qaReport = {
    checks: ["speech_duration_sanity", "bound_speech_vs_shot_duration"],
    outcomes: [
      { check: "speech_duration_sanity", status: "pass", reason: "实测时长与文本估算一致。", details: {} },
      {
        check: "bound_speech_vs_shot_duration",
        status: "warn",
        reason: "1 处 bound 台词超出所属镜头时长。",
        details: {},
      },
    ],
    failed: [],
    warned: ["bound_speech_vs_shot_duration"],
    passed: true,
  };

  function renderWithQa() {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        json: async () => ({
          success: true,
          scene_script: scene(),
          summary: {
            segment_count: 2,
            duration_source: "measured",
            issues: [],
            segments: [],
            qa_report: qaReport,
          },
        }),
      }),
    );
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin"]}
        initialLines={[{ character_id: "lin", text: "就是这里", start_time: 0.5, emotion: null }]}
        onSceneScriptApplied={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("👄 应用唇形到场景"));
  }

  it("surfaces the warn entries and passes stay quiet", async () => {
    renderWithQa();

    await waitFor(() => {
      expect(screen.getByTestId("dialogue-lipsync-qa")).toBeTruthy();
    });
    // The pass never appears; the warn does, with its reason.
    expect(screen.queryByText(/实测时长与文本估算一致/)).toBeNull();
    expect(screen.getByText(/1 处 bound 台词超出所属镜头时长/)).toBeTruthy();
    // The summary line counts them.
    expect(screen.getByTestId("dialogue-lipsync-summary").textContent).toContain("QA 1 项提醒");
  });

  it("stays quiet when every check passes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        json: async () => ({
          success: true,
          scene_script: scene(),
          summary: {
            segment_count: 1,
            duration_source: "estimated",
            issues: [],
            segments: [],
            qa_report: { ...qaReport, outcomes: [qaReport.outcomes[0]], warned: [] },
          },
        }),
      }),
    );
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin"]}
        initialLines={[{ character_id: "lin", text: "就是这里", start_time: null, emotion: null }]}
        onSceneScriptApplied={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("👄 应用唇形到场景"));

    await waitFor(() => {
      expect(screen.getByTestId("dialogue-lipsync-summary")).toBeTruthy();
    });
    expect(screen.queryByTestId("dialogue-lipsync-qa")).toBeNull();
  });
});

describe("DialogueLipSyncPanel — word-level lip-sync (V0.2 §14.9)", () => {
  it("forwards the alignment's word timings with the apply", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => ({
        success: true,
        scene_script: scene(),
        summary: { segment_count: 1, duration_source: "aligned", segments: [] },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin"]}
        initialLines={[
          {
            character_id: "lin",
            text: "别出声",
            start_time: 1.0,
            emotion: null,
            word_timings: [
              { text: "别", start: 1.0, end: 1.5 },
              { text: "出声", start: 1.6, end: 2.3 },
            ],
          },
        ]}
        onSceneScriptApplied={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("👄 应用唇形到场景"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    // The mouth moves WITH the words, so the scene side must receive them.
    expect(body.dialogue_lines[0].word_timings).toEqual([
      { text: "别", start: 1.0, end: 1.5 },
      { text: "出声", start: 1.6, end: 2.3 },
    ]);
  });

  it("omits the field for lines without word timings (the metronome stands)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => ({
        success: true,
        scene_script: scene(),
        summary: { segment_count: 1, duration_source: "estimated", segments: [] },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin"]}
        initialLines={[
          { character_id: "lin", text: "就是这里", start_time: null, emotion: null },
        ]}
        onSceneScriptApplied={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("👄 应用唇形到场景"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.dialogue_lines[0].word_timings).toBeUndefined();
  });
});

describe("DialogueLipSyncPanel — subtitle publish", () => {
  const segments = [
    { segment_id: "s0", character_id: "lin", text: "第一句。", start_time: 0.5, end_time: 2 },
    { segment_id: "s1", character_id: "su", text: "第二句。", start_time: 3, end_time: 4 },
  ];

  beforeEach(() => {
    publishMock.mockReset();
    bumpMock.mockReset();
    publishMock.mockResolvedValue({ created: 2, failed: [] });
  });

  it("publishes the applied segment timings to the subtitle track", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ scene_script: scene(), summary: { segment_count: 2, duration_source: "aligned", segments } }),
      }),
    );
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        workflowId="wf-1"
        initialLines={[
          { character_id: "lin", text: "第一句。", start_time: 0.5, emotion: null },
          { character_id: "su", text: "第二句。", start_time: 3, emotion: null },
        ]}
        onSceneScriptApplied={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("👄 应用唇形到场景"));

    // The cues ride the same authorial act as the lip-sync (C-mode chain:
    // bed -> align -> lip-sync -> subtitles) — no second trip needed.
    await waitFor(() => {
      expect(publishMock).toHaveBeenCalledTimes(1);
    });
    // The cues carry the service's boundaries — 1.5s and 1.0s, not re-estimated.
    expect(publishMock.mock.calls[0][0]).toBe("wf-1");
    expect(publishMock.mock.calls[0][1]).toEqual([
      { start_time: 0.5, duration: 1.5, subtitle_text: "第一句。", label: "lin: 第一句。" },
      { start_time: 3, duration: 1, subtitle_text: "第二句。", label: "su: 第二句。" },
    ]);
    await waitFor(() => {
      expect(screen.getByTestId("dialogue-lipsync-publish-result").textContent).toContain(
        "已上字幕轨 2 条",
      );
    });
    // An open timeline panel hears nothing over SSE for this mutation: the
    // publish must signal it explicitly.
    expect(bumpMock).toHaveBeenCalledTimes(1);
  });

  it("surfaces publish failures instead of reporting success", async () => {
    publishMock.mockResolvedValue({
      created: 1,
      failed: [{ index: 1, message: "Timeline API 400: invalid duration" }],
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ scene_script: scene(), summary: { segment_count: 2, duration_source: "aligned", segments } }),
      }),
    );
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        workflowId="wf-1"
        initialLines={[{ character_id: "lin", text: "第一句。", start_time: 0.5, emotion: null }]}
        onSceneScriptApplied={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("👄 应用唇形到场景"));

    // The failure surfaces from the automatic publish — the author sees it
    // without taking a second trip.
    await waitFor(() => {
      expect(screen.getByText(/1 条写入失败/)).toBeTruthy();
    });
    expect(screen.getByText(/Timeline API 400/)).toBeTruthy();
    // One cue DID land before the other failed, so the panel was signalled.
    expect(bumpMock).toHaveBeenCalledTimes(1);
  });

  it("does not signal the timeline when nothing landed", async () => {
    publishMock.mockResolvedValue({
      created: 0,
      replaced: 0,
      failed: [{ index: 0, message: "no track" }],
    });
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        workflowId="wf-1"
        initialLines={[{ character_id: "lin", text: "第一句。", start_time: 0.5, emotion: null }]}
        onSceneScriptApplied={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("👄 应用唇形到场景"));
    fireEvent.click(await screen.findByTestId("dialogue-lipsync-publish"));

    await waitFor(() => {
      expect(screen.getByText(/1 条写入失败/)).toBeTruthy();
    });
    expect(bumpMock).not.toHaveBeenCalled();
  });

  it("hides the publish affordance before any lip-sync applied", () => {
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        workflowId="wf-1"
        onSceneScriptApplied={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("dialogue-lipsync-publish")).toBeNull();
  });
});


describe("DialogueLipSyncPanel — durable lines on the node", () => {
  it("seeds from the persisted lines when no handoff is present", () => {
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        onSceneScriptApplied={vi.fn()}
        persistedLines={[
          { character_id: "lin", text: "就是这里。", start_time: 1.25, emotion: null },
        ]}
      />,
    );

    expect((screen.getByLabelText("第 1 行台词") as HTMLInputElement).value).toBe("就是这里。");
    expect((screen.getByLabelText("第 1 行开始 (s，可空)") as HTMLInputElement).value).toBe("1.25");
  });

  it("persists edited lines back to the node (debounced)", async () => {
    const onLinesPersist = vi.fn();
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        onSceneScriptApplied={vi.fn()}
        persistedLines={[
          { character_id: "lin", text: "就是这里。", start_time: null, emotion: null },
        ]}
        onLinesPersist={onLinesPersist}
      />,
    );

    fireEvent.change(screen.getByLabelText("第 1 行台词"), {
      target: { value: "就是这里，信号源在墙后面。" },
    });

    await waitFor(
      () => {
        expect(onLinesPersist).toHaveBeenCalledTimes(1);
      },
      { timeout: 2000 },
    );
    expect(onLinesPersist.mock.calls[0][0]).toEqual([
      {
        character_id: "lin",
        text: "就是这里，信号源在墙后面。",
        start_time: null,
        emotion: null,
      },
    ]);
  });

  it("prefers the alignment handoff over the persisted lines", () => {
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        initialLines={[
          { character_id: "su", text: "（交接）下一句。", start_time: 4, emotion: null },
        ]}
        persistedLines={[
          { character_id: "lin", text: "旧句。", start_time: 1, emotion: null },
        ]}
        onSceneScriptApplied={vi.fn()}
        onLinesPersist={vi.fn()}
      />,
    );

    expect((screen.getByLabelText("第 1 行台词") as HTMLInputElement).value).toBe("（交接）下一句。");
  });
});

describe("DialogueLipSyncPanel — cues ride the apply (C-mode chain)", () => {
  const segments = [
    { segment_id: "s0", character_id: "lin", text: "第一句。", start_time: 0.5, end_time: 2 },
  ];

  beforeEach(() => {
    publishMock.mockReset();
    bumpMock.mockReset();
    publishMock.mockResolvedValue({ created: 1, failed: [] });
  });

  it("publishes the subtitle cues as part of applying lip-sync", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          scene_script: scene(),
          summary: { segment_count: 1, duration_source: "aligned", segments },
        }),
      }),
    );
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin"]}
        workflowId="wf-1"
        initialLines={[{ character_id: "lin", text: "第一句。", start_time: 0.5, emotion: null }]}
        onSceneScriptApplied={vi.fn()}
      />,
    );

    // One click: the mouths move AND the cues reach the subtitle track.
    fireEvent.click(screen.getByText("👄 应用唇形到场景"));

    await waitFor(() => {
      expect(publishMock).toHaveBeenCalledTimes(1);
    });
    expect(publishMock.mock.calls[0][0]).toBe("wf-1");
    expect(publishMock.mock.calls[0][1]).toEqual([
      { start_time: 0.5, duration: 1.5, subtitle_text: "第一句。", label: "lin: 第一句。" },
    ]);
  });

  it("writes nothing to the timeline without a workflow id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          scene_script: scene(),
          summary: { segment_count: 1, duration_source: "aligned", segments },
        }),
      }),
    );
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin"]}
        initialLines={[{ character_id: "lin", text: "第一句。", start_time: 0.5, emotion: null }]}
        onSceneScriptApplied={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("👄 应用唇形到场景"));

    // The apply itself still lands (the scene side is the point of the panel);
    // only the timeline side stays out of it.
    await waitFor(() => {
      expect(screen.getByTestId("dialogue-lipsync-summary")).toBeTruthy();
    });
    expect(publishMock).not.toHaveBeenCalled();
  });
});

describe("DialogueLipSyncPanel — subtitle republish", () => {
  const segments = [
    { segment_id: "s0", character_id: "lin", text: "第一句。", start_time: 0.5, end_time: 2 },
  ];

  beforeEach(() => {
    publishMock.mockReset();
    publishMock.mockResolvedValue({ created: 1, replaced: 3, failed: [] });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          scene_script: scene(),
          summary: { segment_count: 1, duration_source: "aligned", segments },
        }),
      }),
    );
  });

  it("counts the replaced cues so a republish is visibly a replace", async () => {
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["lin", "su"]}
        workflowId="wf-1"
        sourceNodeId="scene-node"
        initialLines={[{ character_id: "lin", text: "第一句。", start_time: 0.5, emotion: null }]}
        onSceneScriptApplied={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("👄 应用唇形到场景"));
    // Round 1 is the automatic publish that rides the apply.
    await waitFor(() => {
      expect(publishMock).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(await screen.findByTestId("dialogue-lipsync-publish"));

    // Round 2 is the manual re-publish: the scene node id travels so it
    // REPLACES this node's cues instead of stacking.
    await waitFor(() => {
      expect(publishMock).toHaveBeenCalledTimes(2);
    });
    expect(publishMock.mock.calls[1][2]).toEqual({ sourceNodeId: "scene-node" });
    const result = await screen.findByTestId("dialogue-lipsync-publish-result");
    expect(result.textContent).toContain("替换 3 条旧 cues");
    expect(result.textContent).toContain("已上字幕轨 1 条");
  });
});

describe("DialogueLipSyncPanel — shot advisories", () => {
  const segments = [
    { segment_id: "s0", character_id: "char_a", text: "就是这里。", start_time: 0.5, end_time: 2 },
  ];

  beforeEach(() => {
    publishMock.mockReset();
    publishMock.mockResolvedValue({ created: 1, replaced: 0, failed: [] });
  });

  it("shows the shot advisories with their remedies (advisory, never blocking)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          scene_script: scene(),
          summary: {
            segment_count: 1,
            duration_source: "aligned",
            segments,
            shot_advisories: [
              {
                code: "line_crosses_cut",
                shot_id: "shot1",
                message: "台词「就是这里。」跨过镜头 shot1 的剪切点 1.5s。",
                remedy: "有意保留就是 L-cut；或把剪切点移到 2.0s 附近的停顿里。",
                severity: "warning",
              },
            ],
          },
        }),
      }),
    );
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["char_a", "char_b"]}
        initialLines={[{ character_id: "char_a", text: "就是这里。", start_time: 0.5, emotion: null }]}
        onSceneScriptApplied={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("👄 应用唇形到场景"));

    const panel = await screen.findByTestId("dialogue-shot-advisories");
    expect(panel.textContent).toContain("分镜提示（不自动修改）");
    expect(panel.textContent).toContain("话音跨切点");
    expect(panel.textContent).toContain("跨过镜头 shot1 的剪切点");
    // Every advisory carries its remedy.
    expect(panel.textContent).toContain("L-cut");
  });

  it("stays silent when the run reports no advisories", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ scene_script: scene(), summary: { segment_count: 1, segments } }),
      }),
    );
    render(
      <DialogueLipSyncPanel
        sceneScript={scene()}
        characterIds={["char_a", "char_b"]}
        initialLines={[{ character_id: "char_a", text: "就是这里。", start_time: 0.5, emotion: null }]}
        onSceneScriptApplied={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("👄 应用唇形到场景"));

    await waitFor(() => {
      expect(screen.getByTestId("dialogue-lipsync-summary")).toBeTruthy();
    });
    expect(screen.queryByTestId("dialogue-shot-advisories")).toBeNull();
  });
});
