// Spike harness: render the real jinghai SceneScript in the three.js preview and
// expose a deterministic frame stepper + PNG capture for the browser spec.
//
// What this proves (the only two questions the spike asks):
//   1. Can the three.js preview be driven frame-by-frame deterministically?
//   2. Can each frame be captured off the live canvas, and how fast?
//
// Deliberately NOT in scope for the spike: the articulated character rig (the
// preview still draws characters as a box + sphere). That gap is known and
// measured, and the point of the spike is the capture path, not the model.

import { createRoot } from "react-dom/client";
import { StrictMode } from "react";
import { useSceneScriptPlayback } from "../../src/features/agent-canvas/canvas/SceneScriptPlaybackContext";
import { SceneScript3DPreview } from "../../src/features/agent-canvas/canvas/SceneScript3DPreview";
import { SceneScriptPlaybackProvider } from "../../src/features/agent-canvas/canvas/SceneScriptPlaybackContext";
import type { SceneScriptRoot } from "../../src/types/scene-script";
// @ts-expect-error - plain JSON import from the repo's test materials
import script from "../../../../test-materials/jinghai_scenescript.json";

const scene = script as SceneScriptRoot;

const host = document.createElement("div");
host.id = "spike-root";
document.body.appendChild(host);

// Sits INSIDE the provider so it can borrow the real seek; publishes a
// deterministic stepper on window for the spec to drive.
function Driver() {
  const { seekToFrame } = useSceneScriptPlayback();
  (window as unknown as { __spikeSeek: (frame: number) => void }).__spikeSeek = seekToFrame;
  return (
    <SceneScript3DPreview sceneScript={scene} height={540} editMode={false} />
  );
}

createRoot(host).render(
  <StrictMode>
    <SceneScriptPlaybackProvider sceneScript={scene}>
      <Driver />
    </SceneScriptPlaybackProvider>
  </StrictMode>,
);

const raf = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

(window as unknown as {
  spike: {
    totalFrames: () => number;
    frameRate: () => number;
    step: (frame: number) => Promise<void>;
    capture: () => Promise<{ width: number; height: number; bytes: number; ms: number }>;
  };
}).spike = {
  totalFrames: () => scene.shots.reduce((max, shot) => Math.max(max, shot.end_frame + 1), 0),
  frameRate: () => scene.scene.frame_rate,
  step: async (frame: number) => {
    const seek = (window as unknown as { __spikeSeek?: (f: number) => void }).__spikeSeek;
    if (!seek) throw new Error("driver not mounted");
    seek(frame);
    // Two rAFs: one for the playhead state to land, one for the render loop to
    // consume it. Anything less races the rAF loop and captures the old frame.
    await raf();
    await raf();
  },
  capture: async () => {
    const canvas = document.querySelector("canvas");
    if (!(canvas instanceof HTMLCanvasElement)) throw new Error("no canvas");
    const started = performance.now();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error("capture failed");
    return {
      width: canvas.width,
      height: canvas.height,
      bytes: blob.size,
      ms: performance.now() - started,
    };
  },
};
