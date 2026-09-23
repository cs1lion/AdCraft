/**
 * SceneScript 3D Preview Component.
 *
 * Renders a low-fidelity 3D preview of a SceneScript using Three.js
 * (via @react-three/fiber). Shows characters, props, environment objects,
 * and camera positions with orbit controls.
 *
 * This is the frontend preview engine (ADR 0005 §3). The backend Blender
 * renderer produces production frames; this component gives instant feedback.
 */

import { Canvas } from "@react-three/fiber";
import { OrbitControls, Grid } from "@react-three/drei";
import { useRef, useMemo } from "react";
import * as THREE from "three";
import { useSceneScriptPlayback } from "./SceneScriptPlaybackContext";
import type {
  SceneScriptRoot,
  SceneCharacter,
  SceneProp,
  SceneCamera,
  CharacterKeyframe,
} from "../../../types/scene-script";
import { PLACEHOLDER_ASSET_COLOR } from "../../../types/scene-script.generated";
import {
  assetGeometryFor,
  unimplementedKinds,
} from "./sceneScriptGeometry";

// ---------------------------------------------------------------------------
// Low-poly Human
// ---------------------------------------------------------------------------

interface LowPolyHumanProps {
  character: SceneCharacter;
  frame: number;
}

function interpolateKeyframes(
  keyframes: CharacterKeyframe[],
  frame: number,
): { position: [number, number, number]; rotationY: number } {
  if (keyframes.length === 0) {
    return { position: [0, 0, 0], rotationY: 0 };
  }
  if (keyframes.length === 1 || frame <= keyframes[0].frame) {
    return {
      position: keyframes[0].position,
      rotationY: (keyframes[0].rotation_y * Math.PI) / 180,
    };
  }
  if (frame >= keyframes[keyframes.length - 1].frame) {
    const last = keyframes[keyframes.length - 1];
    return {
      position: last.position,
      rotationY: (last.rotation_y * Math.PI) / 180,
    };
  }
  for (let i = 0; i < keyframes.length - 1; i++) {
    const a = keyframes[i];
    const b = keyframes[i + 1];
    if (frame >= a.frame && frame <= b.frame) {
      const t = (frame - a.frame) / (b.frame - a.frame || 1);
      return {
        position: [
          a.position[0] + (b.position[0] - a.position[0]) * t,
          a.position[1] + (b.position[1] - a.position[1]) * t,
          a.position[2] + (b.position[2] - a.position[2]) * t,
        ],
        rotationY:
          ((a.rotation_y + (b.rotation_y - a.rotation_y) * t) * Math.PI) / 180,
      };
    }
  }
  return {
    position: keyframes[0].position,
    rotationY: (keyframes[0].rotation_y * Math.PI) / 180,
  };
}

function LowPolyHuman({ character, frame }: LowPolyHumanProps) {
  const groupRef = useRef<THREE.Group>(null);
  const color = character.appearance.color ?? "#8B4513";
  const height = character.appearance.height ?? 1.7;
  const scale = character.appearance.scale ?? 1.0;
  const bodyHeight = height * 0.55 * scale;
  const headRadius = height * 0.18 * scale;

  const { position, rotationY } = useMemo(
    () => interpolateKeyframes(character.keyframes, frame),
    [character.keyframes, frame],
  );

  return (
    <group ref={groupRef} position={position} rotation={[0, rotationY, 0]}>
      {/* Body */}
      <mesh position={[0, bodyHeight / 2, 0]} castShadow>
        <boxGeometry
          args={[height * 0.35 * scale, bodyHeight, height * 0.35 * scale]}
        />
        <meshStandardMaterial color={color} />
      </mesh>
      {/* Head */}
      <mesh position={[0, bodyHeight + headRadius * 0.8, 0]} castShadow>
        <sphereGeometry args={[headRadius, 8, 8]} />
        <meshStandardMaterial color="#E8D5C4" />
      </mesh>
      {/* ID label (small cone on top) */}
      <mesh position={[0, bodyHeight + headRadius * 2 + 0.1, 0]}>
        <coneGeometry args={[0.08, 0.15, 4]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.3} />
      </mesh>
    </group>
  );
}

// ---------------------------------------------------------------------------
// Prop / environment mesh
// ---------------------------------------------------------------------------

/**
 * Render one prop or environment object.
 *
 * Environment objects come through here too, which is why the geometry lookup
 * is a total map over both enums (see ``sceneScriptGeometry.tsx``). The old
 * version was a ``switch`` over prop kinds only, so 10 of the 13 environment
 * kinds fell through to the default box -- as did 11 of the 12 prop kinds.
 */
function PropMesh({ prop }: { prop: SceneProp }) {
  const scale = prop.scale ?? 1.0;
  const rotationY = ((prop.rotation_y ?? 0) * Math.PI) / 180;
  const pos = prop.position;

  const geometry = useMemo(() => {
    const build = assetGeometryFor(prop.type);
    if (build) {
      return build({ scale, rotationY, pos });
    }
    // No geometry for this kind. Deliberately not grey: the converter's own
    // placeholder colour is magenta because nothing real is that colour, and a
    // reviewer must be able to tell "missing" from "faithful" at a glance
    // (ADR 0005 §4: queryable degradation, never silent).
    return (
      <mesh
        position={[pos[0], pos[1] + 0.25 * scale, pos[2]]}
        rotation={[0, rotationY, 0]}
        castShadow
      >
        <boxGeometry args={[0.5 * scale, 0.5 * scale, 0.5 * scale]} />
        <meshStandardMaterial
          color={PLACEHOLDER_ASSET_COLOR}
          emissive={PLACEHOLDER_ASSET_COLOR}
          emissiveIntensity={0.6}
        />
      </mesh>
    );
  }, [prop.type, pos, rotationY, scale]);

  return <>{geometry}</>;
}

// ---------------------------------------------------------------------------
// Camera Gizmo
// ---------------------------------------------------------------------------

function CameraGizmo({ camera, active }: { camera: SceneCamera; active: boolean }) {
  const kf = camera.keyframes[0];
  if (!kf) return null;

  const direction = new THREE.Vector3(
    kf.look_at[0] - kf.position[0],
    kf.look_at[1] - kf.position[1],
    kf.look_at[2] - kf.position[2],
  ).normalize();

  return (
    <group position={kf.position}>
      {/* Camera body */}
      <mesh>
        <boxGeometry args={[0.3, 0.2, 0.4]} />
        <meshStandardMaterial
          color={active ? "#00FF00" : "#4444FF"}
          emissive={active ? "#00FF00" : "#4444FF"}
          emissiveIntensity={0.3}
        />
      </mesh>
      {/* Lens (cone pointing toward look_at) */}
      <mesh
        position={[direction.x * 0.3, direction.y * 0.3, direction.z * 0.3]}
        rotation={[0, Math.atan2(direction.x, direction.z), 0]}
      >
        <coneGeometry args={[0.12, 0.25, 8]} />
        <meshStandardMaterial color="#222222" />
      </mesh>
      {/* Frustum lines */}
      <lineSegments>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[
              new Float32Array([
                0, 0, 0, direction.x * 3, direction.y * 3 - 1, direction.z * 3,
                0, 0, 0, direction.x * 3, direction.y * 3 + 1, direction.z * 3,
              ]),
              3,
            ]}
          />
        </bufferGeometry>
        <lineBasicMaterial color={active ? "#00FF00" : "#4444FF"} opacity={0.4} transparent />
      </lineSegments>
    </group>
  );
}

// ---------------------------------------------------------------------------
// Animation controller
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Main Preview Component
// ---------------------------------------------------------------------------

export interface SceneScript3DPreviewProps {
  sceneScript: SceneScriptRoot;
  height?: number;
}

export function SceneScript3DPreview({
  sceneScript,
  height = 400,
}: SceneScript3DPreviewProps) {
  const { currentFrame, isPlaying, totalFrames, toggle, seekToFrame, pause } =
    useSceneScriptPlayback();

  const activeCameraId = useMemo(() => {
    for (const shot of sceneScript.shots) {
      if (currentFrame >= shot.start_frame && currentFrame <= shot.end_frame) {
        return shot.camera;
      }
    }
    return sceneScript.shots[0]?.camera ?? "";
  }, [currentFrame, sceneScript.shots]);

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

  return (
    <div style={{ width: "100%", height, position: "relative", background: "#1a1a2e" }}>
      <Canvas
        shadows
        camera={{ position: [8, -12, 6], fov: 50 }}
        style={{ width: "100%", height: "100%" }}
      >
        <color attach="background" args={["#1a1a2e"]} />
        <ambientLight intensity={0.4} />
        <directionalLight
          position={[5, -5, 8]}
          intensity={1.0}
          castShadow
          shadow-mapSize={[1024, 1024]}
        />
        <directionalLight position={[-5, -3, 5]} intensity={0.3} />

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

        {/* Environment objects */}
        {sceneScript.environment.map((env) => (
          <PropMesh key={env.id} prop={env} />
        ))}

        {/* Props */}
        {sceneScript.props.map((prop) => (
          <PropMesh key={prop.id} prop={prop} />
        ))}

        {/* Characters */}
        {sceneScript.characters.map((char) => (
          <LowPolyHuman key={char.id} character={char} frame={currentFrame} />
        ))}

        {/* Cameras */}
        {sceneScript.cameras.map((cam) => (
          <CameraGizmo key={cam.id} camera={cam} active={cam.id === activeCameraId} />
        ))}

        <OrbitControls
          makeDefault
          enableDamping
          dampingFactor={0.05}
          minDistance={2}
          maxDistance={30}
          maxPolarAngle={Math.PI / 2 - 0.1}
        />
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
          onClick={toggle}
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
          min={0}
          max={totalFrames - 1}
          value={currentFrame}
          onChange={(e) => {
            pause();
            seekToFrame(Number(e.target.value));
          }}
          style={{ width: 150 }}
        />
      </div>
    </div>
  );
}
