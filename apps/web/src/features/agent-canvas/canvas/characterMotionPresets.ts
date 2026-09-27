/**
 * Character motion presets — the blocking vocabulary for the 3D workbench.
 *
 * A camera has rigs; a character has blocking. Before this module the author
 * moved a character by typing position vectors into keyframes — which means
 * a walk across the room is nine keyframes of arithmetic and the facing is
 * wrong the whole way. These presets author the WHOLE move:
 *
 * 1. SAMPLED, not two-point: the renderer interpolates position/yaw
 *    LINEARLY, so a walk described by start + end slides through walls and
 *    furniture. Each preset samples the real path (every
 *    ``sample_step_frames``), so linear playback traces the move.
 * 2. FACING rides along: a walk turns the character toward where it is going
 *    (and a turn takes the SHORT way — never a 350° sweep for a -10° nudge).
 * 3. The preset owns its window: keys inside [start, start + duration] are
 *    replaced; everything else survives, so re-applying a longer move
 *    extends it instead of stacking contradictory keys.
 * 4. Actions follow the backend merge semantics: walking keys say "walk", the
 *    landing key says "stand", and a turn leaves actions untouched (the
 *    character can be mid-dialogue and still turn).
 * 5. THE SPEECH LAYER IS LOCKED (V0.2 §14.13 "锁住 Audio，只重做 Visual"):
 *    walk/approach frames that land inside a speech window keep action
 *    "talk" — the body may be re-blocked, the mouth may not be closed. The
 *    only way to change when the actor speaks is to redo the audio layer
 *    (re-apply lip-sync), which owns that channel by construction.
 *
 * Coordinates are SceneScript space (Blender Z-up: x=right, y=forward,
 * z=up); sceneScriptAxes converts once, at render.
 */

import type { CharacterKeyframe, SceneScriptRoot } from "../../../types/scene-script.ts";
import type { SceneVec3 } from "./sceneScriptAxes";

export type CharacterMotionPresetId = "walk_to" | "turn_to" | "approach" | "mark_talk";

export interface CharacterMotionPreset {
  id: CharacterMotionPresetId;
  /** UI label (Chinese, like the rest of the workbench). */
  label: string;
  /** One-line explanation of what the character will do. */
  description: string;
  /** Whether the preset needs a target (a position or another object). */
  needsTarget: boolean;
}

export const CHARACTER_MOTION_PRESETS: readonly CharacterMotionPreset[] = [
  {
    id: "walk_to",
    label: "走到",
    description: "直线走到目标点，途中面朝行进方向，到位立定",
    needsTarget: true,
  },
  {
    id: "turn_to",
    label: "转身面向",
    description: "原地转向目标（走最短弧），不影响位移与动作",
    needsTarget: true,
  },
  {
    id: "approach",
    label: "靠近至",
    description: "朝目标走近到指定距离并面朝它（对话机位常用）",
    needsTarget: true,
  },
  {
    id: "mark_talk",
    label: "标记说话",
    description: "在当前帧标记 talk（与台词浮层/唇形关键帧同一语义）",
    needsTarget: false,
  },
];

/** Keyframe density along the path (30fps: 15 frames = 0.5s per sample). */
export const CHARACTER_MOTION_SAMPLE_STEP_FRAMES = 15;

/** Default stand-off distance for `approach` (metres). */
export const APPROACH_DEFAULT_STOP_DISTANCE = 1.2;

export class UnknownCharacterPresetError extends Error {
  readonly code = "character_preset_unknown";

  constructor(presetId: string) {
    super(`Unknown character motion preset: ${presetId}`);
    this.name = "UnknownCharacterPresetError";
  }
}

export interface CharacterMotionOptions {
  /** First frame of the move (inclusive). */
  startFrame: number;
  /** Move length in frames (>= 1). */
  durationFrames: number;
  /** Destination in SceneScript space (for the target-based presets). */
  target: SceneVec3;
  /** Stand-off distance for `approach`. */
  stopDistance?: number;
}

function distance2D(a: readonly number[], b: readonly number[]): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

/** Yaw (degrees, [0,360)) that faces `from` toward `to` in the X/Y plane. */
export function yawFacing(from: SceneVec3, to: SceneVec3): number {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const degrees = (Math.atan2(dx, dy) * 180) / Math.PI;
  return ((degrees % 360) + 360) % 360;
}

/** Interpolate yaw the SHORT way (a -10° nudge is not a 350° sweep). */
function lerpYaw(from: number, to: number, t: number): number {
  const delta = ((to - from + 540) % 360) - 180;
  const raw = from + delta * t;
  return ((raw % 360) + 360) % 360;
}

function sampleFrames(startFrame: number, durationFrames: number): number[] {
  const step = Math.max(1, CHARACTER_MOTION_SAMPLE_STEP_FRAMES);
  const frames: number[] = [];
  for (let frame = startFrame; frame <= startFrame + durationFrames; frame += step) {
    frames.push(frame);
  }
  const last = startFrame + durationFrames;
  if (frames[frames.length - 1] !== last) frames.push(last);
  return frames;
}

/** The character's pose at the anchor frame (existing keys or a stand at 0). */
function anchorPose(characterKeyframes: readonly CharacterKeyframe[], startFrame: number) {
  const atOrBefore = [...characterKeyframes]
    .filter((keyframe) => keyframe.frame <= startFrame)
    .sort((a, b) => b.frame - a.frame)[0];
  const chosen = atOrBefore ?? characterKeyframes[0];
  return {
    position: [...(chosen?.position ?? [0, 0, 0])] as SceneVec3,
    rotationY: chosen?.rotation_y ?? 0,
    action: chosen?.action ?? "stand",
  };
}

/**
 * Is the character SPEAKING at `frame`? Nearest-at-or-before semantics (same
 * as the preview's action lookup): a lip-sync run writes `talk` at a line's
 * start and `stand` at its end, so everything between them is the speech
 * window. This is the predicate that LOCKS THE AUDIO LAYER (V0.2 §14.13):
 * a visual redo (motion preset) may move the body but must not close the
 * mouth — re-doing the look is never allowed to silently mute the actor.
 */
export function isSpeakingAtFrame(
  characterKeyframes: readonly CharacterKeyframe[],
  frame: number,
): boolean {
  const ordered = [...characterKeyframes].sort((a, b) => a.frame - b.frame);
  const atOrBefore = [...ordered].reverse().find((keyframe) => keyframe.frame <= frame);
  const chosen = atOrBefore ?? ordered[0];
  return chosen?.action === "talk";
}

/** How many of a preset's sampled frames would land inside a speech window. */
export function countSpeakingFramesInWindow(
  characterKeyframes: readonly CharacterKeyframe[],
  startFrame: number,
  durationFrames: number,
): number {
  return sampleFrames(startFrame, durationFrames).filter((frame) =>
    isSpeakingAtFrame(characterKeyframes, frame),
  ).length;
}

/**
 * Apply a motion preset to a character, replacing keyframes inside the window.
 * Pure: returns a new SceneScriptRoot; unknown presets fail loud.
 */
export function applyCharacterMotionPreset(
  sceneScript: SceneScriptRoot,
  characterId: string,
  presetId: CharacterMotionPresetId,
  options: CharacterMotionOptions,
): SceneScriptRoot {
  if (!CHARACTER_MOTION_PRESETS.some((preset) => preset.id === presetId)) {
    throw new UnknownCharacterPresetError(presetId);
  }
  const character = sceneScript.characters.find((candidate) => candidate.id === characterId);
  if (!character) {
    throw new Error(`Character not found: ${characterId}`);
  }
  const startFrame = Math.max(0, Math.round(options.startFrame));
  const durationFrames = Math.max(1, Math.round(options.durationFrames));
  const anchor = anchorPose(character.keyframes, startFrame);
  const frames = sampleFrames(startFrame, durationFrames);
  const endFrame = startFrame + durationFrames;
  const target = options.target;

  let nextKeyframes: CharacterKeyframe[];

  switch (presetId) {
    case "mark_talk": {
      // A single key at the start frame. The window clear happens in the
      // shared merge below (NOT here — filtering twice would duplicate the
      // surviving keys).
      nextKeyframes = [
        {
          frame: startFrame,
          position: anchor.position,
          rotation_y: anchor.rotationY,
          action: "talk",
        },
      ];
      break;
    }
    case "turn_to": {
      const targetYaw = yawFacing(anchor.position, target);
      nextKeyframes = frames.map((frame) => {
        const t = durationFrames === 0 ? 0 : (frame - startFrame) / durationFrames;
        const existing = character.keyframes.find((keyframe) => keyframe.frame === frame);
        return {
          frame,
          // Turn in place: position is inherited from the authored pose so a
          // character mid-walk keeps its arc.
          position: existing?.position ?? anchor.position,
          rotation_y: Math.round(lerpYaw(anchor.rotationY, targetYaw, t) * 100) / 100,
          // A turn never clobbers the action: the character may be talking.
          action: existing?.action ?? anchor.action,
        };
      });
      break;
    }
    case "walk_to":
    case "approach": {
      const destination: SceneVec3 =
        presetId === "walk_to"
          ? [target[0], target[1], anchor.position[2]]
          : (() => {
              const reach = Math.max(0, options.stopDistance ?? APPROACH_DEFAULT_STOP_DISTANCE);
              const gap = distance2D(anchor.position, target);
              if (gap <= reach + 1e-6) return [anchor.position[0], anchor.position[1], anchor.position[2]];
              const ratio = (gap - reach) / gap;
              return [
                anchor.position[0] + (target[0] - anchor.position[0]) * ratio,
                anchor.position[1] + (target[1] - anchor.position[1]) * ratio,
                anchor.position[2],
              ];
            })();
      const arrivalYaw = yawFacing(anchor.position, target);
      nextKeyframes = frames.map((frame, index) => {
        const t = durationFrames === 0 ? 0 : (frame - startFrame) / durationFrames;
        const isLanding = index === frames.length - 1;
        return {
          frame,
          position: [
            anchor.position[0] + (destination[0] - anchor.position[0]) * t,
            anchor.position[1] + (destination[1] - anchor.position[1]) * t,
            // Height is preserved: a walk is a floor move, not a levitation.
            anchor.position[2],
          ] as SceneVec3,
          rotation_y: Math.round(lerpYaw(anchor.rotationY, arrivalYaw, t) * 100) / 100,
          // The speech layer is locked (V0.2 §14.13): on a speaking frame the
          // action stays "talk" — the character walks WHILE talking. To change
          // when the mouth opens/closes, redo the audio layer (re-apply
          // lip-sync); a visual redo may never silently mute the actor.
          action: isSpeakingAtFrame(character.keyframes, frame)
            ? "talk"
            : isLanding
              ? "stand"
              : "walk",
        };
      });
      break;
    }
  }

  const outside = character.keyframes.filter(
    (keyframe) => keyframe.frame < startFrame || keyframe.frame > endFrame,
  );
  const merged = [...outside, ...nextKeyframes].sort((a, b) => a.frame - b.frame);

  return {
    ...sceneScript,
    characters: sceneScript.characters.map((candidate) =>
      candidate.id === characterId ? { ...candidate, keyframes: merged } : candidate,
    ),
  };
}
