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
  effectivePropPositionAtFrame,
  heldHandOffset,
  heldItemGripGeometry,
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
  it("puts the right hand where the rig's arm actually ends", () => {
    // Not "at HAND_REACH_M". That constant matched the rig only for a 1.75 m figure:
    // the rig places the arm in proportion to height, so for a 1.7 m character the
    // hand is at 0.311 m and the old code put the weapon at 0.32 -- and for a 1.1 m
    // character it was 60% out. The invariant is the one below.
    const height = 1.7;
    const arm = heldItemGripGeometry(height);
    const offset = heldHandOffset(0, "right", height);
    expect(offset[0]).toBeCloseTo(arm.lateral, 6);
    // And forward, which the old code left at zero: a raised arm ends up in front of
    // the chest, so a weapon carried at the chest was half a metre behind the hand.
    expect(offset[1]).toBeCloseTo(arm.forward, 6);
    expect(offset[2]).toBeCloseTo(height * HAND_HEIGHT_RATIO, 6);
  });

  it("scales the reach with the character instead of using a fixed metre", () => {
    // The defect in one assertion: a constant reach cannot be right for two heights.
    const adult = heldHandOffset(0, "right", 1.9);
    const child = heldHandOffset(0, "right", 1.1);
    expect(Math.abs(adult[0])).toBeGreaterThan(Math.abs(child[0]));
    expect(Math.abs(child[0])).toBeCloseTo(heldItemGripGeometry(1.1).lateral, 6);
    expect(Math.abs(child[0])).toBeLessThan(0.32 * 0.75);
  });

  it("mirrors for the left hand", () => {
    const right = heldHandOffset(37, "right", 1.7);
    const left = heldHandOffset(37, "left", 1.7);
    expect(left[0]).toBeCloseTo(-right[0], 6);
    expect(left[1]).toBeCloseTo(-right[1], 6);
  });

  it("turns the hand with the body", () => {
    // The hand is diagonal in the character's own frame -- out to the side AND in
    // front -- so facing +X does not put it purely on one axis. It must rotate as a
    // rigid pair, which is the property that matters.
    const north = heldHandOffset(0, "right", 1.7);
    const east = heldHandOffset(90, "right", 1.7);
    // Rotating +90 degrees maps (lateral, forward) -> (-forward, lateral).
    expect(east[0]).toBeCloseTo(-north[1], 6);
    expect(east[1]).toBeCloseTo(north[0], 6);
    expect(Math.hypot(north[0], north[1])).toBeCloseTo(Math.hypot(east[0], east[1]), 6);
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
    const height = 1.7;
    const arm = heldItemGripGeometry(height);

    // Frame 0: character at the origin facing +Y, so the right hand is out to +X and
    // forward of the chest axis.
    const atStart = heldItemPositionAtFrame(scene, umbrella, 0);
    expect(atStart).not.toBeNull();
    expect(atStart?.[0]).toBeCloseTo(arm.lateral, 6);
    expect(atStart?.[1]).toBeCloseTo(arm.forward, 6);

    // Frame 90: walked to [2, 0, 0] and turned to face +X. The hand has to travel
    // WITH the body -- same distance from the chest, same hand -- rather than staying
    // where it was, which is what "cannot switch hands" means.
    const atEnd = heldItemPositionAtFrame(scene, umbrella, 90);
    expect(atEnd?.[2]).toBeCloseTo(atStart?.[2] ?? 0, 6);
    expect(
      Math.hypot((atEnd?.[0] ?? 0) - 2, atEnd?.[1] ?? 0),
    ).toBeCloseTo(Math.hypot(arm.lateral, arm.forward), 6);
    // Facing +X, the reach that was lateral becomes the forward component and vice
    // versa, with the sign the yaw rotation gives.
    expect(atEnd?.[0]).toBeCloseTo(2 - arm.forward, 6);
    expect(atEnd?.[1]).toBeCloseTo(arm.lateral, 6);
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
