/**
 * heldItems tests — the Continuity State prop dimension (V0.2 §5).
 *
 * Locks the follow math (parity with `held_items.py` — same constants, same
 * convention: yaw 0 = facing +Y, right hand = facing rotated -90°) and the
 * preview's effective-position rule: a held prop renders at the holder's hand,
 * an unheld prop at its authored position.
 */

import { describe, expect, it } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import {
  AUTHORED_POSITION_SLACK_M,
  HAND_HEIGHT_RATIO,
  HAND_REACH_M,
  effectivePropPositionAtFrame,
  heldHandOffset,
  heldItemPositionAtFrame,
} from "./heldItems";

function script(overrides: Partial<SceneScriptRoot> = {}): SceneScriptRoot {
  return {
    scene: { name: "street", environment: "outdoor", lighting: "cool", duration: 6, frame_rate: 30 },
    characters: [
      {
        id: "girl",
        type: "lowpoly_human",
        character_asset_id: null,
        appearance: { color: "#E74C3C", height: 1.7, scale: 1 },
        keyframes: [
          { frame: 0, position: [0, 0, 0], rotation_y: 0, action: "stand" },
          { frame: 90, position: [2, 0, 0], rotation_y: 90, action: "walk" },
        ],
      },
    ],
    props: [],
    environment: [],
    cameras: [
      { id: "c1", shot_type: "wide", keyframes: [{ frame: 0, position: [3, -4, 2], look_at: [0, 0, 1] }] },
    ],
    shots: [{ id: "s1", camera: "c1", start_frame: 0, end_frame: 179, description: "" }],
    speech_bindings: [],
    ...overrides,
  };
}

const umbrella = {
  id: "umbrella",
  type: "weapon",
  position: [0, 0, 0] as [number, number, number],
  scale: 1,
  rotation_y: 0,
  held_by: "girl",
  held_side: "right" as const,
};

describe("heldHandOffset", () => {
  it("puts the right hand off +X when facing +Y (face north, right hand east)", () => {
    const offset = heldHandOffset(0, "right", 1.7);
    expect(offset[0]).toBeCloseTo(HAND_REACH_M, 6);
    expect(offset[1]).toBeCloseTo(0, 6);
    expect(offset[2]).toBeCloseTo(1.7 * HAND_HEIGHT_RATIO, 6);
  });

  it("mirrors for the left hand", () => {
    const right = heldHandOffset(37, "right", 1.7);
    const left = heldHandOffset(37, "left", 1.7);
    expect(left[0]).toBeCloseTo(-right[0], 6);
    expect(left[1]).toBeCloseTo(-right[1], 6);
  });

  it("turns the hand with the body (facing +X puts the right hand at -Y)", () => {
    const offset = heldHandOffset(90, "right", 1.7);
    expect(offset[0]).toBeCloseTo(0, 6);
    expect(offset[1]).toBeCloseTo(-HAND_REACH_M, 6);
  });

  it("lifts the hand with the character's height", () => {
    expect(heldHandOffset(0, "right", 2.0)[2]).toBeCloseTo(2.0 * HAND_HEIGHT_RATIO, 6);
  });

  it("shares the slack constant with the backend gate", () => {
    expect(AUTHORED_POSITION_SLACK_M).toBeGreaterThan(0);
  });
});

describe("heldItemPositionAtFrame", () => {
  it("rides the holder's hand at every authored pose (the item cannot switch hands)", () => {
    const scene = script();
    const atStart = heldItemPositionAtFrame(scene, umbrella, 0);
    expect(atStart).not.toBeNull();
    expect(atStart?.[0]).toBeCloseTo(HAND_REACH_M, 6);

    const atEnd = heldItemPositionAtFrame(scene, umbrella, 90);
    // Character walked to [2,0,0] facing +X; the hand followed.
    expect(atEnd?.[0]).toBeCloseTo(2, 6);
    expect(atEnd?.[1]).toBeCloseTo(-HAND_REACH_M, 6);
  });

  it("interpolates with the character between poses", () => {
    const mid = heldItemPositionAtFrame(script(), umbrella, 45);
    expect(mid?.[0]).toBeGreaterThan(0);
    expect(mid?.[0]).toBeLessThan(2);
  });

  it("returns null for an unheld prop (authored position stands)", () => {
    const scene = script();
    const table = { id: "table", type: "round_table", position: [1, 1, 0] as [number, number, number] };
    expect(heldItemPositionAtFrame(scene, table, 0)).toBeNull();
    expect(effectivePropPositionAtFrame(scene, table, 30)).toEqual([1, 1, 0]);
  });

  it("returns null when the holder is missing (fail-visible, not a silent teleport)", () => {
    const scene = script();
    const orphan = { ...umbrella, held_by: "ghost" };
    expect(heldItemPositionAtFrame(scene, orphan, 0)).toBeNull();
    expect(effectivePropPositionAtFrame(scene, orphan, 0)).toEqual(umbrella.position);
  });

  it("prefers the hand position in the effective position", () => {
    const scene = script();
    expect(effectivePropPositionAtFrame(scene, umbrella, 0)).toEqual(
      heldItemPositionAtFrame(scene, umbrella, 0),
    );
  });

  it("defaults the carry side to the right", () => {
    const scene = script();
    const noSide = { ...umbrella, held_side: null };
    const implicit = heldItemPositionAtFrame(scene, noSide, 0);
    const explicit = heldItemPositionAtFrame(scene, umbrella, 0);
    expect(implicit).toEqual(explicit);
  });
});
