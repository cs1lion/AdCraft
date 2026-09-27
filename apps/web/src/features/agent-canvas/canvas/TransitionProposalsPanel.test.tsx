/**
 * TransitionProposalsPanel tests — the Scene A → B 衔接方案 picker.
 *
 * Locks the contract: the pair is the playhead shot + its successor, the four
 * readings render with feasibility, applying a feasible proposal replays its
 * operations through the preset libraries (and reports deferred steps), and
 * nothing is auto-applied on load.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import { TransitionProposalsPanel } from "./TransitionProposalsPanel.tsx";
import type { TransitionVariant } from "./transitionVariants.ts";

function script(): SceneScriptRoot {
  return {
    scene: { name: "lab", environment: "indoor", lighting: "cool", duration: 8, frame_rate: 30 },
    characters: [
      {
        id: "lin",
        type: "lowpoly_human",
        appearance: { color: "#E74C3C" },
        keyframes: [{ frame: 0, position: [0, 0, 0], rotation_y: 0, action: "stand" }],
      },
    ],
    props: [],
    environment: [],
    cameras: [
      { id: "cam1", shot_type: "wide", keyframes: [{ frame: 0, position: [5, -6, 2.6], look_at: [0, 0, 1.2] }] },
    ],
    shots: [
      { id: "s1", camera: "cam1", start_frame: 0, end_frame: 89, description: "" },
      { id: "s2", camera: "cam1", start_frame: 90, end_frame: 179, description: "" },
    ],
    speech_bindings: [],
  };
}

function proposalPayload(overrides: Record<string, unknown> = {}) {
  return {
    id: "continuous_motion",
    label: "连续运动",
    narrative: "人物穿过空间，摄影机跟随。",
    feasible: true,
    operations: [
      {
        kind: "character_preset",
        rationale: "走向下一镜主体",
        preset_id: "walk_to",
        character_id: "lin",
        start_frame: 0,
        duration_frames: 45,
      },
    ],
    ...overrides,
  };
}

afterEach(cleanup);

describe("TransitionProposalsPanel", () => {
  it("asks for the playhead shot paired with its successor", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, proposals: [proposalPayload()] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <TransitionProposalsPanel
        sceneScript={script()}
        currentShotId="s1"
        onChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.shot_a_id).toBe("s1");
    expect(body.shot_b_id).toBe("s2");
  });

  it("renders the readings with feasibility and the honest hint", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          proposals: [
            proposalPayload(),
            proposalPayload({ id: "time_jump", label: "时间/空间跳跃", feasible: false, infeasible_reason: "没有可用停顿", operations: [] }),
          ],
        }),
      }),
    );
    render(
      <TransitionProposalsPanel sceneScript={script()} currentShotId="s1" onChange={vi.fn()} />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));

    await waitFor(() => {
      expect(screen.getByText("连续运动")).toBeTruthy();
    });
    // Infeasible readings stay visible with their reason — the creator learns
    // WHY a reading is unavailable instead of wondering where it went.
    expect(screen.getByText(/暂不可用：没有可用停顿/)).toBeTruthy();
    expect(
      (screen.getByTestId("transition-apply-time_jump") as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByText(/不自动修改镜头结构/)).toBeTruthy();
  });

  it("applies a feasible proposal through the preset libraries", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true, proposals: [proposalPayload()] }),
      }),
    );
    const onChange = vi.fn();
    render(
      <TransitionProposalsPanel sceneScript={script()} currentShotId="s1" onChange={onChange} />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => {
      expect(screen.getByTestId("transition-apply-continuous_motion")).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId("transition-apply-continuous_motion"));

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    // The walk preset wrote keyframes: the character moved and landed standing.
    expect(next.characters[0].keyframes[next.characters[0].keyframes.length - 1].action).toBe("stand");
    expect(screen.getByTestId("transition-proposals-note").textContent).toContain("已应用 1 步");
  });

  it("explains the pair requirement with a single shot", () => {
    const single = script();
    single.shots = [single.shots[0]];
    render(
      <TransitionProposalsPanel sceneScript={single} currentShotId="s1" onChange={vi.fn()} />,
    );
    expect(screen.getByText(/至少需要两个镜头/)).toBeTruthy();
  });

  it("surfaces a fetch failure without hiding the panel", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => null }),
    );
    render(
      <TransitionProposalsPanel sceneScript={script()} currentShotId="s1" onChange={vi.fn()} />,
    );

    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));

    await waitFor(() => {
      expect(screen.getByText(/衔接方案获取失败/)).toBeTruthy();
    });
    expect(screen.getByTestId("transition-proposals")).toBeTruthy();
  });
});

describe("TransitionProposalsPanel — variants (V0.2 §9 局部分叉)", () => {
  afterEach(cleanup);

  const llmReading = () =>
    proposalPayload({
      id: "shadow_pass",
      label: "剪影过渡",
      narrative: "主体化作剪影，光替它完成转场。",
      origin: "llm",
      operations: [
        { kind: "camera_preset", rationale: "切点前推近", preset_id: "push_in", camera_id: "cam1" },
      ],
    });

  function renderWithVariants(
    onVariantsChange: (variants: TransitionVariant[]) => void,
    initial: TransitionVariant[] = [],
  ) {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true, proposals: [llmReading()], narrative_source: "rules" }),
      }),
    );
    return render(
      <TransitionProposalsPanel
        sceneScript={script()}
        currentShotId="s1"
        onChange={vi.fn()}
        variants={initial}
        onVariantsChange={onVariantsChange}
      />,
    );
  }

  it("saves the current script as a comparable variant", async () => {
    const onVariantsChange = vi.fn();
    renderWithVariants(onVariantsChange);
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() =>
      expect(screen.getByTestId("transition-save-variant-shadow_pass")).toBeTruthy(),
    );

    fireEvent.click(screen.getByTestId("transition-save-variant-shadow_pass"));

    expect(onVariantsChange).toHaveBeenCalledTimes(1);
    const saved = onVariantsChange.mock.calls[0][0] as TransitionVariant[];
    expect(saved).toHaveLength(1);
    // The WHOLE script rides along: the readings differ in camera and
    // character keyframes alike, so a partial snapshot would mix readings.
    expect(saved[0].scene_script).toEqual(script());
    expect(saved[0].proposal_id).toBe("shadow_pass");
    expect(saved[0].label).toBe("方案 A");
  });

  it("restores a saved variant into the draft", async () => {
    const stored = script();
    stored.scene = { ...stored.scene, name: "kept version" };
    const variant: TransitionVariant = {
      id: "v1",
      label: "方案 A",
      proposal_id: null,
      scene_script: stored as unknown as Record<string, unknown>,
    };
    const onChange = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true, proposals: [] }),
      }),
    );
    render(
      <TransitionProposalsPanel
        sceneScript={script()}
        currentShotId="s1"
        onChange={onChange}
        variants={[variant]}
        onVariantsChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId("transition-variant-restore-v1"));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect((onChange.mock.calls[0][0] as SceneScriptRoot).scene.name).toBe("kept version");
  });

  it("removes a variant", async () => {
    const variant: TransitionVariant = {
      id: "v1",
      label: "方案 A",
      proposal_id: null,
      scene_script: script() as unknown as Record<string, unknown>,
    };
    const onVariantsChange = vi.fn();
    renderWithVariants(onVariantsChange, [variant]);

    fireEvent.click(screen.getByTestId("transition-variant-remove-v1"));

    expect(onVariantsChange).toHaveBeenCalledWith([]);
  });

  it("states the cap so the branch explosion is visible, not silent", async () => {
    renderWithVariants(vi.fn());
    expect(screen.getByText(/已存方案（0\/4/)).toBeTruthy();
  });

  it("stays inert when the parent persists nothing (no variants support)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true, proposals: [llmReading()] }),
      }),
    );
    render(
      <TransitionProposalsPanel sceneScript={script()} currentShotId="s1" onChange={vi.fn()} />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => expect(screen.getByText("剪影过渡")).toBeTruthy());

    expect(screen.queryByTestId("transition-save-variant-shadow_pass")).toBeNull();
    expect(screen.queryByTestId("transition-variants")).toBeNull();
  });
});

describe("TransitionProposalsPanel — multi-round memory (V0.2 §15)", () => {
  afterEach(cleanup);

  const llmReading = () =>
    proposalPayload({
      id: "shadow_pass",
      label: "剪影过渡",
      narrative: "主体化作剪影，光替它完成转场。",
      origin: "llm",
      operations: [
        { kind: "camera_preset", rationale: "切点前推近", preset_id: "push_in", camera_id: "cam1" },
      ],
    });

  function renderPanel(fetchMock: ReturnType<typeof vi.fn>) {
    vi.stubGlobal("fetch", fetchMock);
    return render(
      <TransitionProposalsPanel sceneScript={script()} currentShotId="s1" onChange={vi.fn()} />,
    );
  }

  it("reserves an applied reading for the next round", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, proposals: [llmReading()], narrative_source: "rules" }),
    });
    renderPanel(fetchMock);
    fireEvent.click(screen.getByTestId("transition-proposals-propose"));
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => expect(screen.getByText("剪影过渡")).toBeTruthy());

    fireEvent.click(screen.getByTestId("transition-apply-shadow_pass"));

    // The applied reading leaves the picker (its effect is in the script).
    expect(screen.queryByText("剪影过渡")).toBeNull();
    // And it rides along as excluded on the next fetch (call 2).
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const body = JSON.parse(
      (fetchMock.mock.calls[1][1] as RequestInit).body as string,
    );
    expect(body.exclude_reading_ids).toEqual(["shadow_pass"]);
  });

  it("reserves a dismissed reading and hides it immediately", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, proposals: [llmReading()], narrative_source: "rules" }),
    });
    renderPanel(fetchMock);
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => expect(screen.getByText("剪影过渡")).toBeTruthy());

    fireEvent.click(screen.getByTestId("transition-dismiss-shadow_pass"));

    expect(screen.queryByText("剪影过渡")).toBeNull();
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const body = JSON.parse(
      (fetchMock.mock.calls[1][1] as RequestInit).body as string,
    );
    expect(body.exclude_reading_ids).toEqual(["shadow_pass"]);
  });

  it("never offers a dismiss affordance on the rule catalogue's readings", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          proposals: [proposalPayload({ id: "sound_bridge", label: "声音桥（有意保留）", operations: [] })],
          narrative_source: "rules",
        }),
      }),
    );
    render(
      <TransitionProposalsPanel sceneScript={script()} currentShotId="s1" onChange={vi.fn()} />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => expect(screen.getByText("声音桥（有意保留）")).toBeTruthy());

    // The rule catalogue is the honest baseline, not a suggestion to dismiss.
    expect(screen.queryByTestId("transition-dismiss-sound_bridge")).toBeNull();
  });
});

describe("TransitionProposalsPanel — LLM-proposed readings (V0.2 §15 deepening)", () => {
  afterEach(cleanup);

  it("sends the propose flag only when the author opts in", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, proposals: [proposalPayload()], narrative_source: "rules" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <TransitionProposalsPanel sceneScript={script()} currentShotId="s1" onChange={vi.fn()} />,
    );

    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(
      JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string).propose_readings,
    ).toBe(false);

    fireEvent.click(screen.getByTestId("transition-proposals-propose"));
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(
      JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string).propose_readings,
    ).toBe(true);
  });

  it("marks machine-invented readings so the author knows what to distrust", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          proposals: [
            proposalPayload({ id: "sound_bridge", label: "声音桥（有意保留）", operations: [] }),
            proposalPayload({
              id: "shadow_pass",
              label: "剪影过渡",
              narrative: "主体化作剪影，光替它完成转场。",
              origin: "llm",
              operations: [
                { kind: "camera_preset", rationale: "切点前推近，让光接管画面", preset_id: "push_in", camera_id: "cam1" },
              ],
            }),
          ],
          narrative_source: "rules",
          warnings: ["LLM 读法 bad 被拒绝：操作校验失败：未知相机预设 'nope'"],
        }),
      }),
    );
    render(
      <TransitionProposalsPanel sceneScript={script()} currentShotId="s1" onChange={vi.fn()} />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));

    await waitFor(() => {
      expect(screen.getByText("剪影过渡")).toBeTruthy();
    });
    // The badge is on the machine's reading, never on the rule catalogue's.
    expect(screen.getByTestId("transition-origin-shadow_pass").textContent).toContain("LLM 补充");
    expect(screen.queryByTestId("transition-origin-sound_bridge")).toBeNull();
    // A dropped machine reading is reported, not silent.
    expect(screen.getByText(/被拒绝/)).toBeTruthy();
  });
});

describe("TransitionProposalsPanel — the LLM narrative layer (V0.2 §6.2/§15)", () => {
  afterEach(cleanup);

  it("sends the polish flag only when the author opts in", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, proposals: [proposalPayload()], narrative_source: "llm" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <TransitionProposalsPanel sceneScript={script()} currentShotId="s1" onChange={vi.fn()} />,
    );

    // Default: no LLM traffic.
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(
      JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string).polish_narratives,
    ).toBe(false);

    fireEvent.click(screen.getByTestId("transition-proposals-polish"));
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(
      JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string).polish_narratives,
    ).toBe(true);
  });

  it("shows that the narratives are LLM-explained (operations unchanged)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          proposals: [proposalPayload({ id: "sound_bridge", label: "声音桥（有意保留）", narrative: "声音先到，画面后到——把反应留给新画面。", operations: [] })],
          narrative_source: "llm",
          warnings: [],
        }),
      }),
    );
    render(
      <TransitionProposalsPanel sceneScript={script()} currentShotId="s1" onChange={vi.fn()} />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));

    await waitFor(() => {
      expect(screen.getByTestId("transition-proposals-llm")).toBeTruthy();
    });
    expect(screen.getByText("声音先到，画面后到——把反应留给新画面。")).toBeTruthy();
  });

  it("surfaces the degradation reason when the LLM is unavailable", async () => {    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          proposals: [proposalPayload()],
          narrative_source: "rules",
          warnings: ["LLM 未配置（LLM_API_KEY / LLM_BASE_URL），保留规则解释。"],
        }),
      }),
    );
    render(
      <TransitionProposalsPanel sceneScript={script()} currentShotId="s1" onChange={vi.fn()} />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));

    await waitFor(() => {
      expect(screen.getByText(/保留规则解释/)).toBeTruthy();
    });
    // The readings themselves still arrive — degradation is not failure.
    expect(screen.getByText("连续运动")).toBeTruthy();
    expect(screen.queryByTestId("transition-proposals-llm")).toBeNull();
  });
});

describe("TransitionProposalsPanel — the sound-bridge family (V0.2 §15)", () => {
  const speechSegments = [
    { segment_id: "s0", character_id: "lin", text: "你终于来了", start_time: 1.0, end_time: 3.0 },
  ];

  afterEach(cleanup);

  it("forwards the measured speech segments so pause readings are priced", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, proposals: [proposalPayload()] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <TransitionProposalsPanel
        sceneScript={script()}
        currentShotId="s1"
        onChange={vi.fn()}
        speechSegments={speechSegments}
      />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    // The picker must not re-estimate: the mouth timeline rides on.
    expect(body.segments).toEqual(speechSegments);
  });

  it("jumps to the readings when an advisory points at the pair", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, proposals: [proposalPayload()] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <TransitionProposalsPanel
        sceneScript={script()}
        currentShotId="s1"
        onChange={vi.fn()}
        autoFetchShotId="s1"
      />,
    );

    // One click in the lip-sync panel becomes readings on screen — the pair
    // is the shot the advisory named plus its successor.
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.shot_a_id).toBe("s1");
    expect(body.shot_b_id).toBe("s2");
  });

  it("does not auto-fetch for a shot that is not the current pair", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, proposals: [proposalPayload()] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <TransitionProposalsPanel
        sceneScript={script()}
        currentShotId="s2"
        onChange={vi.fn()}
        autoFetchShotId="s1"
      />,
    );

    // No manual click either: nothing fetches until the pair matches.
    await Promise.resolve();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders the six readings including the two new sound-bridge ones", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          proposals: [
            proposalPayload(),
            proposalPayload({ id: "gaze_closeup", label: "视线/特写切换" }),
            proposalPayload({ id: "sound_bridge", label: "声音桥（有意保留）", operations: [] }),
            proposalPayload({
              id: "cut_after_line",
              label: "说完再切",
              operations: [
                { kind: "cut", rationale: "把剪切点移到这句结束处", at_seconds: 3.0, shot_id: "s2" },
              ],
            }),
            proposalPayload({ id: "time_jump", label: "时间/空间跳跃" }),
            proposalPayload({
              id: "angle_switch",
              label: "视角切换",
              operations: [{ kind: "camera_place", rationale: "放新机位", camera_id: "cam1" }],
            }),
          ],
        }),
      }),
    );
    render(
      <TransitionProposalsPanel sceneScript={script()} currentShotId="s1" onChange={vi.fn()} />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));

    await waitFor(() => {
      expect(screen.getByText("声音桥（有意保留）")).toBeTruthy();
    });
    expect(screen.getByText("说完再切")).toBeTruthy();
    expect(screen.getByText(/六个读法由系统提出/)).toBeTruthy();
    // The zero-operation reading says so instead of showing an empty list.
    expect(screen.getByTestId("transition-noop-sound_bridge").textContent).toContain(
      "此读法无需修改",
    );
  });

  it("applying the keep-the-cut reading records the entry and changes nothing else", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          proposals: [
            proposalPayload({ id: "sound_bridge", label: "声音桥（有意保留）", operations: [] }),
          ],
        }),
      }),
    );
    const onChange = vi.fn();
    render(
      <TransitionProposalsPanel sceneScript={script()} currentShotId="s1" onChange={onChange} />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => {
      expect(screen.getByTestId("transition-apply-sound_bridge")).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId("transition-apply-sound_bridge"));

    // Nothing STRUCTURAL changed — a sound bridge is the cut you already
    // have — but the relation is now declared (§13 第 5 问), so onChange
    // fires exactly once and the ONLY difference is the recorded reading.
    expect(onChange).toHaveBeenCalledTimes(1);
    const before = script();
    const after = onChange.mock.calls[0][0] as SceneScriptRoot;
    const declared = after.shots.find((shot) => shot.id === "s2");
    expect(declared?.transition_intent).toBe("sound_bridge");
    const stripped = (root: SceneScriptRoot): SceneScriptRoot => ({
      ...root,
      shots: root.shots.map((shot) => {
        const { transition_intent: _ignored, ...rest } = shot;
        return rest;
      }),
    });
    expect(stripped(after)).toEqual(stripped(before));
    expect(screen.getByTestId("transition-proposals-note").textContent).toContain(
      "此读法无需修改",
    );
  });
});


describe("TransitionProposalsPanel — declared entry reading (V0.2 §13 第 5 问)", () => {
  function fetchReturning(body: unknown) {
    return vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => body });
  }

  it("applying a reading records it as the shot's entry", async () => {
    vi.stubGlobal(
      "fetch",
      fetchReturning({ success: true, proposals: [proposalPayload()] }),
    );
    const onChange = vi.fn();
    render(
      <TransitionProposalsPanel
        sceneScript={script()}
        currentShotId="s1"
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => {
      expect(screen.getByTestId("transition-apply-continuous_motion")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("transition-apply-continuous_motion"));

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    // The relation outlives the click: "哪一镜以何种读法接入" now has an answer
    // on the script itself (and therefore on the shot strip).
    expect(next.shots.find((shot) => shot.id === "s2")?.transition_intent).toBe(
      "continuous_motion",
    );
  });

  it("records the reading WITHOUT replaying its operations", async () => {
    vi.stubGlobal(
      "fetch",
      fetchReturning({ success: true, proposals: [proposalPayload()] }),
    );
    const onChange = vi.fn();
    render(
      <TransitionProposalsPanel
        sceneScript={script()}
        currentShotId="s1"
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => {
      expect(screen.getByTestId("transition-intent-continuous_motion")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("transition-intent-continuous_motion"));

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.shots.find((shot) => shot.id === "s2")?.transition_intent).toBe(
      "continuous_motion",
    );
    // No keyframes were authored: the declaration is the whole edit.
    expect(next.characters[0].keyframes).toHaveLength(1);
  });

  it("says so when a declared reading no longer holds for this pair", async () => {
    vi.stubGlobal(
      "fetch",
      fetchReturning({
        success: true,
        proposals: [proposalPayload({ feasible: false, infeasible_reason: "没有可用的摄影机" })],
        intent_audit: {
          declared: "continuous_motion",
          holds: false,
          label: "连续运动",
          reason: "登记的「连续运动」在当前场景里不再成立：没有可用的摄影机。",
          remedy: "改选一条可行的读法。",
        },
      }),
    );
    render(
      <TransitionProposalsPanel
        sceneScript={script()}
        currentShotId="s1"
        onChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));

    const audit = await waitFor(() => {
      const line = screen.getByTestId("transition-intent-audit");
      expect(line.getAttribute("data-holds")).toBe("false");
      return line;
    });
    expect(audit.textContent).toContain("已不成立");
    expect(audit.textContent).toContain("改选一条可行的读法");
  });

  it("confirms a declared reading that still holds", async () => {
    vi.stubGlobal(
      "fetch",
      fetchReturning({
        success: true,
        proposals: [proposalPayload()],
        intent_audit: {
          declared: "continuous_motion",
          holds: true,
          label: "连续运动",
          reason: null,
          remedy: null,
        },
      }),
    );
    render(
      <TransitionProposalsPanel
        sceneScript={script()}
        currentShotId="s1"
        onChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));

    const audit = await waitFor(() => {
      const line = screen.getByTestId("transition-intent-audit");
      expect(line.getAttribute("data-holds")).toBe("true");
      return line;
    });
    expect(audit.textContent).toContain("仍然成立");
  });

  it("stays silent when nothing is declared (a first shot has no entry)", async () => {
    vi.stubGlobal(
      "fetch",
      fetchReturning({
        success: true,
        proposals: [proposalPayload()],
        intent_audit: { declared: null, holds: null, label: null, reason: null, remedy: null },
      }),
    );
    render(
      <TransitionProposalsPanel
        sceneScript={script()}
        currentShotId="s1"
        onChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("transition-proposals-fetch"));
    await waitFor(() => {
      expect(screen.getByTestId("transition-apply-continuous_motion")).toBeTruthy();
    });
    expect(screen.queryByTestId("transition-intent-audit")).toBeNull();
  });
});
