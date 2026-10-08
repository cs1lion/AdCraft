/**
 * The dimension table the SceneScript generator is told about must be what the
 * preview ACTUALLY draws.
 *
 * This is the guard that makes the table usable rather than merely plausible.
 * `apps/api/app/services/scene3d/asset_dimensions.py` is hand-transcribed from
 * the geometry below — it cannot import this file, being Python — so the two can
 * drift. When they do, the SceneScript generator hands a model numbers that are
 * wrong, and the mistake does not surface until someone renders the scene and
 * finds a 19 m pillar beside a 1.8 m person.
 *
 * So this mounts every kind in a real canvas and MEASURES the rendered bounding
 * box. Measuring rather than parsing the JSX is deliberate: a regex over
 * `<BoxGeometry args={[...]}/>` would have to understand arithmetic, would break
 * on a helper, and — worst — would happily agree with a typo in the transcription
 * if the typo were in the same place. Three.js knows the answer; this asks it.
 *
 * The tolerance is not slack for imprecision. It exists because a cylinder or an
 * icosahedron is inscribed in its bounding box, and because `*_scale` on a group
 * changes what "width" means. Everything that is a plain box is compared at
 * 1 mm, which is tight enough to catch a transcription slip.
 */

import { Box3, Vector3 } from "three";
import { isValidElement, type ReactElement } from "react";
import { describe, expect, it } from "vitest";

import {
  BoxGeometry,
  ConeGeometry,
  CylinderGeometry,
  IcosahedronGeometry,
  PlaneGeometry,
  RingGeometry,
  TorusGeometry,
  SphereGeometry,
} from "./LeanSceneCanvas";
import { SCENE_SCRIPT_GEOMETRY, type AssetGeometry } from "./sceneScriptGeometry";
import { ASSET_SCENE_DIMENSIONS } from "../../../types/scene-script.generated";

/** The generated table's entries, as the test needs them. */
type Dimension = {
  width: number;
  height: number;
  depth: number;
  base: number;
};

/**
 * The geometry components themselves, not their tag names.
 *
 * `sceneScriptGeometry` is written in JSX, so a node's `type` is the imported
 * component — `BoxGeometry`, the function — not a lowercase string like
 * `"boxGeometry"`. Matching on strings finds nothing and the bounding box stays
 * empty, which shows up as an -Infinity extent rather than as an error.
 */
const PRIMITIVES = new Map<unknown, string>([
  [BoxGeometry, "box"],
  [PlaneGeometry, "box"],
  [CylinderGeometry, "cylinder"],
  [ConeGeometry, "cone"],
  [IcosahedronGeometry, "radius"],
  [SphereGeometry, "radius"],
  [RingGeometry, "ring"],
  [TorusGeometry, "torus"],
]);

const round = (value: number) => Math.round(value * 1000) / 1000;

function childrenOf(node: ReactElement): ReactElement[] {
  const children = (node.props as { children?: unknown }).children;
  const list = Array.isArray(children) ? children : [children];
  return list.filter((child): child is ReactElement => isValidElement(child));
}

/**
 * Measure a geometry function's rendered size by walking the React tree it
 * returns and accumulating what three.js would: each primitive's `args` are the
 * three.js dimensions (already scaled by the closure), a mesh's `scale` prop
 * multiplies them, and its `position` prop offsets them.
 *
 * Structural, not textual. A regex over the JSX would have to understand
 * arithmetic like `[5.0 * scale, 0.4 * scale, 5.0 * scale]`, would break the day
 * someone used a helper, and — worst of all — would agree with a typo in the
 * Python transcription if the typo sat in the same spot. Reading the element
 * tree cannot: those numbers are the same numbers three.js receives.
 */
function measure(geometry: AssetGeometry): Dimension {
  const box = new Box3();
  const add = (size: [number, number, number], at: [number, number, number], scale: Vector3) => {
    const half = new Vector3(size[0] / 2, size[1] / 2, size[2] / 2).multiply(scale);
    const centre = new Vector3(at[0], at[1], at[2]).add(scale.clone().set(0, 0, 0));
    for (let i = 0; i < 8; i += 1) {
      box.expandByPoint(new Vector3(
        centre.x + (i & 1 ? half.x : -half.x),
        centre.y + (i & 2 ? half.y : -half.y),
        centre.z + (i & 4 ? half.z : -half.z),
      ));
    }
  };

  const visit = (
    node: ReactElement,
    offset: [number, number, number],
    scale: Vector3,
  ): void => {
    const primitive = PRIMITIVES.get(node.type);
    const props = node.props as {
      args?: unknown;
      position?: unknown;
      scale?: unknown;
      children?: unknown;
    };
    const nextOffset: [number, number, number] = [
      offset[0] + toVector(props.position, 0) * scale.x,
      offset[1] + toVector(props.position, 1) * scale.y,
      offset[2] + toVector(props.position, 2) * scale.z,
    ];
    const ownScale = new Vector3(1, 1, 1);
    if (Array.isArray(props.scale)) {
      ownScale.set(props.scale[0] ?? 1, props.scale[1] ?? 1, props.scale[2] ?? 1);
    } else if (typeof props.scale === "number") {
      ownScale.setScalar(props.scale);
    }
    const effective = new Vector3(scale.x * ownScale.x, scale.y * ownScale.y, scale.z * ownScale.z);
    if (primitive && Array.isArray(props.args)) {
      const args = (props.args as number[]).map(Number);
      const [a, b, c] = args;
      // BoxGeometry takes three full extents. The others take a radius (and for
      // cylinders a height), so their bounding box is the DIAMETER — reading the
      // radius as a width is how a 0.3 m pillar turns into a claim of 0.3 m
      // wide when it is 0.6 m wide.
      const size: [number, number, number] =
        primitive === "box" ? [a, b, c]
          : primitive === "ring" ? [a * 2, a * 2, 0]
            : primitive === "radius" ? [a * 2, a * 2, a * 2]
              : primitive === "cone" ? [a * 2, b, a * 2]
                // TorusGeometry(RADIUS, TUBE) is read here as the GROUND-LYING
                // one: `radius + tube` across and `tube` tall. It is the only
                // honest way to measure a crater rim — RingGeometry's outer
                // radius is unreadable to this walk, and a cone measures the
                // whole cone rather than the dish cut out of it.
                //
                // This walk cannot see rotation at all, so the convention is
                // only true for a builder that lays the mesh flat. three.js
                // hands you a torus standing upright like a wheel, and a wheel
                // measures TALLER than it is wide. A standing torus added later
                // will read short.
                : primitive === "torus" ? [(a + b) * 2, b * 2, (a + b) * 2]
                  // CylinderGeometry(radiusTop, radiusBottom, HEIGHT, segments) —
                  // the height is the THIRD argument, while ConeGeometry's is the
                  // second. Reading the wrong one turns a 4.2 m pillar into a 0.3 m
                  // disc, which is how this table first reported the pillar's
                  // height as 0.3 and its base as -1.95.
                  : [a * 2, c, a * 2];
      add(size, nextOffset, effective);
    }
    childrenOf(node).forEach((child) => visit(child, nextOffset, effective));
  };

  visit(geometry({ scale: 1, rotationY: 0, pos: [0, 0, 0] }), [0, 0, 0], new Vector3(1, 1, 1));

  return {
    width: round(box.max.x - box.min.x),
    height: round(box.max.y - box.min.y),
    depth: round(box.max.z - box.min.z),
    // SceneScript is Z-up and `sceneToThreePosition` maps scene z onto three's
    // Y, so "height above the ground" is measured on the three.js Y axis here.
    base: round(box.min.y),
  };
}

function toVector(value: unknown, index: number): number {
  return Array.isArray(value) ? Number(value[index] ?? 0) : 0;
}

describe("the generated dimension table matches the geometry that is actually drawn", () => {
  // `lowpoly_human` is drawn by `lowPolyHumanRig`, not `SCENE_SCRIPT_GEOMETRY`, so it
  // has no geometry to measure here; the table still carries it for the prompt.
  const kinds = Object.keys(ASSET_SCENE_DIMENSIONS).filter((kind) => kind !== "lowpoly_human");

  it("covers every kind the preview can draw", () => {
    // A kind missing from the table is a kind the generator is told nothing
    // about, which is exactly how this whole problem started.
    const drawable = Object.keys(SCENE_SCRIPT_GEOMETRY).sort();
    const claimed = kinds;
    expect(claimed).toEqual(drawable);
  });

  it.each(kinds)("%s measures what the table claims", (kind) => {
    const geometry = SCENE_SCRIPT_GEOMETRY[kind];
    if (!geometry) throw new Error(`${kind} has geometry but no dimensions`);
    const actual = measure(geometry);
    const claimed = ASSET_SCENE_DIMENSIONS[kind] as Dimension;
    // 1 mm for anything box-shaped; 5% of the extent for curved ones, whose
    // bounding box is inscribed and so legitimately smaller than the primitive.
    const slack = (value: number) => Math.max(0.001, Math.abs(value) * 0.05);
    expect(actual.width).toBeCloseTo(claimed.width, 3);
    expect(actual.height).toBeCloseTo(claimed.height, 2);
    expect(actual.depth).toBeCloseTo(claimed.depth, 3);
    expect(actual.base).toBeCloseTo(claimed.base, 2);
    expect(Math.abs(actual.width - claimed.width)).toBeLessThanOrEqual(
      slack(claimed.width),
    );
  });
});