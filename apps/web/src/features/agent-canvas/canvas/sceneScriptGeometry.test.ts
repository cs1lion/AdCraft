/**
 * The preview must cover every kind the backend schema declares.
 *
 * This is the frontend half of the same guarantee the Python side enforces in
 * ``tests/test_scene_script_preview_contract.py``. It exists because the
 * coverage used to be implied by a ``switch`` statement's ``default`` branch:
 * 18 of the 25 declared kinds fell through it and rendered as a ``#888888``
 * box, which is indistinguishable from an unimplemented asset -- so the browser
 * told a reviewer "this is your scene" about a scene it had not actually built.
 *
 * The registry is typed as a total map over the generated enums, so a new kind
 * normally fails ``tsc`` rather than this test. These tests cover what the type
 * system cannot: that each entry is real geometry, and that none of it can be
 * mistaken for the missing-asset placeholder.
 */

import { describe, expect, it } from "vitest";

import {
  ENVIRONMENT_TYPES,
  PLACEHOLDER_ASSET_COLOR,
  PROP_TYPES,
  SCENE_SCRIPT_ASSET_COLORS,
  SCENE_SCRIPT_PART_COLOR_OVERRIDES,
} from "../../../types/scene-script.generated";
import {
  SCENE_SCRIPT_GEOMETRY,
  assetGeometryFor,
  unimplementedKinds,
  type SceneScriptKind,
} from "./sceneScriptGeometry";
import { Mesh } from "./LeanSceneCanvas";

const ALL_KINDS: SceneScriptKind[] = [...PROP_TYPES, ...ENVIRONMENT_TYPES];

/** Every ``color`` prop anywhere in a returned element tree. */
function collectColours(node: unknown, found: string[] = []): string[] {
  if (Array.isArray(node)) {
    for (const child of node) collectColours(child, found);
    return found;
  }
  if (!node || typeof node !== "object") return found;
  const element = node as { props?: Record<string, unknown> };
  const color = element.props?.color;
  if (typeof color === "string") found.push(color);
  collectColours(element.props?.children, found);
  return found;
}

/**
 * Count mesh nodes in a returned tree. The scene intrinsics are real React
 * components (not R3F's lowercase string tags), so the element type is the
 * `Mesh` component itself.
 */
function countMeshes(node: unknown): number {
  if (Array.isArray(node)) {
    return node.reduce<number>((total, child) => total + countMeshes(child), 0);
  }
  if (!node || typeof node !== "object") return 0;
  const element = node as { type?: unknown; props?: Record<string, unknown> };
  const self = element.type === Mesh ? 1 : 0;
  return self + countMeshes(element.props?.children);
}

/** Every number appearing in a returned tree's props, in walk order. */
function numbers(node: unknown, found: number[] = []): number[] {
  if (Array.isArray(node)) {
    for (const child of node) numbers(child, found);
    return found;
  }
  if (!node || typeof node !== "object") return found;
  const props = (node as { props?: Record<string, unknown> }).props;
  for (const value of Object.values(props ?? {})) {
    if (typeof value === "number") found.push(value);
    else if (Array.isArray(value)) {
      for (const inner of value) if (typeof inner === "number") found.push(inner);
    }
  }
  numbers(props?.children, found);
  return found;
}

function build(kind: SceneScriptKind, scale = 1) {
  return SCENE_SCRIPT_GEOMETRY[kind]({ scale, rotationY: 0, pos: [0, 0, 0] });
}

describe("scene script preview geometry coverage", () => {
  it("has an entry for every declared kind and nothing else", () => {
    expect(Object.keys(SCENE_SCRIPT_GEOMETRY).sort()).toEqual([...ALL_KINDS].sort());
  });

  it.each(ALL_KINDS)("%s renders at least one mesh", (kind) => {
    expect(countMeshes(build(kind))).toBeGreaterThan(0);
  });

  it.each(ALL_KINDS)("%s is painted in a colour the converter also uses", (kind) => {
    // The point of sharing the palette: the browser and the Blender frames must
    // agree, and neither may use the placeholder colour. A hardcoded hex here
    // would be the same drift that made the backend render a grey frame.
    const allowed = new Set([
      ...Object.values(SCENE_SCRIPT_ASSET_COLORS),
      ...Object.values(SCENE_SCRIPT_PART_COLOR_OVERRIDES),
    ]);
    const colours = collectColours(build(kind));
    expect(colours.length).toBeGreaterThan(0);
    for (const color of colours) {
      expect(allowed, `${kind} uses ${color}, which the converter does not`).toContain(color);
    }
    expect(colours).not.toContain(PLACEHOLDER_ASSET_COLOR);
  });

  it.each(ALL_KINDS)("%s responds to its own scale", (kind) => {
    // A stub that ignores ``scale`` would render every instance of a kind at
    // the same size, which reads as a bug in the scene rather than in the
    // preview. Compare the numbers each tree produces.
    expect(numbers(build(kind, 2)).join()).not.toBe(numbers(build(kind, 1)).join());
  });
});

describe("missing geometry is unmistakable", () => {
  it("uses the placeholder colour for a kind with no geometry", () => {
    expect(assetGeometryFor("chandelier")).toBeUndefined();
  });

  it("reports the kinds a script needs that this build lacks", () => {
    expect(unimplementedKinds(["tree", "chandelier", "rock", "gazebo"])).toEqual([
      "chandelier",
      "gazebo",
    ]);
    expect(unimplementedKinds(ALL_KINDS)).toEqual([]);
  });

  it("keeps the placeholder distinct from every real colour", () => {
    expect(PLACEHOLDER_ASSET_COLOR).not.toBe("#888888");
    for (const color of Object.values(SCENE_SCRIPT_ASSET_COLORS)) {
      expect(color).not.toBe(PLACEHOLDER_ASSET_COLOR);
    }
  });

  it("ignores inherited properties when looking a kind up", () => {
    // ``assetGeometryFor`` guards with hasOwnProperty so that a script whose
    // ``type`` happens to be "constructor" or "toString" does not resolve to
    // Object.prototype and render something.
    expect(assetGeometryFor("constructor")).toBeUndefined();
    expect(assetGeometryFor("toString")).toBeUndefined();
    expect(assetGeometryFor("")).toBeUndefined();
  });
});
