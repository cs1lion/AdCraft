/**
 * LowPolyActorMesh — what a NON-HUMAN actor looks like in the preview.
 *
 * WHY THIS IS ITS OWN COMPONENT, NOT A BRANCH INSIDE THE FIGURE
 * `LowPolyHuman` is a seven-segment rig with hips and shoulders: every pose it
 * can hold is a limb angle pitched about a segment's top end. A door is neither
 * a hip nor a shoulder — a hinge has no vocabulary in that rig — so routing a
 * door through it would draw a person where a door belongs. The non-human
 * actor therefore renders here, and `objectMotionAt` supplies its motion (a
 * rotation about its own pivot, a translation) instead of a `SegmentPose`.
 *
 * WHY THE SHAPE TABLE IS SHARED WITH THE PROPS
 * `assetGeometryFor` is the same registry `PropMesh` renders from, and that is
 * the load-bearing part: an actor and a prop of the same kind call the same
 * builder with the same scale, so they are guaranteed to look identical — same
 * silhouette, same palette colour, same shadows. The builders own their own
 * `MeshStandardMaterial` (the palette is the shared colour contract in
 * `sceneScriptGeometry.tsx`), and the Blender converter paints a non-human type
 * from that same palette — `_build_asset` hands a builder an explicit colour
 * only for `lowpoly_human` — so repainting here would make the preview disagree
 * with the render. A kind with no geometry renders the magenta placeholder the
 * rest of the preview uses, so a stale bundle shows a hole instead of a
 * confident wrong answer (ADR 0005 §4).
 *
 * Everything positional belongs to the caller: the outer group carries the
 * authored position and yaw, the inner one the motion delta. This component
 * contributes the shape, and the pointer plumbing that makes it editable.
 */

import { useCallback, useMemo } from "react";
import {
  BoxGeometry,
  Group,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
} from "./LeanSceneCanvas";
import { assetGeometryFor } from "./sceneScriptGeometry";
import { PLACEHOLDER_ASSET_COLOR } from "../../../types/scene-script.generated";
import type { SceneObjectRef } from "./sceneScriptEditModel";
import type { SceneVec3 } from "./sceneScriptAxes";

/**
 * The edit contract every selectable object answers to.
 *
 * A structural copy of the same-named interface in `SceneScript3DPreview.tsx`
 * (which does not export it): identical shape is what lets the preview's
 * `handlersFor` value land here unchanged, so a non-human actor is selected and
 * dragged by exactly the code path a prop uses.
 */
interface EditHandlers {
  editMode: boolean;
  selected: boolean;
  onSelect: (ref: SceneObjectRef) => void;
  onDragStart: (ref: SceneObjectRef, scenePosition: SceneVec3) => void;
  onDragMove: (ref: SceneObjectRef, scenePosition: SceneVec3) => void;
  onDragEnd: () => void;
  overridePosition?: SceneVec3;
}

/**
 * Pointer plumbing for one selectable object, mirroring the preview's
 * `useEditHandlers`: the ground-plane drag itself is owned by `useGroundDrag`
 * at the scene root, so a mesh only announces "grabbed here" on pointer down
 * and relays moves while a button is held.
 */
function useActorEditHandlers(
  handlers: EditHandlers,
  ref: SceneObjectRef,
  scenePosition: SceneVec3,
) {
  const { editMode, onSelect, onDragStart, onDragMove } = handlers;
  const handlePointerDown = useCallback(
    (event: { stopPropagation: () => void }) => {
      if (!editMode) return;
      // Do not let the canvas orbit the camera when grabbing an object.
      event.stopPropagation();
      onSelect(ref);
      onDragStart(ref, scenePosition);
    },
    [editMode, onSelect, onDragStart, ref, scenePosition],
  );
  const handlePointerMove = useCallback(
    (event: { buttons: number }) => {
      if (!editMode || event.buttons === 0) return;
      onDragMove(ref, scenePosition);
    },
    [editMode, onDragMove, ref, scenePosition],
  );
  return { handlePointerDown, handlePointerMove };
}

/**
 * The canonical scale: the shape table's own. The branch passes no
 * `appearance.scale` down, so an actor builds at the same scale a prop with no
 * declared scale does — which is what keeps the two identical.
 */
const ACTOR_SCALE = 1;

/**
 * The caller's groups own the yaw (and the motion delta rides on it), so the
 * builder's own `rotationY` stays zero: passing one here would yaw the shape a
 * second time.
 */
const ACTOR_YAW = 0;

/** The caller's groups own the position too; builders add their own lift. */
const ACTOR_ORIGIN: SceneVec3 = [0, 0, 0];

export function ActorMesh({
  kind,
  color,
  handlers,
  ref,
}: {
  /** The declared kind — `door`, `crate`, `box`, `pillar`: the shape-table key. */
  kind: string;
  /**
   * The actor's authored appearance colour. Deliberately not painted onto the
   * shape: the shared builders own their materials and the converter paints a
   * non-human type from the same palette, so the actor's look comes from the
   * table (see the header). Kept in the contract because it is part of what a
   * character carries, and it is what a future per-actor tint would hook.
   */
  color: string;
  handlers: EditHandlers;
  /** Which scene object this is (`{ kind: "character", id }`), for select/drag. */
  ref: SceneObjectRef;
}) {
  const geometry = useMemo(() => {
    // The same lookup `PropMesh` makes: one registry, one answer per kind.
    const build = assetGeometryFor(kind);
    if (build) {
      return build({ scale: ACTOR_SCALE, rotationY: ACTOR_YAW, pos: ACTOR_ORIGIN });
    }
    // No geometry for this kind — the magenta box the props render, for the same
    // reason: the converter's placeholder colour is the one colour nothing real
    // uses, so "missing" is never mistaken for "faithful". `unimplementedKinds`
    // is exactly `assetGeometryFor(kind) === undefined`, so the HUD's count and
    // this box agree by construction.
    return (
      <Mesh
        position={[
          ACTOR_ORIGIN[0],
          ACTOR_ORIGIN[1] + 0.25 * ACTOR_SCALE,
          ACTOR_ORIGIN[2],
        ]}
        rotation={[0, ACTOR_YAW, 0]}
        castShadow
      >
        <BoxGeometry args={[0.5 * ACTOR_SCALE, 0.5 * ACTOR_SCALE, 0.5 * ACTOR_SCALE]} />
        <MeshStandardMaterial
          color={PLACEHOLDER_ASSET_COLOR}
          emissive={PLACEHOLDER_ASSET_COLOR}
          emissiveIntensity={0.6}
        />
      </Mesh>
    );
  }, [kind]);

  // `PropMesh` seeds a drag from the object's authored position. The branch
  // passes none — the position lives on the caller's groups — so the origin is
  // the drag ghost when there is one and the object's own rest pose (the pivot
  // the groups translate) otherwise. Every buildable actor kind stands on the
  // ground plane, so the ground-plane drag lands where the object is.
  const scenePosition: SceneVec3 = handlers.overridePosition ?? ACTOR_ORIGIN;
  const { handlePointerDown, handlePointerMove } = useActorEditHandlers(
    handlers,
    ref,
    scenePosition,
  );

  return (
    // Pointer events bubble up the object graph, so one handler on the group
    // covers every mesh the geometry builder produced.
    <Group onPointerDown={handlePointerDown}>
      {geometry}
      {handlers.editMode && (
        // Grab proxy: some actor shapes are thin targets (a door is 15 cm), so
        // edit mode adds an invisible box over the silhouette that also carries
        // the move/up half of the gesture. Invisible meshes are NOT raycast by
        // three.js — hence opacity 0, not visible={false}.
        <Mesh
          position={[
            ACTOR_ORIGIN[0],
            ACTOR_ORIGIN[1] + 0.25 * ACTOR_SCALE,
            ACTOR_ORIGIN[2],
          ]}
          onPointerMove={handlePointerMove}
          onPointerUp={handlers.onDragEnd}
        >
          <BoxGeometry
            args={[
              Math.max(0.6, ACTOR_SCALE),
              Math.max(0.6, ACTOR_SCALE),
              Math.max(0.6, ACTOR_SCALE),
            ]}
          />
          <MeshBasicMaterial transparent opacity={0} depthWrite={false} />
        </Mesh>
      )}
    </Group>
  );
}
