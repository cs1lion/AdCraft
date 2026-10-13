import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import { SceneScriptPanel } from "./SceneScriptPanel";
import { useSceneScriptPlayback } from "./SceneScriptPlaybackContext";
import { useEffect } from "react";
import { PlayheadSyncProvider, usePlayheadSync } from "../PlayheadSyncContext";

vi.mock("./SceneScript3DPreview", () => ({
  SceneScript3DPreview: ({ showGizmos = true, editMode = false, height }: {
    showGizmos?: boolean; editMode?: boolean; height?: number;
  }) => {
    const playback = useSceneScriptPlayback();
    return <div data-testid="camera-output" data-edit-mode={String(editMode)} data-height={height} data-frame={playback.currentFrame} data-playing={String(playback.isPlaying)}>
      {showGizmos && <div data-testid="camera-body-in-frame" />}
      <button type="button" onClick={() => playback.seekToFrame(60)}>seek fixture</button>
      <button type="button" onClick={playback.play}>play fixture</button>
    </div>;
  },
}));

const scene: SceneScriptRoot = {
  scene: { name: "camera output", environment: "indoor", lighting: "neutral", duration: 10, frame_rate: 30 },
  characters: [], props: [], environment: [], speech_bindings: [],
  cameras: [{ id: "camera", shot_type: "wide", keyframes: [
    { frame: 0, position: [4, -6, 3], look_at: [0, 0, 1] },
  ] }],
  shots: [{ id: "shot", camera: "camera", start_frame: 0, end_frame: 299, description: "locked camera" }],
};

function EmptyTimeline() {
  const { playhead, setFromTimeline } = usePlayheadSync();
  useEffect(() => {
    if (playhead.origin === "preview") setFromTimeline({ time: 0, playing: false });
  }, [playhead, setFromTimeline]);
  return <span data-testid="empty-timeline-playing">{String(playhead.playing)}</span>;
}

afterEach(cleanup);

describe("scene node camera output", () => {
  it("owns each unlinked version's clock independently of the empty global timeline", async () => {
    render(<PlayheadSyncProvider><EmptyTimeline />
      <SceneScriptPanel sceneScript={scene} />
      <SceneScriptPanel sceneScript={{ ...scene, scene: { ...scene.scene, name: "V2" } }} />
    </PlayheadSyncProvider>);
    await screen.findAllByTestId("camera-output");
    fireEvent.click(screen.getAllByRole("button", { name: "play fixture" })[0]);
    expect(screen.getAllByTestId("camera-output").map((output) => output.getAttribute("data-playing")))
      .toEqual(["true", "false"]);
    expect(screen.getByTestId("empty-timeline-playing").textContent).toBe("false");
    fireEvent.click(screen.getAllByRole("button", { name: "seek fixture" })[0]);
    expect(screen.getAllByTestId("camera-output").map((output) => output.getAttribute("data-frame")))
      .toEqual(["60", "0"]);
  });
  it("excludes authoring camera bodies from the read-only output after a tab round trip", async () => {
    // The active camera's own lens cone otherwise covers the scene. Lock the
    // node-card boundary; the editor's authoring surface keeps its default.
    render(<SceneScriptPanel sceneScript={scene} />);
    expect((await screen.findByTestId("camera-output")).getAttribute("data-edit-mode")).toBe("false");
    expect(screen.queryByTestId("camera-body-in-frame")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Scene Info" }));
    expect(screen.queryByTestId("camera-output")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "3D Preview" }));
    await screen.findByTestId("camera-output");
    expect(screen.queryByTestId("camera-body-in-frame")).toBeNull();
  });

  it("opens an uncropped camera viewport sharing the node's seek clock, and closes with Escape", async () => {
    render(<SceneScriptPanel sceneScript={scene} height={320} />);
    await screen.findByTestId("camera-output");
    fireEvent.click(screen.getByRole("button", { name: "放大相机预览" }));
    const dialog = screen.getByRole("dialog", { name: "相机预览" });
    expect(dialog.parentElement).toBe(document.body);
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    const outputs = screen.getAllByTestId("camera-output");
    expect(outputs).toHaveLength(2);
    expect(Number(outputs[1].getAttribute("data-height"))).toBeGreaterThan(320);
    fireEvent.click(screen.getAllByRole("button", { name: "seek fixture" })[1]);
    expect(outputs.map((output) => output.getAttribute("data-frame"))).toEqual(["60", "60"]);
    expect(screen.queryByTestId("camera-body-in-frame")).toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("camera-output").getAttribute("data-frame")).toBe("60");
  });
});
