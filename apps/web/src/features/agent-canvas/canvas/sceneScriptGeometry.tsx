/**
 * Geometry registry for the SceneScript browser preview (ADR 0005 §3).
 *
 * The preview used to be a ``switch (prop.type)`` with a grey-box ``default``.
 * That list drifted from the schema: 7 of the 25 kinds the backend declares had
 * geometry, and the other 18 rendered as the same ``#888888`` box Blender uses
 * for an unimplemented asset -- so the browser could not tell a faithful
 * preview from a missing one any better than the renderer could.
 *
 * Two things changed. First, this is now a *registry* rather than a switch, so
 * the missing kinds are a visible hole in a typed ``Record`` instead of a
 * fallthrough. Second, the set of kinds is not ours to invent: it comes from
 * ``src/types/scene-script.generated.ts``, which the Python schema emits, so
 * adding a kind on the backend makes ``TypeScript`` fail to compile here until
 * someone gives it geometry.
 *
 * The proportions mirror ``app/services/scene3d/blender_converter.py`` so the
 * browser and the Blender frames agree on what a thing looks like. They will
 * drift again eventually; the colours at least cannot, because they are shared
 * (``SCENE_SCRIPT_ASSET_COLORS``). When geometry does drift, the rendered
 * preview is still honest -- it is a low-fidelity sketch, not the deliverable.
 *
 * Axis note: Blender is Z-up and three.js is Y-up, so every builder's
 * ``scale = (x, y, z)`` becomes ``args = [x, z, y]`` here, and a Blender
 * ``location=(x, y, z)`` becomes ``position=[x, z, y]``.
 */

import type { ReactElement } from "react";

import {
  BoxGeometry,
  ConeGeometry,
  CylinderGeometry,
  Group,
  IcosahedronGeometry,
  Mesh,
  MeshStandardMaterial,
} from "./LeanSceneCanvas";
import {
  KIND_ROTATION_PIVOT,
  PLACEHOLDER_ASSET_COLOR,
  SCENE_SCRIPT_ASSET_COLORS,
  SCENE_SCRIPT_PART_COLOR_OVERRIDES,
  type EnvironmentTypeName,
  type PropTypeName,
} from "../../../types/scene-script.generated";

/** Every asset kind the backend schema declares. */
export type SceneScriptKind = PropTypeName | EnvironmentTypeName;

export interface AssetGeometryArgs {
  /** The asset's own ``scale`` multiplier, defaulted to 1. */
  scale: number;
  /** Yaw in radians. */
  rotationY: number;
  /** World position. */
  pos: [number, number, number];
}

export type AssetGeometry = (args: AssetGeometryArgs) => ReactElement;

/**
 * Colour a kind renders in, from the converter's palette.
 *
 * Falls back to the converter's own fallback brown rather than to a hardcoded
 * value, so a kind that exists in the enum but not in the palette still looks
 * like a surface instead of like the missing-asset placeholder.
 */
function colourFor(kind: SceneScriptKind): string {
  return SCENE_SCRIPT_ASSET_COLORS[kind] ?? SCENE_SCRIPT_ASSET_COLORS.box ?? "#B08D57";
}

/** A box at an already-scaled local position and size. */
function box(
  position: readonly [number, number, number],
  size: readonly [number, number, number],
  colour: string,
  key?: string,
): ReactElement {
  return (
    <Mesh key={key} position={position} castShadow>
      <BoxGeometry args={size} />
      <MeshStandardMaterial color={colour} />
    </Mesh>
  );
}

/** A cylinder/cone standing on the ground, centred on its local position. */
function column(
  position: readonly [number, number, number],
  radiusTop: number,
  radiusBottom: number,
  height: number,
  colour: string,
  segments = 16,
): ReactElement {
  return (
    <Mesh position={position} castShadow>
      <CylinderGeometry args={[radiusTop, radiusBottom, height, segments]} />
      <MeshStandardMaterial color={colour} />
    </Mesh>
  );
}

/** Four legs at the corners of a footprint, for tables and chairs. */
function legs(
  offsets: readonly (readonly [number, number])[],
  y: number,
  size: readonly [number, number, number],
  colour: string,
): ReactElement[] {
  return offsets.map(([x, z], i) => box([x, y, z], size, colour, `leg${i}`));
}

// ---------------------------------------------------------------------------
// Prop geometry
// ---------------------------------------------------------------------------

const roundTable: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Group position={pos} rotation={[0, rotationY, 0]}>
    {column([0, 0.75 * scale, 0], 0.6 * scale, 0.6 * scale, 0.05, colourFor("round_table"))}
    {column([0, 0.375 * scale, 0], 0.08, 0.08, 0.75, colourFor("round_table"), 8)}
  </Group>
);

const rectTable: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Group position={pos} rotation={[0, rotationY, 0]}>
    {box([0, 0.75 * scale, 0], [1.5 * scale, 0.05, 0.9 * scale], colourFor("rect_table"), "top")}
    {legs(
      [
        [-0.65, -0.35],
        [0.65, -0.35],
        [-0.65, 0.35],
        [0.65, 0.35],
      ],
      0.36 * scale,
      [0.08 * scale, 0.36 * scale, 0.08 * scale],
      colourFor("rect_table"),
    )}
  </Group>
);

const chair: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Group position={pos} rotation={[0, rotationY, 0]}>
    {box([0, 0.45 * scale, 0], [0.5 * scale, 0.05, 0.5 * scale], colourFor("chair"), "seat")}
    {box([0, 0.9 * scale, -0.24 * scale], [0.5 * scale, 0.45, 0.05], colourFor("chair"), "back")}
    {legs(
      [
        [-0.2, -0.2],
        [0.2, -0.2],
        [-0.2, 0.2],
        [0.2, 0.2],
      ],
      0.22 * scale,
      [0.05 * scale, 0.22 * scale, 0.05 * scale],
      colourFor("chair"),
    )}
  </Group>
);

const stool: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Group position={pos} rotation={[0, rotationY, 0]}>
    {column([0, 0.5 * scale, 0], 0.28 * scale, 0.28 * scale, 0.06, colourFor("stool"))}
    {column([0, 0.25 * scale, 0], 0.05, 0.05, 0.5 * scale, colourFor("stool"), 8)}
  </Group>
);

const lantern: AssetGeometry = ({ scale, rotationY, pos }) => {
  const colour = colourFor("lantern");
  return (
    <Mesh position={[pos[0], pos[1] + 2.8 * scale, pos[2]]} rotation={[0, rotationY, 0]}>
      <BoxGeometry args={[0.3 * scale, 0.4 * scale, 0.3 * scale]} />
      {/* Emissive, matching the converter: a lantern is the one asset whose
          whole point is that it is a light source. */}
      <MeshStandardMaterial color={colour} emissive={colour} emissiveIntensity={0.5} />
    </Mesh>
  );
};

const boxProp: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh position={[pos[0], pos[1] + 0.4 * scale, pos[2]]} rotation={[0, rotationY, 0]} castShadow>
    <BoxGeometry args={[0.8 * scale, 0.8 * scale, 0.8 * scale]} />
    <MeshStandardMaterial color={colourFor("box")} />
  </Mesh>
);

const crate: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh position={[pos[0], pos[1] + 0.45 * scale, pos[2]]} rotation={[0, rotationY, 0]} castShadow>
    <BoxGeometry args={[0.9 * scale, 0.9 * scale, 0.9 * scale]} />
    <MeshStandardMaterial color={colourFor("crate")} />
  </Mesh>
);

/**
 * Tapered solid. ``cylinderGeometry(radiusTop, radiusBottom, ...)`` is the
 * three.js spelling of Blender's ``primitive_cone_add(radius1, radius2)`` --
 * the converter uses the cone operator for the same reason: a cylinder takes a
 * single radius and cannot express a top/bottom pair.
 */
const vase: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh position={[pos[0], pos[1] + 0.3 * scale, pos[2]]} rotation={[0, rotationY, 0]} castShadow>
    <CylinderGeometry args={[0.14 * scale, 0.24 * scale, 0.6 * scale, 16]} />
    <MeshStandardMaterial color={colourFor("vase")} />
  </Mesh>
);

const weapon: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Group position={pos} rotation={[0, rotationY, 0]}>
    {box([0, 1.0 * scale, 0], [0.06 * scale, 1.1 * scale, 0.02], colourFor("weapon"), "blade")}
    {box([0, 0.32 * scale, 0], [0.05 * scale, 0.28 * scale, 0.05], colourFor("weapon"), "grip")}
  </Group>
);

const scroll: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh
    position={[pos[0], pos[1] + 1.0 * scale, pos[2]]}
    // Laid on its side, as in the converter's ``rotation_euler.x = 90``.
    rotation={[Math.PI / 2, rotationY, 0]}
    castShadow
  >
    <CylinderGeometry args={[0.12 * scale, 0.12 * scale, 0.9 * scale, 12]} />
    <MeshStandardMaterial color={colourFor("scroll")} />
  </Mesh>
);

const book: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh position={[pos[0], pos[1] + 0.04 * scale, pos[2]]} rotation={[0, rotationY, 0]} castShadow>
    <BoxGeometry args={[0.34 * scale, 0.08 * scale, 0.26 * scale]} />
    <MeshStandardMaterial color={colourFor("book")} />
  </Mesh>
);

const cup: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh position={[pos[0], pos[1] + 0.07 * scale, pos[2]]} rotation={[0, rotationY, 0]} castShadow>
    <CylinderGeometry args={[0.07 * scale, 0.09 * scale, 0.14 * scale, 12]} />
    <MeshStandardMaterial color={colourFor("cup")} />
  </Mesh>
);

// ---------------------------------------------------------------------------
// Environment geometry
// ---------------------------------------------------------------------------

const wall: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh
    position={[pos[0], pos[1] + 2.5 * scale, pos[2]]}
    rotation={[0, rotationY, 0]}
    castShadow
    receiveShadow
  >
    <BoxGeometry args={[6.0 * scale, 5.0 * scale, 0.3 * scale]} />
    <MeshStandardMaterial color={colourFor("wall")} />
  </Mesh>
);

const pillar: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh
    position={[pos[0], pos[1] + 2.1 * scale, pos[2]]}
    rotation={[0, rotationY, 0]}
    castShadow
  >
    <CylinderGeometry args={[0.3 * scale, 0.3 * scale, 4.2 * scale, 8]} />
    <MeshStandardMaterial color={colourFor("pillar")} />
  </Mesh>
);

const floor: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh
    position={[pos[0], pos[1] - 0.05 * scale, pos[2]]}
    rotation={[0, rotationY, 0]}
    receiveShadow
  >
    <BoxGeometry args={[15.0 * scale, 0.1 * scale, 15.0 * scale]} />
    <MeshStandardMaterial color={colourFor("floor")} />
  </Mesh>
);

const ground: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh
    position={[pos[0], pos[1] - 0.05 * scale, pos[2]]}
    rotation={[0, rotationY, 0]}
    receiveShadow
  >
    <BoxGeometry args={[15.0 * scale, 0.1 * scale, 15.0 * scale]} />
    <MeshStandardMaterial color={colourFor("ground")} />
  </Mesh>
);

/** A gable roof: a 4-sided cone, yawed 45° so a ridge faces the camera. */
const gableRoof: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh
    position={[pos[0], pos[1] + 5.5 * scale, pos[2]]}
    rotation={[0, rotationY, Math.PI / 4]}
    castShadow
  >
    <ConeGeometry args={[4.0 * scale, 3.0 * scale, 4]} />
    <MeshStandardMaterial color={colourFor("gable_roof")} />
  </Mesh>
);

const flatRoof: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh
    position={[pos[0], pos[1] + 5.2 * scale, pos[2]]}
    rotation={[0, rotationY, 0]}
    castShadow
  >
    <BoxGeometry args={[6.4 * scale, 0.25 * scale, 5.2 * scale]} />
    <MeshStandardMaterial color={colourFor("flat_roof")} />
  </Mesh>
);

const door: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh
    position={[pos[0], pos[1] + 1.1 * scale, pos[2]]}
    rotation={[0, rotationY, 0]}
    castShadow
  >
    <BoxGeometry args={[1.0 * scale, 2.2 * scale, 0.15 * scale]} />
    <MeshStandardMaterial color={colourFor("door")} />
  </Mesh>
);

const windowEnv: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh
    position={[pos[0], pos[1] + 1.8 * scale, pos[2]]}
    rotation={[0, rotationY, 0]}
    castShadow
  >
    <BoxGeometry args={[1.4 * scale, 1.6 * scale, 0.12 * scale]} />
    <MeshStandardMaterial color={colourFor("window")} />
  </Mesh>
);

const stairs: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Group position={pos} rotation={[0, rotationY, 0]}>
    {[0, 1, 2, 3, 4].map((i) => (
      <Mesh key={i} position={[0, 0.2 * scale * (i + 1), 0.9 * scale * i]} castShadow>
        <BoxGeometry args={[2.4 * scale, 0.2 * scale, 0.9 * scale]} />
        <MeshStandardMaterial color={colourFor("stairs")} />
      </Mesh>
    ))}
  </Group>
);

const platform: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh
    position={[pos[0], pos[1] + 0.4 * scale, pos[2]]}
    rotation={[0, rotationY, 0]}
    castShadow
    receiveShadow
  >
    <BoxGeometry args={[5.0 * scale, 0.4 * scale, 5.0 * scale]} />
    <MeshStandardMaterial color={colourFor("platform")} />
  </Mesh>
);

const tree: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Group position={pos} rotation={[0, rotationY, 0]}>
    {column(
      [0, 1.3 * scale, 0],
      0.22 * scale,
      0.22 * scale,
      2.6 * scale,
      SCENE_SCRIPT_PART_COLOR_OVERRIDES._Trunk ?? colourFor("tree"),
      8,
    )}
    <Mesh position={[0, 3.4 * scale, 0]} castShadow>
      <IcosahedronGeometry args={[1.7 * scale, 1]} />
      <MeshStandardMaterial
        color={SCENE_SCRIPT_PART_COLOR_OVERRIDES._Canopy ?? colourFor("tree")}
      />
    </Mesh>
  </Group>
);

const rock: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Mesh
    position={[pos[0], pos[1] + 0.6 * scale, pos[2]]}
    rotation={[0, rotationY, 0]}
    scale={[1.4 * scale, 0.8 * scale, 1.1 * scale]}
    castShadow
  >
    <IcosahedronGeometry args={[0.9, 1]} />
    <MeshStandardMaterial color={colourFor("rock")} />
  </Mesh>
);

const fence: AssetGeometry = ({ scale, rotationY, pos }) => (
  <Group position={pos} rotation={[0, rotationY, 0]}>
    {[0, 1, 2, 3].map((i) => (
      <Mesh key={i} position={[0, 0.8 * scale, 1.5 * scale * (i - 1.5)]} castShadow>
        <BoxGeometry args={[0.12 * scale, 0.8 * scale, 0.12 * scale]} />
        <MeshStandardMaterial color={colourFor("fence")} />
      </Mesh>
    ))}
  </Group>
);

// ---------------------------------------------------------------------------
// The registry
// ---------------------------------------------------------------------------

/**
 * Geometry per declared kind.
 *
 * ``Record<SceneScriptKind, ...>`` is the load-bearing part: it is a total map
 * over the schema's enums, so ``TypeScript`` refuses to compile if a kind is
 * added to ``PROP_TYPES``/``ENVIRONMENT_TYPES`` without an entry here. The old
 * ``switch`` accepted a new kind silently and rendered a grey box.
 */
export const SCENE_SCRIPT_GEOMETRY: Record<SceneScriptKind, AssetGeometry> = {
  // Props
  round_table: roundTable,
  rect_table: rectTable,
  chair,
  stool,
  lantern,
  box: boxProp,
  crate,
  vase,
  weapon,
  scroll,
  book,
  cup,
  // Environment
  wall,
  pillar,
  floor,
  gable_roof: gableRoof,
  flat_roof: flatRoof,
  door,
  window: windowEnv,
  stairs,
  platform,
  tree,
  rock,
  fence,
  ground,
};

/** A kind's rotation pivot, or the origin when it declares none.
 *
 * Re-exported from the generated contract so ``PropMesh`` reads the same table
 * the Blender converter does. Coords are SceneScript's Z-up; the geometry builders
 * below work in three.js's Y-up, so a vertical offset gets swapped on the way into
 * the scene graph. Yaw is not in the table -- ``rotation[1]`` is applied to the
 * inner mesh, which already spins about the object's own vertical axis.
 */
export function rotationPivotFor(kind: string): readonly [number, number, number] {
  return Object.prototype.hasOwnProperty.call(KIND_ROTATION_PIVOT, kind)
    ? KIND_ROTATION_PIVOT[kind as SceneScriptKind]!
    : [0, 0, 0];
}

/** Geometry for a kind, or ``undefined`` if the preview has none for it. */
export function assetGeometryFor(kind: string): AssetGeometry | undefined {
  return Object.prototype.hasOwnProperty.call(SCENE_SCRIPT_GEOMETRY, kind)
    ? SCENE_SCRIPT_GEOMETRY[kind as SceneScriptKind]
    : undefined;
}

/**
 * Kinds the schema declares but the preview has no geometry for.
 *
 * Empty in practice -- the ``Record`` type makes it hard to be otherwise -- but
 * a script can still arrive from the backend with a kind the *frontend build*
 * predates (a stale bundle), and this is what the HUD counts.
 */
export function unimplementedKinds(kinds: readonly string[]): string[] {
  return kinds.filter((kind) => assetGeometryFor(kind) === undefined);
}

export { PLACEHOLDER_ASSET_COLOR };
