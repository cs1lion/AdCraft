/**
 * PrevisRenderEntry — the server-side render entry point.
 *
 * The plan (`docs/plans/threejs-renderer-replacement.md`) replaces the Blender
 * renderer with a headless-Chrome render of the SAME `SceneScript3DPreview` the
 * author edits in. That is the whole point: one scene implementation, so what
 * the author sees is what gets rendered. This module is the page a headless
 * browser loads to do it.
 *
 * It is deliberately not a component of the product UI. It mounts the preview
 * with a script handed in on the URL fragment, then exposes a small imperative
 * command surface on `window.__previsRender` for the render driver
 * (`scripts/render-frames.mjs`) to drive frame by frame.
 *
 * Two things it must NOT do:
 *   - read pixels without `captureFrames` on. The drawing buffer is cleared
 *     after compositing, which is how the first attempt produced 12 identical
 *     black PNGs that still "passed" a test.
 *   - depend on anything interactive. Nothing is clicking here, so the preview
 *     is mounted with `editMode={false}` and no pointer handlers are wanted.
 */

import { createRoot } from "react-dom/client";
import { StrictMode } from "react";

import { SceneScript3DPreview } from "../features/agent-canvas/canvas/SceneScript3DPreview";
import {
  SceneScriptPlaybackProvider,
  useSceneScriptPlayback,
} from "../features/agent-canvas/canvas/SceneScriptPlaybackContext";
import type { SceneScriptRoot } from "../types/scene-script";

interface RenderCommand {
  meta: () => { frames: number; frameRate: number };
  /** Seek to a frame and render it. Resolves once the draw has happened. */
  seek: (frame: number) => Promise<void>;
  /** Read the canvas as base64 PNG. Requires `captureFrames` on. */
  capture: () => Promise<string>;
}

declare global {
  interface Window {
    __previsRender?: RenderCommand;
    __previsSeek?: (frame: number) => void;
    __previsCurrentFrame?: number;
  }
}

function parseScript(): SceneScriptRoot | null {
  // The script rides in the fragment rather than the query string: it can be
  // tens of kilobytes, and fragments are never sent to a server.
  const raw = decodeURIComponent(location.hash.replace(/^#/, ""));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SceneScriptRoot;
  } catch {
    return null;
  }
}

/** Sits inside the provider so it can borrow the real seek. */
function Seeker() {
  const { seekToFrame, currentFrame } = useSceneScriptPlayback();
  window.__previsSeek = seekToFrame;
  // Diagnostic: proves whether the provider the PREVIEW reads is the one this
  // component writes to. If these diverge, StrictMode mounted two providers.
  window.__previsCurrentFrame = currentFrame;
  return null;
}

const raf = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

function boot() {
  const scene = parseScript();
  const host = document.createElement("div");
  host.id = "previs-render-root";
  document.body.appendChild(host);

  if (!scene) {
    document.body.dataset.renderError = "scene_script_missing";
    return;
  }

  createRoot(host).render(
    <StrictMode>
      <SceneScriptPlaybackProvider sceneScript={scene}>
        <Seeker />
        <SceneScript3DPreview
          sceneScript={scene}
          height={540}
          editMode={false}
          captureFrames
        />
      </SceneScriptPlaybackProvider>
    </StrictMode>,
  );

  window.__previsRender = {
    meta: () => ({
      frames: scene.shots.reduce((max, shot) => Math.max(max, shot.end_frame + 1), 0),
      frameRate: scene.scene.frame_rate,
    }),
    seek: async (frame: number) => {
      const seek = window.__previsSeek;
      if (!seek) throw new Error("seeker not mounted");
      seek(frame);
      // Two frames: one for the playhead state to land, one for the render loop
      // to consume it. Anything less races the rAF loop and captures the old
      // frame — the same class of bug that produced the black PNGs.
      await raf();
      await raf();
    },
    capture: async () => {
      const canvas = document.querySelector("canvas");
      if (!(canvas instanceof HTMLCanvasElement)) throw new Error("no canvas");
      return canvas.toDataURL("image/png").split(",")[1];
    },
  };
  document.body.dataset.renderReady = "true";
}

boot();
