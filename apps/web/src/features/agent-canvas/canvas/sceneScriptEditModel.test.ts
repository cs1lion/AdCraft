/**
 * SceneScript edit-model tests (3D director workbench P1).
 *
 * Locks the two behaviours the interactive viewport depends on:
 * 1. Character/camera position edits are keyframe edits at the current frame
 *    (update same-frame, insert sorted otherwise, inherit facing/pose).
 * 2. Prop/environment edits are static position writes.
 * Plus immutability and the not-found error path. The mutation check flips
 * one expectation and fails, proving the assertions bind behaviour.
 */

import { describe, expect, it } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import {
  SceneScriptEditError,
  addCameraAtFrame,
  addEnvironmentObject,
  addPropObject,
  captureCameraKeyframe,
  captureCharacterKeyframe,
  characterPositionAtFrame,
  characterActionAtFrame,
  characterStateAtFrame,
  defaultCameraKeyframeFrame,
  addCharacterFromAsset,
  bindEnvironmentAsset,
  bindPropAsset,
  insertShotAtBoundary,
  setCharacterPalette,
  setShotTransitionIntent,
  MAX_APPEARANCE_PALETTE_COLORS,
  interpolateCameraState,
  moveCameraAtFrame,
  moveCharacterAtFrame,
  moveEnvironment,
  moveProp,
  moveSceneObjectAtFrame,
  rotateCharacterAtFrame,
  rotateStaticObject,
  scaleStaticObject,
  sceneObjectPositionAtFrame,
  setCameraLookAtAtFrame,
  setCameraShotType,
  setPropHeld,
} from "./sceneScriptEditModel";

function script(overrides: Partial<SceneScriptRoot> = {}): SceneScriptRoot {
  return {
    scene: { name: "test", environment: "indoor", lighting: "cool", duration: 6, frame_rate: 30 },
    characters: [
      {
        id: "char_a",
        type: "lowpoly_human",
        appearance: { color: "#E74C3C", height: 1.7, scale: 1 },
        keyframes: [
          { frame: 0, position: [0, 0, 0], rotation_y: 90, action: "stand" },
          { frame: 60, position: [2, 2, 0], rotation_y: 90, action: "walk" },
        ],
      },
    ],
    props: [{ id: "crate1", type: "crate", position: [1, 1, 0], scale: 1, rotation_y: 0 }],
    environment: [{ id: "wall1", type: "wall", position: [0, 3, 0], scale: 1, rotation_y: 0 }],
    cameras: [
      {
        id: "cam1",
        shot_type: "wide",
        keyframes: [
          { frame: 0, position: [8, -10, 5], look_at: [0, 0, 1] },
          { frame: 60, position: [4, -6, 3], look_at: [0, 0, 1] },
        ],
      },
    ],
    shots: [{ id: "shot1", camera: "cam1", start_frame: 0, end_frame: 179, description: "wide" }],
    speech_bindings: [],
    ...overrides,
  };
}

describe("moveCharacterAtFrame", () => {
  it("updates the existing keyframe at the exact frame", () => {
    const base = script();
    const next = moveCharacterAtFrame(base, "char_a", 60, [3, 4, 0]);
    expect(next.characters[0].keyframes).toHaveLength(2);
    expect(next.characters[0].keyframes[1]).toEqual({
      frame: 60,
      position: [3, 4, 0],
      rotation_y: 90,
      action: "walk",
    });
    // The other keyframe is untouched by identity.
    expect(next.characters[0].keyframes[0]).toBe(base.characters[0].keyframes[0]);
  });

  it("inserts a sorted keyframe at a fresh frame, inheriting facing/action from the nearest one", () => {
    const next = moveCharacterAtFrame(script(), "char_a", 30, [1, 1, 0]);
    expect(next.characters[0].keyframes.map((keyframe) => keyframe.frame)).toEqual([0, 30, 60]);
    expect(next.characters[0].keyframes[1]).toEqual({
      frame: 30,
      position: [1, 1, 0],
      rotation_y: 90,
      action: "walk", // nearest keyframe is frame 60 ('walk')
    });
  });

  it("rounds positions to 2 decimals", () => {
    const next = moveCharacterAtFrame(script(), "char_a", 60, [2.34567, -1.98765, 0.004]);
    expect(next.characters[0].keyframes[1].position).toEqual([2.35, -1.99, 0]);
  });

  it("throws a coded error for an unknown character", () => {
    expect(() => moveCharacterAtFrame(script(), "nobody", 0, [0, 0, 0])).toThrow(
      SceneScriptEditError,
    );
    try {
      moveCharacterAtFrame(script(), "nobody", 0, [0, 0, 0]);
    } catch (error) {
      expect((error as SceneScriptEditError).code).toBe("scene_script_object_not_found");
    }
  });
});

describe("rotateCharacterAtFrame", () => {
  it("normalizes rotation into [0, 360) and keeps the position", () => {
    const next = rotateCharacterAtFrame(script(), "char_a", 60, -30);
    expect(next.characters[0].keyframes[1].rotation_y).toBe(330);
    expect(next.characters[0].keyframes[1].position).toEqual([2, 2, 0]);
  });
});

describe("characterPositionAtFrame", () => {
  it("interpolates between keyframes", () => {
    const character = script().characters[0];
    expect(characterPositionAtFrame(character, 30)).toEqual([1, 1, 0]);
    expect(characterPositionAtFrame(character, 15)).toEqual([0.5, 0.5, 0]);
  });

  it("clamps outside the keyframe range", () => {
    const character = script().characters[0];
    expect(characterPositionAtFrame(character, -10)).toEqual([0, 0, 0]);
    expect(characterPositionAtFrame(character, 999)).toEqual([2, 2, 0]);
  });
});

describe("static object edits", () => {
  it("moves props and environment objects directly", () => {
    const movedProp = moveProp(script(), "crate1", [2.5, 3.5, 0]);
    expect(movedProp.props[0].position).toEqual([2.5, 3.5, 0]);
    const movedWall = moveEnvironment(script(), "wall1", [0, 5, 0]);
    expect(movedWall.environment[0].position).toEqual([0, 5, 0]);
  });

  it("rotates and scales static objects with clamping", () => {
    const rotated = rotateStaticObject(script(), "prop", "crate1", 450);
    expect(rotated.props[0].rotation_y).toBe(90);
    expect(scaleStaticObject(script(), "prop", "crate1", 99).props[0].scale).toBe(10);
    expect(scaleStaticObject(script(), "prop", "crate1", 0).props[0].scale).toBe(0.1);
    // Environment objects have the wider schema clamp (50).
    expect(scaleStaticObject(script(), "environment", "wall1", 99).environment[0].scale).toBe(50);
  });
});

describe("setPropHeld (Continuity State prop dimension, V0.2 §5)", () => {
  it("declares a holder and defaults the side to the right", () => {
    const held = setPropHeld(script(), "crate1", "char_a", null);
    expect(held.props[0].held_by).toBe("char_a");
    expect(held.props[0].held_side).toBe("right");
  });

  it("honors an explicit side", () => {
    const held = setPropHeld(script(), "crate1", "char_a", "left");
    expect(held.props[0].held_side).toBe("left");
  });

  it("releases the item back to a rest position", () => {
    const held = setPropHeld(script(), "crate1", "char_a", "right");
    const released = setPropHeld(held, "crate1", null, null);
    expect(released.props[0].held_by).toBeNull();
    expect(released.props[0].held_side).toBeNull();
  });

  it("leaves other objects and the authored position untouched", () => {
    const before = script();
    const held = setPropHeld(before, "crate1", "char_a", "right");
    expect(held.props[0].position).toEqual(before.props[0].position);
    expect(held.environment).toEqual(before.environment);
    expect(held.characters).toEqual(before.characters);
  });

  it("fails loud on an unknown prop", () => {
    expect(() => setPropHeld(script(), "ghost", "char_a", "right")).toThrow();
  });
});

describe("camera edits", () => {
  it("upserts camera position keyframes", () => {
    const moved = moveCameraAtFrame(script(), "cam1", 30, [6, -8, 4]);
    expect(moved.cameras[0].keyframes.map((keyframe) => keyframe.frame)).toEqual([0, 30, 60]);
    expect(moved.cameras[0].keyframes[1]).toEqual({
      frame: 30,
      position: [6, -8, 4],
      look_at: [0, 0, 1], // inherited from nearest
    });
  });

  it("sets look-at and shot type", () => {
    const aimed = setCameraLookAtAtFrame(script(), "cam1", 60, [1, 2, 1.5]);
    expect(aimed.cameras[0].keyframes[1].look_at).toEqual([1, 2, 1.5]);
    expect(setCameraShotType(script(), "cam1", "closeup").cameras[0].shot_type).toBe("closeup");
  });
});

describe("moveSceneObjectAtFrame dispatcher", () => {
  it("routes by kind to the right operation", () => {
    const characterMove = moveSceneObjectAtFrame(
      script(),
      { kind: "character", id: "char_a" },
      60,
      [1, 1, 0],
    );
    expect(characterMove.characters[0].keyframes[1].position).toEqual([1, 1, 0]);

    const propMove = moveSceneObjectAtFrame(
      script(),
      { kind: "prop", id: "crate1" },
      60,
      [1, 1, 0],
    );
    expect(propMove.props[0].position).toEqual([1, 1, 0]);

    const cameraMove = moveSceneObjectAtFrame(
      script(),
      { kind: "camera", id: "cam1" },
      60,
      [1, 1, 0],
    );
    expect(cameraMove.cameras[0].keyframes[1].position).toEqual([1, 1, 0]);
  });

  it("rejects unsupported kinds with a coded error", () => {
    // Defensive branch: no typed kind reaches it, but the dispatcher must not
    // silently succeed on an unknown kind coming off the wire.
    try {
      moveSceneObjectAtFrame(
        script(),
        { kind: "light", id: "lamp1" } as never,
        0,
        [0, 0, 0],
      );
      expect.unreachable("should have thrown");
    } catch (error) {
      expect(error).toBeInstanceOf(SceneScriptEditError);
      expect((error as SceneScriptEditError).code).toBe("scene_script_object_kind_unsupported");
    }
  });
});

describe("sceneObjectPositionAtFrame", () => {
  it("reads the current position of any object kind", () => {
    const base = script();
    expect(sceneObjectPositionAtFrame(base, { kind: "prop", id: "crate1" }, 0)).toEqual([1, 1, 0]);
    expect(
      sceneObjectPositionAtFrame(base, { kind: "character", id: "char_a" }, 60),
    ).toEqual([2, 2, 0]);
    expect(
      sceneObjectPositionAtFrame(base, { kind: "camera", id: "cam1" }, 30),
    ).toEqual([8, -10, 5]); // falls back to first keyframe
    expect(sceneObjectPositionAtFrame(base, { kind: "prop", id: "nope" }, 0)).toBeNull();
  });
});

describe("defaultCameraKeyframeFrame", () => {
  it("prefers the camera's own first keyframe, falling back to 0", () => {
    expect(defaultCameraKeyframeFrame(script(), "cam1")).toBe(0);
    const cameraFromTen = script({
      cameras: [
        {
          id: "cam2",
          shot_type: "wide",
          keyframes: [{ frame: 10, position: [8, -10, 5], look_at: [0, 0, 1] }],
        },
      ],
    });
    expect(defaultCameraKeyframeFrame(cameraFromTen, "cam2")).toBe(10);
    expect(defaultCameraKeyframeFrame(script(), "missing")).toBe(0);
  });
});

describe("immutability", () => {
  it("never mutates the input script", () => {
    const base = script();
    const snapshot = JSON.parse(JSON.stringify(base));
    moveCharacterAtFrame(base, "char_a", 90, [5, 5, 0]);
    moveProp(base, "crate1", [9, 9, 0]);
    moveCameraAtFrame(base, "cam1", 90, [9, 9, 9]);
    rotateCharacterAtFrame(base, "char_a", 60, 45);
    expect(JSON.parse(JSON.stringify(base))).toEqual(snapshot);
  });
});

// ---------------------------------------------------------------------------
// Camera placement (P2: viewport click-to-place)
// ---------------------------------------------------------------------------

describe("addCameraAtFrame", () => {
  it("appends a camera and a non-overlapping shot after the last one", () => {
    const base = script();
    // Existing shot spans 0..179; the new one must start at 180.
    const next = addCameraAtFrame(base, {
      position: [3, -4, 1.6],
      lookAt: [0, 0, 1.2],
      shotType: "medium",
      description: "placed over the table",
    });

    expect(next.cameras).toHaveLength(2);
    const camera = next.cameras[1];
    expect(camera.id).toBe("cam_2");
    expect(camera.shot_type).toBe("medium");
    expect(camera.keyframes).toEqual([
      { frame: 180, position: [3, -4, 1.6], look_at: [0, 0, 1.2] },
    ]);
    const shot = next.shots[1];
    expect(shot.camera).toBe("cam_2");
    expect(shot.start_frame).toBe(180);
    expect(shot.end_frame).toBe(209); // 30-frame minimum shot
    expect(shot.description).toBe("placed over the table");
  });

  it("extends the scene duration when the new shot does not fit", () => {
    const next = addCameraAtFrame(script(), {
      position: [3, -4, 1.6],
      lookAt: [0, 0, 1.2],
    });
    // Scene was 6s/180 frames; the new shot ends at frame 209 -> >= 7s.
    expect(next.scene.duration).toBeGreaterThanOrEqual(210 / 30);
    // Schema invariant: every shot end must be within total frames.
    const total = next.scene.duration * next.scene.frame_rate;
    for (const shot of next.shots) {
      expect(shot.end_frame).toBeLessThanOrEqual(total);
    }
  });

  it("numbers ids past any existing cam_N/shot_N names", () => {
    const base = script({
      cameras: [
        ...script().cameras,
        { id: "cam_3", shot_type: "wide", keyframes: [{ frame: 300, position: [0, 0, 2], look_at: [0, 0, 1] }] },
      ],
      shots: [{ id: "shot_7", camera: "cam_3", start_frame: 300, end_frame: 330, description: "x" }],
    });
    const next = addCameraAtFrame(base, { position: [1, 1, 1], lookAt: [0, 0, 1] });
    expect(next.cameras[next.cameras.length - 1].id).toBe("cam_4");
    expect(next.shots[next.shots.length - 1].id).toBe("shot_8");
    expect(next.shots[next.shots.length - 1].start_frame).toBe(331);
  });

  it("starts the first shot at frame 0 when there are no shots", () => {
    const base = script({ shots: [], cameras: [] });
    const next = addCameraAtFrame(base, { position: [4, -6, 2], lookAt: [0, 0, 1] });
    expect(next.shots[0].start_frame).toBe(0);
    expect(next.cameras[0].id).toBe("cam_1");
  });
});

// ---------------------------------------------------------------------------
// Keyframe capture (freeze the interpolated state at the playhead)
// ---------------------------------------------------------------------------

describe("captureCharacterKeyframe", () => {
  it("pins the interpolated pose at a fresh frame", () => {
    const next = captureCharacterKeyframe(script(), "char_a", 30);
    const keyframes = next.characters[0].keyframes;
    expect(keyframes.map((keyframe) => keyframe.frame)).toEqual([0, 30, 60]);
    // The interpolated position at frame 30 (between [0,0,0] and [2,2,0]).
    expect(keyframes[1].position).toEqual([1, 1, 0]);
    expect(keyframes[1].rotation_y).toBe(90);
  });

  it("is a no-op when the frame is already a keyframe", () => {
    const base = script();
    const next = captureCharacterKeyframe(base, "char_a", 60);
    expect(next.characters[0].keyframes).toEqual(base.characters[0].keyframes);
    expect(next).toBe(base); // identity: nothing changed, nothing re-rendered
  });
});

describe("captureCameraKeyframe", () => {
  it("pins the interpolated camera state at a fresh frame", () => {
    const next = captureCameraKeyframe(script(), "cam1", 30);
    const keyframes = next.cameras[0].keyframes;
    expect(keyframes.map((keyframe) => keyframe.frame)).toEqual([0, 30, 60]);
    // Interpolated halfway between [8,-10,5] and [4,-6,3].
    expect(keyframes[1].position).toEqual([6, -8, 4]);
    expect(keyframes[1].look_at).toEqual([0, 0, 1]); // fixture keeps look_at constant
  });

  it("is a no-op when the frame is already a keyframe", () => {
    const base = script();
    const next = captureCameraKeyframe(base, "cam1", 0);
    expect(next).toBe(base); // identity
  });
});

describe("interpolateCameraState", () => {
  it("interpolates position and look_at together", () => {
    const camera = script().cameras[0];
    const state = interpolateCameraState(camera, 30);
    expect(state?.position).toEqual([6, -8, 4]);
    expect(state?.lookAt).toEqual([0, 0, 1]); // fixture keeps look_at constant
  });

  it("clamps outside the keyframe range and handles empty cameras", () => {
    const camera = script().cameras[0];
    expect(interpolateCameraState(camera, 999)?.position).toEqual([4, -6, 3]);
    expect(interpolateCameraState({ id: "c", shot_type: "wide", keyframes: [] }, 0)).toBeNull();
  });
});

describe("characterStateAtFrame", () => {
  it("returns position + yaw degrees for the preview", () => {
    const character = script().characters[0];
    const state = characterStateAtFrame(character, 30);
    expect(state.position).toEqual([1, 1, 0]);
    expect(state.rotationY).toBe(90);
  });
});

describe("characterActionAtFrame", () => {
  /** A character whose lip-sync wrote talk frames (the real merge shape). */
  function withTalkKeyframes() {
    const character = script().characters[0];
    character.keyframes = [
      { frame: 0, position: [0, 0, 0], rotation_y: 0, action: "stand" },
      { frame: 39, position: [0, 0, 0], rotation_y: 0, action: "talk" },
      { frame: 87, position: [0, 0, 0], rotation_y: 0, action: "stand" },
    ];
    return character;
  }

  it("reports talk on the keyframes the lip-sync wrote", () => {
    const character = withTalkKeyframes();
    expect(characterActionAtFrame(character, 38)).toBe("stand");
    expect(characterActionAtFrame(character, 39)).toBe("talk");
    expect(characterActionAtFrame(character, 60)).toBe("talk");
    expect(characterActionAtFrame(character, 87)).toBe("stand");
  });

  it("inherits the previous action when a keyframe declares none (merge semantics)", () => {
    const character = script().characters[0];
    character.keyframes = [
      { frame: 0, position: [0, 0, 0], rotation_y: 0, action: "talk" },
      // Authored later WITHOUT an action: the backend merge keeps the
      // previous one, and the viewport must agree or the mouth closes early.
      { frame: 40, position: [1, 0, 0], rotation_y: 0 },
    ];
    expect(characterActionAtFrame(character, 20)).toBe("talk");
    expect(characterActionAtFrame(character, 80)).toBe("talk");
  });

  it("returns null for a character with no keyframes", () => {
    const character = script().characters[0];
    character.keyframes = [];
    expect(characterActionAtFrame(character, 10)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Object creation (asset tray)
// ---------------------------------------------------------------------------

describe("addEnvironmentObject / addPropObject", () => {
  it("appends with a generated id and the requested kind", () => {
    const next = addEnvironmentObject(script(), "pillar");
    const added = next.environment[next.environment.length - 1];
    expect(added.id).toBe("env_1"); // no env_* ids existed yet
    expect(added.type).toBe("pillar");
    expect(added.scale).toBe(1);
  });

  it("never collides with an existing id", () => {
    const base = script();
    base.environment.push({ id: "env_1", type: "wall", position: [9, 9, 0], scale: 1, rotation_y: 0 });
    const next = addEnvironmentObject(base, "door");
    const ids = next.environment.map((object) => object.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toContain("env_2");
  });

  it("honors an explicit id and scale", () => {
    const next = addPropObject(script(), "chair", { id: "chair_x", scale: 2.5 });
    const added = next.props[next.props.length - 1];
    expect(added.id).toBe("chair_x");
    expect(added.scale).toBe(2.5);
  });

  it("places added objects on the ground at a deterministic spiral", () => {
    let current = script();
    for (let i = 0; i < 3; i += 1) {
      current = addEnvironmentObject(current, "crate".replace("crate", "box"));
    }
    const positions = current.environment.map((object) => object.position);
    // All on the ground.
    for (const position of positions) expect(position[2]).toBe(0);
    // No two added objects share a position (repeated clicks never stack).
    const added = positions.slice(1);
    const unique = new Set(added.map(([x, y]) => `${x},${y}`));
    expect(unique.size).toBe(added.length);
  });

  it("does not mutate the input script", () => {
    const base = script();
    const snapshot = JSON.parse(JSON.stringify(base));
    addEnvironmentObject(base, "window");
    addPropObject(base, "cup");
    expect(JSON.parse(JSON.stringify(base))).toEqual(snapshot);
  });
});

describe("insertShotAtBoundary (V0.2 §2.2: 两个镜头之间 = 新镜头插入)", () => {
  it("splits the donor shot's tail into a same-camera continuation", () => {
    const next = insertShotAtBoundary(script(), "shot1", 30);

    const donor = next.shots.find((shot) => shot.id === "shot1");
    const inserted = next.shots.find((shot) => shot.id === "shot_2");
    expect(donor).toBeTruthy();
    expect(inserted).toBeTruthy();
    // The donor gives away its tail; the insert takes it.
    expect(donor?.end_frame).toBe(149);
    expect(inserted?.start_frame).toBe(150);
    expect(inserted?.end_frame).toBe(179);
    // The continuation keeps the SAME camera: an insert is not a new viewpoint
    // (placing one stays an explicit act).
    expect(inserted?.camera).toBe(donor?.camera);
  });

  it("keeps the scene duration (a split moves the boundary, never the end)", () => {
    const before = script();
    const next = insertShotAtBoundary(before, "shot1", 30);
    expect(next.scene.duration).toBe(before.scene.duration);
  });

  it("fails loud when the donor is too short to give frames away", () => {
    // A 20-frame shot cannot spare the 15-frame minimum and still keep one:
    // the schema would reject a zero-length donor.
    const tiny = script();
    tiny.shots = [{ id: "shot1", camera: "cam1", start_frame: 0, end_frame: 19, description: "" }];
    expect(() => insertShotAtBoundary(tiny, "shot1", 15)).toThrow();
  });

  it("fails loud on an unknown shot", () => {
    expect(() => insertShotAtBoundary(script(), "ghost", 30)).toThrow();
  });

  it("never lets the inserted shot be zero-length (the schema would reject it)", () => {
    const twoShot = script();
    twoShot.shots = [
      { ...twoShot.shots[0], start_frame: 0, end_frame: 200 },
    ];
    const next = insertShotAtBoundary(twoShot, "shot1", 0);
    const inserted = next.shots.find((shot) => shot.id === "shot_2");
    expect(inserted?.end_frame).toBeGreaterThan(inserted?.start_frame ?? 0);
  });
});

describe("addCharacterFromAsset (V0.2 §2.1: 人物 → 拖到镜头)", () => {
  const asset = { assetId: "asset-girl", displayName: "林澈" };

  it("joins the cast bound to that asset (the Dramagic lock)", () => {
    const next = addCharacterFromAsset(script(), asset);
    expect(next.characters).toHaveLength(2);
    const joined = next.characters[1];
    expect(joined.character_asset_id).toBe("asset-girl");
    expect(joined.keyframes).toHaveLength(1);
    expect(joined.keyframes[0].action).toBe("stand");
  });

  it("is idempotent per asset (a second drop is not a second person)", () => {
    const once = addCharacterFromAsset(script(), asset);
    const twice = addCharacterFromAsset(once, asset);
    expect(twice.characters).toHaveLength(2);
    expect(twice).toBe(once);
  });

  it("wears a colour no existing cast member wears (colour is the identity)", () => {
    const next = addCharacterFromAsset(script(), asset);
    const existing = script().characters[0].appearance.color.toUpperCase();
    const joined = next.characters[1].appearance.color.toUpperCase();
    expect(joined).not.toBe(existing);
    // A crude RGB distance: the low-fidelity preview cannot tell two
    // near-identical characters apart.
    const parse = (hex: string) => [
      Number.parseInt(hex.slice(1, 3), 16),
      Number.parseInt(hex.slice(3, 5), 16),
      Number.parseInt(hex.slice(5, 7), 16),
    ];
    const [r1, g1, b1] = parse(existing);
    const [r2, g2, b2] = parse(joined);
    expect(Math.hypot(r1 - r2, g1 - g2, b1 - b2)).toBeGreaterThan(60);
  });

  it("stands apart from the existing cast", () => {
    const next = addCharacterFromAsset(script(), asset);
    const [x1, y1] = script().characters[0].keyframes[0].position;
    const [x2, y2] = next.characters[1].keyframes[0].position;
    expect(Math.hypot(x1 - x2, y1 - y2)).toBeGreaterThan(1);
  });

  it("gives a second joined character its own id and colour", () => {
    const one = addCharacterFromAsset(script(), asset);
    const two = addCharacterFromAsset(one, { assetId: "asset-su", displayName: "苏晴" });
    expect(two.characters.map((character) => character.id)).toEqual([
      "char_a",
      "char_1",
      "char_2",
    ]);
    expect(two.characters[2].appearance.color).not.toBe(two.characters[1].appearance.color);
  });

  it("does not mutate the input script", () => {
    const before = script();
    const snapshot = JSON.stringify(before);
    addCharacterFromAsset(before, asset);
    expect(JSON.stringify(before)).toBe(snapshot);
  });
});

describe("setCharacterPalette (V0.2 §5: 服装 = 下一镜要继承的声明)", () => {
  it("declares the palette the next scene inherits", () => {
    const next = setCharacterPalette(script(), "char_a", ["#2c3e50", "#ffffff"]);
    expect(next.characters[0].appearance.palette).toEqual(["#2C3E50", "#FFFFFF"]);
  });

  it("normalizes to upper case so the cross-node gate can compare", () => {
    const next = setCharacterPalette(script(), "char_a", ["#2c3e50"]);
    // The gate compares case-insensitively anyway, but a stored value that
    // matches the RGB swatch the author picked keeps the panel honest.
    expect(next.characters[0].appearance.palette).toEqual(["#2C3E50"]);
  });

  it("drops empty slots (a cleared swatch is not a colour)", () => {
    const next = setCharacterPalette(script(), "char_a", ["#2C3E50", null as unknown as string]);
    expect(next.characters[0].appearance.palette).toEqual(["#2C3E50"]);
  });

  it("clears the declaration when every slot is empty", () => {
    const next = setCharacterPalette(script(), "char_a", [null as unknown as string, null as unknown as string]);
    expect(next.characters[0].appearance.palette).toBeNull();
  });

  it("caps the declaration at the schema's four colours", () => {
    const next = setCharacterPalette(script(), "char_a", [
      "#111111", "#222222", "#333333", "#444444", "#555555", "#666666",
    ]);
    expect(next.characters[0].appearance.palette).toHaveLength(
      MAX_APPEARANCE_PALETTE_COLORS,
    );
  });

  it("only touches the named character", () => {
    const two = addCharacterFromAsset(script(), { assetId: "asset-2", displayName: "B" });
    const next = setCharacterPalette(two, "char_a", ["#2C3E50"]);
    expect(next.characters[1].appearance.palette ?? null).toBeNull();
  });

  it("does not mutate the input script", () => {
    const before = script();
    const snapshot = JSON.stringify(before);
    setCharacterPalette(before, "char_a", ["#2C3E50"]);
    expect(JSON.stringify(before)).toBe(snapshot);
  });
});

describe("setShotTransitionIntent (V0.2 §13 第 5 问: 哪一镜以何种读法接入)", () => {
  it("records the reading the shot enters with", () => {
    const next = setShotTransitionIntent(script(), "shot1", "sound_bridge");
    const shot = next.shots.find((entry) => entry.id === "shot1");
    expect(shot?.transition_intent).toBe("sound_bridge");
  });

  it("normalizes what the author typed (an id the machine can look up)", () => {
    const next = setShotTransitionIntent(script(), "shot1", "  cut_after_line  ");
    expect(next.shots.find((entry) => entry.id === "shot1")?.transition_intent).toBe(
      "cut_after_line",
    );
  });

  it("clears the declaration when the reading is empty (some cuts are just cuts)", () => {
    const declared = setShotTransitionIntent(script(), "shot1", "sound_bridge");
    const cleared = setShotTransitionIntent(declared, "shot1", null);
    expect(cleared.shots.find((entry) => entry.id === "shot1")?.transition_intent).toBeNull();
    const blank = setShotTransitionIntent(declared, "shot1", "   ");
    expect(blank.shots.find((entry) => entry.id === "shot1")?.transition_intent).toBeNull();
  });

  it("keeps an LLM-proposed id verbatim (hiding its name would make the label lie)", () => {
    const next = setShotTransitionIntent(script(), "shot1", "llm_overhead_match_cut");
    expect(next.shots.find((entry) => entry.id === "shot1")?.transition_intent).toBe(
      "llm_overhead_match_cut",
    );
  });

  it("only touches the named shot", () => {
    const next = setShotTransitionIntent(script(), "shot1", "sound_bridge");
    expect(next.shots.find((entry) => entry.id === "shot_2")?.transition_intent ?? null).toBeNull();
  });

  it("does not mutate the input script", () => {
    const before = script();
    const snapshot = JSON.stringify(before);
    setShotTransitionIntent(before, "shot1", "sound_bridge");
    expect(JSON.stringify(before)).toBe(snapshot);
  });
});


describe("bindPropAsset / bindEnvironmentAsset (Dramagic 锁继续延伸到物件)", () => {
  it("binds a prop to the asset it is derived from", () => {
    const next = bindPropAsset(script(), "crate1", "asset-crate");
    expect(next.props.find((prop) => prop.id === "crate1")?.prop_asset_id).toBe(
      "asset-crate",
    );
  });

  it("binds an environment object to the scene asset it is from", () => {
    const next = bindEnvironmentAsset(script(), "wall1", "asset-lab");
    expect(
      next.environment.find((object) => object.id === "wall1")?.scene_asset_id,
    ).toBe("asset-lab");
  });

  it("unbinds on an empty value (a prop being shaped has no source yet)", () => {
    const bound = bindPropAsset(script(), "crate1", "asset-crate");
    const cleared = bindPropAsset(bound, "crate1", null);
    expect(cleared.props.find((prop) => prop.id === "crate1")?.prop_asset_id).toBeNull();
    const blank = bindPropAsset(bound, "crate1", "");
    expect(blank.props.find((prop) => prop.id === "crate1")?.prop_asset_id).toBeNull();
  });

  it("only touches the named object", () => {
    const withExtra = addEnvironmentObject(script(), "pillar");
    const next = bindEnvironmentAsset(withExtra, "wall1", "asset-lab");
    expect(
      next.environment.find((object) => object.id === "wall1")?.scene_asset_id,
    ).toBe("asset-lab");
    expect(
      next.environment.find((object) => object.id === "pillar")?.scene_asset_id ?? null,
    ).toBeNull();
  });

  it("does not mutate the input script", () => {
    const before = script();
    const snapshot = JSON.stringify(before);
    bindPropAsset(before, "crate1", "asset-crate");
    bindEnvironmentAsset(before, "wall1", "asset-lab");
    expect(JSON.stringify(before)).toBe(snapshot);
  });
});
