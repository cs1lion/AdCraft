/**
 * SceneScript3DEditor tests (inspector + save bar).
 *
 * The r3f preview is mocked: this layer's contract is the inspector plumbing
 * — selection -> fields, field/commit -> edit-model writes -> onChange, and
 * the save/revert bar. The preview's own drag math lives in
 * sceneScriptEditModel.test.ts and sceneScriptAxes.test.ts.
 */

import { cleanup, fireEvent, render, screen, act, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import type { SceneScriptRoot } from "../../../types/scene-script";
import type { SceneObjectRef } from "./sceneScriptEditModel";

const previewProps: {
  editMode?: boolean;
  selectedObject?: SceneObjectRef | null;
  placementMode?: boolean;
  onSelect?: (ref: SceneObjectRef | null) => void;
  onDragCommit?: (ref: SceneObjectRef, position: [number, number, number]) => void;
  onPlacementCommit?: (placement: {
    position: [number, number, number];
    lookAt: [number, number, number];
  }) => void;
} = {};

vi.mock("./SceneScript3DPreview.tsx", () => ({
  SceneScript3DPreview: (props: Record<string, unknown>) => {
    Object.assign(previewProps, props);
    return <div data-testid="preview-mock" />;
  },
}));

import { SceneScript3DEditor } from "./SceneScript3DEditor.tsx";

function sceneScript(): SceneScriptRoot {
  return {
    scene: { name: "地下研究所 B2", environment: "indoor", lighting: "cool", duration: 6, frame_rate: 30 },
    characters: [
      {
        id: "char_a",
        type: "lowpoly_human",
        appearance: { color: "#E74C3C", height: 1.7, scale: 1 },
        keyframes: [
          { frame: 0, position: [0, 0, 0], rotation_y: 90, action: "stand" },
          { frame: 60, position: [2, 2, 0], rotation_y: 90, action: "walk" },
        ],
      },
    ],
    props: [{ id: "crate1", type: "crate", position: [1, 1, 0], scale: 1, rotation_y: 0 }],
    environment: [{ id: "wall1", type: "wall", position: [0, 3, 0], scale: 1, rotation_y: 0 }],
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

function renderEditor(overrides: Partial<Parameters<typeof SceneScript3DEditor>[0]> = {}) {
  const onChange = vi.fn();
  const onSave = vi.fn();
  const onRevert = vi.fn();
  const utils = render(
    <SceneScript3DEditor
      sceneScript={sceneScript()}
      onChange={onChange}
      onSave={onSave}
      onRevert={onRevert}
      {...overrides}
    />,
  );
  return { onChange, onSave, onRevert, ...utils };
}

function selectObject(ref: SceneObjectRef) {
  act(() => {
    previewProps.onSelect?.(ref);
  });
}

/**
 * The inspector panel's number fields, in document order. The director
 * command bar renders its own duration spinbutton, so tests target the
 * inspector panel explicitly rather than the global spinbutton set.
 */
function inspectorSpinbuttons(): HTMLInputElement[] {
  const panel = document.querySelector(".scene-script-3d-editor__panel");
  return Array.from(panel?.querySelectorAll("input[type=number]") ?? []);
}

afterEach(cleanup);

describe("SceneScript3DEditor", () => {
  it("applies a director command end-to-end: local preview then gate round trip", async () => {
    const { onChange } = renderEditor();
    // The director gate client is mocked so no network call is attempted; the
    // mock rejects so the bar keeps its optimistic preview and reports it.
    const directorClient = await import("./directorOperationsClient.ts");
    vi.spyOn(directorClient, "applyDirectorMotion").mockResolvedValue({
      ok: false,
      error: "gate offline (test)",
    });

    // 1. Pick the camera target + a preset in the bar (fireEvent, like the
    // rest of this suite — user-event is not a dependency).
    fireEvent.change(screen.getByLabelText("导演指令对象"), { target: { value: "cam1" } });
    const presetSelect = screen.getByLabelText("导演指令");
    fireEvent.change(presetSelect, { target: { value: "push_in" } });
    fireEvent.click(screen.getByTestId("scene-script-3d-director-submit"));

    // 2. The bar applied the optimistic preview exactly once before the gate.
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    const optimistic = onChange.mock.calls[0][0] as SceneScriptRoot;
    // push_in over 60 frames writes >= 3 sampled camera keyframes including frame 60.
    const cameraKeyframes = optimistic.cameras[0].keyframes;
    expect(cameraKeyframes.length).toBeGreaterThanOrEqual(3);
    expect(cameraKeyframes.map((k) => k.frame)).toContain(60);

    // 3. The status line reports the optimistic-keep (gate rejected in mock).
    const status = screen.getByTestId("scene-script-3d-director-status");
    expect(status.textContent).toContain("已预览");
  });

  it("adopts the gate-applied script when the round trip succeeds", async () => {
    const { onChange } = renderEditor();
    const directorClient = await import("./directorOperationsClient.ts");
    // A gate that PASSES returns a distinct, authoritative script the bar must
    // adopt as its second (and final) write — preview and persisted state in
    // lockstep.
    const gateScript: SceneScriptRoot = {
      ...sceneScript(),
      scene: { ...sceneScript().scene, name: "gate-applied" },
    };
    vi.spyOn(directorClient, "applyDirectorMotion").mockResolvedValue({
      ok: true,
      appliedSceneScript: gateScript,
      operations: [],
    });

    fireEvent.change(screen.getByLabelText("导演指令对象"), { target: { value: "cam1" } });
    fireEvent.change(screen.getByLabelText("导演指令"), { target: { value: "orbit_left" } });
    fireEvent.click(screen.getByTestId("scene-script-3d-director-submit"));

    // Two writes: optimistic preview, then the gate's post-apply script.
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2));
    const adopted = onChange.mock.calls[1][0] as SceneScriptRoot;
    expect(adopted.scene.name).toBe("gate-applied");
    const status = screen.getByTestId("scene-script-3d-director-status");
    expect(status.textContent).toContain("已过闸门");
  });
  // Restore the module-level spy between tests.
  afterEach(() => {
    vi.restoreAllMocks();
  });
  it("passes editMode + callbacks to the preview", () => {
    renderEditor();
    expect(previewProps.editMode).toBe(true);
    expect(typeof previewProps.onSelect).toBe("function");
    expect(typeof previewProps.onDragCommit).toBe("function");
  });

  it("shows the empty hint until something is selected", () => {
    renderEditor();
    expect(screen.getByText(/点击角色、道具或相机/)).toBeTruthy();
    expect(previewProps.selectedObject ?? null).toBeNull();
  });

  it("shows character fields after selection, with keyframe info", () => {
    renderEditor();
    selectObject({ kind: "character", id: "char_a" });
    expect(screen.getByText("角色")).toBeTruthy();
    expect(screen.getByText(/2 个关键帧/)).toBeTruthy();
    // Position x/y/z fields exist with the frame-0 values.
    // The director command bar adds its own duration spinbutton, so scope to
    // the inspector panel (its x/y/z fields, not the command bar's).
    const inputs = inspectorSpinbuttons();
    const values = inputs.map((input) => input.value);
    expect(values).toContain("0"); // position x at frame 0
  });

  it("writes through the edit model when a position field changes", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "character", id: "char_a" });
    // xInput is the first inspector spinbutton (character x).
    const xInput = inspectorSpinbuttons()[0] as HTMLInputElement;
    fireEvent.focus(xInput);
    fireEvent.change(xInput, { target: { value: "3.5" } });
    fireEvent.blur(xInput);

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    // Frame 0's keyframe moved in x; the frame-60 keyframe is untouched.
    expect(next.characters[0].keyframes[0].position[0]).toBe(3.5);
    expect(next.characters[0].keyframes[1].position[0]).toBe(2);
  });

  it("writes prop scale and rotation through the static-object path", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "prop", id: "crate1" });
    // x, y, z, rotation, scale -> index 4
    const scaleInput = inspectorSpinbuttons()[4] as HTMLInputElement;
    fireEvent.focus(scaleInput);
    fireEvent.change(scaleInput, { target: { value: "2.5" } });
    fireEvent.blur(scaleInput);

    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.props[0].scale).toBe(2.5);
  });

  it("commits a preview drag through moveSceneObjectAtFrame", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "prop", id: "crate1" });
    previewProps.onDragCommit?.({ kind: "prop", id: "crate1" }, [4, 5, 0]);

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.props[0].position).toEqual([4, 5, 0]);
  });

  it("declares the wardrobe palette through the edit model (V0.2 §5)", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "character", id: "char_a" });
    const swatches = screen.getAllByLabelText(
      /声明服装色板第 \d+ 色/,
    ) as HTMLInputElement[];
    expect(swatches).toHaveLength(2);
    // jsdom cannot paint a colour input; the value is what matters.
    fireEvent.change(swatches[0], { target: { value: "#2c3e50" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.characters[0].appearance.palette).toEqual(["#2C3E50"]);
  });

  it("clears the wardrobe declaration", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "character", id: "char_a" });
    fireEvent.click(screen.getByRole("button", { name: "清除" }));
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.characters[0].appearance.palette ?? null).toBeNull();
  });

  it("shows camera look-at and shot-type controls", () => {
    renderEditor();
    selectObject({ kind: "camera", id: "cam1" });
    expect(screen.getByText("机位")).toBeTruthy();
    expect(screen.getByText("注视点 (look_at)")).toBeTruthy();
    // The camera inspector has several selects now (shot type + motion
    // preset): query the field by its label, not by role.
    const select = screen.getByRole("combobox", { name: /景别/ }) as HTMLSelectElement
      ?? document.querySelector("select") as HTMLSelectElement;
    expect(select.value).toBe("wide");
  });

  it("gates save/revert on the dirty flag", () => {
    const clean = renderEditor({ dirty: false });
    expect((clean.getByText("保存场景") as HTMLButtonElement).disabled).toBe(true);
    expect((clean.getByText("撤销修改") as HTMLButtonElement).disabled).toBe(true);

    cleanup();
    const dirty = renderEditor({ dirty: true, saving: false });
    expect((dirty.getByText("保存场景") as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(dirty.getByText("保存场景"));
    fireEvent.click(dirty.getByText("撤销修改"));
    expect(dirty.onSave).toHaveBeenCalledTimes(1);
    expect(dirty.onRevert).toHaveBeenCalledTimes(1);
  });

  it("shows the saving label and error", () => {
    renderEditor({ dirty: true, saving: true, error: "版本冲突" });
    expect(screen.getByText("保存中…")).toBeTruthy();
    expect(screen.getByText("版本冲突")).toBeTruthy();
  });
});

describe("SceneScript3DEditor camera placement (P2)", () => {
  it("toggles placement mode and passes it to the preview", () => {
    renderEditor();
    expect(previewProps.placementMode ?? false).toBe(false);
    fireEvent.click(screen.getByText("放置相机"));
    expect(previewProps.placementMode).toBe(true);
    expect(screen.getByText(/点击两次放置一个新相机/)).toBeTruthy();
    fireEvent.click(screen.getByText("取消放置"));
    expect(previewProps.placementMode).toBe(false);
  });

  it("spawns a new camera + shot when nothing is selected", () => {
    const { onChange } = renderEditor();
    fireEvent.click(screen.getByText("放置相机"));
    previewProps.onPlacementCommit?.({
      position: [2.5, -3.5, 0],
      lookAt: [0, 0, 0],
    });

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.cameras).toHaveLength(2);
    const camera = next.cameras[1];
    // Eye-level placement height, not the raw ground z=0.
    expect(camera.keyframes[0].position).toEqual([2.5, -3.5, 1.6]);
    expect(camera.keyframes[0].look_at).toEqual([0, 0, 1.2]);
    // The new shot starts after the existing one and the scene grows to fit.
    const shot = next.shots[1];
    expect(shot.camera).toBe(camera.id);
    expect(shot.start_frame).toBe(180);
    expect(shot.end_frame).toBeLessThanOrEqual(next.scene.duration * next.scene.frame_rate);
  });

  it("retargets the selected camera (keeping its height) during placement", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "camera", id: "cam1" });
    fireEvent.click(screen.getByText("放置相机"));
    previewProps.onPlacementCommit?.({
      position: [1, -2, 0],
      lookAt: [0.5, 0.5, 0],
    });

    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.cameras).toHaveLength(1); // no new camera
    const keyframe = next.cameras[0].keyframes[0];
    // Ground x/y replaced; the camera's own height (5) preserved.
    expect(keyframe.position[0]).toBe(1);
    expect(keyframe.position[1]).toBe(-2);
    expect(keyframe.position[2]).toBe(5);
    // look_at ground moved, its z preserved.
    expect(keyframe.look_at[0]).toBe(0.5);
    expect(keyframe.look_at[1]).toBe(0.5);
    expect(keyframe.look_at[2]).toBe(1);
  });

  it("captures the selected character's interpolated pose as a keyframe", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "character", id: "char_a" });
    fireEvent.click(screen.getByText("捕获关键帧"));

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.characters[0].keyframes.map((keyframe) => keyframe.frame)).toEqual([0, 60]);
  });

  it("shows the bound character's reference image (the lock is visible)", () => {
    const bound = sceneScript();
    bound.characters[0].character_asset_id = "asset-1";
    render(
      <SceneScript3DEditor
        sceneScript={bound}
        onChange={vi.fn()}
        onSave={vi.fn()}
        onRevert={vi.fn()}
        characterAssets={[{ asset_id: "asset-1", display_name: "林澈设定", preview_url: "/media/char-lin.jpg" }]}
      />,
    );
    act(() => {
      // Select the character so the inspector renders.
      previewProps.onSelect?.({ kind: "character", id: "char_a" });
    });
    const reference = screen.getByTestId("character-reference");
    expect(reference.querySelector("img")?.getAttribute("src")).toBe("/media/char-lin.jpg");
    expect(reference.textContent).toContain("林澈设定");
  });

  it("shows no reference for an unbound character", () => {
    renderEditor();
    selectObject({ kind: "character", id: "char_a" });
    expect(screen.queryByTestId("character-reference")).toBeNull();
  });

  it("survives a bound asset whose preview is missing", () => {
    const bound = sceneScript();
    bound.characters[0].character_asset_id = "asset-1";
    render(
      <SceneScript3DEditor
        sceneScript={bound}
        onChange={vi.fn()}
        onSave={vi.fn()}
        onRevert={vi.fn()}
        characterAssets={[{ asset_id: "asset-1", display_name: "林澈设定", preview_url: null }]}
      />,
    );
    act(() => {
      previewProps.onSelect?.({ kind: "character", id: "char_a" });
    });
    const reference = screen.getByTestId("character-reference");
    expect(reference.querySelector("img")).toBeNull();
    expect(reference.textContent).toContain("无参考图");
  });

  it("disables capture when nothing is selected", () => {
    renderEditor();
    expect((screen.getByText("捕获关键帧") as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("SceneScript3DEditor consistency gate (live mirror)", () => {
  it("shows no banner for a clean single-shot scene", () => {
    renderEditor();
    expect(screen.queryByLabelText("场景一致性提示")).toBeNull();
  });

  it("warns about unbound characters once the scene has multiple shots", () => {
    const multiShot = sceneScript();
    multiShot.shots = [
      { id: "s1", camera: "cam1", start_frame: 0, end_frame: 90, description: "wide" },
      { id: "s2", camera: "cam1", start_frame: 91, end_frame: 179, description: "medium" },
    ];
    render(
      <SceneScript3DEditor
        sceneScript={multiShot}
        onChange={vi.fn()}
        onSave={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    const banner = screen.getByLabelText("场景一致性提示");
    expect(banner.textContent).toContain("没有绑定角色资产");
  });

  it("clicking a character warning selects that character for binding", () => {
    const multiShot = sceneScript();
    multiShot.shots = [
      { id: "s1", camera: "cam1", start_frame: 0, end_frame: 90 },
      { id: "s2", camera: "cam1", start_frame: 91, end_frame: 179 },
    ];
    render(
      <SceneScript3DEditor
        sceneScript={multiShot}
        onChange={vi.fn()}
        onSave={vi.fn()}
        onRevert={vi.fn()}
        characterAssets={[{ asset_id: "asset-1", display_name: "林澈设定", preview_url: "/media/char-lin.jpg" }]}
      />,
    );
    act(() => {
      fireEvent.click(screen.getByText(/没有绑定角色资产/));
    });
    // The inspector now shows the binding dropdown for the selected character.
    expect(screen.getByLabelText("角色资产绑定")).toBeTruthy();
  });

  it("binding a character asset writes character_asset_id", () => {
    const multiShot = sceneScript();
    multiShot.shots = [
      { id: "s1", camera: "cam1", start_frame: 0, end_frame: 90 },
      { id: "s2", camera: "cam1", start_frame: 91, end_frame: 179 },
    ];
    const onChange = vi.fn();
    render(
      <SceneScript3DEditor
        sceneScript={multiShot}
        onChange={onChange}
        onSave={vi.fn()}
        onRevert={vi.fn()}
        characterAssets={[{ asset_id: "asset-1", display_name: "林澈设定", preview_url: "/media/char-lin.jpg" }]}
      />,
    );
    act(() => {
      fireEvent.click(screen.getByText(/没有绑定角色资产/));
    });
    fireEvent.change(screen.getByLabelText("角色资产绑定"), {
      target: { value: "asset-1" },
    });
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.characters[0].character_asset_id).toBe("asset-1");
    // The warning disappears once the character is bound (fresh render: the
    // first editor is unmounted so its banner cannot satisfy the query).
    cleanup();
    render(
      <SceneScript3DEditor
        sceneScript={next}
        onChange={vi.fn()}
        onSave={vi.fn()}
        onRevert={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText("场景一致性提示")).toBeNull();
  });
});

describe("SceneScript3DEditor camera motion presets", () => {
  it("applies the selected preset from the current frame", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "camera", id: "cam1" });

    // 2s at 30fps = 60 frames from frame 0.
    fireEvent.click(screen.getByTestId("camera-preset-apply-cam1"));

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    const keys = next.cameras[0].keyframes;
    // push_in sampled at 15-frame steps: 0, 15, 30, 45, 60.
    expect(keys.map((key) => key.frame)).toEqual([0, 15, 30, 45, 60]);
    // The camera closed the distance to its look-at point.
    const radius = (key: (typeof keys)[number]) =>
      Math.hypot(
        key.position[0] - key.look_at![0],
        key.position[1] - key.look_at![1],
        key.position[2] - key.look_at![2],
      );
    expect(radius(keys[keys.length - 1])).toBeLessThan(radius(keys[0]));
  });

  it("honors a custom duration", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "camera", id: "cam1" });

    fireEvent.change(screen.getByLabelText("为相机 cam1 设置运镜时长 (s)"), {
      target: { value: "1" },
    });
    fireEvent.click(screen.getByTestId("camera-preset-apply-cam1"));

    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    const frames = next.cameras[0].keyframes.map((key) => key.frame);
    expect(frames[frames.length - 1]).toBe(30);
  });
});

describe("SceneScript3DEditor character motion presets", () => {
  it("walks the selected character toward the chosen target", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "character", id: "char_a" });

    fireEvent.change(screen.getByLabelText("为角色 char_a 选择动作目标"), {
      target: { value: "crate1" },
    });
    fireEvent.click(screen.getByTestId("character-preset-apply-char_a"));

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    const keys = next.characters[0].keyframes;
    const landing = keys[keys.length - 1];
    // The crate sits at [1, 1, 0]; the character walked to it and stands.
    expect(landing.position[0]).toBeCloseTo(1, 5);
    expect(landing.position[1]).toBeCloseTo(1, 5);
    expect(landing.action).toBe("stand");
    // Facing rides along: the character looks where it walks.
    expect(landing.rotation_y).toBeGreaterThan(0);
    expect(landing.rotation_y).toBeLessThan(90);
  });

  it("falls back to one metre along the character's facing without a target", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "character", id: "char_a" });

    fireEvent.click(screen.getByTestId("character-preset-apply-char_a"));

    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    const landing = next.characters[0].keyframes[next.characters[0].keyframes.length - 1];
    // rotation_y is 90 at frame 0 -> facing +X -> the fallback is 1m right.
    expect(landing.position[0]).toBeCloseTo(1, 5);
    expect(landing.position[1]).toBeCloseTo(0, 5);
  });

  it("approach honors its stop distance and only shows that field for approach", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "character", id: "char_a" });
    // walk_to has no stop-distance input.
    expect(screen.queryByLabelText("为角色 char_a 设置靠近停止距离 (m)")).toBeNull();

    fireEvent.change(screen.getByLabelText("为角色 char_a 选择动作预设"), {
      target: { value: "approach" },
    });
    const stop = screen.getByLabelText("为角色 char_a 设置靠近停止距离 (m)") as HTMLInputElement;
    expect(stop.value).toBe("1.2");

    fireEvent.change(screen.getByLabelText("为角色 char_a 选择动作目标"), {
      target: { value: "crate1" },
    });
    fireEvent.change(stop, { target: { value: "0.5" } });
    fireEvent.click(screen.getByTestId("character-preset-apply-char_a"));

    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    const landing = next.characters[0].keyframes[next.characters[0].keyframes.length - 1];
    const gap = Math.hypot(landing.position[0] - 1, landing.position[1] - 1);
    expect(gap).toBeCloseTo(0.5, 2);
  });

  it("mark_talk writes a talk action at the current frame", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "character", id: "char_a" });

    fireEvent.change(screen.getByLabelText("为角色 char_a 选择动作预设"), {
      target: { value: "mark_talk" },
    });
    // mark_talk needs no target.
    expect(screen.queryByLabelText("为角色 char_a 选择动作目标")).toBeNull();

    fireEvent.click(screen.getByTestId("character-preset-apply-char_a"));

    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.characters[0].keyframes[0].action).toBe("talk");
  });

  it("reports the locked speech layer when a walk crosses a spoken line", () => {
    // The character speaks across frames 30–59 (lip-sync's talk window); a
    // 2-second walk applied at frame 30 must keep the mouth open AND say so.
    const speaking = sceneScript();
    speaking.characters[0].keyframes = [
      { frame: 0, position: [0, 0, 0], rotation_y: 90, action: "stand" },
      { frame: 30, position: [0, 0, 0], rotation_y: 90, action: "talk" },
      { frame: 59, position: [0, 0, 0], rotation_y: 90, action: "talk" },
      { frame: 60, position: [0, 0, 0], rotation_y: 90, action: "stand" },
      { frame: 200, position: [0, 0, 0], rotation_y: 90, action: "stand" },
    ];
    const { onChange } = renderEditor({ sceneScript: speaking });
    selectObject({ kind: "character", id: "char_a" });

    fireEvent.click(screen.getByTestId("character-preset-apply-char_a"));

    // The note names the lock — the author learns the mouth was preserved.
    expect(screen.getByTestId("character-preset-note-char_a").textContent).toContain("唇形已保留");
    // And the applied script proves it: the sampled speaking frames still talk
    // while the body moves.
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    const window = next.characters[0].keyframes.filter(
      (key) => key.frame >= 30 && key.frame <= 59,
    );
    expect(window.length).toBeGreaterThan(0);
    expect(window.every((key) => key.action === "talk")).toBe(true);
  });
});

describe("SceneScript3DEditor blocking continuity banner", () => {
  it("warns about a facing flip across the cut and selects the character", () => {
    const scene = sceneScript();
    // The B-side pose is authored at the cut with no turn: a 1-frame flip.
    scene.characters[0].keyframes = [
      { frame: 0, position: [0, 0, 0], rotation_y: 0, action: "stand" },
      { frame: 89, position: [0, 0, 0], rotation_y: 0, action: "stand" },
      { frame: 90, position: [0, 0, 0], rotation_y: 180, action: "stand" },
    ];
    scene.shots = [
      { id: "s1", camera: "cam1", start_frame: 0, end_frame: 89, description: "w" },
      { id: "s2", camera: "cam1", start_frame: 90, end_frame: 179, description: "m" },
    ];
    render(
      <SceneScript3DEditor
        sceneScript={scene}
        onChange={vi.fn()}
        onSave={vi.fn()}
        onRevert={vi.fn()}
      />,
    );

    const banner = screen.getByLabelText("场景一致性提示");
    expect(banner.textContent).toContain("两个镜头之间没有转身");

    // Clicking the advisory selects the character: the inspector (with its
    // motion presets) is the remedy surface.
    act(() => {
      fireEvent.click(screen.getByText(/两个镜头之间没有转身/));
    });
    expect(screen.getByText("角色")).toBeTruthy();
    expect(screen.getByLabelText("角色资产绑定")).toBeTruthy();
  });

  it("stays silent for a scene whose poses carry across the cuts", () => {
    const scene = sceneScript();
    scene.characters[0].keyframes = [
      { frame: 0, position: [0, 0, 0], rotation_y: 90, action: "stand" },
      { frame: 179, position: [0, 0, 0], rotation_y: 90, action: "stand" },
    ];
    render(
      <SceneScript3DEditor
        sceneScript={scene}
        onChange={vi.fn()}
        onSave={vi.fn()}
        onRevert={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText("场景一致性提示")).toBeNull();
  });
});

describe("SceneScript3DEditor draw-a-path camera motion", () => {
  it("converts a drawn trajectory into constant-speed camera keyframes", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "camera", id: "cam1" });
    fireEvent.click(screen.getByText("画运镜"));
    expect(screen.getByText(/拖动画出轨迹/)).toBeTruthy();

    // A 4m line along +X drawn from the origin.
    act(() => {
      previewProps.onGestureCommit?.([
        [0, 0, 0],
        [4, 0, 0],
      ]);
    });

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    const keys = next.cameras[0].keyframes;
    // 2s at 30fps = 60 frames, sampled every 15: 0/15/30/45/60.
    expect(keys.map((key) => key.frame)).toEqual([0, 15, 30, 45, 60]);
    const xs = keys.map((key) => key.position[0]);
    expect(xs[0]).toBe(0);
    expect(xs[xs.length - 1]).toBe(4);
    // Constant speed along the drawn line.
    expect(xs[1] - xs[0]).toBeCloseTo(1, 6);
    // The authored eye height (5) survives the gesture.
    expect(keys.every((key) => key.position[2] === 5)).toBe(true);
    // The gaze leads the camera along the path.
    expect(keys[1].look_at![0]).toBeGreaterThan(keys[1].position[0]);
    // Gesture mode exits after a commit.
    expect(screen.queryByText(/拖动画出轨迹/)).toBeNull();
  });

  it("explains that a camera must be selected first", () => {
    const { onChange } = renderEditor();
    fireEvent.click(screen.getByText("画运镜"));

    act(() => {
      previewProps.onGestureCommit?.([
        [0, 0, 0],
        [4, 0, 0],
      ]);
    });

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText(/先选择一个相机/)).toBeTruthy();
  });

  it("rejects a click that has no travel", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "camera", id: "cam1" });
    fireEvent.click(screen.getByText("画运镜"));

    act(() => {
      previewProps.onGestureCommit?.([
        [1, 1, 0],
        [1, 1, 0],
      ]);
    });

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText(/没有位移/)).toBeTruthy();
  });
});

describe("SceneScript3DEditor animatic audio (V0.2 §7/§14.9)", () => {
  it("hands the speech track to the preview only when one exists", () => {
    renderEditor();
    expect(previewProps.speechAudioUrl ?? null).toBeNull();

    cleanup();
    render(
      <SceneScript3DEditor
        sceneScript={sceneScript()}
        onChange={vi.fn()}
        onSave={vi.fn()}
        onRevert={vi.fn()}
        speechAudioUrl="/api/v2/assets/bed/content"
      />,
    );
    expect(previewProps.speechAudioUrl).toBe("/api/v2/assets/bed/content");
  });
});

describe("SceneScript3DEditor shot strip (V0.2 §2.2 镜间插入)", () => {
  const twoShotScene = () => {
    const script = sceneScript();
    script.shots = [
      { id: "shot1", camera: "cam1", start_frame: 0, end_frame: 89, description: "wide" },
      { id: "shot2", camera: "cam1", start_frame: 90, end_frame: 179, description: "closeup" },
    ];
    return script;
  };

  it("renders a bar per shot and an insert affordance per gap", () => {
    renderEditor({ sceneScript: twoShotScene() });

    expect(screen.getByTestId("shot-strip")).toBeTruthy();
    expect(screen.getByTitle(/shot1：帧 0–89/)).toBeTruthy();
    expect(screen.getByTitle(/shot2：帧 90–179/)).toBeTruthy();
    expect(screen.getByTestId("shot-strip-insert-shot1")).toBeTruthy();
    expect(screen.getByTestId("shot-strip-insert-shot2")).toBeTruthy();
  });

  it("revoking a declared reading removes the relation and keeps the shot", () => {
    const declared = twoShotScene();
    declared.shots[1].transition_intent = "sound_bridge";
    const { onChange } = renderEditor({ sceneScript: declared });

    expect(screen.getByTestId("shot-strip-intent-shot2")).toBeTruthy();
    fireEvent.click(screen.getByTestId("shot-strip-clear-intent-shot2"));

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    const shot = next.shots.find((entry) => entry.id === "shot2");
    // The declaration goes; the shot itself is untouched (a revoke is not a
    // destructive act, and the copy must not pretend otherwise).
    expect(shot?.transition_intent ?? null).toBeNull();
    expect(shot?.start_frame).toBe(declared.shots[1].start_frame);
    expect(shot?.camera).toBe(declared.shots[1].camera);
  });

  it("inserting after a shot splits its tail into a same-camera continuation", () => {
    const { onChange } = renderEditor({ sceneScript: twoShotScene() });

    fireEvent.click(screen.getByTestId("shot-strip-insert-shot1"));

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    const donor = next.shots.find((shot) => shot.id === "shot1");
    // The scene already owns shot1/shot2, so the insert takes the next free
    // id — find it by position rather than by a hard-coded name.
    const inserted = next.shots.find(
      (shot) => shot.id !== "shot1" && shot.id !== "shot2",
    );
    // The tail moved to the new shot; the camera is unchanged (an insert is
    // a continuation, not a new viewpoint).
    expect(donor?.end_frame).toBe(74);
    expect(inserted?.start_frame).toBe(75);
    expect(inserted?.camera).toBe("cam1");
  });

  it("seeks the playhead when a shot bar is clicked", () => {
    renderEditor({ sceneScript: twoShotScene() });

    fireEvent.click(screen.getByTitle(/shot2：帧 90–179/));

    // The strip's playhead rides the same playback context as the viewport.
    expect(screen.getByTestId("shot-strip-playhead")).toBeTruthy();
  });
});

describe("SceneScript3DEditor held items (V0.2 §5 Continuity State)", () => {
  it("declares a holder from the prop inspector", () => {
    const { onChange } = renderEditor();
    selectObject({ kind: "prop", id: "crate1" });

    const holderSelect = screen.getByLabelText("道具 crate1 的持有者") as HTMLSelectElement;
    expect(holderSelect.value).toBe(""); // unheld by default

    fireEvent.change(holderSelect, { target: { value: "char_a" } });

    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.props[0].held_by).toBe("char_a");
    expect(next.props[0].held_side).toBe("right");
  });

  it("explains the follow once held (the authored position is a rest position)", () => {
    const held = sceneScript();
    held.props[0] = { ...held.props[0], held_by: "char_a", held_side: "right" };
    renderEditor({ sceneScript: held });
    selectObject({ kind: "prop", id: "crate1" });

    expect(screen.getByTestId("held-hint-crate1").textContent).toContain("手部跟随");
    expect(screen.getByLabelText("道具 crate1 的持手")).toBeTruthy();
  });

  it("switches the carry side while held", () => {
    const held = sceneScript();
    held.props[0] = { ...held.props[0], held_by: "char_a", held_side: "right" };
    const { onChange } = renderEditor({ sceneScript: held });
    selectObject({ kind: "prop", id: "crate1" });

    fireEvent.change(screen.getByLabelText("道具 crate1 的持手"), { target: { value: "left" } });

    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.props[0].held_side).toBe("left");
  });

  it("releases a held prop back to its rest position", () => {
    const held = sceneScript();
    held.props[0] = { ...held.props[0], held_by: "char_a", held_side: "right" };
    const { onChange } = renderEditor({ sceneScript: held });
    selectObject({ kind: "prop", id: "crate1" });

    fireEvent.change(screen.getByLabelText("道具 crate1 的持有者"), { target: { value: "" } });

    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.props[0].held_by).toBeNull();
    expect(next.props[0].held_side).toBeNull();
  });

  it("clicking a held-item warning selects the prop (the remedy is one click away)", () => {
    const conflict = sceneScript();
    conflict.props = [
      { ...conflict.props[0], id: "umbrella", held_by: "char_a", held_side: "right" },
      { ...conflict.props[0], id: "cup", type: "cup", held_by: "char_a", held_side: "right" },
    ];
    renderEditor({ sceneScript: conflict });

    const warning = screen.getByText(/一只手放不下两件东西/);
    fireEvent.click(warning);

    // Selecting a prop opens the inspector where its holder can change
    // (the shared banner convention picks the first subject in the list).
    expect(screen.getByLabelText("道具 cup 的持有者")).toBeTruthy();
  });
});

describe("SceneScript3DEditor animatic provenance (V0.2 §14.9 成片侧)", () => {
  it("reports the render that carries the bed", () => {
    renderEditor({ animaticAudio: { muxed: true, reason: null } });
    const line = screen.getByTestId("scene-script-3d-animatic");
    expect(line.getAttribute("data-muxed")).toBe("true");
    expect(line.textContent).toContain("已带上台词床音");
  });

  it("translates the executor's skip reasons", () => {
    renderEditor({
      animaticAudio: { muxed: false, reason: "keyframes_only_render" },
    });
    const line = screen.getByTestId("scene-script-3d-animatic");
    expect(line.getAttribute("data-muxed")).toBe("false");
    expect(line.textContent).toContain("关键帧");
  });

  it("stays quiet when the node has no provenance yet", () => {
    renderEditor();
    expect(screen.queryByTestId("scene-script-3d-animatic")).toBeNull();
  });
});

describe("SceneScript3DEditor cross-node drift (V0.2 §5 服装维度)", () => {
  const drift = {
    checked: true,
    reason: null,
    findings: [
      {
        code: "character_appearance_drift",
        subject: "asset-girl",
        message:
          "角色资产 asset-girl 被多个场景节点绑定，但外观不一致：node-a/char_a 用 #e74c3c、node-b/char_a 用 #3498db。身份绑定说这是同一个人，预览却说不是。",
        remedy: "把各场景节点里该角色的外观色统一；确需换装时，让叙事说明这次变化。",
      },
    ],
  };

  it("names the disagreement and its remedy", () => {
    renderEditor({ wardrobeDrift: drift });
    const line = screen.getByTestId("scene-script-3d-drift-0");
    expect(line.textContent).toContain("外观不一致");
    expect(line.textContent).toContain("外观色统一");
  });

  it("stays quiet when there is nothing to report", () => {
    renderEditor({ wardrobeDrift: { checked: true, reason: null, findings: [] } });
    expect(screen.queryByTestId("scene-script-3d-drift-0")).toBeNull();
  });

  it("stays quiet when the check did not run (unreadable workflow)", () => {
    renderEditor({
      wardrobeDrift: {
        checked: false,
        reason: "workflow_scripts_unreadable",
        findings: [],
      },
    });
    expect(screen.queryByTestId("scene-script-3d-drift-0")).toBeNull();
  });
});

describe("SceneScript3DEditor continuity + declared reading (V0.2 §13 第 4 问)", () => {
  const blocking = [
    {
      code: "facing_flip",
      severity: "warning",
      subject: "char_a",
      boundary: "shot1→shot2",
      message: "角色 char_a 在 shot1→shot2 之间转身 170°，运动方向断了。",
      remedy: "在剪切点补一个转身关键帧，或让下一镜从他背後开始。",
    },
  ];

  it("shows a continuity finding that nobody declared a reading for", () => {
    renderEditor({ blockingContinuity: blocking });
    const line = screen.getByTestId("scene-script-3d-blocking-0");
    expect(line.textContent).toContain("转身 170°");
    expect(line.textContent).toContain("运动方向断了");
  });

  it("says a change reading EXPLAINS the finding (informational, not an alarm)", () => {
    renderEditor({
      blockingContinuity: blocking,
      transitionIntentNotes: [
        {
          code: "transition_intent_explains_continuity",
          severity: "info",
          shot_id: "shot2",
          reading_id: "time_jump",
          message: "shot2 声明以「时间跳跃」接入，而这一镜边界上确有 facing_flip：变化是读法的一部分，不是连续性缺陷。",
          remedy: "无需处理；若这不符合作者本意，改登记或改走位，两者应对得上。",
        },
      ],
    });
    const line = screen.getByTestId("scene-script-3d-intent-0");
    expect(line.textContent).toContain("变化是读法的一部分");
    // Informational: the row must not wear the alarm colour.
    expect(line.className).not.toContain("is-stale");
  });

  it("says a continuity reading CONTRADICTS the finding (the one worth stopping for)", () => {
    renderEditor({
      blockingContinuity: blocking,
      transitionIntentNotes: [
        {
          code: "transition_intent_contradicts_continuity",
          severity: "warning",
          shot_id: "shot2",
          reading_id: "continuous_motion",
          message: "shot2 声明以「连续运动」接入（承诺连续），但这一镜边界上有 facing_flip：登记与关键帧互相矛盾。",
          remedy: "要么把走位改回连续，要么把登记改成时间跳跃。",
        },
      ],
    });
    const line = screen.getByTestId("scene-script-3d-intent-0");
    expect(line.textContent).toContain("登记与关键帧互相矛盾");
    expect(line.className).toContain("is-stale");
  });

  it("stays quiet when there are no findings and no notes", () => {
    renderEditor({ blockingContinuity: [], transitionIntentNotes: [] });
    expect(screen.queryByTestId("scene-script-3d-blocking-0")).toBeNull();
    expect(screen.queryByTestId("scene-script-3d-intent-0")).toBeNull();
  });

  it("shows a note even when the continuity list itself is empty", () => {
    renderEditor({
      blockingContinuity: [],
      transitionIntentNotes: [
        {
          code: "transition_intent_explains_continuity",
          severity: "info",
          shot_id: "shot2",
          reading_id: "angle_switch",
          message: "shot2 声明以「视角切换」接入。",
          remedy: "无需处理。",
        },
      ],
    });
    expect(screen.getByTestId("scene-script-3d-intent-0").textContent).toContain(
      "视角切换",
    );
  });
});

describe("SceneScript3DEditor consistency report (V0.2 §12 核心问题)", () => {
  const errorFinding = {
    code: "character_unbound",
    severity: "error",
    subject: "char_a",
    message: "Character 'char_a' has no bound character asset in a 2-shot scene.",
    remedy: "Bind a character asset so later shots and the video model keep the same identity.",
  };
  const warningFinding = {
    code: "shot_coverage_gap",
    severity: "warning",
    subject: "frames 90-119",
    message: "No shot covers frames 90-119 of 120.",
    remedy: "Extend a shot's range or add a shot for the gap.",
  };

  it("shows each finding with its Chinese label and the backend remedy", () => {
    renderEditor({
      consistency: { passed: false, issues: [errorFinding] },
    });
    const line = screen.getByTestId("scene-script-3d-consistency-0");
    expect(line.textContent).toContain("角色未绑定资产");
    // The backend prose rides along as the detail, so nothing is lost.
    expect(line.textContent).toContain("char_a");
    expect(line.textContent).toContain("Bind a character asset");
  });

  it("puts an ERROR above the cosmetic warnings", () => {
    renderEditor({
      consistency: { passed: false, issues: [warningFinding, errorFinding] },
    });
    const first = screen.getByTestId("scene-script-3d-consistency-0");
    expect(first.textContent).toContain("角色未绑定资产");
    expect(first.className).toContain("is-error");
    expect(screen.getByTestId("scene-script-3d-consistency-1").textContent).toContain(
      "镜头覆盖有空缺",
    );
  });

  it("labels every code the backend can emit", () => {
    // An unknown code must still render (as the raw code) rather than vanish.
    renderEditor({
      consistency: {
        passed: true,
        issues: [{ ...warningFinding, code: "some_future_check" }],
      },
    });
    expect(screen.getByTestId("scene-script-3d-consistency-0").textContent).toContain(
      "some_future_check",
    );
  });

  it("stays quiet when the report is clean", () => {
    renderEditor({ consistency: { passed: true, issues: [] } });
    expect(screen.queryByTestId("scene-script-3d-consistency-0")).toBeNull();
  });
});

describe("SceneScript3DEditor prop/scene asset binding (Dramagic 锁延伸到物件)", () => {
  it("binds a prop through the inspector and writes the schema field", () => {
    // The asset must be offered before it can be chosen (a select cannot
    // hold a value its option list does not contain).
    const { onChange } = renderEditor({
      propAssets: [{ asset_id: "asset-crate", display_name: "木箱" }],
    });
    selectObject({ kind: "prop", id: "crate1" });
    fireEvent.change(screen.getByLabelText("道具 crate1 资产绑定"), {
      target: { value: "asset-crate" },
    });
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(next.props.find((prop) => prop.id === "crate1")?.prop_asset_id).toBe(
      "asset-crate",
    );
  });

  it("binds an environment object the same way", () => {
    const { onChange } = renderEditor({
      sceneAssets: [{ asset_id: "asset-lab", display_name: "实验室" }],
    });
    selectObject({ kind: "environment", id: "wall1" });
    fireEvent.change(screen.getByLabelText("环境 wall1 资产绑定"), {
      target: { value: "asset-lab" },
    });
    const next = onChange.mock.calls[0][0] as SceneScriptRoot;
    expect(
      next.environment.find((object) => object.id === "wall1")?.scene_asset_id,
    ).toBe("asset-lab");
  });

  it("shows the binding the executor stamped (publish ≠ visible)", () => {
    const stamped = sceneScript();
    stamped.props = [{ ...stamped.props[0], prop_asset_id: "asset-crate" }];
    renderEditor({
      sceneScript: stamped,
      propAssets: [{ asset_id: "asset-crate", display_name: "木箱" }],
    });
    selectObject({ kind: "prop", id: stamped.props[0].id });
    expect(
      (screen.getByLabelText(`道具 ${stamped.props[0].id} 资产绑定`) as HTMLSelectElement)
        .value,
    ).toBe("asset-crate");
  });

  it("offers the assets of the matching kind, not every asset", () => {
    renderEditor({
      propAssets: [
        { asset_id: "asset-crate", display_name: "木箱" },
        { asset_id: "asset-other", display_name: "别的" },
      ],
    });
    selectObject({ kind: "prop", id: "crate1" });
    const options = Array.from(
      screen.getByLabelText("道具 crate1 资产绑定").querySelectorAll("option"),
    ).map((option) => option.value);
    expect(options).toEqual(["", "asset-crate", "asset-other"]);
  });
});

describe("SceneScript3DEditor auto-lip-sync provenance (ADR 0003)", () => {
  const measured = {
    applied: true,
    duration_source: "measured",
    segment_count: 2,
    warnings: [],
  };

  it("says how the mouths were driven, and how many lines they follow", () => {
    renderEditor({ autoLipSync: measured });
    const line = screen.getByTestId("scene-script-3d-auto-lip-sync");
    expect(line.textContent).toContain("已按 2 句台词写入唇形");
    expect(line.textContent).toContain("实测");
    expect(line.className).not.toContain("is-error");
  });

  it("flags an ESTIMATE as the warning it is (a guess is not a measurement)", () => {
    renderEditor({
      autoLipSync: { ...measured, duration_source: "estimated" },
    });
    const line = screen.getByTestId("scene-script-3d-auto-lip-sync");
    expect(line.textContent).toContain("估算");
    expect(line.textContent).toContain("嘴动得对不上");
    expect(line.className).toContain("is-error");
  });

  it("names a partially measured run for what it is", () => {
    renderEditor({ autoLipSync: { ...measured, duration_source: "mixed" } });
    expect(screen.getByTestId("scene-script-3d-auto-lip-sync").textContent).toContain(
      "部分实测",
    );
  });

  it("carries the warnings the run reported", () => {
    renderEditor({
      autoLipSync: { ...measured, warnings: ["第 2 句的对齐置信度偏低"] },
    });
    expect(screen.getByTestId("scene-script-3d-auto-lip-sync").textContent).toContain(
      "对齐置信度偏低",
    );
  });

  it("stays quiet when nothing was applied", () => {
    renderEditor({
      autoLipSync: { applied: false, duration_source: "none", segment_count: 0, warnings: [] },
    });
    expect(screen.queryByTestId("scene-script-3d-auto-lip-sync")).toBeNull();
  });
});

describe("SceneScript3DEditor reference inputs (资产驱动场景)", () => {
  const bindings = [
    { asset_id: "asset-board", semantic_role: "scene_board", recorded_on: "scene_asset_id", media_type: "image" },
  ];

  it("names what this previs node was fed", () => {
    renderEditor({ referenceBindings: bindings });
    const line = screen.getByTestId("scene-script-3d-reference-0");
    expect(line.textContent).toContain("场景设计板");
    expect(line.textContent).toContain("asset-board");
    expect(line.textContent).toContain("已标注到环境资产绑定");
    expect(line.getAttribute("data-asset")).toBe("asset-board");
  });

  it("says WHY a reference was not attributed when it is ambiguous", () => {
    renderEditor({
      referenceBindings: [
        { ...bindings[0], recorded_on: null },
      ],
    });
    const line = screen.getByTestId("scene-script-3d-reference-0");
    expect(line.textContent).toContain("未标注到具体元素");
    expect(line.textContent).toContain("交由作者决定");
    expect(line.getAttribute("data-recorded-on")).toBe("");
  });

  it("stays quiet when nothing was delivered", () => {
    renderEditor({ referenceBindings: [] });
    expect(screen.queryByTestId("scene-script-3d-reference-0")).toBeNull();
    renderEditor({ referenceBindings: null });
    expect(screen.queryByTestId("scene-script-3d-reference-0")).toBeNull();
  });
});

describe("SceneScript3DEditor advisory jump (V0.2 §15)", () => {
  it("moves the playhead into the named shot and fetches that pair's readings", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, proposals: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const twoShot = sceneScript();
    twoShot.shots = [
      { id: "shot1", camera: "cam1", start_frame: 0, end_frame: 89, description: "wide" },
      { id: "shot2", camera: "cam1", start_frame: 90, end_frame: 179, description: "closeup" },
    ];

    renderEditor({ sceneScript: twoShot, focusShotId: "shot1" });

    // The whole wire: focus -> playhead inside the boundary shot -> the
    // picker's pair forms -> the readings for THAT pair fetch once.
    // StoryboardPanel fires on mount (storyboard tab) — wait for both fetches to settle
    // so the test does not leave a pending request that changes the call count mid-assertion.
    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
    // The transition-proposals call is the first one (fired before the panel's mount fetch).
    // Find the transition-proposals call: its URL contains /transition-proposals.
    const transitionCall = fetchMock.mock.calls.find(
      (call) => String(call[0]).includes("/transition-proposals"),
    );
    expect(transitionCall).toBeDefined();
    const body = JSON.parse((transitionCall![1] as RequestInit).body as string);
    expect(body.shot_a_id).toBe("shot1");
    expect(body.shot_b_id).toBe("shot2");
  });

  it("reports the spent signal so the parent can clear it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true, proposals: [] }),
      }),
    );
    const twoShot = sceneScript();
    twoShot.shots = [
      { id: "shot1", camera: "cam1", start_frame: 0, end_frame: 89, description: "wide" },
      { id: "shot2", camera: "cam1", start_frame: 90, end_frame: 179, description: "closeup" },
    ];
    const onFocusShotConsumed = vi.fn();

    renderEditor({
      sceneScript: twoShot,
      focusShotId: "shot1",
      onFocusShotConsumed,
    });

    await waitFor(() => {
      expect(onFocusShotConsumed).toHaveBeenCalledTimes(1);
    });
  });
});

describe("SceneScript3DEditor director takes (V3)", () => {
  it("shows no take controls without an onSaveTake callback", () => {
    renderEditor();
    expect(screen.queryByTestId("scene-script-3d-take-save")).toBeNull();
  });

  it("saves a labelled take from the current scene and frame", () => {
    const onSaveTake = vi.fn();
    const { onChange } = renderEditor({ takes: [], onSaveTake });
    fireEvent.click(screen.getByTestId("scene-script-3d-take-save"));
    expect(onSaveTake).toHaveBeenCalledTimes(1);
    const take = onSaveTake.mock.calls[0][0];
    expect(take.label).toBe("Take 1");
    expect(take.scene_script).toEqual(sceneScript());
    expect(Array.isArray(take.operations)).toBe(true);
  });

  it("restores a saved take over the live scene", () => {
    const other: SceneScriptRoot = {
      ...sceneScript(),
      scene: { ...sceneScript().scene, name: "take-version" },
    };
    const takes = [
      {
        id: "take_x",
        label: "Take X",
        scene_script: JSON.parse(JSON.stringify(other)) as Record<string, unknown>,
        operations: [{ op: "move" }],
        frame: 12,
      },
    ];
    const { onChange } = renderEditor({ takes, onSaveTake: vi.fn() });
    fireEvent.click(screen.getByTestId("scene-script-3d-take-restore-take_x"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect((onChange.mock.calls[0][0] as SceneScriptRoot).scene.name).toBe(
      "take-version",
    );
  });

  it("labels new takes in the Take 1/2/3 series, skipping used labels", () => {
    const onSaveTake = vi.fn();
    const used = [
      {
        id: "t1",
        label: "Take 1",
        scene_script: {} as Record<string, unknown>,
        operations: [],
        frame: null,
      },
    ];
    renderEditor({ takes: used, onSaveTake });
    fireEvent.click(screen.getByTestId("scene-script-3d-take-save"));
    expect(onSaveTake.mock.calls[0][0].label).toBe("Take 2");
  });
});
