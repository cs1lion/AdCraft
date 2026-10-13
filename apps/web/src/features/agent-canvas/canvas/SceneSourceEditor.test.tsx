import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import { SceneSourceEditor } from "./SceneSourceEditor";

const scene: SceneScriptRoot = {
  scene: { name: "original", environment: "indoor", lighting: "neutral", duration: 2, frame_rate: 30 },
  characters: [], props: [], environment: [], cameras: [], shots: [], speech_bindings: [],
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("server-validated scene import", () => {
  it("validates the complete document without an empty operation batch and preserves authored values", async () => {
    // Locks the live endpoint contract: the old empty-op request is rejected
    // before it can validate a SceneScript. No-op aspect adaptation would also
    // lose camera names and may change authored floating-point positions.
    const accepted: SceneScriptRoot = { ...scene, scene: { ...scene.scene, name: "accepted" },
      cameras: [{ id: "camera1", display_name: "作者机位", shot_type: "wide",
        keyframes: [{ frame: 0, position: [0.1, 0.2, 0.3], look_at: [0, 0, 0] }] }] };
    const request = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ success: true, passed: true, issues: [] }) });
    vi.stubGlobal("fetch", request);
    const onChange = vi.fn();
    render(<SceneSourceEditor sceneScript={scene} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "导入场景数据" }));
    fireEvent.change(screen.getByLabelText("SceneScript JSON"), { target: { value: JSON.stringify(accepted) } });
    fireEvent.click(screen.getByRole("button", { name: "校验并应用" }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(accepted));
    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/api/v1/scene-3d/consistency-check", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scene_script: accepted }),
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("portals the import outside transformed canvas ancestors and seeds compact JSON", () => {
    const { container } = render(<div style={{ transform: "scale(0.2)" }}>
      <SceneSourceEditor sceneScript={scene} onChange={vi.fn()} />
    </div>);
    fireEvent.click(screen.getByRole("button", { name: "导入场景数据" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.parentElement).toBe(document.body);
    expect(container.contains(dialog)).toBe(false);
    expect((screen.getByLabelText("SceneScript JSON") as HTMLTextAreaElement).value)
      .toBe(JSON.stringify(scene));
  });

  it("keeps the existing draft when the server rejects an unknown pose channel", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 400,
      json: async () => ({ detail: { error: "unknown joint" } }) }));
    const onChange = vi.fn();
    render(<SceneSourceEditor sceneScript={scene} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "导入场景数据" }));
    fireEvent.change(screen.getByLabelText("SceneScript JSON"), { target: { value: JSON.stringify({ ...scene, unknown: true }) } });
    fireEvent.click(screen.getByRole("button", { name: "校验并应用" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("unknown joint"));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("rejects a partial document locally without changing the draft", async () => {
    const request = vi.fn();
    vi.stubGlobal("fetch", request);
    const onChange = vi.fn();
    render(<SceneSourceEditor sceneScript={scene} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "导入场景数据" }));
    const { cameras: _omitted, ...partial } = scene;
    fireEvent.change(screen.getByLabelText("SceneScript JSON"), { target: { value: JSON.stringify(partial) } });
    fireEvent.click(screen.getByRole("button", { name: "校验并应用" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("完整 SceneScript"));
    expect(request).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });
});
