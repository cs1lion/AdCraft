/**
 * Pure SceneScript edit operations for the 3D director workbench (P1).
 *
 * Every operation is immutable: it returns a new `SceneScriptRoot` and never
 * mutates the input, so React state updates and optimistic canvas patches
 * stay predictable. The operations here are the ONLY writers the interactive
 * viewport uses — the same model is what an agent-side SceneScript tool
 * service would mirror on the backend, keeping the canonical format single.
 *
 * Keyframe semantics: editing a character or camera at frame F writes the
 * keyframe at F — updating it when one exists at exactly F, inserting a new
 * (sorted) keyframe otherwise. This makes "edit at the current frame" and
 * "capture a keyframe at the current frame" the same gesture, which is what
 * makes the blade of an animation editable without a separate keyframe
 * editor.
 */

import type {
  CameraKeyframe,
  CharacterKeyframe,
  CharacterAppearance,
  SceneCamera,
  SceneCharacter,
  SceneEnvironment,
  SceneProp,
  SceneScriptRoot,
  SceneShot,
} from "../../../types/scene-script";
import type { SceneVec3 } from "./sceneScriptAxes";
import { resolvePropFallback, resolveEnvironmentFallback, buildFallbackReport } from "./propTypeFallback.ts";

export type SceneScriptObjectKind = "character" | "prop" | "environment" | "camera";

export interface SceneObjectRef {
  kind: SceneScriptObjectKind;
  id: string;
}

/** Round to 2 decimals: the schema/frames stay clean and ETags stay stable. */
function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function roundVec3(position: SceneVec3): SceneVec3 {
  return [round2(position[0]), round2(position[1]), round2(position[2])];
}

function replaceCharacter(
  script: SceneScriptRoot,
  id: string,
  replace: (character: SceneCharacter) => SceneCharacter,
): SceneScriptRoot {
  let found = false;
  const characters = script.characters.map((character) => {
    if (character.id !== id) return character;
    found = true;
    return replace(character);
  });
  if (!found) {
    throw new SceneScriptEditError(
      "scene_script_object_not_found",
      `SceneScript has no character '${id}'.`,
    );
  }
  return { ...script, characters };
}

function replacePropOrEnvironment(
  script: SceneScriptRoot,
  kind: "prop" | "environment",
  id: string,
  replace: (object: SceneProp | SceneEnvironment) => SceneProp | SceneEnvironment,
): SceneScriptRoot {
  const key = kind === "prop" ? "props" : "environment";
  let found = false;
  const objects = script[key].map((object) => {
    if (object.id !== id) return object;
    found = true;
    return replace(object);
  });
  if (!found) {
    throw new SceneScriptEditError(
      "scene_script_object_not_found",
      `SceneScript has no ${kind} '${id}'.`,
    );
  }
  return { ...script, [key]: objects };
}

function replaceCamera(
  script: SceneScriptRoot,
  id: string,
  replace: (camera: SceneCamera) => SceneCamera,
): SceneScriptRoot {
  let found = false;
  const cameras = script.cameras.map((camera) => {
    if (camera.id !== id) return camera;
    found = true;
    return replace(camera);
  });
  if (!found) {
    throw new SceneScriptEditError(
      "scene_script_object_not_found",
      `SceneScript has no camera '${id}'.`,
    );
  }
  return { ...script, cameras };
}

/**
 * Upsert a keyframe in a sorted-by-frame list.
 *
 * Same-frame keyframes are replaced (re-capturing a frame is an edit, not a
 * duplicate); other frames keep their identity so unrelated animation is
 * untouched by an edit elsewhere on the timeline.
 */
function upsertKeyframe<T extends { frame: number }>(
  keyframes: T[],
  frame: number,
  merge: (existing: T | undefined) => T,
): T[] {
  const index = keyframes.findIndex((keyframe) => keyframe.frame === frame);
  if (index >= 0) {
    const next = [...keyframes];
    next[index] = merge(keyframes[index]);
    return next;
  }
  return [...keyframes, merge(undefined)].sort((a, b) => a.frame - b.frame);
}

export class SceneScriptEditError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "SceneScriptEditError";
    this.code = code;
  }
}

/** Nearest existing keyframe's rotation/action, for inherited continuities. */
function nearestKeyframe<T extends { frame: number }>(
  keyframes: T[],
  frame: number,
): T | undefined {
  if (keyframes.length === 0) return undefined;
  let best = keyframes[0];
  for (const keyframe of keyframes) {
    // Ties prefer the LATER keyframe: a frame inserted mid-segment adopts the
    // pose/animation it is heading toward, which is what a drag-in-progress
    // should look like.
    if (Math.abs(keyframe.frame - frame) <= Math.abs(best.frame - frame)) best = keyframe;
  }
  return best;
}

/** Move a character: writes (or inserts) the keyframe at `frame`. */
export function moveCharacterAtFrame(
  script: SceneScriptRoot,
  characterId: string,
  frame: number,
  position: SceneVec3,
): SceneScriptRoot {
  return replaceCharacter(script, characterId, (character) => ({
    ...character,
    keyframes: upsertKeyframe<CharacterKeyframe>(character.keyframes, frame, (existing) => {
      // Inherit rotation/action from the same-or-nearest keyframe so dragging
      // a character mid-animation never snaps its facing or pose to zero.
      const inherited = existing ?? nearestKeyframe(character.keyframes, frame);
      return {
        frame,
        position: roundVec3(position),
        rotation_y: inherited?.rotation_y ?? 0,
        action: inherited?.action ?? "stand",
      };
    }),
  }));
}

/** Rotate a character: writes (or inserts) the keyframe at `frame`. */
export function rotateCharacterAtFrame(
  script: SceneScriptRoot,
  characterId: string,
  frame: number,
  rotationYDegrees: number,
): SceneScriptRoot {
  return replaceCharacter(script, characterId, (character) => ({
    ...character,
    keyframes: upsertKeyframe<CharacterKeyframe>(character.keyframes, frame, (existing) => {
      const inherited = existing ?? nearestKeyframe(character.keyframes, frame);
      return {
        frame,
        position: inherited?.position ?? [0, 0, 0],
        rotation_y: round2(((rotationYDegrees % 360) + 360) % 360),
        action: inherited?.action ?? "stand",
      };
    }),
  }));
}

/** Current static position of a character at `frame` (interpolated to the frame). */
export function characterPositionAtFrame(
  character: SceneCharacter,
  frame: number,
): SceneVec3 {
  return characterStateAtFrame(character, frame).position;
}

/**
 * The character's action at `frame` — the nearest keyframe's action, with
 * the same inheritance the backend's lip-sync merge uses (a keyframe holds
 * its action until the next one that declares one).
 *
 * This is what makes speech VISIBLE in the 3D viewport: the lip-sync writes
 * `talk` keyframes, and the preview must open a mouth at exactly the frames
 * the Blender render will.
 */
export function characterActionAtFrame(
  character: SceneCharacter,
  frame: number,
): string | null {
  const keyframes = character.keyframes;
  if (keyframes.length === 0) return null;
  // Before the first keyframe: the first declared action governs (the
  // character existed before the first authored pose).
  let current: string | null = null;
  for (const keyframe of keyframes) {
    // A keyframe's action governs frames AT and AFTER it — never before.
    if (keyframe.frame > frame) return current;
    if (keyframe.action) current = keyframe.action;
  }
  return current;
}

/**
 * Interpolated character state (position in SceneScript coords + yaw
 * degrees) at `frame`. Single source of truth shared by the preview
 * renderer and the inspector readouts.
 */export function characterStateAtFrame(
  character: SceneCharacter,
  frame: number,
): { position: SceneVec3; rotationY: number } {
  const keyframes = character.keyframes;
  if (keyframes.length === 0) return { position: [0, 0, 0], rotationY: 0 };
  if (keyframes.length === 1 || frame <= keyframes[0].frame) {
    return { position: keyframes[0].position, rotationY: keyframes[0].rotation_y };
  }
  const last = keyframes[keyframes.length - 1];
  if (frame >= last.frame) return { position: last.position, rotationY: last.rotation_y };
  for (let index = 0; index < keyframes.length - 1; index += 1) {
    const a = keyframes[index];
    const b = keyframes[index + 1];
    if (frame >= a.frame && frame <= b.frame) {
      const t = (frame - a.frame) / (b.frame - a.frame || 1);
      return {
        position: [
          a.position[0] + (b.position[0] - a.position[0]) * t,
          a.position[1] + (b.position[1] - a.position[1]) * t,
          a.position[2] + (b.position[2] - a.position[2]) * t,
        ],
        rotationY: a.rotation_y + (b.rotation_y - a.rotation_y) * t,
      };
    }
  }
  return { position: keyframes[0].position, rotationY: keyframes[0].rotation_y };
}

/**
 * A prop or environment object's state at `frame`.
 *
 * Third interpolation of the same rule in the codebase (after
 * `characterStateAtFrame` here and `held_items._pose_at` on the backend), and
 * deliberately the same shape: shared keyframes between two frames, clamped
 * outside their span. They are kept separate rather than unified because a
 * prop's keyframe carries a full rotation triple and a scale where a
 * character's carries an `action`, and merging the models would force one to
 * carry the other's field.
 *
 * `keyframes` empty returns null so callers can fall through to the authored
 * rest pose without special-casing: a prop that has never moved is not a
 * different code path, it is the same one with no keyframes.
 */
export function propStateAtFrame(
  prop: {
    position: SceneVec3;
    rotation_y?: number;
    scale?: number;
    keyframes?: readonly {
      frame: number;
      position: SceneVec3;
      rotation?: readonly number[];
      scale?: number | null;
    }[];
  },
  frame: number,
): { position: SceneVec3; rotation: [number, number, number]; scale?: number } | null {
  const keyframes = prop.keyframes;
  if (!keyframes || keyframes.length === 0) return null;

  const rotationOf = (keyframe: (typeof keyframes)[number]): [number, number, number] => {
    // A keyframe may state only the axes it changes; the rest fall back to the
    // authored rest yaw so a partial keyframe is not a teleport to 0.
    const rotation = keyframe.rotation ?? [0, prop.rotation_y ?? 0, 0];
    return [rotation[0] ?? 0, rotation[1] ?? 0, rotation[2] ?? 0];
  };
  const at = (keyframe: (typeof keyframes)[number]) => ({
    position: keyframe.position,
    rotation: rotationOf(keyframe),
    scale: keyframe.scale ?? prop.scale,
  });

  const first = keyframes[0];
  if (keyframes.length === 1 || frame <= first.frame) return at(first);
  const last = keyframes[keyframes.length - 1];
  if (frame >= last.frame) return at(last);

  for (let index = 0; index < keyframes.length - 1; index += 1) {
    const a = keyframes[index];
    const b = keyframes[index + 1];
    if (frame >= a.frame && frame <= b.frame) {
      const t = (frame - a.frame) / (b.frame - a.frame || 1);
      const from = at(a);
      const to = at(b);
      return {
        position: [
          from.position[0] + (to.position[0] - from.position[0]) * t,
          from.position[1] + (to.position[1] - from.position[1]) * t,
          from.position[2] + (to.position[2] - from.position[2]) * t,
        ],
        rotation: [
          from.rotation[0] + (to.rotation[0] - from.rotation[0]) * t,
          from.rotation[1] + (to.rotation[1] - from.rotation[1]) * t,
          from.rotation[2] + (to.rotation[2] - from.rotation[2]) * t,
        ],
        scale: from.scale === undefined || to.scale === undefined
          ? undefined
          : from.scale + (to.scale - from.scale) * t,
      };
    }
  }
  return at(first);
}

/**
 * Add an environment object (or prop) from a palette kind, at a default
 * spiral position so repeated clicks never stack into one spot. The kind is
 * validated against the generated enum lists by the caller (the tray UI);
 * an unknown kind fails loudly here rather than rendering as a silent box.
 */
export function addEnvironmentObject(
  script: SceneScriptRoot,
  kind: string,
  options: { id?: string; scale?: number; rotationY?: number; position?: SceneVec3 } = {},
): SceneScriptRoot {
  const id = options.id ?? nextFreeId(script.environment.map((object) => object.id), "env");
  const index = script.environment.length;
  const resolvedKind = resolveEnvironmentFallback(kind) ?? kind; // degrade unknown types in place
  return {
    ...script,
    environment: [
      ...script.environment,
      {
        id,
        type: resolvedKind as unknown as import("../../../types/scene-script.generated").EnvironmentTypeName,
        position: options.position ? roundVec3(options.position) : spiralPosition(index),
        scale: options.scale ?? 1,
        rotation_y: options.rotationY ?? 0,
      },
    ],
  };
}

export function addPropObject(
  script: SceneScriptRoot,
  kind: string,
  options: { id?: string; scale?: number; rotationY?: number; position?: SceneVec3 } = {},
): SceneScriptRoot {
  const id = options.id ?? nextFreeId(script.props.map((object) => object.id), "prop");
  const index = script.props.length;
  const resolvedKind = resolvePropFallback(kind) ?? kind; // degrade unknown types in place
  return {
    ...script,
    props: [
      ...script.props,
      {
        id,
        type: resolvedKind as unknown as import("../../../types/scene-script.generated").PropTypeName,
        position: options.position ? roundVec3(options.position) : spiralPosition(index),
        scale: options.scale ?? 1,
        rotation_y: options.rotationY ?? 0,
      },
    ],
  };
}

/** Deterministic placement ring: each new object lands further around. */
function spiralPosition(index: number): SceneVec3 {
  const golden = 2.39996; // radians; even angular spacing without clustering
  const angle = index * golden;
  const radius = 1.6 + 0.5 * Math.min(index, 6);
  return [
    Math.round(Math.cos(angle) * radius * 100) / 100,
    Math.round(Math.sin(angle) * radius * 100) / 100,
    0,
  ];
}

/** Smallest `prefix_N` not already used (collisions never happen silently). */
function nextFreeId(existing: string[], prefix: string): string {
  let index = 1;
  const used = new Set(existing);
  while (used.has(`${prefix}_${index}`)) index += 1;
  return `${prefix}_${index}`;
}

/** Move a prop (static object): writes `position` directly. */
/**
 * A character asset dropped onto the scene joins the cast (V0.2 §2.1: 人物 →
 * 拖到镜头：成为该镜头的角色). The character carries the asset as its
 * identity binding — the Dramagic lock the consistency gate checks — and a
 * deterministic appearance colour, because in the low-fidelity previs the
 * colour IS the identity channel (two same-coloured characters are
 * indistinguishable to a reviewer AND to the video model's reference
 * mapping).
 *
 * Idempotent per asset: dropping the same character twice must not create a
 * duplicate cast member (a second copy would read as two people while the
 * binding says one).
 */
/**
 * Declare (or clear) a character's wardrobe palette (V0.2 §5 服装).
 *
 * WHY THIS EXISTS AS A FIELD: within one SceneScript a character has exactly
 * one appearance, so a scene cannot contradict itself about her jacket. The
 * workflow's scene-3d nodes each hold their OWN script, so "Scene 02 把她
 * 换成黑风衣" CAN be authored — and nobody painting scene 02 can see what
 * scene 03 declared. The palette is the declaration; the cross-node gate
 * (``wardrobe_drift.check_cross_node_character_drift``) refuses to guess
 * which one is right.
 *
 * The colours are the AUTHOR's call, not derived from the bound asset's image:
 * the previs is a proxy, and a proxy that invents the character's colours
 * would be lying about the one thing the asset binding is supposed to pin.
 */
export const MAX_APPEARANCE_PALETTE_COLORS = 4;

export function setCharacterPalette(
  script: SceneScriptRoot,
  characterId: string,
  palette: (string | null)[],
): SceneScriptRoot {
  const normalized = palette
    .filter((entry): entry is string => typeof entry === "string" && entry.length > 0)
    .map((entry) => entry.toUpperCase())
    .slice(0, MAX_APPEARANCE_PALETTE_COLORS);
  return {
    ...script,
    characters: script.characters.map((character) =>
      character.id === characterId
        ? {
            ...character,
            appearance: {
              ...character.appearance,
              palette: normalized.length > 0 ? normalized : null,
            },
          }
        : character,
    ),
  };
}

/**
 * Record how a shot ENTERS (V0.2 §13 第 5 问: 哪一镜以何种读法接入).
 *
 * §13 asks whether the relation needs a connector LINE or suits a label, a
 * status, a hint, or hiding. The label wins here: a reading is ALREADY
 * authored as keyframes inside the script (camera + character motion), so a
 * line would be a second copy of the same information that can disagree with
 * the first. What was missing is that the CHOICE was not recorded — the cut
 * the author picked left no answer that outlived the pick, so "哪一镜以什么读法
 * 接入" could not be asked, shown on the strip, or checked at the boundary.
 *
 * ``null`` clears the declaration: not every shot has a reading worth naming
 * (a first shot has no entry, and some cuts are just cuts).
 */
/**
 * Bind a prop to the asset it is derived from (the Dramagic lock, past
 * characters).
 *
 * ``SceneProp.prop_asset_id`` exists in the schema and the executor's
 * reference applier even stamps it when a prop reference is unambiguous — but
 * nothing on the canvas path could set it, so a prop the author DID bind by
 * hand had nowhere to be recorded, and one the applier stamped had nowhere to
 * be seen. Passing ``null`` unbinds (a prop the author is still shaping has no
 * source yet, and inventing one would make the lock lie).
 */
export function bindPropAsset(
  script: SceneScriptRoot,
  propId: string,
  assetId: string | null,
): SceneScriptRoot {
  return {
    ...script,
    props: script.props.map((prop) =>
      prop.id === propId ? { ...prop, prop_asset_id: assetId || null } : prop,
    ),
  };
}

/** Bind an environment object to the scene asset it is from (same lock). */
export function bindEnvironmentAsset(
  script: SceneScriptRoot,
  objectId: string,
  assetId: string | null,
): SceneScriptRoot {
  return {
    ...script,
    environment: script.environment.map((object) =>
      object.id === objectId ? { ...object, scene_asset_id: assetId || null } : object,
    ),
  };
}

export function setShotTransitionIntent(
  script: SceneScriptRoot,
  shotId: string,
  readingId: string | null,
): SceneScriptRoot {
  const normalized = readingId?.trim() ?? "";
  return {
    ...script,
    shots: script.shots.map((shot) =>
      shot.id === shotId
        ? { ...shot, transition_intent: normalized.length > 0 ? normalized : null }
        : shot,
    ),
  };
}

/**
 * Add a plain lowpoly_human character (language builder / quick add) — no
 * bound asset. Positioned via a frame-0 keyframe: the schema has no
 * top-level position on characters and requires at least one keyframe, so
 * anything else the gate rejects on save.
 */
export function addCharacterObject(
  script: SceneScriptRoot,
  options: { id?: string; position?: SceneVec3; appearance?: CharacterAppearance } = {},
): SceneScriptRoot {
  const id = options.id ?? nextFreeId(script.characters.map((character) => character.id), "char");
  const index = script.characters.length;
  return {
    ...script,
    characters: [
      ...script.characters,
      {
        id,
        type: "lowpoly_human",
        character_asset_id: null,
        appearance: options.appearance ?? {
          color: nextCastColor(script, index),
          height: 1.7,
          scale: 1,
        },
        keyframes: [
          {
            frame: 0,
            position: options.position ? roundVec3(options.position) : castPosition(index),
            rotation_y: 0,
            action: "stand",
          },
        ],
      },
    ],
  };
}

export function addCharacterFromAsset(
  script: SceneScriptRoot,
  asset: { assetId: string; displayName: string },
): SceneScriptRoot {
  if (script.characters.some((character) => character.character_asset_id === asset.assetId)) {
    return script; // already in the cast
  }
  const id = nextFreeId(script.characters.map((character) => character.id), "char");
  const index = script.characters.length;
  return {
    ...script,
    characters: [
      ...script.characters,
      {
        id,
        type: "lowpoly_human",
        character_asset_id: asset.assetId,
        appearance: {
          color: nextCastColor(script, index),
          height: 1.7,
          scale: 1,
        },
        keyframes: [
          {
            frame: 0,
            position: castPosition(index),
            rotation_y: 0,
            action: "stand",
          },
        ],
      },
    ],
  };
}

/** A hue no existing cast member already wears (the colour is the identity). */
function nextCastColor(script: SceneScriptRoot, index: number): string {
  const taken = script.characters.map(
    (character) => character.appearance?.color ?? "#8B4513",
  );
  // Golden-angle hue steps: a new character lands far from the ones before
  // it, and the same script always yields the same colour (deterministic).
  for (let step = 0; step < 12; step += 1) {
    const hue = Math.round(((index * 137.508 + step * 47) % 360 + 360) % 360);
    const candidate = hslToHex(hue, 0.55, 0.42);
    if (taken.every((color) => colorDistance(color, candidate) > 60)) {
      return candidate;
    }
  }
  return hslToHex((index * 137.508) % 360, 0.55, 0.42);
}

/** Cast members stand on a ring so a new one never lands on an existing one. */
function castPosition(index: number): SceneVec3 {
  const golden = 2.39996;
  const angle = index * golden;
  const radius = 1.8 + 0.6 * Math.min(index, 6);
  return [
    Math.round(Math.cos(angle) * radius * 100) / 100,
    Math.round(Math.sin(angle) * radius * 100) / 100,
    0,
  ];
}

function hslToHex(hue: number, saturation: number, lightness: number): string {
  const c = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const x = c * (1 - Math.abs(((hue / 60) % 2) - 1));
  const m = lightness - c / 2;
  const [r, g, b] = (
    hue < 60 ? [c, x, 0]
    : hue < 120 ? [x, c, 0]
    : hue < 180 ? [0, c, x]
    : hue < 240 ? [0, x, c]
    : hue < 300 ? [x, 0, c]
    : [c, 0, x]
  ) as [number, number, number];
  const toHex = (value: number) =>
    Math.round((value + m) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`.toUpperCase();
}

function colorDistance(left: string, right: string): number {
  const parse = (hex: string): [number, number, number] => [
    Number.parseInt(hex.slice(1, 3), 16),
    Number.parseInt(hex.slice(3, 5), 16),
    Number.parseInt(hex.slice(5, 7), 16),
  ];
  const [r1, g1, b1] = parse(left);
  const [r2, g2, b2] = parse(right);
  return Math.sqrt((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2);
}

export function moveProp(
  script: SceneScriptRoot,
  propId: string,
  position: SceneVec3,
): SceneScriptRoot {
  return replacePropOrEnvironment(script, "prop", propId, (prop) => ({
    ...prop,
    position: roundVec3(position),
  }));
}

/** Move an environment object (static): writes `position` directly. */
export function moveEnvironment(
  script: SceneScriptRoot,
  environmentId: string,
  position: SceneVec3,
): SceneScriptRoot {
  return replacePropOrEnvironment(script, "environment", environmentId, (object) => ({
    ...object,
    position: roundVec3(position),
  }));
}

/** Rotate a static object (prop or environment) in degrees. */
export function rotateStaticObject(
  script: SceneScriptRoot,
  kind: "prop" | "environment",
  id: string,
  rotationYDegrees: number,
): SceneScriptRoot {
  const normalized = round2(((rotationYDegrees % 360) + 360) % 360);
  return replacePropOrEnvironment(script, kind, id, (object) => ({
    ...object,
    rotation_y: normalized,
  }));
}

/** Scale a static object (props clamp 0.1–10, environment 0.1–50). */
export function scaleStaticObject(
  script: SceneScriptRoot,
  kind: "prop" | "environment",
  id: string,
  scale: number,
): SceneScriptRoot {
  const limit = kind === "prop" ? 10 : 50;
  const clamped = Math.min(limit, Math.max(0.1, round2(scale)));
  return replacePropOrEnvironment(script, kind, id, (object) => ({
    ...object,
    scale: clamped,
  }));
}

/**
 * Declare a held item (V0.2 §5 Continuity State): the prop follows the named
 * character's hand on every surface, so it cannot vanish or switch hands at a
 * cut. Passing a null holder releases it back to its authored rest position.
 * Only props can be held; environment objects are fixed by definition.
 */
export function setPropHeld(
  script: SceneScriptRoot,
  id: string,
  heldBy: string | null,
  heldSide: "left" | "right" | null,
): SceneScriptRoot {
  return replacePropOrEnvironment(script, "prop", id, (object) =>
    heldBy
      ? { ...object, held_by: heldBy, held_side: heldSide ?? "right" }
      : { ...object, held_by: null, held_side: null },
  );
}

/** Move a camera: upserts the keyframe at `frame` (position only). */
export function moveCameraAtFrame(
  script: SceneScriptRoot,
  cameraId: string,
  frame: number,
  position: SceneVec3,
): SceneScriptRoot {
  return replaceCamera(script, cameraId, (camera) => ({
    ...camera,
    keyframes: upsertKeyframe<CameraKeyframe>(camera.keyframes, frame, (existing) => ({
      frame,
      position: roundVec3(position),
      look_at: existing?.look_at ?? [0, 0, 1],
    })),
  }));
}

/** Set a camera's look-at target: upserts the keyframe at `frame`. */
export function setCameraLookAtAtFrame(
  script: SceneScriptRoot,
  cameraId: string,
  frame: number,
  lookAt: SceneVec3,
): SceneScriptRoot {
  return replaceCamera(script, cameraId, (camera) => ({
    ...camera,
    keyframes: upsertKeyframe<CameraKeyframe>(camera.keyframes, frame, (existing) => ({
      frame,
      position: existing?.position ?? [0, 0, 0],
      look_at: roundVec3(lookAt),
    })),
  }));
}

/** Change a camera's shot type (schema enum; `top_down` kept for parity). */
export function setCameraShotType(
  script: SceneScriptRoot,
  cameraId: string,
  shotType: string,
): SceneScriptRoot {
  return replaceCamera(script, cameraId, (camera) => ({
    ...camera,
    shot_type: shotType,
  }));
}

/**
 * Add a brand-new camera + its shot at a viewport-placed position.
 *
 * The new shot starts after the last existing shot ends (the schema forbids
 * overlapping shots) and runs at least one second; if that pushes past the
 * current scene length, the scene duration is extended to fit. This is the
 * spontaneous-camera flow: click twice in the viewport and a new shot exists.
 */
export function addCameraAtFrame(
  script: SceneScriptRoot,
  placement: {
    position: SceneVec3;
    lookAt: SceneVec3;
    shotType?: string;
    description?: string;
    minShotFrames?: number;
  },
): SceneScriptRoot {
  const fps = script.scene.frame_rate || 30;
  const lastEnd = script.shots.reduce((max, shot) => Math.max(max, shot.end_frame), -1);
  const startFrame = lastEnd + 1;
  const shotLength = Math.max(30, placement.minShotFrames ?? 30);
  const endFrame = startFrame + shotLength - 1;

  // Extend the scene when the new shot does not fit (duration is seconds).
  const requiredDuration = (endFrame + 1) / fps;
  const scene =
    requiredDuration > script.scene.duration
      ? { ...script.scene, duration: Math.ceil(requiredDuration * 100) / 100 }
      : script.scene;

  const cameraIndex = nextIndex(script.cameras.map((camera) => camera.id), "cam");
  const shotIndex = nextIndex(script.shots.map((shot) => shot.id), "shot");
  const cameraId = `cam_${cameraIndex}`;
  const shotId = `shot_${shotIndex}`;

  const camera: SceneCamera = {
    id: cameraId,
    shot_type: placement.shotType ?? "wide",
    keyframes: [
      {
        frame: startFrame,
        position: roundVec3(placement.position),
        look_at: roundVec3(placement.lookAt),
      },
    ],
  };
  const shot: SceneShot = {
    id: shotId,
    camera: cameraId,
    start_frame: startFrame,
    end_frame: endFrame,
    description: placement.description ?? "placed camera",
  };
  return {
    ...script,
    scene,
    cameras: [...script.cameras, camera],
    shots: [...script.shots, shot],
  };
}

/**
 * Insert a new shot at the END of an existing shot (V0.2 §2.2: 两个镜头之间
 * = 新镜头插入). The shot's tail is split off and handed to a new shot that
 * reuses the SAME camera — an inserted shot is a continuation of the same
 * viewpoint, not a new one the author has to place (placing stays explicit).
 *
 * The scene duration never grows: the split moves the boundary inside the
 * existing range, so no shot can end up past the total frames. Fails loud
 * when the donor shot is too short to give away `frames`.
 */
export function insertShotAtBoundary(
  script: SceneScriptRoot,
  shotId: string,
  frames: number,
  options: { description?: string } = {},
): SceneScriptRoot {
  const donor = script.shots.find((shot) => shot.id === shotId);
  if (!donor) {
    throw new SceneScriptEditError("scene_script_shot_not_found", `No shot ${shotId}`);
  }
  const fps = script.scene.frame_rate || 30;
  const minFrames = Math.max(1, Math.round(fps / 2));
  const wanted = Math.max(minFrames, Math.round(frames));
  const donorStart = donor.start_frame;
  const donorEnd = donor.end_frame;
  if (donorEnd - donorStart + 1 < wanted + minFrames) {
    throw new SceneScriptEditError(
      "scene_script_shot_too_short",
      `Shot ${shotId} is too short to give away ${wanted} frames (it has ${donorEnd - donorStart + 1}).`,
    );
  }
  const boundary = donorEnd - wanted + 1;
  const shotIndex = nextIndex(script.shots.map((shot) => shot.id), "shot");
  const inserted = {
    id: `shot_${shotIndex}`,
    camera: donor.camera,
    start_frame: boundary,
    end_frame: donorEnd,
    description: options.description ?? "inserted shot",
  };
  return {
    ...script,
    shots: script.shots
      .map((shot) =>
        shot.id === shotId ? { ...shot, end_frame: boundary - 1 } : shot,
      )
      .concat(inserted),
  };
}

/** Monotonic next id: `cam1`/`cam_1` and `cam_3` yield `cam_4`. */
function nextIndex(ids: string[], prefix: string): number {  const used: number[] = [];
  // Both spellings exist in the wild: generator output writes `cam_1` while
  // LLM-authored scripts often write `cam1`. Treat them as the same series
  // so a placed camera never collides with an existing id.
  const pattern = new RegExp(`^${prefix}_?([0-9]+)$`);
  for (const id of ids) {
    const match = pattern.exec(id);
    if (match) used.push(Number.parseInt(match[1], 10));
  }
  return used.length === 0 ? 1 : Math.max(...used) + 1;
}

/**
 * Freeze a character's interpolated state at `frame` as a keyframe — the
 * "capture" gesture when the user scrubs to a moment and wants to pin the
 * pose. No-op when a keyframe already exists at that frame (it is already
 * pinned).
 */
export function captureCharacterKeyframe(
  script: SceneScriptRoot,
  characterId: string,
  frame: number,
): SceneScriptRoot {
  const character = script.characters.find((candidate) => candidate.id === characterId);
  if (!character) {
    throw new SceneScriptEditError(
      "scene_script_object_not_found",
      `SceneScript has no character '${characterId}'.`,
    );
  }
  // Identity no-op: an existing keyframe at this frame is already pinned, so
  // callers can safely re-capture without churning React state.
  if (character.keyframes.some((keyframe) => keyframe.frame === frame)) return script;
  const state = characterStateAtFrame(character, frame);
  return replaceCharacter(script, characterId, (current) => ({
    ...current,
    keyframes: [
      ...current.keyframes,
      {
        frame,
        position: roundVec3(state.position),
        rotation_y: round2(state.rotationY),
        action: current.keyframes[0]?.action ?? "stand",
      },
    ].sort((a, b) => a.frame - b.frame),
  }));
}

/** Freeze a camera's interpolated state at `frame` as a keyframe (no-op if present). */
export function captureCameraKeyframe(
  script: SceneScriptRoot,
  cameraId: string,
  frame: number,
): SceneScriptRoot {
  const camera = script.cameras.find((candidate) => candidate.id === cameraId);
  if (!camera) {
    throw new SceneScriptEditError(
      "scene_script_object_not_found",
      `SceneScript has no camera '${cameraId}'.`,
    );
  }
  // Identity no-op when the frame is already a keyframe (see character version).
  if (camera.keyframes.some((keyframe) => keyframe.frame === frame)) return script;
  const state = interpolateCameraState(camera, frame);
  if (!state) return script;
  return replaceCamera(script, cameraId, (current) => ({
    ...current,
    keyframes: [
      ...current.keyframes,
      {
        frame,
        position: roundVec3(state.position),
        look_at: roundVec3(state.lookAt),
      },
    ].sort((a, b) => a.frame - b.frame),
  }));
}

/** Interpolated camera state (position + look_at) at `frame`; null with no keyframes. */
export function interpolateCameraState(
  camera: SceneCamera,
  frame: number,
): { position: SceneVec3; lookAt: SceneVec3 } | null {
  const keyframes = camera.keyframes;
  if (keyframes.length === 0) return null;
  if (keyframes.length === 1 || frame <= keyframes[0].frame) {
    return { position: keyframes[0].position, lookAt: keyframes[0].look_at };
  }
  const last = keyframes[keyframes.length - 1];
  if (frame >= last.frame) return { position: last.position, lookAt: last.look_at };
  for (let index = 0; index < keyframes.length - 1; index += 1) {
    const a = keyframes[index];
    const b = keyframes[index + 1];
    if (frame >= a.frame && frame <= b.frame) {
      const t = (frame - a.frame) / (b.frame - a.frame || 1);
      return {
        position: [
          a.position[0] + (b.position[0] - a.position[0]) * t,
          a.position[1] + (b.position[1] - a.position[1]) * t,
          a.position[2] + (b.position[2] - a.position[2]) * t,
        ],
        lookAt: [
          a.look_at[0] + (b.look_at[0] - a.look_at[0]) * t,
          a.look_at[1] + (b.look_at[1] - a.look_at[1]) * t,
          a.look_at[2] + (b.look_at[2] - a.look_at[2]) * t,
        ],
      };
    }
  }
  return { position: keyframes[0].position, lookAt: keyframes[0].look_at };
}

/**
 * Generic dispatcher used by the viewport's drag-commit callback: resolves
 * the object kind once and routes to the right operation, so the viewport
 * never re-implements "who owns position edits".
 */
export function moveSceneObjectAtFrame(
  script: SceneScriptRoot,
  ref: SceneObjectRef,
  frame: number,
  position: SceneVec3,
): SceneScriptRoot {
  switch (ref.kind) {
    case "character":
      return moveCharacterAtFrame(script, ref.id, frame, position);
    case "prop":
      return moveProp(script, ref.id, position);
    case "environment":
      return moveEnvironment(script, ref.id, position);
    case "camera":
      return moveCameraAtFrame(script, ref.id, frame, position);
    default:
      throw new SceneScriptEditError(
        "scene_script_object_kind_unsupported",
        `Unsupported object kind '${String(ref.kind)}'.`,
      );
  }
}

/** The scene position the viewport should render for an object at `frame`. */
export function sceneObjectPositionAtFrame(
  script: SceneScriptRoot,
  ref: SceneObjectRef,
  frame: number,
): SceneVec3 | null {
  switch (ref.kind) {
    case "character": {
      const character = script.characters.find((candidate) => candidate.id === ref.id);
      return character ? characterPositionAtFrame(character, frame) : null;
    }
    case "prop":
    case "environment": {
      const object = (ref.kind === "prop" ? script.props : script.environment).find(
        (candidate) => candidate.id === ref.id,
      );
      if (!object) return null;
      // A keyframed prop moves: where it IS at this frame, not where it rests.
      // Without this the preview showed the rest pose for every frame while
      // the render (which reads the keyframes) moved — the same class of
      // disagreement the shot-camera fix closed.
      return propStateAtFrame(object, frame)?.position ?? object.position;
    }
    case "camera": {
      const camera = script.cameras.find((candidate) => candidate.id === ref.id);
      if (!camera) return null;
      const keyframe =
        camera.keyframes.find((candidate) => candidate.frame === frame)
        ?? camera.keyframes[0];
      return keyframe?.position ?? null;
    }
    default:
      return null;
  }
}

/** Frame the SceneScript's single default shot covers (for camera edits). */
export function defaultCameraKeyframeFrame(script: SceneScriptRoot, cameraId: string): number {
  const camera = script.cameras.find((candidate) => candidate.id === cameraId);
  if (camera && camera.keyframes.length > 0) return camera.keyframes[0].frame;
  return 0;
}

export type { CharacterKeyframe, CameraKeyframe };
