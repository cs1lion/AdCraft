/**
 * DepthPassRecorder — the React seam between the playhead and the depth pass.
 *
 * `sceneDepthPass.ts` holds everything pure (frame selection, file layout,
 * normalization, the camera pose) plus one narrow GL seam. This component is
 * the glue that makes the pass happen in the real preview: it owns a
 * `DepthPassCapture` for the canvas' renderer and, whenever the playhead lands
 * on one of the shot keyframes the pass samples, renders that frame's depth
 * from the SHOT's camera and hands the PNG to the caller.
 *
 * It renders as a child of the preview's canvas (see `SceneScript3DPreview`'s
 * `controlDepthPass` prop), so it reads `useThree()` like every other scene
 * component.
 *
 * TWO THINGS IT IS CAREFUL ABOUT
 * - Camera: the preview's canvas is the author's ORBIT camera, but a control
 *   pass is guidance for the SHOT, so the capture temporarily poses the preview
 *   camera at the shot camera's interpolated keyframe and puts it back. The
 *   author's viewpoint is never visibly disturbed.
 * - Timing: a seek commits the new pose through layout effects, which can land
 *   during the same rAF the capture would run in. Capturing on the very next
 *   frame callback would therefore render the OLD pose — the same class of race
 *   that produced 12 identical black PNGs the first time somebody read pixels
 *   without `preserveDrawingBuffer`. So a planned frame is armed on one callback
 *   and captured on the NEXT one, and the caller awaits `onFrame`.
 */

import { useEffect, useMemo, useRef } from "react";

import * as THREE from "three";

import { useFrame, useThree } from "./LeanSceneCanvas";
import {
  DepthPassCapture,
  depthPassFileName,
  depthPassFramePlan,
  encodeDepthPng,
  shotCameraPoseAtFrame,
  type ShotCamera,
} from "./sceneDepthPass";
import { sceneToThreePosition } from "./sceneScriptAxes";
import { useSceneScriptPlayback } from "./SceneScriptPlaybackContext";
import type { SceneScriptRoot } from "../../../types/scene-script";

/** One captured depth frame, named the way the collector looks it up. */
export interface DepthPassDelivery {
  /** 0-based SceneScript frame the pass was captured at. */
  frame: number;
  /** ``depth_<N>.png`` — the name `control_passes.collect_control_passes` reads. */
  fileName: string;
  /** The camera the frame was rendered from (null when the script has none). */
  cameraId: string | null;
  blob: Blob;
  /** Content numbers a caller can assert on without decoding the PNG. */
  stats: { maxDepth: number; geometryPixels: number };
}

export interface DepthPassRecorderProps {
  sceneScript: SceneScriptRoot;
  /**
   * One call per shot keyframe frame, in capture order. Awaited: an upload
   * pipeline can serialize its writes here without a second queue.
   */
  onFrame: (delivery: DepthPassDelivery) => void | Promise<void>;
  /** Default true — mounting the recorder arms the pass. */
  enabled?: boolean;
}

/**
 * What `SceneScript3DPreview` accepts for the pass: everything the recorder
 * needs except the script, which the preview already has.
 */
export type ControlDepthPassOptions = Omit<DepthPassRecorderProps, "sceneScript">;

/**
 * Pose the camera at the shot camera's keyframe for the duration of `run`.
 *
 * The camera object is the preview's own (its fov / aspect / near / far are the
 * render parameters); only position and orientation are borrowed, and they are
 * restored afterwards so OrbitControls — which re-derives the camera pose from
 * its own spherical state every frame — keeps driving the author's view.
 */
function withShotCameraPose<T>(
  camera: THREE.PerspectiveCamera,
  pose: { position: [number, number, number]; lookAt: [number, number, number] },
  run: () => T,
): T {
  const position = camera.position.clone();
  const quaternion = camera.quaternion.clone();
  const target = sceneToThreePosition(pose.lookAt);
  camera.position.set(...sceneToThreePosition(pose.position));
  camera.lookAt(target[0], target[1], target[2]);
  camera.updateMatrixWorld();
  try {
    return run();
  } finally {
    camera.position.copy(position);
    camera.quaternion.copy(quaternion);
    camera.updateMatrixWorld();
  }
}

export function DepthPassRecorder({
  sceneScript,
  onFrame,
  enabled = true,
}: DepthPassRecorderProps) {
  const { gl, scene, camera } = useThree();
  const { currentFrame } = useSceneScriptPlayback();

  const plan = useMemo(() => depthPassFramePlan(sceneScript.shots), [sceneScript]);
  const wanted = useMemo(() => new Set(plan.frames), [plan]);
  const cameras = useMemo(() => sceneScript.cameras as ShotCamera[], [sceneScript]);

  const onFrameRef = useRef(onFrame);
  onFrameRef.current = onFrame;
  const captureRef = useRef<DepthPassCapture | null>(null);
  const pendingRef = useRef<{ frame: number; shotId: string; armed: boolean } | null>(null);
  const capturedRef = useRef<ReadonlySet<number>>(new Set());
  const drawingBufferRef = useRef(new THREE.Vector2());

  // A new script is a new plan: the frames already shot belong to the old one.
  useEffect(() => {
    capturedRef.current = new Set();
    pendingRef.current = null;
  }, [plan]);

  // The capture object lives and dies with the renderer it renders into.
  useEffect(() => {
    if (!enabled) return;
    captureRef.current = new DepthPassCapture(gl);
    return () => {
      captureRef.current?.dispose();
      captureRef.current = null;
    };
  }, [gl, enabled]);

  // Arm the next planned frame the playhead reaches and has not shot yet.
  useEffect(() => {
    if (!enabled) return;
    if (!wanted.has(currentFrame) || capturedRef.current.has(currentFrame)) return;
    const owner = plan.frameShots.find((entry) => entry.frame === currentFrame);
    if (!owner) return;
    pendingRef.current = { frame: currentFrame, shotId: owner.shotId, armed: false };
  }, [currentFrame, enabled, wanted, plan]);

  useFrame(() => {
    const pending = pendingRef.current;
    if (!pending) return;
    // One callback of settle (see the timing note at the top of this file).
    if (!pending.armed) {
      pending.armed = true;
      return;
    }
    pendingRef.current = null;
    const capture = captureRef.current;
    if (!capture) return;
    const shot = sceneScript.shots.find((candidate) => candidate.id === pending.shotId) ?? null;
    const pose = shotCameraPoseAtFrame(cameras, shot, pending.frame);
    gl.getDrawingBufferSize(drawingBufferRef.current);
    const size = { width: drawingBufferRef.current.x, height: drawingBufferRef.current.y };
    const shoot = () => capture.capture(scene, camera, size);
    const frame = pose ? withShotCameraPose(camera, pose, shoot) : shoot();
    if (!frame) return;
    capturedRef.current = new Set(capturedRef.current).add(pending.frame);
    const capturedFrame = pending.frame;
    const cameraId = pose?.cameraId ?? null;
    void (async () => {
      // Encode off the render loop; `capture` has already read the pixels back,
      // so the GL work is done and only the PNG encode runs here.
      const blob = await encodeDepthPng(frame);
      await onFrameRef.current({
        frame: capturedFrame,
        fileName: depthPassFileName(capturedFrame),
        cameraId,
        blob,
        stats: { maxDepth: frame.maxDepth, geometryPixels: frame.geometryPixels },
      });
    })();
  });

  return null;
}

export default DepthPassRecorder;
