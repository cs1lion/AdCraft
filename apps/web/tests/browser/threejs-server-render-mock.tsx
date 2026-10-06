// Server-side render throughput harness.
//
// The go/no-go question for replacing Blender with a server-rendered three.js:
// how many frames per second can headless Chrome produce from the real preview?
//
// This bypasses the DOM screenshot path entirely: the harness renders N frames
// inside the page and reads pixels back through toBlob, so the measurement is
// the GL + encode cost alone. `captureFrames` is on, which is what makes the
// drawing buffer readable outside the render callback.

import { createRoot } from "react-dom/client";
import { StrictMode } from "react";
import {
  SceneScriptPlaybackProvider,
  useSceneScriptPlayback,
} from "../../src/features/agent-canvas/canvas/SceneScriptPlaybackContext";
import { SceneScript3DPreview } from "../../src/features/agent-canvas/canvas/SceneScript3DPreview";
import type { SceneScriptRoot } from "../../src/types/scene-script";
// @ts-expect-error - plain JSON import from the repo's test materials
import script from "../../../../test-materials/jinghai_scenescript.json";

const scene = script as SceneScriptRoot;

const host = document.createElement("div");
host.id = "spike-root";
document.body.appendChild(host);

function Driver() {
  const { seekToFrame } = useSceneScriptPlayback();
  (window as unknown as { __seek: (frame: number) => void }).__seek = seekToFrame;
  return <SceneScript3DPreview sceneScript={scene} height={540} editMode={false} />;
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
  render: {
    meta: () => { frames: number; fps: number };
    /**
     * Render `count` frames starting at `from`, capturing each one.
     * Returns per-frame milliseconds and a checksum so the caller can prove the
     * frames actually differ (a pure-black capture also "succeeds").
     */
    run: (from: number, count: number) => Promise<{
      ms: number[];
      checksums: (string | null)[];
      bytes: number[];
      glVendor: string;
    }>;
  };
}).render = {
  meta: () => ({
    frames: scene.shots.reduce((max, shot) => Math.max(max, shot.end_frame + 1), 0),
    fps: scene.scene.frame_rate,
  }),
  run: async (from, count) => {
    const canvas = document.querySelector("canvas");
    if (!(canvas instanceof HTMLCanvasElement)) throw new Error("no canvas");
    const seek = (window as unknown as { __seek?: (f: number) => void }).__seek;
    if (!seek) throw new Error("driver not mounted");

    const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
    const debug = gl instanceof WebGL2RenderingContext || gl instanceof WebGLRenderingContext
      ? gl.getExtension("WEBGL_debug_renderer_info")
      : null;
    const vendor = debug && gl
      ? String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL))
      : gl ? "masked" : "none";

    const ms: number[] = [];
    const checksums: (string | null)[] = [];
    const bytes: number[] = [];

    // Warm up: the first frames pay shader compilation and texture upload.
    for (let i = 0; i < 3; i += 1) {
      seek(from + i);
      await raf();
      await raf();
    }

    for (let i = 3; i < count; i += 1) {
      const frame = from + i;
      const started = performance.now();
      seek(frame);
      await raf();
      await raf();
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
      if (!blob) throw new Error("capture failed");
      // A cheap content check: a flat black frame compresses to a few hundred
      // bytes; a scene is far larger. This is the anti-false-pass guard.
      bytes.push(blob.size);
      checksums.push(blob.size > 5000 ? `size:${blob.size}` : `BLACK(${blob.size})`);
      ms.push(performance.now() - started);
    }
    return { ms, checksums, bytes, glVendor: vendor };
  },
};
