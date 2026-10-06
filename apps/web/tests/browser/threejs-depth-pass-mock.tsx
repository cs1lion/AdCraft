// Depth control pass harness — real WebGL, the real preview, the real pass.
//
// The two questions this page answers for the spec:
//   1. Does the three.js renderer produce a greyscale DEPTH pass for every shot
//      keyframe, named the way `control_passes.collect_control_passes` looks
//      it up (`control_depth/depth_<N>.png`, 0-based frames)?
//   2. Is the output REAL content? A broken capture (the drawing buffer read
//      after compositing, say) yields an all-black PNG that still "succeeds",
//      which is exactly how 12 identical black PNGs passed a test once. Every
//      delivery therefore carries the page's own content stats, and the spec
//      asserts on those — not on the PNG merely existing.
//
// The pass renders each frame from the SHOT's camera (the same viewpoint
// Blender's own depth pass used), not the preview's orbit camera: a control
// pass is guidance for the shot, not for wherever the author last dragged the
// viewport.

import { createRoot } from "react-dom/client";
import { StrictMode } from "react";

import {
  SceneScriptPlaybackProvider,
  useSceneScriptPlayback,
} from "../../src/features/agent-canvas/canvas/SceneScriptPlaybackContext";
import { SceneScript3DPreview } from "../../src/features/agent-canvas/canvas/SceneScript3DPreview";
import type { DepthPassDelivery } from "../../src/features/agent-canvas/canvas/sceneDepthPassRecorder";
import { depthPassFramePlan } from "../../src/features/agent-canvas/canvas/sceneDepthPass";
import type { SceneScriptRoot } from "../../src/types/scene-script";
// @ts-expect-error - plain JSON import from the repo's test materials
import script from "../../../../test-materials/jinghai_scenescript.json";

const scene = script as SceneScriptRoot;

interface Delivery {
  frame: number;
  fileName: string;
  bytes: number;
  checksum: number;
  stats: DepthPassDelivery["stats"];
}

const deliveries = new Map<number, Delivery>();

function checksum(bytes: Uint8Array): number {
  let sum = 0;
  for (let i = 0; i < bytes.length; i += 1) sum = (sum + bytes[i]) % 2147483647;
  return sum;
}

/** Sits inside the provider so it can borrow the real seek. */
function Driver() {
  const { seekToFrame } = useSceneScriptPlayback();
  (window as unknown as { __seek: (frame: number) => void }).__seek = seekToFrame;
  return (
    <SceneScript3DPreview
      sceneScript={scene}
      height={540}
      editMode={false}
      captureFrames
      controlDepthPass={{
        onFrame: async (delivery: DepthPassDelivery) => {
          const bytes = new Uint8Array(await delivery.blob.arrayBuffer());
          deliveries.set(delivery.frame, {
            frame: delivery.frame,
            fileName: delivery.fileName,
            bytes: bytes.length,
            checksum: checksum(bytes),
            stats: delivery.stats,
          });
        },
      }}
    />
  );
}

const host = document.createElement("div");
host.id = "depth-pass-root";
document.body.appendChild(host);

createRoot(host).render(
  <StrictMode>
    <SceneScriptPlaybackProvider sceneScript={scene}>
      <Driver />
    </SceneScriptPlaybackProvider>
  </StrictMode>,
);

const raf = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

(window as unknown as {
  depthPass: {
    plan: () => { shots: { shotId: string; frames: number[] }[]; frames: number[] };
    /** Seek every planned frame and collect its depth delivery. */
    captureAll: () => Promise<Delivery[]>;
  };
}).depthPass = {
  plan: () => depthPassFramePlan(scene.shots),
  captureAll: async () => {
    const plan = depthPassFramePlan(scene.shots).frames;
    for (const frame of plan) {
      const seek = (window as unknown as { __seek?: (f: number) => void }).__seek;
      if (!seek) throw new Error("driver not mounted");
      seek(frame);
      // Two rAFs: one for the playhead to land, one for the render loop (and
      // the recorder's one-frame settle) to consume it.
      await raf();
      await raf();
      const deadline = Date.now() + 5000;
      while (!deliveries.has(frame) && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 16));
      }
      if (!deliveries.has(frame)) throw new Error(`no depth delivery for frame ${frame}`);
    }
    return plan.map((frame) => deliveries.get(frame)!);
  },
};
