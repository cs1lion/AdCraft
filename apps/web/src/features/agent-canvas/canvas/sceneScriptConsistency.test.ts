/**
 * Client consistency-mirror tests. Locks that the frontend mirror emits the
 * same codes and trigger conditions as the backend gate
 * (app/services/scene3d/scene_consistency.py) — the banner is only useful
 * when it tells the same truth as the gate. The mutation check flips the
 * multi-shot condition and fails, proving it binds.
 */

import { describe, expect, it } from "vitest";

import type { SceneScriptRoot } from "../../../types/scene-script";
import {
  SCENE_CONSISTENCY_CODES,
  checkSceneScriptConsistency,
} from "./sceneScriptConsistency.ts";

function script(overrides: Partial<SceneScriptRoot> = {}): SceneScriptRoot {
  return {
    scene: { name: "lab", environment: "indoor", lighting: "cool", duration: 6, frame_rate: 30 },
    characters: [
      {
        id: "char_a",
        type: "lowpoly_human",
        appearance: { color: "#E74C3C", height: 1.7, scale: 1 },
        keyframes: [{ frame: 0, position: [0, 0, 0], rotation_y: 0, action: "stand" }],
      },
    ],
    props: [],
    environment: [],
    cameras: [
      {
        id: "cam1",
        shot_type: "wide",
        keyframes: [{ frame: 0, position: [8, -10, 5], look_at: [0, 0, 1] }],
      },
    ],
    shots: [{ id: "shot1", camera: "cam1", start_frame: 0, end_frame: 179, description: "wide" }],
    speech_bindings: [],
    ...overrides,
  };
}

const codes = (issues: { code: string }[]) => issues.map((issue) => issue.code);

describe("checkSceneScriptConsistency", () => {
  it("is silent for a clean single-shot bound scene", () => {
    expect(checkSceneScriptConsistency(script())).toEqual([]);
  });

  it("warns about unbound characters only in multi-shot scenes", () => {
    // Mutation-locked: single shot must NOT warn (bound is a multi-shot risk).
    expect(codes(checkSceneScriptConsistency(script()))).not.toContain("character_unbound");

    const multi = script({
      shots: [
        { id: "s1", camera: "cam1", start_frame: 0, end_frame: 90 },
        { id: "s2", camera: "cam1", start_frame: 91, end_frame: 179 },
      ],
    });
    const issues = checkSceneScriptConsistency(multi);
    expect(codes(issues)).toContain("character_unbound");
    const issue = issues.find((item) => item.code === "character_unbound");
    expect(issue?.subject).toBe("char_a");
    expect(issue?.remedy).toBeTruthy();
  });

  it("is silent for bound characters in multi-shot scenes", () => {
    const bound = script({
      shots: [
        { id: "s1", camera: "cam1", start_frame: 0, end_frame: 90 },
        { id: "s2", camera: "cam1", start_frame: 91, end_frame: 179 },
      ],
    });
    bound.characters[0].character_asset_id = "asset-1";
    expect(codes(checkSceneScriptConsistency(bound))).not.toContain("character_unbound");
  });

  it("flags color collisions case-insensitively", () => {
    const collision = script();
    collision.characters.push({
      id: "char_b",
      type: "lowpoly_human",
      appearance: { color: "#e74c3c", height: 1.7, scale: 1 },
      keyframes: [{ frame: 0, position: [1, 0, 0], rotation_y: 0, action: "stand" }],
    });
    expect(codes(checkSceneScriptConsistency(collision))).toContain(
      "character_color_collision",
    );
  });

  it("flags unused cameras", () => {
    const dead = script();
    dead.cameras.push({
      id: "cam2",
      shot_type: "medium",
      keyframes: [{ frame: 0, position: [4, -6, 3], look_at: [0, 0, 1] }],
    });
    const issue = checkSceneScriptConsistency(dead).find((item) => item.code === "camera_unused");
    expect(issue?.subject).toBe("cam2");
  });

  it("flags shot coverage gaps", () => {
    const gapped = script({
      shots: [
        { id: "s1", camera: "cam1", start_frame: 0, end_frame: 50 },
        { id: "s2", camera: "cam1", start_frame: 100, end_frame: 179 },
      ],
    });
    const gaps = checkSceneScriptConsistency(gapped).filter(
      (issue) => issue.code === "shot_coverage_gap",
    );
    expect(gaps).toHaveLength(1);
    expect(gaps[0].subject).toBe("frames 51-99");
  });

  it("flags empty scenes but not prop-only scenes", () => {
    const empty = script({ characters: [] });
    expect(codes(checkSceneScriptConsistency(empty))).toContain("scene_empty");
    const propOnly = script({ characters: [] });
    propOnly.props.push({ id: "crate1", type: "crate", position: [0, 0, 0] });
    expect(codes(checkSceneScriptConsistency(propOnly))).not.toContain("scene_empty");
  });

  it("only ever emits codes from the backend parity list", () => {
    // Every code the mirror emits exists in the backend gate's vocabulary.
    for (const base of [script(), script({ shots: [] }), script({ characters: [] })]) {
      for (const issue of checkSceneScriptConsistency(base)) {
        expect(SCENE_CONSISTENCY_CODES).toContain(issue.code);
      }
    }
    expect([...SCENE_CONSISTENCY_CODES]).toContain("character_color_collision");
  });
});

describe("held-item checks (Continuity State prop dimension, V0.2 §5)", () => {
  const heldProp = (id: string, side: "left" | "right" | null = "right") => ({
    id,
    type: "weapon",
    position: [0.32, 0, 1.224] as [number, number, number],
    scale: 1,
    held_by: "char_a",
    held_side: side,
  });

  it("is silent for a clean single held item", () => {
    const scene = script();
    scene.props.push(heldProp("umbrella"));
    expect(codes(checkSceneScriptConsistency(scene))).not.toContain("held_item_hand_conflict");
  });

  it("flags two props claiming the same hand", () => {
    const scene = script();
    scene.props.push(heldProp("umbrella"));
    scene.props.push(heldProp("cup", "right"));
    const issues = checkSceneScriptConsistency(scene);
    const conflict = issues.find((issue) => issue.code === "held_item_hand_conflict");
    expect(conflict).toBeTruthy();
    expect(conflict?.subject).toContain("umbrella");
    expect(conflict?.subject).toContain("cup");
  });

  it("allows one item per hand", () => {
    const scene = script();
    scene.props.push(heldProp("umbrella", "right"));
    scene.props.push(heldProp("cup", "left"));
    expect(codes(checkSceneScriptConsistency(scene))).not.toContain("held_item_hand_conflict");
  });

  it("flags a rest position far from the holder's whole path", () => {
    const scene = script();
    scene.props.push({ ...heldProp("umbrella"), position: [30, 30, 0] });
    const issues = checkSceneScriptConsistency(scene);
    expect(codes(issues)).toContain("held_item_authored_position_far");
  });

  it("emits the backend parity codes for the held family", () => {
    expect([...SCENE_CONSISTENCY_CODES]).toContain("held_item_hand_conflict");
    expect([...SCENE_CONSISTENCY_CODES]).toContain("held_item_authored_position_far");
  });
});
