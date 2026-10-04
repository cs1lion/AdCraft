/**
 * Shot/camera labels — the human-readable side of the SceneScript camera model.
 *
 * The reference framework (docs/plans/scene3d-shot-preview-bridge.md) shows a
 * single 机位 as the join between three things that already exist separately:
 *
 *   SceneCamera  ──(SceneShot.camera)──►  SceneShot  ──(published_previs_clips
 *      id: "cam_1"      keyframes          id: "shot_1"     .shot_id)──►  clip
 *
 * What that framework has and this codebase does not is a NAME. Camera ids are
 * machine identifiers (`cam_1`, from `sceneScriptEditModel`'s `nextIndex`), and
 * `SceneShot.description` is free prose — so "机位05 | 飞船俯瞰" has nowhere to
 * live. Everything here derives that label from what already exists, so no new
 * storage and no second source of truth is introduced.
 *
 * All functions are pure: they are the only place the label format is decided,
 * and the viewport, the shot picker and the agent-facing reports must all agree
 * on it (a label two components spell differently is a label a reviewer cannot
 * search for).
 */

import type { SceneCamera, SceneScriptRoot, SceneShot } from "../../../types/scene-script";

/** Separator between the ordinal and the authored name, as in "机位05 | 飞船俯瞰". */
export const CAMERA_LABEL_SEPARATOR = " | ";

/** Zero-padded width for the ordinal: 机位01 … 机位12 (matches the reference). */
const CAMERA_ORDINAL_WIDTH = 2;

/**
 * The display label for a camera at `index` (its position in `script.cameras`).
 *
 * Precedance, and why: an authored `display_name` always wins because it is the
 * only part a human chose. Without one the ordinal alone is shown rather than
 * the raw id — `cam_1` is a machine identifier and showing it would make the
 * reviewer read a database key where a shot name belongs. `display_name` is
 * declared in the types for the additive schema change; until the backend
 * emits it every call falls through to the ordinal, which is the whole reason
 * this is safe to ship before that change lands.
 */
export function cameraLabel(camera: SceneCamera, index: number): string {
  const ordinal = `机位${String(index + 1).padStart(CAMERA_ORDINAL_WIDTH, "0")}`;
  const authored = camera.display_name?.trim();
  return authored ? `${ordinal}${CAMERA_LABEL_SEPARATOR}${authored}` : ordinal;
}

/**
 * A map from camera id to label, built once per script.
 *
 * The viewport renders a label per camera on every frame change, so the lookup
 * must not be O(cameras) per camera. Returns a plain object rather than a Map so
 * it can sit directly in a `useMemo` dependency list.
 */
export function cameraLabelsById(script: SceneScriptRoot): Record<string, string> {
  const labels: Record<string, string> = {};
  script.cameras.forEach((camera, index) => {
    labels[camera.id] = cameraLabel(camera, index);
  });
  return labels;
}

/**
 * The shot covering `frame`, or the first shot when the playhead sits in a gap.
 *
 * Gaps are real: `sceneScriptConsistency` already flags shots that leave one,
 * and an author scrubbing through a gap must still see *a* shot selected rather
 * than the viewport going blank. Falling back to the first shot (rather than
 * null) also keeps the shot picker stable while the author is mid-scrub.
 */
export function shotForFrame(script: SceneScriptRoot, frame: number): SceneShot | null {
  if (script.shots.length === 0) return null;
  const covering = script.shots.find(
    (shot) => frame >= shot.start_frame && frame <= shot.end_frame,
  );
  return covering ?? script.shots[0];
}

/** The camera a shot names, or null when the reference dangles. */
export function cameraForShot(script: SceneScriptRoot, shot: SceneShot | null): SceneCamera | null {
  if (!shot) return null;
  return script.cameras.find((camera) => camera.id === shot.camera) ?? null;
}

/**
 * The label for the shot covering `frame` — the title a shot preview card shows.
 *
 * Derived through the camera, because the shot itself carries no name: the shot
 * IS the camera's moment on the timeline, which is exactly the 1:1 mapping the
 * reference framework draws ("「机位05」对应的镜像段（4.5s-8.0s）").
 */
export function shotLabel(script: SceneScriptRoot, frame: number): string | null {
  const shot = shotForFrame(script, frame);
  const camera = cameraForShot(script, shot);
  if (!camera) return null;
  const index = script.cameras.findIndex((candidate) => candidate.id === camera.id);
  return cameraLabel(camera, index < 0 ? 0 : index);
}

/**
 * Seconds → `m:ss` for a frame-accurate timecode (25s total reads "00:25").
 *
 * Frames are converted with the script's own frame_rate rather than assuming
 * 30: a 24fps script and a 30fps script disagree about where 00:08 lands, and
 * the playhead label is the one number an author uses to align an audio cue.
 */
export function formatTimecode(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  const minutes = Math.floor(safe / 60);
  const remainder = Math.floor(safe % 60);
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

/**
 * The shot's span in seconds, at the script's frame rate.
 *
 * The `+ 1` matters: `start_frame`/`end_frame` are inclusive bounds and the
 * schema keeps consecutive shots contiguous with no gap, so a shot covering
 * frames 0..149 is 150 frames — 5.0s at 30fps, not 4.97s. `ShotStrip` measures
 * the same span for its bar widths (`endFrame - startFrame + 1`); a card that
 * disagreed with the strip about how long one shot is would put two different
 * numbers on the same length.
 */
export function shotDurationSeconds(shot: SceneShot, frameRate: number): number {
  return (shot.end_frame - shot.start_frame + 1) / frameRate;
}

// ---------------------------------------------------------------------------
// Per-segment edit report (the backend's `/scene-3d/*` `edit_report`)
// ---------------------------------------------------------------------------

/**
 * One change the backend's `scene_edit_report` can attribute to an object.
 * Stable strings: the renderer matches them to pick a label, so a new backend
 * code arrives as an unknown code rather than as a crash.
 */
export type SceneChangeCode =
  | "camera_moved"
  | "camera_aimed"
  | "camera_renamed"
  | "camera_shot_type"
  | "camera_added"
  | "camera_removed"
  | "object_moved"
  | "object_rotated"
  | "object_scaled"
  | "object_added"
  | "object_removed"
  | "character_action"
  | "shot_added"
  | "shot_removed"
  | "shot_repointed";

export interface SceneEditShotReport {
  id: string;
  camera_id: string;
  /** "机位05 | 飞船俯瞰" — the label the workbench spells everywhere. */
  camera_label: string;
  start_seconds: number;
  end_seconds: number;
  changes: SceneChangeCode[];
  objects_touched: string[];
}

export interface SceneEditReport {
  /** Object id → the change codes attributed to it. */
  changes: Record<string, SceneChangeCode[]>;
  /** Only the shots whose content or range changed; an untouched shot is not news. */
  shots: SceneEditShotReport[];
  shot_count: number;
  change_count: number;
  /** Change code → Chinese label, from the backend so every caller agrees. */
  labels: Record<string, string>;
}

/** Seconds for the report's span readout: "3s", "4.5s". */
export function formatSegmentSeconds(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  return safe % 1 === 0 ? `${safe.toFixed(0)}s` : `${safe.toFixed(1)}s`;
}

/**
 * "机位02 | 飞船俯瞰 的 3s–6s" — the one line the reference framework prints for
 * a delivered edit. Built here (not per caller) so the report panel, the
 * instruction confirmation and any future agent reply cannot spell one fact
 * three different ways.
 */
export function shotChangeHeadline(shot: SceneEditShotReport): string {
  const span = `${formatSegmentSeconds(shot.start_seconds)}–${formatSegmentSeconds(shot.end_seconds)}`;
  return `${shot.camera_label} 的 ${span}`;
}
