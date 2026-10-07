/**
 * SceneScript 3D Preview Component.
 *
 * Renders a low-fidelity 3D preview of a SceneScript using Three.js
 * (via @react-three/fiber). Shows characters, props, environment objects,
 * and camera positions with orbit controls.
 *
 * This is the frontend preview engine (ADR 0005 §3). The backend Blender
 * renderer produces production frames; this component gives instant feedback.
 *
 * Interactive editing (3D director workbench P1): with `editMode` enabled the
 * same viewport becomes the editor — click to select, drag on the ground
 * plane to move, and the drop commits through `onDragCommit` to the pure
 * edit model (sceneScriptEditModel). Playback and editing are two modes of
 * ONE scene state, so what the agent builds can be grabbed by hand without a
 * second editor.
 *
 * Axis discipline: SceneScript is Blender Z-up ([x, y, z] = right, forward,
 * up); three.js is Y-up. Every scene coordinate crosses `sceneScriptAxes`
 * exactly once, in both directions, so drags land in the axis Blender means.
 */

import {
  AmbientLight,
  BoxGeometry,
  BufferAttribute,
  BufferGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  DirectionalLight,
  Grid,
  Group,
  Html,
  IcosahedronGeometry,
  LeanSceneCanvas as Canvas,
  Line,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  OrbitControls,
  RingGeometry,
  SphereGeometry,
  useFrame,
  useThree,
} from "./LeanSceneCanvas";
import {
  bobOffset,
  cyclePhaseForDistance,
  segmentPoseAt,
  travelledMetres,
  type SegmentPose,
} from "./characterPose";
import { cyclePhaseForFrame, objectMotionAt } from "./objectMotion";
import { cameraLabel, cameraLabelsById, shotForFrame } from "./shotLabels";
import { shotCameraPoseAtFrame } from "./sceneDepthPass";
import { useRef, useMemo, useCallback, useEffect, useState, type ReactNode } from "react";
import * as THREE from "three";
import { useSceneScriptPlayback } from "./SceneScriptPlaybackContext";
import { activeDialogueLineAtFrame } from "./activeDialogueLine.ts";
import { audioTimeForFrame, shouldSeekAudio } from "./animaticAudio.ts";
import { blockingPathLength, characterPathPoints, type BlockingPathPoint } from "./blockingPath";
import { heldItemPositionAtFrame } from "./heldItems";
import type {
  SceneScriptRoot,
  SceneCharacter,
  SceneProp,
  SceneCamera,
  SceneEnvironment,
  CameraKeyframe,
} from "../../../types/scene-script";
import { PLACEHOLDER_ASSET_COLOR } from "../../../types/scene-script.generated";
import { assetGeometryFor, unimplementedKinds } from "./sceneScriptGeometry";
import {
  CHARACTER_SKIN_COLOR,
  characterRig,
  DEFAULT_CHARACTER_COLOR,
  type CharacterSegment,
} from "./lowPolyHumanRig";
import { ActorMesh } from "./LowPolyActorMesh";
import { objectLodTier } from "./sceneFidelity";
import { DepthPassRecorder, type ControlDepthPassOptions } from "./sceneDepthPassRecorder";
import {
  sceneToThreePosition,
  sceneYawToThreeRotation,
  type SceneVec3,
} from "./sceneScriptAxes";
import {
  characterActionAtFrame,
  characterStateAtFrame,
  sceneObjectPositionAtFrame,
  type SceneObjectRef,
  propStateAtFrame,
} from "./sceneScriptEditModel";

// ---------------------------------------------------------------------------
// Shared edit handlers (one contract for every selectable object)
// ---------------------------------------------------------------------------

interface EditHandlers {
  editMode: boolean;
  selected: boolean;
  onSelect: (ref: SceneObjectRef) => void;
  onDragStart: (ref: SceneObjectRef, scenePosition: SceneVec3) => void;
  onDragMove: (ref: SceneObjectRef, scenePosition: SceneVec3) => void;
  onDragEnd: () => void;
  overridePosition?: SceneVec3;
}

function useEditHandlers(handlers: EditHandlers, ref: SceneObjectRef, scenePosition: SceneVec3) {
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

// ---------------------------------------------------------------------------
// Keyframe interpolation (characters + cameras share the shape)
// ---------------------------------------------------------------------------


function interpolateCameraKeyframes(
  keyframes: CameraKeyframe[],
  frame: number,
): CameraKeyframe | null {
  if (keyframes.length === 0) return null;
  if (keyframes.length === 1 || frame <= keyframes[0].frame) return keyframes[0];
  const last = keyframes[keyframes.length - 1];
  if (frame >= last.frame) return last;
  for (let i = 0; i < keyframes.length - 1; i++) {
    const a = keyframes[i];
    const b = keyframes[i + 1];
    if (frame >= a.frame && frame <= b.frame) {
      const t = (frame - a.frame) / (b.frame - a.frame || 1);
      return {
        frame,
        position: [
          a.position[0] + (b.position[0] - a.position[0]) * t,
          a.position[1] + (b.position[1] - a.position[1]) * t,
          a.position[2] + (b.position[2] - a.position[2]) * t,
        ],
        look_at: [
          a.look_at[0] + (b.look_at[0] - a.look_at[0]) * t,
          a.look_at[1] + (b.look_at[1] - a.look_at[1]) * t,
          a.look_at[2] + (b.look_at[2] - a.look_at[2]) * t,
        ],
      };
    }
  }
  return keyframes[0];
}

// ---------------------------------------------------------------------------
// Low-poly Human
// ---------------------------------------------------------------------------

/** The geometry one rig segment renders with, at the segment's own scale. */
function SegmentGeometry({ segment }: { segment: CharacterSegment }) {
  if (segment.geometry.kind === "box") return <BoxGeometry args={segment.geometry.size} />;
  if (segment.geometry.kind === "cylinder") {
    return (
      <CylinderGeometry
        args={[segment.geometry.radius, segment.geometry.radius, segment.geometry.depth, 8]}
      />
    );
  }
  return <SphereGeometry args={[segment.geometry.radius, 8, 8]} />;
}

function LowPolyHuman({
  character,
  frame,
  dialogueLines,
  frameRate,
  handlers,
}: {
  character: SceneCharacter;
  frame: number;
  dialogueLines: readonly SpeechOverlayLine[];
  frameRate: number;
  handlers: EditHandlers;
}) {
  const color = character.appearance.color ?? DEFAULT_CHARACTER_COLOR;
  // The body is the rig the Blender converter emits — seven segments at the
  // converter's own proportions of `height`, not a box with a sphere on top.
  // A box character in the preview and a leg-having character in the render
  // is the disagreement this closes (docs/plans/threejs-renderer-replacement
  // .md §3.6): after the renderer swap, the preview IS the render.
  const rig = useMemo(() => characterRig(character.appearance), [character.appearance]);
  const { height, headY, headRadius } = rig;
  // The head is a rig segment like any other, except that a gesture keyframe
  // tilts it: it renders inside its own group so the tilt cannot drag the
  // torso, the mouth or the label with it.
  const head = rig.segments.find((segment) => segment.part === "head")!;
  const bodySegments = rig.segments.filter((segment) => segment.part !== "head");

  const ref = useMemo<SceneObjectRef>(() => ({ kind: "character", id: character.id }), [character.id]);
  const interpolated = useMemo(() => {
    const state = characterStateAtFrame(character, frame);
    return { position: state.position, rotationY: sceneYawToThreeRotation(state.rotationY) };
  }, [character, frame]);
  const scenePosition = handlers.overridePosition ?? interpolated.position;
  const threePosition = sceneToThreePosition(scenePosition);
  const { handlePointerDown, handlePointerMove } = useEditHandlers(handlers, ref, scenePosition);

  // Lip-sync visibility: the talk keyframes the dialogue pipeline wrote are
  // the same state the Blender render animates — the viewport must show the
  // mouth open at exactly those frames, or "who speaks now" is invisible.
  const action = characterActionAtFrame(character, frame);
  const isSpeaking = action === "talk";
  const isGesturing = action === "gesture";

  // NON-HUMAN ACTOR BRANCH.
  //
  // A door, a wheel and a dropship are authored in `characters[]` because the
  // scene acts through them, and their motion is a delta on the object's own
  // rest pose — not a limb angle. Routing them through the human rig would
  // leave the rig drawing a person where a door belongs, so they render from
  // the same geometry table the props use (which already knows every buildable
  // kind) with `objectMotionAt` applied on top.
  //
  // Deliberately NOT a special case inside the rig: the rig's vocabulary is
  // hips and shoulders, and a hinge is neither.
  if (character.type !== "lowpoly_human") {
    const motion = objectMotionAt(action, cyclePhaseForFrame(action, frame, frameRate));
    return (
      <Group position={threePosition} rotation={[0, interpolated.rotationY, 0]}>
        <Group
          position={[
            motion.translation?.[0] ?? 0,
            motion.translation?.[2] ?? 0,
            -(motion.translation?.[1] ?? 0),
          ]}
          rotation={[
            motion.rotation?.[0] ?? 0,
            -(motion.rotation?.[1] ?? 0),
            -(motion.rotation?.[2] ?? 0),
          ]}
        >
          <ActorMesh
            kind={character.type}
            color={character.appearance.color ?? DEFAULT_CHARACTER_COLOR}
            handlers={handlers}
            ref={ref}
          />
        </Group>
      </Group>
    );
  }
  const mouthOpen = isSpeaking ? headRadius * 0.5 : headRadius * 0.08;

  // The POSE: what the limbs are doing at this frame. Before this existed the
  // rig built the seven segments once and never rotated them again, so `walk`
  // slid the whole body along the ground with its legs welded in place — the
  // schema had said "walk" all along and nothing translated it.
  //
  // Phase comes from how far the character has TRAVELLED, not from the wall
  // clock: a character whose keyframes hold it still keeps both feet down, and
  // one that runs takes more steps per second. A clock would also desynchronise
  // from the motion, and the feet would skate.
  const pose = useMemo(() => {
    const keyframes = character.keyframes;
    const distance = travelledMetres(
      keyframes.map((keyframe) => keyframe.position),
      keyframes.map((keyframe) => keyframe.frame),
      frame,
    );
    return segmentPoseAt(action, cyclePhaseForDistance(distance));
  }, [character, frame, action]);

  // The bob is a TRANSLATION of the whole figure, and it is deliberately not
  // multiplied by a limb length: that is how a walk ends up bouncing someone off
  // the ground.
  const bob = bobOffset(pose, rig);
  // A gesture keyframe tilts the whole head group forward ~15 deg; the pose's
  // own head pitch rides with it.
  const headTilt = (isGesturing ? -0.26 : 0) + (pose.head ?? 0);
  // The line whose time window covers "now" for THIS speaker.
  const activeLine = activeDialogueLineAtFrame(dialogueLines, character.id, frame, frameRate);
  return (
    <Group
      position={[threePosition[0], threePosition[1] + bob, threePosition[2]]}
      rotation={[0, interpolated.rotationY, 0]}
    >
      {/* Body: the converter's segments. The whole figure highlights when
          selected — a highlight that stopped at the torso would leave the
          author selecting legs that do not answer.

          Each segment is wrapped in a group pinned to its PROXIMAL end (the
          hip for a leg, the shoulder for an arm), and the mesh is offset down
          inside it. That is what makes the segment swing rather than orbit: a
          rotation applied to the segment's own centre would carry the foot
          sideways in an arc, which reads as a puppet on strings. The rig has no
          bones — seven boxes is what the converter emits — so pivoting about
          the top end is the whole of the articulation. */}
      {bodySegments.map((segment) => {
                const pitchField = POSE_FIELD[segment.part];
        const pitch = pitchField ? (pose[pitchField] ?? 0) : 0;
        // The pivot is the segment's TOP end, so the extent below it is what
        // matters: a box's height, a cylinder's depth, and a sphere has none
        // (the head carries no limb rotation, and its own pitch is on its group).
        const reach =
          segment.geometry.kind === "box" ? segment.geometry.size[1] / 2
            : segment.geometry.kind === "cylinder" ? segment.geometry.depth / 2
              : 0;
        return (
          <Group
            key={segment.part}
            position={[segment.position[0], segment.position[1] + reach, segment.position[2]]}
            rotation={[pitch, 0, 0]}
          >
            <Mesh position={[0, -reach, 0]} castShadow>
              <SegmentGeometry segment={segment} />
              <MeshStandardMaterial
                color={segment.paint === "skin" ? CHARACTER_SKIN_COLOR : color}
                emissive={handlers.selected ? "#FFD166" : "#000000"}
                emissiveIntensity={handlers.selected ? 0.35 : 0}
              />
            </Mesh>
          </Group>
        );
      })}
      {/* Head: a gesture keyframe tilts the whole head group forward ~15 deg.
          The segment's own position is the head centre, which this group
          carries, so the mesh sits at its group's origin. */}
      <Group rotation={[headTilt, 0, 0]} position={[0, headY, 0]}
        data-gesturing={isGesturing ? "true" : "false"}>
        <Mesh castShadow>
          <SegmentGeometry segment={head} />
          <MeshStandardMaterial
            color={CHARACTER_SKIN_COLOR}
            emissive={handlers.selected ? "#FFD166" : "#000000"}
            emissiveIntensity={handlers.selected ? 0.35 : 0}
          />
        </Mesh>
      </Group>
      {/* Mouth: opens on the talk keyframes the dialogue pipeline wrote.
          Deterministic from the frame (no animation loop) so the preview,
          the inspector and the Blender render agree. Anchored to the head
          exactly as before: just below the head centre, forward of the face. */}
      <Mesh
        position={[0, headY - headRadius * 0.18, headRadius * 0.82]}
        data-testid={`character-mouth-${character.id}`}
        data-speaking={isSpeaking ? "true" : "false"}
      >
        <BoxGeometry args={[headRadius * 0.5, mouthOpen, headRadius * 0.12]} />
        <MeshStandardMaterial color={isSpeaking ? "#3B2F2F" : "#C9A88F"} />
      </Mesh>
      {/* Speech overlay: the current line floats above its speaker.
          DOM (not troika text): the viewport already loads three.js and drei,
          and a canvas-texture sprite would cost a texture upload per line. */}
      {activeLine && (
        <Html position={[0, headY + headRadius * 1.8, 0]} center distanceFactor={10}>
          <div className="scene-script-speech-overlay" data-testid={`speech-overlay-${character.id}`}>
            {activeLine.text}
          </div>
        </Html>
      )}
      {/* ID label (small cone on top) */}
      <Mesh position={[0, headY + headRadius * 1.2 + 0.1, 0]}>
        <ConeGeometry args={[0.08, 0.15, 4]} />
        <MeshStandardMaterial color={color} emissive={color} emissiveIntensity={0.3} />
      </Mesh>
      {/* Grab proxy: the segment meshes are small targets, so edit mode adds a
          transparent cylinder covering the whole silhouette. (Invisible meshes
          are NOT raycast by three.js — hence opacity 0, not visible={false}.) */}
      {handlers.editMode && (
        <Mesh
          position={[0, height * 0.5, 0]}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlers.onDragEnd}
        >
          <CylinderGeometry args={[height * 0.3, height * 0.3, height, 8]} />
          <MeshBasicMaterial transparent opacity={0} depthWrite={false} />
        </Mesh>
      )}
    </Group>
  );
}

// ---------------------------------------------------------------------------
// Blocking marks (per-keyframe floor marks + path length)
// ---------------------------------------------------------------------------

/**
 * Dots on the selected character's keyframes with their frame numbers, plus
 * the total blocking length. Pairs with the existing TrajectoryLine (which
 * draws the path itself): this adds the READING — which frame, how far.
 */
function BlockingMarks({
  points,
  characterId,
}: {
  points: BlockingPathPoint[];
  characterId: string;
}) {
  const metres = blockingPathLength(points);
  return (
    <Group>
      {points.map((point) => (
        <Group key={`mark-${point.frame}`} position={point.threePosition}>
          <Mesh>
            <SphereGeometry args={[0.06, 8, 8]} />
            <MeshBasicMaterial color="#FFD166" />
          </Mesh>
          <Html position={[0, 0.3, 0]} center distanceFactor={9}>
            <span className="blocking-mark" data-testid={`blocking-mark-${characterId}`}>
              ◆{point.frame}
            </span>
          </Html>
        </Group>
      ))}
      <Html position={points[points.length - 1].threePosition} center distanceFactor={9}>
        <span className="blocking-length" data-testid={`blocking-length-${characterId}`}>
          走位 {metres.toFixed(1)}m
        </span>
      </Html>
    </Group>
  );
}

// Prop / environment mesh
// ---------------------------------------------------------------------------

function PropMesh({
  prop,
  kind,
  handlers,
  frame,
  heldPosition,
  /** V3 ④ LOD: the object's declared coarseness tier. ``rough`` collapses the geometry to a single primitive box. */
  lodTier = "standard",
}: {
  prop: SceneProp | SceneEnvironment;
  /** V3 ④ LOD tier: ``rough`` collapses the geometry to a primitive box. */
  lodTier?: import("./sceneFidelity.ts").LodTier;
  kind: "prop" | "environment";
  handlers: EditHandlers;
  /** The playhead, for keyframed motion. */
  frame: number;
  /**
   * Held-item follow (V0.2 §5): the holder's hand position at the current
   * frame. Wins over the authored position (which is only the rest position
   * once held) but loses to the drag ghost — the author is always right.
   */
  heldPosition?: [number, number, number] | null;
}) {
  const scale = prop.scale ?? 1.0;
  const rotationY = ((prop.rotation_y ?? 0) * Math.PI) / 180;
  const scenePosition = handlers.overridePosition ?? heldPosition ?? prop.position;
  const pos = sceneToThreePosition(scenePosition);

  // KEYFRAMED MOTION. null for a prop that never moves, in which case every
  // value below is the authored rest pose and this branch is inert.
  //
  // The non-yaw half of the rotation has to be applied about the OBJECT's own
  // pivot, so when a prop is keyframed the geometry is built at local origin
  // and a wrapping group carries both the pivot and that rotation. Building it
  // at the interpolated position instead would spin it about the world origin.
  const keyframed = useMemo(
    () => propStateAtFrame({ ...prop, rotation_y: prop.rotation_y ?? 0 }, frame),
    [prop, frame],
  );
  const liveScale = keyframed?.scale ?? scale;
  const liveYaw = keyframed ? (keyframed.rotation[1] * Math.PI) / 180 : rotationY;
  const buildPos: SceneVec3 = keyframed ? [0, 0, 0] : pos;
  const pivot = keyframed
    ? sceneToThreePosition(
        handlers.overridePosition ?? heldPosition ?? keyframed.position,
      )
    : pos;
  const extraRotation: [number, number, number] = keyframed
    ? [
        (keyframed.rotation[0] * Math.PI) / 180,
        0,
        (keyframed.rotation[2] * Math.PI) / 180,
      ]
    : [0, 0, 0];

  const ref = useMemo<SceneObjectRef>(() => ({ kind, id: prop.id }), [kind, prop.id]);

  const geometry = useMemo(() => {
    // V3 ④ LOD 阶梯：rough tier 只画一个原语占位（白模阶段“有”比“像”重要）。
    if (lodTier === "rough") {
      return (
        <Mesh
          position={[buildPos[0], buildPos[1] + 0.25 * liveScale, buildPos[2]]}
          rotation={[0, liveYaw, 0]}
          castShadow
          data-testid={`lod-rough-${kind}-${prop.id}`}
        >
          <BoxGeometry args={[0.5 * liveScale, 0.5 * liveScale, 0.5 * liveScale]} />
          <MeshStandardMaterial
            color={PLACEHOLDER_ASSET_COLOR}
            emissive={PLACEHOLDER_ASSET_COLOR}
            emissiveIntensity={0.35}
          />
        </Mesh>
      );
    }
    const build = assetGeometryFor(prop.type);
    if (build) {
      return build({ scale: liveScale, rotationY: liveYaw, pos: buildPos });
    }
    // No geometry for this kind. Deliberately not grey: the converter's own
    // placeholder colour is magenta because nothing real is that colour, and a
    // reviewer must be able to tell "missing" from "faithful" at a glance
    // (ADR 0005 §4: queryable degradation, never silent).
    return (
      <Mesh
        position={[buildPos[0], buildPos[1] + 0.25 * liveScale, buildPos[2]]}
        rotation={[0, liveYaw, 0]}
        castShadow
      >
        <BoxGeometry args={[0.5 * liveScale, 0.5 * liveScale, 0.5 * liveScale]} />
        <MeshStandardMaterial
          color={PLACEHOLDER_ASSET_COLOR}
          emissive={PLACEHOLDER_ASSET_COLOR}
          emissiveIntensity={0.6}
        />
      </Mesh>
    );
  }, [prop.type, lodTier, buildPos, liveYaw, liveScale]);

  const { handlePointerDown, handlePointerMove } = useEditHandlers(handlers, ref, scenePosition);

  const body = (
    // r3f pointer events bubble up the object graph, so one handler on the
    // group covers every mesh the geometry builder produced.
    <Group onPointerDown={handlePointerDown}>
      {geometry}
      {handlers.editMode && (
        <Mesh
          position={[buildPos[0], buildPos[1] + 0.25 * liveScale, buildPos[2]]}
          onPointerMove={handlePointerMove}
          onPointerUp={handlers.onDragEnd}
        >
          <BoxGeometry
            args={[Math.max(0.6, liveScale), Math.max(0.6, liveScale), Math.max(0.6, liveScale)]}
          />
          <MeshBasicMaterial transparent opacity={0} depthWrite={false} />
        </Mesh>
      )}
    </Group>
  );

  // A keyframed prop's non-yaw rotation turns about its own pivot, so the body
  // (built at local origin) is placed and rotated by this group instead.
  if (!keyframed) return body;
  return (
    <Group position={[pivot[0], pivot[1], pivot[2]]} rotation={extraRotation}>
      {body}
    </Group>
  );
}

// ---------------------------------------------------------------------------
// Camera Gizmo
// ---------------------------------------------------------------------------

function CameraGizmo({
  camera,
  label,
  active,
  frame,
  handlers,
}: {
  camera: SceneCamera;
  /** Human-readable shot name, e.g. "机位05 | 飞船俯瞰". */
  label: string;
  active: boolean;
  frame: number;
  handlers: EditHandlers;
}) {
  const keyframe = useMemo(
    () => interpolateCameraKeyframes(camera.keyframes, frame),
    [camera.keyframes, frame],
  );
  const ref = useMemo<SceneObjectRef>(() => ({ kind: "camera", id: camera.id }), [camera.id]);

  // All hooks run before any early return: a camera with zero keyframes
  // renders nothing, but the hook order must stay stable across renders.
  const position = useMemo(
    () => (keyframe ? sceneToThreePosition(keyframe.position) : null),
    [keyframe],
  );
  const lookAt = useMemo(
    () => (keyframe ? sceneToThreePosition(keyframe.look_at) : null),
    [keyframe],
  );
  const direction = useMemo(
    () =>
      position && lookAt
        ? new THREE.Vector3(
            lookAt[0] - position[0],
            lookAt[1] - position[1],
            lookAt[2] - position[2],
          ).normalize()
        : null,
    [lookAt, position],
  );
  const { handlePointerDown, handlePointerMove } = useEditHandlers(
    handlers,
    ref,
    keyframe?.position ?? [0, 0, 0],
  );
  if (!keyframe || !position || !lookAt || !direction) return null;

  // The gizmo follows the camera's interpolated position at the current frame,
  // so a multi-keyframe camera move is visible instead of frozen at frame 0.
  const bodyColor = handlers.selected ? "#FFD166" : active ? "#00FF00" : "#4444FF";
  return (
    <Group position={position} onPointerDown={handlePointerDown}>
      {/* Camera body */}
      <Mesh>
        <BoxGeometry args={[0.3, 0.2, 0.4]} />
        <MeshStandardMaterial color={bodyColor} emissive={bodyColor} emissiveIntensity={0.3} />
      </Mesh>
      {/* Lens (cone pointing toward look_at) */}
      <Mesh
        position={[direction.x * 0.3, direction.y * 0.3, direction.z * 0.3]}
        rotation={[0, Math.atan2(direction.x, direction.z), 0]}
      >
        <ConeGeometry args={[0.12, 0.25, 8]} />
        <MeshStandardMaterial color="#222222" />
      </Mesh>
      {/* Frustum lines */}
      <LineSegments>
        <BufferGeometry>
          <BufferAttribute
            attach="attributes-position"
            args={[
              new Float32Array([
                0, 0, 0, direction.x * 3, direction.y * 3 - 1, direction.z * 3,
                0, 0, 0, direction.x * 3, direction.y * 3 + 1, direction.z * 3,
              ]),
              3,
            ]}
          />
        </BufferGeometry>
        <LineBasicMaterial color={bodyColor} opacity={0.4} transparent />
      </LineSegments>
      {/* Shot name, floating above the body. A camera you cannot name is a
          camera you cannot ask an agent to move: this label is the handle the
          reference framework's "选中一个元素或机位" refers to. */}
      <Html position={[0, 0.42, 0]} center distanceFactor={9}>
        <span
          className="scene-script-camera-label"
          data-camera-label={camera.id}
          data-active={active ? "true" : "false"}
        >
          {label}
        </span>
      </Html>
    </Group>
  );
}

// ---------------------------------------------------------------------------
// Selection ring + trajectory lines
// ---------------------------------------------------------------------------

function SelectionRing({ position }: { position: [number, number, number] }) {
  return (
    <Mesh position={[position[0], 0.02, position[2]]} rotation={[-Math.PI / 2, 0, 0]} renderOrder={999}>
      <RingGeometry args={[0.45, 0.62, 32]} />
      <MeshBasicMaterial color="#FFD166" transparent opacity={0.95} depthTest={false} />
    </Mesh>
  );
}

/** Polyline through converted scene positions (camera move / character path). */
function TrajectoryLine({
  points,
  color,
  opacity = 0.75,
}: {
  points: SceneVec3[];
  color: string;
  /** Emphasis knob: the selected object's path is drawn brighter. */
  opacity?: number;
}) {
  const flat = useMemo(() => {
    const values: number[] = [];
    for (const point of points) {
      const converted = sceneToThreePosition(point);
      values.push(converted[0], 0.06, converted[2]);
    }
    return new Float32Array(values);
  }, [points]);

  if (points.length < 2) return null;
  return (
    <LineSegments>
      <BufferGeometry>
        <BufferAttribute attach="attributes-position" args={[flat, 3]} />
      </BufferGeometry>
      <LineBasicMaterial color={color} transparent opacity={opacity} />
    </LineSegments>
  );
}

// ---------------------------------------------------------------------------
// Shot camera rig (lives inside the Canvas: needs useThree + useFrame)
// ---------------------------------------------------------------------------

/**
 * Puts the render camera where the SCRIPT says the camera is.
 *
 * WHY A COMPONENT, NOT THE `<Canvas camera={{...}}>` PROP
 * `LeanSceneCanvas` reads that prop once, in a mount-only effect, to construct
 * the `PerspectiveCamera` — see the `camera` prop's own docstring. A prop that
 * changes with the playhead therefore changes nothing: a headless render captured
 * all 720 frames of a 4-shot previs from one fixed vantage, so every cut and
 * camera move — the entire reason a previs exists — was absent from the output.
 * Two earlier attempts to fix that through the prop failed for the same reason.
 *
 * So the pose is applied here, to the camera object, on every frame, from the
 * same `shotCameraPoseAtFrame` the depth pass uses: preview, control pass and
 * captured frames cannot disagree about where the camera is.
 *
 * Three things this has to get right, each of which was wrong before:
 *   - AXES. SceneScript is Z-up ([right, forward, up]); three.js is Y-up
 *     ([right, up, back]). The pose goes through `sceneToThreePosition` like
 *     every other position in this file. Passing the raw keyframe put shot 1 of
 *     the jinghai scene 18 m UNDERGROUND instead of 6 m up — a render that
 *     produced an empty green screen, identical to having no fix at all.
 *   - AIM. The pose carries a `look_at`, and the canvas camera is only ever
 *     constructed looking at the world origin. Moving it without aiming frames
 *     whatever happens to be in front of a camera pointed at (0,0,0) — which is
 *     how a "fixed" render ends up as a wall in the face.
 *   - WHO OWNS THE CAMERA. `OrbitControls` also writes it, every frame, when
 *     enabled. The rig therefore runs only when the author is not flying the
 *     view (`enabled={!editMode}`), which is the same condition that gates
 *     OrbitControls — so there is never more than one writer.
 */
function ShotCameraRig({
  pose,
  enabled,
}: {
  /** SceneScript-space pose, or null when the script names no usable camera. */
  pose: { position: SceneVec3; lookAt: SceneVec3 } | null;
  enabled: boolean;
}) {
  const { camera } = useThree();
  // Through a ref, so the render loop always reads the current pose without
  // re-subscribing (or rebuilding the callback) on every seek.
  const poseRef = useRef(pose);
  poseRef.current = pose;
  const target = useMemo(() => new THREE.Vector3(), []);

  useFrame(() => {
    const current = poseRef.current;
    if (!enabled || !current) return;
    const position = sceneToThreePosition(current.position);
    const lookAt = sceneToThreePosition(current.lookAt);
    camera.position.set(position[0], position[1], position[2]);
    camera.lookAt(target.set(lookAt[0], lookAt[1], lookAt[2]));
    camera.updateMatrixWorld();
  });

  return null;
}

/** Which pose field drives which segment. A segment with no entry never moves. */
const POSE_FIELD: Partial<Record<string, keyof SegmentPose>> = {
  torso: "torso",
  LegL: "legL",
  LegR: "legR",
  ArmL: "armL",
  ArmR: "armR",
  neck: "spine",
};

// ---------------------------------------------------------------------------
// Ground-plane drag layer (lives inside the Canvas: needs useThree)
// ---------------------------------------------------------------------------

/**
 * Draw-a-path camera motion (V0.2 §8.3): the author drags a trajectory on the
 * ground and the system understands it as Camera Motion. Window-level
 * pointer capture (the same modal-gesture pattern as placement) collects the
 * raw polyline; the pure converter (cameraGesturePath) does the resampling.
 * A drag with no travel commits nothing — a click is not a move.
 */
function CameraGestureLayer({
  onCommit,
  onCancel,
}: {
  onCommit: (points: SceneVec3[]) => void;
  onCancel?: () => void;
}) {
  const { camera, gl, raycaster } = useThree();
  const [drawing, setDrawing] = useState<SceneVec3[] | null>(null);
  const drawingRef = useRef<SceneVec3[] | null>(null);
  drawingRef.current = drawing;

  const groundFromEvent = useCallback(
    (event: PointerEvent): SceneVec3 | null => {
      const rect = gl.domElement.getBoundingClientRect();
      const ndc = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(ndc, camera);
      const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
      const hit = new THREE.Vector3();
      if (!raycaster.ray.intersectPlane(plane, hit)) return null;
      return [Math.round(hit.x * 100) / 100, Math.round(hit.z * 100) / 100, 0];
    },
    [camera, gl, raycaster],
  );

  useEffect(() => {
    const handleDown = (event: PointerEvent) => {
      const ground = groundFromEvent(event);
      if (!ground) return;
      drawingRef.current = [ground];
      setDrawing([ground]);
    };
    const handleMove = (event: PointerEvent) => {
      if (!drawingRef.current) return;
      const ground = groundFromEvent(event);
      if (!ground) return;
      const points = drawingRef.current;
      const last = points[points.length - 1];
      // Skip micro-movements: the converter resamples by arc length anyway,
      // and a leaner polyline keeps the live preview cheap.
      if (Math.hypot(ground[0] - last[0], ground[1] - last[1]) < 0.05) return;
      drawingRef.current = [...points, ground];
      setDrawing(drawingRef.current);
    };
    const handleUp = () => {
      const points = drawingRef.current;
      drawingRef.current = null;
      setDrawing(null);
      if (points && points.length > 1) onCommit(points);
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && onCancel) {
        event.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("pointerdown", handleDown);
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    window.addEventListener("keydown", handleKey);
    return () => {
      window.removeEventListener("pointerdown", handleDown);
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      window.removeEventListener("keydown", handleKey);
    };
  }, [groundFromEvent, onCommit, onCancel]);

  if (!drawing || drawing.length < 2) return null;
  return (
    <Line>
      <BufferGeometry>
        <BufferAttribute
          attach="attributes-position"
          args={[
            new Float32Array(
              drawing.flatMap((point) => {
                const three = sceneToThreePosition(point);
                return [three[0], 0.06, three[2]];
              }),
            ),
            3,
          ]}
        />
      </BufferGeometry>
      <LineBasicMaterial color="#FFD166" linewidth={2} />
    </Line>
  );
}

interface GroundDrag {
  start: (ref: SceneObjectRef, scenePosition: SceneVec3) => void;
  active: boolean;
}

/**
 * Owns the pointer once a drag starts: raycasts the pointer against the
 * ground plane (y=0) on window move/up, so the drag survives leaving the
 * object's mesh, and reports `active` so OrbitControls can stand down for
 * the duration (orbiting and grabbing must not both respond to one drag).
 *
 * Height is preserved from the drag start: ground-plane dragging moves an
 * object in x/y only, exactly like dragging a piece on a floor plan.
 */
function useGroundDrag(
  onDragMove: (ref: SceneObjectRef, scenePosition: SceneVec3) => void,
  onDragCommit: (ref: SceneObjectRef, scenePosition: SceneVec3) => void,
): GroundDrag {
  const { camera, gl, raycaster } = useThree();
  const [active, setActive] = useState(false);
  const dragRef = useRef<{ ref: SceneObjectRef; height: number } | null>(null);
  const lastPositionRef = useRef<SceneVec3 | null>(null);

  // Callbacks live in refs so a parent re-render mid-drag (ghost updates)
  // never re-subscribes the window listeners.
  const moveRef = useRef(onDragMove);
  const commitRef = useRef(onDragCommit);
  useEffect(() => {
    moveRef.current = onDragMove;
    commitRef.current = onDragCommit;
  });

  const start = useCallback((ref: SceneObjectRef, scenePosition: SceneVec3) => {
    dragRef.current = { ref, height: scenePosition[2] };
    lastPositionRef.current = scenePosition;
    setActive(true);
  }, []);

  useEffect(() => {
    if (!active) return;
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const ndc = new THREE.Vector2();
    const hit = new THREE.Vector3();

    const handleMove = (event: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const rect = gl.domElement.getBoundingClientRect();
      ndc.set(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(ndc, camera);
      if (!raycaster.ray.intersectPlane(plane, hit)) return;
      const position: SceneVec3 = [
        Math.round(hit.x * 100) / 100,
        Math.round(hit.z * 100) / 100,
        drag.height,
      ];
      lastPositionRef.current = position;
      moveRef.current(drag.ref, position);
    };

    const handleUp = () => {
      const drag = dragRef.current;
      const last = lastPositionRef.current;
      if (drag && last) commitRef.current(drag.ref, last);
      dragRef.current = null;
      setActive(false);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    window.addEventListener("pointercancel", handleUp);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      window.removeEventListener("pointercancel", handleUp);
    };
  }, [active, camera, gl, raycaster]);

  return { start, active };
}

function SceneDragLayer({
  onDragMove,
  onDragCommit,
  children,
}: {
  onDragMove: (ref: SceneObjectRef, scenePosition: SceneVec3) => void;
  onDragCommit: (ref: SceneObjectRef, scenePosition: SceneVec3) => void;
  children: (drag: GroundDrag) => ReactNode;
}) {
  const drag = useGroundDrag(onDragMove, onDragCommit);
  return <>{children(drag)}</>;
}

// ---------------------------------------------------------------------------
// Camera placement layer (P2: click position -> click look-at)
// ---------------------------------------------------------------------------

interface CameraPlacementProps {
  onCommit: (placement: { position: SceneVec3; lookAt: SceneVec3 }) => void;
  onCancel?: () => void;
}

/**
 * Click-to-place a camera on the ground plane: the first click fixes the
 * camera position, the second fixes the look-at target (with a live preview
 * line between them). Escape cancels; the caller owns the mode toggle.
 */
function CameraPlacementLayer({ onCommit, onCancel }: CameraPlacementProps) {
  const { camera, gl, raycaster } = useThree();
  const [stage, setStage] = useState<"position" | "look_at">("position");
  const [anchor, setAnchor] = useState<SceneVec3 | null>(null);
  const [cursor, setCursor] = useState<SceneVec3 | null>(null);
  const stageRef = useRef(stage);
  const anchorRef = useRef<SceneVec3 | null>(null);
  stageRef.current = stage;
  anchorRef.current = anchor;

  const groundFromEvent = useCallback(
    (event: PointerEvent): SceneVec3 | null => {
      const rect = gl.domElement.getBoundingClientRect();
      const ndc = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(ndc, camera);
      const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
      const hit = new THREE.Vector3();
      if (!raycaster.ray.intersectPlane(plane, hit)) return null;
      // SceneScript ground coords: [right, forward]; height comes from the
      // eye-level anchor gizmo, not from the click.
      return [Math.round(hit.x * 100) / 100, Math.round(hit.z * 100) / 100, 0];
    },
    [camera, gl, raycaster],
  );

  // Window-level capture (same pattern as the drag controller): placement is
  // a modal gesture, so every click in the viewport places the camera and
  // never accidentally selects an object behind the ground plane.
  useEffect(() => {
    const handleMove = (event: PointerEvent) => {
      const ground = groundFromEvent(event);
      if (ground) setCursor(ground);
    };
    const handleDown = (event: PointerEvent) => {
      const ground = groundFromEvent(event);
      if (!ground) return;
      if (stageRef.current === "position") {
        setAnchor(ground);
        setStage("look_at");
        return;
      }
      onCommit({ position: anchorRef.current ?? ground, lookAt: ground });
      setStage("position");
      setAnchor(null);
      setCursor(null);
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && onCancel) {
        event.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerdown", handleDown);
    window.addEventListener("keydown", handleKey);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerdown", handleDown);
      window.removeEventListener("keydown", handleKey);
    };
  }, [groundFromEvent, onCommit, onCancel]);

  // The anchor gizmo sits at camera eye height (1.6 m) so the placed camera
  // is visible in the scene rather than buried in the floor.
  const anchorThree = anchor ? sceneToThreePosition([anchor[0], anchor[1], 1.6]) : null;
  const linePoints = useMemo(() => {
    if (!anchorThree || !cursor) return null;
    const target = sceneToThreePosition([cursor[0], cursor[1], 1.6]);
    return new Float32Array([...anchorThree, ...target]);
  }, [anchorThree, cursor]);

  return (
    <Group>
      {anchorThree && (
        <Mesh position={anchorThree}>
          <BoxGeometry args={[0.3, 0.2, 0.4]} />
          <MeshStandardMaterial color="#FFD166" emissive="#FFD166" emissiveIntensity={0.5} />
        </Mesh>
      )}
      {linePoints && (
        <LineSegments>
          <BufferGeometry>
            <BufferAttribute attach="attributes-position" args={[linePoints, 3]} />
          </BufferGeometry>
          <LineBasicMaterial color="#FFD166" transparent opacity={0.8} />
        </LineSegments>
      )}
    </Group>
  );
}

// ---------------------------------------------------------------------------
// Main Preview Component
// ---------------------------------------------------------------------------

export interface SceneScript3DPreviewProps {
  sceneScript: SceneScriptRoot;
  height?: number;
  /** Interactive editing mode (3D director workbench). Read-only when false. */
  editMode?: boolean;
  /**
   * Keep the drawing buffer readable after compositing, so a caller can read
   * pixels OUTSIDE the render callback. Required by the headless render path;
   * off by default because it costs a buffer copy per frame.
   */
  captureFrames?: boolean;
  /**
   * Draw the AUTHORING aids: per-camera gizmos (body, lens cone, frustum lines)
   * and their `<Html>` labels. Default true — they are how an author reads the
   * shot list, in editing and in playback alike.
   *
   * The headless render passes false, and it must. The lens cone sits 0.3 m in
   * front of its own camera, so once the render camera actually follows the shot
   * camera (it did not, until `ShotCameraRig`), the gizmo for the ACTIVE shot sits
   * 0.3 m from the lens and fills the middle of every delivered frame with a black
   * cone. Verified on jinghai frame 0: gating the gizmos turns a frame dominated by
   * that cone into a legible wide shot of the base.
   *
   * A separate prop rather than a rule like "hide whenever not editing": the
   * editor's playback view genuinely wants the labels, and the render genuinely
   * must not have them, so the caller that knows which one it is says so.
   */
  showGizmos?: boolean;
  selectedObject?: SceneObjectRef | null;
  onSelect?: (ref: SceneObjectRef | null) => void;
  /** Live drag updates: local preview state only. */
  onDragMove?: (ref: SceneObjectRef, scenePosition: SceneVec3) => void;
  /** Drag drop: persisted by the caller through the pure edit model. */
  onDragCommit?: (ref: SceneObjectRef, scenePosition: SceneVec3) => void;
  /** Camera placement mode: first click sets position, second sets look-at. */
  placementMode?: boolean;
  onPlacementCommit?: (placement: { position: SceneVec3; lookAt: SceneVec3 }) => void;
  /** Exit placement without changing the selected object. */
  onPlacementCancel?: () => void;
  /** Draw-a-path camera motion (V0.2 §8.3): drag a trajectory on the ground. */
  gestureMode?: boolean;
  onGestureCommit?: (points: SceneVec3[]) => void;
  /** Exit drawing without changing the selected object. */
  onGestureCancel?: () => void;
  /**
   * Animatic audio (V0.2 §7/§14.9): the scene's speech track plays with the
   * playhead so the author can judge rhythm and performance, not just see the
   * blocking. The voice is the real thing; only the picture is cheap.
   */
  speechAudioUrl?: string | null;
  /**
   * Dialogue lines (seconds) for the speech overlay: the current line floats
   * above its speaker, so "who says what, when" is visible in the 3D
   * viewport — the mouth opens on the same window (both ride the talk
   * keyframes the lip-sync wrote).
   */
  dialogueLines?: readonly SpeechOverlayLine[];
  /**
   * Extra scene content rendered INSIDE the preview's canvas, after the scene
   * itself. Same contract as the canvas' own children: the elements live in
   * the scene graph and can read `useThree`/`useFrame`. Used by the browser
   * test harness to count what the character actually drew.
   */
  children?: ReactNode;
  /**
   * DEPTH control pass (ADR 0005 §4, three.js-renderer plan §4.5). When set,
   * the preview renders a second depth pass at each shot's 5 keyframe frames
   * and delivers `depth_<N>.png` for them — the exact file layout
   * `control_passes.collect_control_passes` collects beside the colour
   * frames. Absent in the authoring UI (a preview should not spend a second
   * render per frame on a pass nobody asked for).
   */
  controlDepthPass?: ControlDepthPassOptions;
}

/** One dialogue line as the live overlay consumes it. */
export interface SpeechOverlayLine {
  character_id: string;
  text: string;
  /** Seconds. */
  start_time: number;
  /** Seconds; may be missing (the caller only knows the start). */
  end_time?: number | null;
}

export function SceneScript3DPreview({
  sceneScript,
  height = 400,
  editMode = false,
  selectedObject = null,
  dialogueLines = [],
  onSelect,
  onDragMove,
  onDragCommit,
  placementMode = false,
  gestureMode = false,
  speechAudioUrl = null,
  onPlacementCommit,
  onPlacementCancel,
  onGestureCommit,
  onGestureCancel,
  captureFrames = false,
  showGizmos = true,
  children,
  controlDepthPass,
}: SceneScript3DPreviewProps) {
  const { currentFrame, isPlaying, totalFrames, toggle, seekToFrame, pause } =
    useSceneScriptPlayback();
  // Animatic audio: the element follows the playhead both ways. While
  // playing the audio IS the clock (no seeks — they would stutter the voice);
  // while paused a drag re-seeks so scrubbing previews the dialogue.
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [audioEnabled, setAudioEnabled] = useState(true);
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (!speechAudioUrl || !audioEnabled) {
      audio.pause();
      return;
    }
    const target = audioTimeForFrame(currentFrame, sceneScript.scene.frame_rate);
    if (isPlaying) {
      if (shouldSeekAudio(currentFrame, sceneScript.scene.frame_rate, audio.currentTime)) {
        audio.currentTime = target;
      }
      void audio.play().catch(() => {
        // Autoplay rejection (or a missing codec) must not break the preview:
        // the picture keeps playing, the author presses Play again.
      });
    } else {
      audio.pause();
      if (shouldSeekAudio(currentFrame, sceneScript.scene.frame_rate, audio.currentTime)) {
        audio.currentTime = target;
      }
    }
  }, [currentFrame, isPlaying, speechAudioUrl, audioEnabled, sceneScript.scene.frame_rate]);

  const [ghost, setGhost] = useState<{ ref: SceneObjectRef; position: SceneVec3 } | null>(null);
  const dragJustEndedRef = useRef(0);

  // One label per camera, built once per script rather than per camera per
  // frame: the viewport re-renders on every playhead move.
  const cameraLabels = useMemo(() => cameraLabelsById(sceneScript), [sceneScript]);

  const activeCameraId = useMemo(
    () => shotForFrame(sceneScript, currentFrame)?.camera ?? sceneScript.shots[0]?.camera ?? "",
    [currentFrame, sceneScript],
  );

  // Where the camera is at this frame: the script's own camera keyframes,
  // interpolated by the same pure function the depth pass uses. Null when the
  // script names no usable camera for this frame — an empty scene, or a dangling
  // shot→camera reference. Null is a real state the rig handles by leaving the
  // camera alone, rather than a pose invented here.
  const shotPose = useMemo(() => {
    const shot = shotForFrame(sceneScript, currentFrame);
    return shotCameraPoseAtFrame(sceneScript.cameras, shot, currentFrame);
  }, [sceneScript, currentFrame]);

  // Kinds this build has no geometry for. Normally empty; a non-empty list means
  // the script came from a backend newer than this bundle, and the magenta boxes
  // are the ones the reviewer should not trust.
  const unimplemented = useMemo(
    () => [
      ...new Set([
        ...unimplementedKinds(sceneScript.environment.map((env) => env.type)),
        ...unimplementedKinds(sceneScript.props.map((prop) => prop.type)),
      ]),
    ],
    [sceneScript.environment, sceneScript.props],
  );

  // Drag wiring: the ground layer owns the pointer; the ghost keeps the
  // dragged object under the cursor between frames; commit goes straight to
  // the caller's edit-model apply.
  const handleDragMove = useCallback(
    (ref: SceneObjectRef, position: SceneVec3) => {
      setGhost({ ref, position });
      onDragMove?.(ref, position);
    },
    [onDragMove],
  );
  const handleDragCommit = useCallback(
    (ref: SceneObjectRef, position: SceneVec3) => {
      setGhost(null);
      dragJustEndedRef.current = Date.now();
      onDragCommit?.(ref, position);
    },
    [onDragCommit],
  );

  const selectedPosition = useMemo(() => {
    if (!selectedObject) return null;
    if (ghost && ghost.ref.kind === selectedObject.kind && ghost.ref.id === selectedObject.id) {
      return ghost.position;
    }
    return sceneObjectPositionAtFrame(sceneScript, selectedObject, currentFrame);
  }, [selectedObject, ghost, sceneScript, currentFrame]);

  return (
    <div
      style={{ width: "100%", height, position: "relative", background: "#1a1a2e" }}
      data-testid="scene-script-3d-preview"
    >
      <Canvas
        shadows
        captureFrames={captureFrames}
        // Seed only — see `LeanCanvasProps.camera`. Following the playhead is
        // `ShotCameraRig`'s job, because a prop read once at mount cannot do it;
        // two attempts to do it through this prop are what left a 720-frame
        // render looking at nothing.
        camera={{ position: [8, -12, 6], fov: 50 }}
        style={{ width: "100%", height: "100%" }}
        onPointerMissed={() => {
          if (!editMode) return;
          // A committed drop ends over empty space: that is a drop, not a
          // deselect click. Guard with a short window.
          if (Date.now() - dragJustEndedRef.current < 150) return;
          onSelect?.(null);
        }}
      >
        <Color attach="background" args={["#1a1a2e"]} />
        <AmbientLight intensity={0.4} />
        <DirectionalLight position={[5, -5, 8]} intensity={1.0} castShadow shadow-mapSize={[1024, 1024]} />
        <DirectionalLight position={[-5, -3, 5]} intensity={0.3} />

        {/* Ground grid */}
        <Grid
          args={[20, 20]}
          cellSize={1}
          cellThickness={0.5}
          cellColor="#3a3a5e"
          sectionSize={5}
          sectionThickness={1}
          sectionColor="#5a5a8e"
          fadeDistance={30}
          fadeStrength={1}
          followCamera={false}
          infiniteGrid
        />

        <SceneDragLayer onDragMove={handleDragMove} onDragCommit={handleDragCommit}>
          {(drag) => {
            const handlersFor = (ref: SceneObjectRef, selected: boolean, overridePosition?: SceneVec3): EditHandlers => ({
              // Object grabbing stands down while placing a camera: placement
              // is a modal gesture owned by the placement layer.
              editMode: editMode && !placementMode,
              selected,
              overridePosition,
              onSelect: onSelect ?? (() => {}),
              onDragStart: drag.start,
              onDragMove: handleDragMove,
              onDragEnd: () => setGhost(null),
            });

            return (              <>
                {/* Environment objects */}
                {sceneScript.environment.map((object) => (
                  <PropMesh
                    key={object.id}
                    prop={object}
                    lodTier={objectLodTier(object)}
                    kind="environment"
                    frame={currentFrame}
                    handlers={handlersFor(
                      { kind: "environment", id: object.id },
                      selectedObject?.kind === "environment" && selectedObject.id === object.id,
                      ghost && ghost.ref.kind === "environment" && ghost.ref.id === object.id
                        ? ghost.position
                        : undefined,
                    )}
                  />
                ))}

                {/* Props */}
                {sceneScript.props.map((object) => (
                  <PropMesh
                    key={object.id}
                    prop={object}
                    lodTier={objectLodTier(object)}
                    kind="prop"
                    frame={currentFrame}
                    heldPosition={heldItemPositionAtFrame(sceneScript, object, currentFrame)}
                    handlers={handlersFor(
                      { kind: "prop", id: object.id },
                      selectedObject?.kind === "prop" && selectedObject.id === object.id,
                      ghost && ghost.ref.kind === "prop" && ghost.ref.id === object.id
                        ? ghost.position
                        : undefined,
                    )}
                  />
                ))}

                {/* Characters */}
                {sceneScript.characters.map((object) => (
                  <LowPolyHuman
                    key={object.id}
                    character={object}
                    frame={currentFrame}
                    dialogueLines={dialogueLines}
                    frameRate={sceneScript.scene.frame_rate}
                    handlers={handlersFor(
                      { kind: "character", id: object.id },
                      selectedObject?.kind === "character" && selectedObject.id === object.id,
                      ghost && ghost.ref.kind === "character" && ghost.ref.id === object.id
                        ? ghost.position
                        : undefined,
                    )}
                  />

                ))}

                {/* Cameras */}
                {showGizmos && sceneScript.cameras.map((object, index) => (
                  <CameraGizmo
                    key={object.id}
                    camera={object}
                    label={cameraLabels[object.id] ?? cameraLabel(object, index)}
                    active={object.id === activeCameraId}
                    frame={currentFrame}
                    handlers={handlersFor(
                      { kind: "camera", id: object.id },
                      selectedObject?.kind === "camera" && selectedObject.id === object.id,
                      undefined,
                    )}
                  />
                ))}

                {/* Trajectories: only meaningful once a move exists; they are
                    the difference between "the camera jumped" and "the camera
                    tracked". */}
                {sceneScript.cameras
                  .filter((object) => object.keyframes.length >= 2)
                  .map((object) => (
                    <TrajectoryLine
                      key={`traj-cam-${object.id}`}
                      points={object.keyframes.map((keyframe) => keyframe.position)}
                      color="#4FC3F7"
                    />
                  ))}
                {sceneScript.characters
                  .filter((object) => object.keyframes.length >= 2)
                  .map((object) => (
                    <TrajectoryLine
                      key={`traj-char-${object.id}`}
                      points={object.keyframes.map((keyframe) => keyframe.position)}
                      // The selected character's blocking is the one being
                      // authored: brighten it and drop floor marks on it.
                      color={
                        selectedObject?.kind === "character" && selectedObject.id === object.id
                          ? "#FFD166"
                          : "#B39DDB"
                      }
                      opacity={
                        selectedObject?.kind === "character" && selectedObject.id === object.id
                          ? 0.95
                          : 0.45
                      }
                    />
                  ))}
                {/* Floor marks + path length for the selected character: the
                    keyframes are the truth, and seeing them (with their frame
                    numbers) is what makes a motion preset reviewable without
                    scrubbing the playhead. */}
                {editMode
                  && selectedObject?.kind === "character"
                  && characterPathPoints(
                    sceneScript.characters.find((object) => object.id === selectedObject.id)
                      ?.keyframes ?? [],
                  ).length >= 2 && (
                  <BlockingMarks
                    points={characterPathPoints(
                      sceneScript.characters.find((object) => object.id === selectedObject.id)!
                        .keyframes,
                    )}
                    characterId={selectedObject.id}
                  />
                )}

                {/* Selection ring follows the selected object's current position. */}
                {editMode && selectedPosition && (
                  <SelectionRing position={sceneToThreePosition(selectedPosition)} />
                )}

                {placementMode && onPlacementCommit && (
                  <CameraPlacementLayer
                    onCommit={onPlacementCommit}
                    onCancel={onPlacementCancel}
                  />
                )}
                {gestureMode && onGestureCommit && (
                  <CameraGestureLayer onCommit={onGestureCommit} onCancel={onGestureCancel} />
                )}

                <OrbitControls
                  makeDefault
                  // Shot camera wins by default: with `makeDefault` an enabled
                  // OrbitControls owns the camera and would fight the
                  // interpolated shot pose on every rendered frame. In edit mode
                  // the author genuinely wants to fly around, and the shot pose
                  // resumes as soon as the playhead moves or the mode is left.
                  enabled={Boolean(editMode) && !drag.active}
                  enableDamping
                  dampingFactor={0.05}
                  minDistance={2}
                  maxDistance={30}
                  maxPolarAngle={Math.PI / 2 - 0.1}
                />

                {/* Caller-supplied scene content (test probes, future overlays). */}
                {children}
              </>
            );
          }}
        </SceneDragLayer>

        {/* DEPTH control pass: opt-in, and only ever a second render of the
            frame the author is already looking at. */}
        {/* The shot camera owns the render camera whenever the author is not
            flying it. It is mounted BEFORE `DepthPassRecorder` so its per-frame
            write lands before the recorder reads the same camera for the depth
            pass — colour and control frames then come from one viewpoint, which
is the entire point of a control pass. */}
        <ShotCameraRig pose={shotPose} enabled={!editMode} />

        {controlDepthPass && (
          <DepthPassRecorder
            sceneScript={sceneScript}
            onFrame={controlDepthPass.onFrame}
            enabled={controlDepthPass.enabled}
          />
        )}
      </Canvas>

      {/* HUD overlay */}
      <div
        style={{
          position: "absolute",
          top: 8,
          left: 8,
          background: "rgba(0,0,0,0.6)",
          color: "#fff",
          padding: "4px 10px",
          borderRadius: 4,
          fontSize: 12,
          fontFamily: "monospace",
        }}
      >
        Frame {currentFrame}/{totalFrames} | {sceneScript.scene.name}
        {editMode && placementMode && (
          <span style={{ color: "#FFD166", marginLeft: 8 }}>
            放置相机：第一次点击设机位 · 第二次点击设注视点 · Esc 取消
          </span>
        )}
        {editMode && !placementMode && (
          <span style={{ color: "#FFD166", marginLeft: 8 }}>
            编辑模式：点击选中 · 拖拽移动 · 点击空白取消
          </span>
        )}
        {unimplemented.length > 0 && (
          <span
            style={{ color: PLACEHOLDER_ASSET_COLOR, marginLeft: 8 }}
            title="This preview has no geometry for these kinds, so they render as magenta placeholder boxes"
          >
            ⚠ no preview geometry: {unimplemented.join(", ")}
          </span>
        )}
      </div>

      {/* Play controls */}
      <div
        style={{
          position: "absolute",
          bottom: 8,
          left: "50%",
          transform: "translateX(-50%)",
          background: "rgba(0,0,0,0.6)",
          padding: "4px 12px",
          borderRadius: 4,
          display: "flex",
          gap: 8,
          alignItems: "center",
        }}
      >
        <button
          type="button"
          onClick={toggle}
          aria-label={isPlaying ? "暂停场景预览" : "播放场景预览"}
          style={{
            background: "none",
            border: "1px solid #666",
            color: "#fff",
            padding: "2px 10px",
            borderRadius: 3,
            cursor: "pointer",
            fontSize: 12,
          }}
        >
          {isPlaying ? "⏸ Pause" : "▶ Play"}
        </button>
        <input
          type="range"
          aria-label="场景预览时间轴"
          aria-valuetext={`第 ${currentFrame + 1} 帧，共 ${totalFrames} 帧`}
          min={0}
          max={totalFrames - 1}
          value={currentFrame}
          onChange={(e) => {
            pause();
            seekToFrame(Number(e.target.value));
          }}
          style={{ width: 150 }}
        />
        {speechAudioUrl && (
          <button
            type="button"
            aria-label={audioEnabled ? "关闭台词音频" : "开启台词音频"}
            onClick={() => setAudioEnabled((current) => !current)}
            aria-pressed={audioEnabled}
            title={audioEnabled ? "关闭台词音频" : "开启台词音频（动画审片）"}
            data-testid="animatic-audio-toggle"
            style={{
              background: "none",
              border: "1px solid #666",
              color: audioEnabled ? "#FFD166" : "#888",
              padding: "2px 8px",
              borderRadius: 3,
              cursor: "pointer",
              fontSize: 12,
            }}
          >
            {audioEnabled ? "🔊" : "🔇"}
          </button>
        )}
      </div>
      {speechAudioUrl && <audio ref={audioRef} src={speechAudioUrl} preload="none" />}
    </div>
  );
}
