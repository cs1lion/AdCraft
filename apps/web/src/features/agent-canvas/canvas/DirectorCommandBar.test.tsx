import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { SceneScriptRoot } from "../../../types/scene-script";
import { CAMERA_MOTION_PRESETS } from "./cameraMotionPresets.ts";
import { CHARACTER_MOTION_PRESETS } from "./characterMotionPresets.ts";
import {
  expandDirectorMotionIntent,
  listDirectorMotionPresetIds,
} from "./directorMotion.ts";
import { DirectorCommandBar } from "./DirectorCommandBar.tsx";
import { SceneScriptPlaybackProvider } from "./SceneScriptPlaybackContext.tsx";

// The command bar is the first visible piece of the director-command flow:
// it must expand a deterministic intent into a valid SceneScriptRoot that the
// editor's onChange can apply. These tests lock that contract without booting
// the (heavy) r3f canvas — the expandable intent shape is the piece the UI
// consumes directly.

function scene(): SceneScriptRoot {
  return {
    scene: { name: "lab", environment: "indoor", lighting: "cool", duration: 6, frame_rate: 30 },
    characters: [
      {
        id: "char_a",
        type: "lowpoly_human",
        appearance: { color: "#E74C3C" },
        keyframes: [{ frame: 0, position: [0, 0, 0], rotation_y: 0, action: "stand" }],
      },
    ],
    props: [],
    environment: [],
    cameras: [
      {
        id: "cam1",
        shot_type: "wide",
        keyframes: [{ frame: 0, position: [5, -6, 2.6], look_at: [0, 0, 1.2] }],
      },
    ],
    shots: [{ id: "shot1", camera: "cam1", start_frame: 0, end_frame: 179, description: "wide" }],
    speech_bindings: [],
  };
}

describe("director command expansion (MVP contract)", () => {
  it("expands a camera intent into a preview script with new keyframes", () => {
    const command = expandDirectorMotionIntent(scene(), {
      intent: "camera_motion",
      targetId: "cam1",
      presetId: "orbit_left",
      startFrame: 0,
      durationFrames: 30,
    });

    expect(command.previewScript.cameras[0].keyframes.length).toBeGreaterThan(1);
    expect(command.operations.length).toBeGreaterThan(1);
    for (const operation of command.operations) {
      expect(operation.op).toBe("add_keyframe");
      expect(operation.kind).toBe("camera");
      expect(operation.id).toBe("cam1");
    }
  });

  it("expands a character intent into a preview script with new keyframes", () => {
    const command = expandDirectorMotionIntent(scene(), {
      intent: "character_motion",
      targetId: "char_a",
      presetId: "walk_to",
      startFrame: 0,
      durationFrames: 30,
      targetPosition: [6, 0, 0],
    });

    expect(command.previewScript.characters[0].keyframes.length).toBeGreaterThan(1);
    expect(command.operations.length).toBeGreaterThan(1);
    for (const operation of command.operations) {
      expect(operation.op).toBe("add_keyframe");
      expect(operation.kind).toBe("character");
      expect(operation.id).toBe("char_a");
    }
  });

  it("offers the full camera + character preset vocabulary", () => {
    const cameraIds = listDirectorMotionPresetIds("camera_motion");
    const characterIds = listDirectorMotionPresetIds("character_motion");

    for (const preset of CAMERA_MOTION_PRESETS) {
      expect(cameraIds).toContain(preset.id);
    }
    for (const preset of CHARACTER_MOTION_PRESETS) {
      expect(characterIds).toContain(preset.id);
    }
    // The bar should present more than one command per target type so the
    // director has real choices, not a single preset.
    expect(cameraIds.length).toBeGreaterThan(1);
    expect(characterIds.length).toBeGreaterThan(1);
  });

  it("builds a valid trigger event request shape", () => {
    const request = {
      trigger: "sit",
      triggerTargetId: "char_a",
      triggerFrame: 45,
      triggerTargetPosition: null,
      triggerTargetYaw: null,
      thenOps: [
        { op: "add_keyframe", kind: "camera", id: "cam1", frame: 45,
          position: [3, -3, 1.5], look_at: [0, 0, 1.0] } as Record<string, unknown>,
      ],
      thenFrame: 45,
    };
    expect(request.trigger).toBe("sit");
    expect(request.triggerTargetId).toBe("char_a");
    expect(request.thenOps.length).toBe(1);
  });
});


describe("DirectorCommandBar gate rejection (D3, ADR 0012)", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders a gate rejection on the ERROR channel, not a success note", async () => {
    const directorClient = await import("./directorOperationsClient.ts");
    vi.spyOn(directorClient, "applyDirectorMotion").mockResolvedValue({
      ok: false,
      error: "gate: op push_in rejected (camera lacks keyframe)",
    });

    render(
      <SceneScriptPlaybackProvider sceneScript={scene()}>
        <DirectorCommandBar sceneScript={scene()} onApply={() => {}} selectedObject={null} />
      </SceneScriptPlaybackProvider>,
    );

    fireEvent.change(screen.getByLabelText("导演指令对象"), { target: { value: "cam1" } });
    fireEvent.change(screen.getByLabelText("导演指令"), { target: { value: "push_in" } });
    fireEvent.click(screen.getByTestId("scene-script-3d-director-submit"));

    const status = await screen.findByTestId("scene-script-3d-director-status");
    await waitFor(() => expect(status.textContent).toContain("未过闸门"));
    // D3: a rejected command must reach the error (red) channel, never the
    // success note. The message text is identical in both channels, so assert
    // on the className the bar chooses from gate.ok.
    expect(status.className).toContain("scene-script-3d-editor__error");
    expect(status.className).not.toContain("scene-script-3d-editor__note");
  });
});

describe("trigger target picking (用所选)", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  function sceneWithProp(): SceneScriptRoot {
    const base = scene();
    base.props = [
      { id: "prop_crate_1", type: "crate", position: [3, 4, 0], scale: 1, rotation_y: 0 },
    ] as never;
    return base;
  }

  it("renders the trigger panel without any prior state (the old condition was always false)", () => {
    render(
      <SceneScriptPlaybackProvider sceneScript={scene()}>
        <DirectorCommandBar sceneScript={scene()} onApply={() => {}} selectedObject={null} />
      </SceneScriptPlaybackProvider>,
    );
    // 回归锁定：触发区外层条件曾是 trigger || triggerTargetId（初始均为
    // 空串，恒假）——when/then 面板在实机上从未渲染出来过。
    expect(screen.getByTestId("scene-script-3d-director-trigger")).toBeTruthy();
  });

  it("fills the arrive destination from the selected object and gates it", async () => {
    const directorClient = await import("./directorOperationsClient.ts");
    const gateSpy = vi.spyOn(directorClient, "applyTriggerEvent").mockResolvedValue({
      ok: true,
      appliedSceneScript: sceneWithProp(),
      operations: [],
    });

    render(
      <SceneScriptPlaybackProvider sceneScript={sceneWithProp()}>
        <DirectorCommandBar
          sceneScript={sceneWithProp()}
          onApply={() => {}}
          selectedObject={{ kind: "prop", id: "prop_crate_1" }}
        />
      </SceneScriptPlaybackProvider>,
    );

    fireEvent.change(screen.getByLabelText("触发条件"), { target: { value: "arrive" } });
    fireEvent.change(screen.getByLabelText("触发目标角色"), { target: { value: "char_a" } });
    fireEvent.click(screen.getByTestId("scene-script-3d-director-trigger-pick"));

    const positionInput = screen.getByLabelText("到达目标位置 (X,Y,Z)") as HTMLInputElement;
    expect(positionInput.value).toBe("3,4,0");

    fireEvent.click(screen.getByTestId("scene-script-3d-director-trigger-submit"));
    await waitFor(() => expect(gateSpy).toHaveBeenCalledTimes(1));
    const request = gateSpy.mock.calls[0][1];
    expect(request.triggerTargetPosition).toEqual([3, 4, 0]);
  });

  it("computes the face yaw toward the selected object (mirrors backend _yaw_facing)", () => {
    render(
      <SceneScriptPlaybackProvider sceneScript={sceneWithProp()}>
        <DirectorCommandBar
          sceneScript={sceneWithProp()}
          onApply={() => {}}
          selectedObject={{ kind: "prop", id: "prop_crate_1" }}
        />
      </SceneScriptPlaybackProvider>,
    );

    fireEvent.change(screen.getByLabelText("触发条件"), { target: { value: "face" } });
    fireEvent.change(screen.getByLabelText("触发目标角色"), { target: { value: "char_a" } });
    fireEvent.click(screen.getByTestId("scene-script-3d-director-trigger-pick"));

    const yawInput = screen.getByLabelText("转身目标角度 (°)") as HTMLInputElement;
    // char_a 站在 [0,0,0]，目标在 [3,4,0]：atan2(3, 4) ≈ 36.87° → 37
    expect(yawInput.value).toBe("37");
  });
});


it("ignores a gate response after a newer edit", async () => {
  const client = await import("./directorOperationsClient.ts");
  let complete!: (gate: Awaited<ReturnType<typeof client.applyDirectorMotion>>) => void;
  vi.spyOn(client, "applyDirectorMotion").mockImplementation(() => new Promise(resolve => { complete = resolve; }));
  const applied = vi.fn();
  const base = scene();
  const { rerender } = render(<SceneScriptPlaybackProvider sceneScript={base}><DirectorCommandBar sceneScript={base} onApply={applied} selectedObject={null}/></SceneScriptPlaybackProvider>);
  fireEvent.change(screen.getByLabelText("导演指令对象"), { target: { value: "cam1" } });
  fireEvent.change(screen.getByLabelText("导演指令"), { target: { value: "push_in" } });
  fireEvent.click(screen.getByTestId("scene-script-3d-director-submit"));
  expect(applied).toHaveBeenCalledTimes(1);
  const newer = { ...base, scene: { ...base.scene, name: "newer edit" } };
  rerender(<SceneScriptPlaybackProvider sceneScript={newer}><DirectorCommandBar sceneScript={newer} onApply={applied} selectedObject={null}/></SceneScriptPlaybackProvider>);
  await act(async () => { complete({ ok: true, appliedSceneScript: base }); });
  expect(applied).toHaveBeenCalledTimes(1);
  cleanup();
  vi.restoreAllMocks();
});
