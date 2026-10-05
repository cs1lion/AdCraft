import { createContext, useContext, useEffect, useRef, useState, StrictMode, Component, Suspense, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { Canvas as DefaultCanvas, useFrame as defaultUseFrame, useThree as defaultUseThree, type RootState } from "@react-three/fiber";
import { Grid as DefaultGrid, Html as DefaultHtml, OrbitControls as DefaultOrbitControls } from "@react-three/drei";
import { Mesh as ThreeMesh, Vector3 } from "three";
import {
  AmbientLight as LeanAmbientLight,
  BoxGeometry as LeanBoxGeometry,
  BufferAttribute as LeanBufferAttribute,
  BufferGeometry as LeanBufferGeometry,
  Color as LeanColor,
  ConeGeometry as LeanConeGeometry,
  CylinderGeometry as LeanCylinderGeometry,
  DirectionalLight as LeanDirectionalLight,
  Grid as LeanGrid,
  Group as LeanGroup,
  Html as LeanHtml,
  LeanSceneCanvas,
  LineBasicMaterial as LeanLineBasicMaterial,
  LineSegments as LeanLineSegments,
  Mesh as LeanMesh,
  MeshBasicMaterial as LeanMeshBasicMaterial,
  MeshStandardMaterial as LeanMeshStandardMaterial,
  OrbitControls as LeanOrbitControls,
  RingGeometry as LeanRingGeometry,
  SphereGeometry as LeanSphereGeometry,
  useFrame as leanUseFrame,
  useThree as leanUseThree,
} from "../../src/features/agent-canvas/canvas/LeanSceneCanvas";
import { SceneScript3DPreview } from "../../src/features/agent-canvas/canvas/SceneScript3DPreview";
import { SceneScriptPlaybackProvider } from "../../src/features/agent-canvas/canvas/SceneScriptPlaybackContext";
import type { SceneScriptRoot } from "../../src/types/scene-script";
import { SCENE_SCRIPT_GEOMETRY } from "../../src/features/agent-canvas/canvas/sceneScriptGeometry";

// Both modes must drive the SAME scene tree through their own implementation:
// baseline through stock R3F + drei, lean through the module under test. The
// `Scene` body below binds nothing itself, so lean-scene-canvas.spec.ts can
// assert identical behaviour on both paths.
//
// In baseline mode the intrinsics are the lowercase string tags R3F registered
// with `extend(THREE)` — that is literally what `<mesh>` compiles to — so the
// capitalized binding below resolves to the same element type React would have
// produced from the lowercase JSX.
const baseline = new URLSearchParams(location.search).has("baseline");
const Canvas = baseline ? DefaultCanvas : LeanSceneCanvas;
const useThree = baseline ? defaultUseThree : leanUseThree;
const useFrame = baseline ? defaultUseFrame : leanUseFrame;
const Grid = baseline ? DefaultGrid : LeanGrid;
const Html = baseline ? DefaultHtml : LeanHtml;
const OrbitControls = baseline ? DefaultOrbitControls : LeanOrbitControls;
const Mesh = baseline ? "mesh" : LeanMesh;
const Group = baseline ? "group" : LeanGroup;
const BoxGeometry = baseline ? "boxGeometry" : LeanBoxGeometry;
const SphereGeometry = baseline ? "sphereGeometry" : LeanSphereGeometry;
const ConeGeometry = baseline ? "coneGeometry" : LeanConeGeometry;
const CylinderGeometry = baseline ? "cylinderGeometry" : LeanCylinderGeometry;
const RingGeometry = baseline ? "ringGeometry" : LeanRingGeometry;
const BufferGeometry = baseline ? "bufferGeometry" : LeanBufferGeometry;
const BufferAttribute = baseline ? "bufferAttribute" : LeanBufferAttribute;
const LineSegments = baseline ? "lineSegments" : LeanLineSegments;
const Color = baseline ? "color" : LeanColor;
const AmbientLight = baseline ? "ambientLight" : LeanAmbientLight;
const DirectionalLight = baseline ? "directionalLight" : LeanDirectionalLight;
const MeshStandardMaterial = baseline ? "meshStandardMaterial" : LeanMeshStandardMaterial;
const MeshBasicMaterial = baseline ? "meshBasicMaterial" : LeanMeshBasicMaterial;
const LineBasicMaterial = baseline ? "lineBasicMaterial" : LeanLineBasicMaterial;

const SceneContext = createContext("red");
let release: (() => void) | null = null;
let resolved = false;
let loading: Promise<void> | null = null;
let latest: RootState | null = null;
let ticks = 0;
const stats = { sceneRenders: 0, sceneSetups: 0, sceneCleanups: 0, selected: 0, missed: 0, drags: 0, color: "", width: 0, height: 0, left: 0, top: 0, meshes: 0, orbit: "" };
Object.assign(window, { leanScene: {
  stats,
  snapshot: () => ({ ...stats, ticks, triangles: latest?.gl.info.render.triangles ?? 0, lost: latest?.gl.getContext().isContextLost() ?? true }),
  resolve: () => { resolved = true; release?.(); },
  pixel: () => {
    if (!latest) return [];
    latest.gl.render(latest.scene, latest.camera);
    const gl = latest.gl.getContext();
    const pixels = new Uint8Array(4);
    gl.readPixels(Math.floor(gl.drawingBufferWidth / 2), Math.floor(gl.drawingBufferHeight / 2), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    return Array.from(pixels);
  },
  project: () => {
    if (!latest) return null;
    const point = new Vector3().project(latest.camera);
    const rect = latest.gl.domElement.getBoundingClientRect();
    return { x: rect.left + (point.x + 1) / 2 * rect.width, y: rect.top + (1 - point.y) / 2 * rect.height };
  },
} });

function ThrowScene(): never { throw new Error("lean scene deliberate error"); }
function PendingScene() {
  if (!resolved) {
    loading ??= new Promise<void>((resolve) => { release = resolve; });
    throw loading;
  }
  return <Mesh position={[0, 0, 0]}><SphereGeometry args={[0.5, 12, 12]} /><MeshBasicMaterial color="lime" /></Mesh>;
}
class Boundary extends Component<{ children: ReactNode }, { error: string }> {
  state = { error: "" };
  static getDerivedStateFromError(error: Error) { return { error: error.message }; }
  render() { return this.state.error ? <output data-testid="error">{this.state.error}</output> : this.props.children; }
}
function Scene() {
  ++stats.sceneRenders;
  const color = useContext(SceneContext);
  const state = useThree();
  const mesh = useRef<ThreeMesh>(null);
  const [dragging, setDragging] = useState(false);
  useEffect(() => { latest = state; }, [state]);
  useEffect(() => {
    ++stats.sceneSetups;
    return () => { ++stats.sceneCleanups; };
  }, []);
  useFrame(() => {
    ++ticks;
    stats.color = color;
    stats.width = state.size.width;
    stats.height = state.size.height;
    stats.left = state.size.left;
    stats.top = state.size.top;
    stats.orbit = state.camera.position.toArray().map((n) => n.toFixed(3)).join(",");
    let meshes = 0;
    state.scene.traverse((object) => { if (object instanceof ThreeMesh) ++meshes; });
    stats.meshes = meshes;
  });
  const down = (event: { stopPropagation: () => void; pointerId: number }) => {
    event.stopPropagation();
    ++stats.selected;
    setDragging(true);
    (event.target as unknown as Element).setPointerCapture(event.pointerId);
  };
  return <>
    <Color attach="background" args={["#101020"]} />
    <AmbientLight intensity={1} />
    <DirectionalLight position={[4, 6, 3]} intensity={2} castShadow />
    <Mesh ref={mesh} onPointerDown={down} onPointerMove={(event) => {
      if (!dragging || !mesh.current) return;
      event.stopPropagation();
      mesh.current.position.x += event.movementX * 0.01;
      ++stats.drags;
    }} onPointerUp={(event) => {
      event.stopPropagation(); setDragging(false);
      (event.target as unknown as Element).releasePointerCapture(event.pointerId);
    }} castShadow>
      <BoxGeometry args={[1.2, 1.2, 1.2]} /><MeshStandardMaterial color={color} />
    </Mesh>
    <Grid position={[0, -0.7, 0]} args={[20, 20]} infiniteGrid fadeDistance={20} />
    <Html position={[0, 1.8, 0]} center><span data-testid="context-label">{color}</span></Html>
    {Object.entries(SCENE_SCRIPT_GEOMETRY).map(([kind, geometry], index) => <Group key={kind} position={[-12 + index, 0, -8]}>{geometry({ scale: 0.5, rotationY: 0, pos: [0, 0, 0] })}</Group>)}
    <Mesh position={[3, 0, 0]}><RingGeometry args={[0.3, 0.5, 16]} /><MeshBasicMaterial color="gold" /></Mesh>
    <Mesh position={[-3, 0, 0]}><ConeGeometry args={[0.5, 1, 8]} /><MeshBasicMaterial color="gold" /></Mesh>
    <LineSegments><BufferGeometry><BufferAttribute attach="attributes-position" args={[new Float32Array([0, 0, -2, 0, 1, -2]), 3]} /></BufferGeometry><LineBasicMaterial color="white" /></LineSegments>
    <OrbitControls makeDefault enabled={!dragging} enableDamping />
  </>;
}
const productionScene: SceneScriptRoot = {
  scene: { name: "Lean production smoke", environment: "outdoor", lighting: "daylight", duration: 2, frame_rate: 30 },
  characters: [{ id: "actor", type: "lowpoly_human", appearance: { color: "#ff4422", height: 1.7, scale: 1 }, keyframes: [{ frame: 0, position: [0, 0, 0], rotation_y: 0, action: "talk" }, { frame: 59, position: [1, 0, 0], rotation_y: 0, action: "talk" }] }],
  props: Object.keys(SCENE_SCRIPT_GEOMETRY).filter((kind) => ["round_table", "rect_table", "chair", "stool", "lantern", "box", "crate", "vase", "weapon", "scroll", "book", "cup"].includes(kind)).map((type, index) => ({ id: `prop-${index}`, type, position: [index * 2 - 12, -5, 0], scale: 0.5 })),
  environment: Object.keys(SCENE_SCRIPT_GEOMETRY).filter((kind) => !["round_table", "rect_table", "chair", "stool", "lantern", "box", "crate", "vase", "weapon", "scroll", "book", "cup"].includes(kind)).map((type, index) => ({ id: `env-${index}`, type, position: [index * 3 - 18, 8, 0], scale: 0.4 })),
  cameras: [{ id: "camera", shot_type: "wide", display_name: "双人全景", keyframes: [{ frame: 0, position: [8, -12, 6], look_at: [0, 0, 1] }, { frame: 59, position: [7, -10, 5], look_at: [0, 0, 1] }] }],

  shots: [{ id: "shot", camera: "camera", start_frame: 0, end_frame: 59, description: "smoke" }],
} as SceneScriptRoot;
function ProductionFixture() {
  const [selection, setSelection] = useState<{ kind: "character" | "prop" | "environment" | "camera"; id: string } | null>({ kind: "character", id: "actor" });
  return <SceneScriptPlaybackProvider sceneScript={productionScene}>
    <output data-testid="production-selection">{selection?.id ?? "none"}</output>
    <SceneScript3DPreview sceneScript={productionScene} height={400} editMode selectedObject={selection} onSelect={setSelection} dialogueLines={[{ character_id: "actor", text: "real preview context", start_time: 0, end_time: 2 }]} />
  </SceneScriptPlaybackProvider>;
}
const camera = { position: [0, 3, 7] as [number, number, number], fov: 50 };
function Fixture() {
  const [color, setColor] = useState("red");
  const [wide, setWide] = useState(false);
  const [visible, setVisible] = useState(true);
  const [epoch, setEpoch] = useState(0);
  const [mode, setMode] = useState("scene");
  return <>
    <button onClick={() => setColor((old) => old === "red" ? "blue" : "red")}>context</button>
    <button onClick={() => setWide((old) => !old)}>resize</button>
    <button onClick={() => setEpoch((old) => old + 1)}>remount</button>
    <button onClick={() => setVisible((old) => !old)}>toggle</button>
    <button onClick={() => setMode("error")}>error</button>
    <button onClick={() => setMode("pending")}>suspend</button>
    <div data-testid="scroll" style={{ height: 450, overflow: "auto", marginTop: 10 }}>
      <div style={{ height: 900 }}>
        <div data-testid="viewport" style={{ width: wide ? 760 : 640, height: wide ? 400 : 360 }}>
          <Boundary key={epoch}><Suspense fallback={<output data-testid="loading">loading</output>}>
            <SceneContext.Provider value={color}>
              {visible && <Canvas key={epoch} shadows camera={camera} onPointerMissed={() => { ++stats.missed; }}>
                {mode === "error" ? <ThrowScene /> : mode === "pending" ? <PendingScene /> : <Scene />}
              </Canvas>}
            </SceneContext.Provider>
          </Suspense></Boundary>
        </div>
      </div>
    </div>
  </>;
}
createRoot(document.getElementById("root")!).render(<StrictMode>{new URLSearchParams(location.search).has("production") ? <ProductionFixture /> : <Fixture />}</StrictMode>);
