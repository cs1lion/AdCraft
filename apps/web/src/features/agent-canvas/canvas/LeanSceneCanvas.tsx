/**
 * LeanSceneCanvas — a React→three.js bridge for the SceneScript 3D preview.
 *
 * WHY THIS EXISTS (budget, not taste): `@react-three/fiber`'s dist bundles
 * react-reconciler, scheduler and a ~600 KiB event system; measured ~368 KiB
 * minified inside the 3D preview chunk (three-subset vs R3F delta). The preview
 * renders a finite, declaratively-authored scene graph, so a dedicated bridge
 * does the same job for a fraction of the bytes. See
 * `tests/browser/lean-scene-canvas.spec.ts` for the behavioural contract this
 * module must honour: parity with stock R3F Canvas, real WebGL, StrictMode
 * semantics, and pointer / orbit / drag independence.
 *
 * HOW IT WORKS
 * - `LeanSceneCanvas` owns a real WebGLRenderer, scene, camera, Raycaster and a
 *   requestAnimationFrame loop, and creates its OWN React root on a host div
 *   layered over the canvas. That secondary root is deliberately not
 *   StrictMode-wrapped (exactly like R3F's Canvas): nested StrictMode replays
 *   renders but not effects, so scene effects run once and never spin the GL
 *   context down in development.
 * - Every intrinsic (`<mesh>`, `<boxGeometry>`, `<meshStandardMaterial>`, …) is
 *   a real React component that builds its three.js object lazily in a ref,
 *   applies props in a layout effect on every commit, attaches itself to its
 *   React parent's Object3D/BufferGeometry, and disposes on unmount. There is
 *   no custom host reconciler: React's tree IS the scene tree.
 * - `useThree()` / `useFrame()` are context reads against that same state.
 * - `Grid`, `Html` and `OrbitControls` are local re-implementations of the drei
 *   components the preview uses, written against this module, so importing the
 *   preview never pulls R3F (or drei) back into the bundle.
 * - Every intrinsic is exported as a CAPITALIZED React component (`<Mesh>`,
 *   `<BoxGeometry>`, …). Lowercase tags compile to DOM host elements, which
 *   only R3F's custom reconciler can reinterpret; see the export block below.
 *
 * WHAT IS NOT REIMPLEMENTED: the full R3F/drei helper surface. Nothing beyond
 * the finite catalogue below is needed by the preview; if a future feature
 * needs more, prefer three.js directly over re-adding the dependency.
 */
import {
  cloneElement,
  createContext,
  Component,
  isValidElement,
  Suspense,
  useContext,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type Key,
  type ReactNode,
  type Ref,
} from "react";
import { createRoot, type Root } from "react-dom/client";
import * as THREE from "three";
import { FiberProvider, useContextBridge } from "its-fine";

// ---------------------------------------------------------------------------
// Canvas state (the `useThree()` shape the preview reads)
// ---------------------------------------------------------------------------

export interface LeanCanvasSize {
  width: number;
  height: number;
  /** Viewport-relative offset of the canvas container, like R3F's `size`. */
  top: number;
  left: number;
}

type FrameCallback = (state: LeanRootState, delta: number) => void;

export interface LeanRootState {
  camera: THREE.PerspectiveCamera;
  gl: THREE.WebGLRenderer;
  raycaster: THREE.Raycaster;
  scene: THREE.Scene;
  /** Object3D that root-level scene children attach to. */
  root: THREE.Object3D;
  size: LeanCanvasSize;
  domElement: HTMLCanvasElement;
  invalidate: () => void;
  /** @internal frame callback registry consumed by the render loop */
  frameCallbacks: Set<{ current: FrameCallback }>;
}

export interface LeanThreeEvent {
  /** The DOM element the pointer event was dispatched on (the canvas). */
  target: HTMLCanvasElement;
  object: THREE.Object3D | null;
  pointerId: number;
  buttons: number;
  movementX: number;
  movementY: number;
  clientX: number;
  clientY: number;
  stopped: boolean;
  stopPropagation: () => void;
}

const LeanThreeContext = createContext<LeanRootState | null>(null);

/** Read live canvas state; mirrors R3F's `useThree()` for what the preview uses. */
export function useThree(): LeanRootState {
  const state = useContext(LeanThreeContext);
  if (!state) {
    throw new Error("useThree must be called inside a <LeanSceneCanvas>");
  }
  return state;
}

/** Register a per-frame callback, invoked before each frame is rendered. */
export function useFrame(callback: FrameCallback): void {
  const state = useContext(LeanThreeContext);
  const holder = useRef(callback);
  holder.current = callback;
  useEffect(() => {
    if (!state) return;
    state.frameCallbacks.add(holder);
    return () => {
      state.frameCallbacks.delete(holder);
    };
  }, [state]);
}

// ---------------------------------------------------------------------------
// Attachment slots
//
// A "slot" is what a node attaches into: an Object3D for scene nodes, a
// BufferGeometry for buffer attributes. Children read it from context.
// ---------------------------------------------------------------------------

type SlotTarget = THREE.Object3D | THREE.BufferGeometry;

const SlotContext = createContext<SlotTarget | null>(null);

function useObjectSlot(): THREE.Object3D | null {
  const target = useContext(SlotContext);
  if (target && (target as THREE.Object3D).isObject3D) return target as THREE.Object3D;
  return null;
}

function useGeometrySlot(): THREE.BufferGeometry | null {
  const target = useContext(SlotContext);
  if (target && (target as THREE.BufferGeometry).isBufferGeometry) {
    return target as THREE.BufferGeometry;
  }
  return null;
}

function attachChild(target: SlotTarget, child: SlotTarget): void {
  if ((target as unknown as THREE.Object3D).isObject3D) {
    const parent = target as THREE.Object3D;
    if ((child as unknown as THREE.Object3D).isObject3D) {
      const node = child as THREE.Object3D;
      if (node.parent !== parent) parent.add(node);
    }
    return;
  }
  if ((child as unknown as THREE.BufferAttribute).isBufferAttribute) {
    (target as THREE.BufferGeometry).setAttribute(
      "position",
      child as unknown as THREE.BufferAttribute,
    );
  }
}

function disposeSubtree(object: THREE.Object3D): void {
  object.traverse((node) => {
    const mesh = node as THREE.Mesh;
    if (mesh.geometry) mesh.geometry.dispose();
    const material = mesh.material;
    if (Array.isArray(material)) {
      for (const item of material) item?.dispose();
    } else if (material) {
      material.dispose();
    }
  });
}

// ---------------------------------------------------------------------------
// Node factory shared by every scene-node intrinsic
// ---------------------------------------------------------------------------

type Props = Record<string, unknown>;

/**
 * Build the three object once per instance, apply props on every commit, keep
 * it attached to its slot parent, expose it through `ref`, and dispose on
 * unmount.
 */
function useThreeNode<T extends THREE.Object3D>(
  factory: () => T,
  apply: (object: T, props: Props) => void,
  props: Props,
): T {
  const objectRef = useRef<T | null>(null);
  if (objectRef.current === null) {
    objectRef.current = factory();
  }
  const object = objectRef.current as T;
  const slot = useContext(SlotContext);

  // React 19 passes `ref` as an ordinary prop on function components, so a
  // `<mesh ref={...}>` receives the live three object (R3F does the same).
  useImperativeHandle(props.ref as Ref<T> | undefined, () => object, [object]);

  // No dep array: re-applied on every commit. Effects flush child-first, so
  // the slot parent object already exists even when the parent attaches itself
  // in its own (later-running) layout effect.
  useLayoutEffect(() => {
    apply(object, props);
    if (slot) attachChild(slot, object);
  });

  // Fires exactly once: scene children live in the canvas' own (non-strict)
  // React root, so React's StrictMode replay never reaches them.
  useEffect(
    () => () => {
      if (slot) {
        const parent = slot as THREE.Object3D;
        if ((parent as THREE.Object3D).isObject3D) parent.remove(object);
      }
      disposeSubtree(object);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  return object;
}

function SlotProvider({ target, children }: { target: SlotTarget | null; children: ReactNode }) {
  return <SlotContext.Provider value={target}>{children}</SlotContext.Provider>;
}

// ---------------------------------------------------------------------------
// Transform / pointer-handler prop application
// ---------------------------------------------------------------------------

function applyCommonProps(object: THREE.Object3D, props: Props): void {
  const position = props.position as [number, number, number] | undefined;
  if (position) object.position.set(position[0], position[1], position[2]);
  const rotation = props.rotation as [number, number, number] | undefined;
  if (rotation) object.rotation.set(rotation[0], rotation[1], rotation[2]);
  const scale = props.scale as [number, number, number] | number | undefined;
  if (typeof scale === "number") object.scale.setScalar(scale);
  else if (scale) object.scale.set(scale[0], scale[1], scale[2]);
  if (typeof props.visible === "boolean") object.visible = props.visible;
  if (typeof props.castShadow === "boolean") object.castShadow = props.castShadow;
  if (typeof props.receiveShadow === "boolean") object.receiveShadow = props.receiveShadow;
  if (typeof props.renderOrder === "number") object.renderOrder = props.renderOrder;
  if (typeof props.frustumCulled === "boolean") object.frustumCulled = props.frustumCulled;
  applyEventHandlers(object, props);
}

/**
 * Handlers live on `userData` and are dispatched by the canvas' single
 * raycasting listener. R3F-style: a handler that disappears is removed so a
 * conditional handler stops firing without a remount.
 */
function applyEventHandlers(object: THREE.Object3D, props: Props): void {
  const handlers = (object.userData.leanHandlers ??= {});
  for (const name of ["onPointerDown", "onPointerMove", "onPointerUp", "onClick"]) {
    const value = props[name];
    if (value === undefined) delete handlers[name];
    else handlers[name] = value;
  }
}

// ---------------------------------------------------------------------------
// Intrinsic prop contracts (also the JSX types declared at the bottom)
// ---------------------------------------------------------------------------

interface SceneNodeProps {
  position?: readonly [number, number, number];
  rotation?: readonly [number, number, number];
  scale?: readonly [number, number, number] | number;
  visible?: boolean;
  castShadow?: boolean;
  receiveShadow?: boolean;
  renderOrder?: number;
  frustumCulled?: boolean;
  key?: Key;
  /** React 19 forwards this as a prop; the live three object lands in it. */
  ref?: Ref<THREE.Object3D>;
  onPointerDown?: (event: LeanThreeEvent) => void;
  onPointerMove?: (event: LeanThreeEvent) => void;
  onPointerUp?: (event: LeanThreeEvent) => void;
  onClick?: (event: LeanThreeEvent) => void;
  children?: ReactNode;
}
interface GroupProps extends SceneNodeProps {}
interface MeshProps extends SceneNodeProps {}
interface LineSegmentsProps extends SceneNodeProps {}
interface ThreeLineProps extends SceneNodeProps {}
interface AmbientLightProps extends Omit<SceneNodeProps, "onPointerMove"> {
  intensity?: number;
  color?: string | number;
}
interface DirectionalLightProps extends AmbientLightProps {
  "shadow-mapSize"?: [number, number];
}
interface GeometryProps {
  args?: readonly number[];
}
interface BufferAttributeProps {
  attach?: string;
  args?: readonly [ArrayBufferView, number];
}
interface ColorProps {
  attach?: string;
  args?: readonly (string | number)[];
}
interface StandardMaterialProps {
  color?: string | number;
  emissive?: string | number;
  emissiveIntensity?: number;
  transparent?: boolean;
  opacity?: number;
  depthWrite?: boolean;
  depthTest?: boolean;
  toneMapped?: boolean;
}
interface BasicMaterialProps {
  color?: string | number;
  transparent?: boolean;
  opacity?: number;
  depthWrite?: boolean;
  depthTest?: boolean;
  toneMapped?: boolean;
}
interface LineMaterialProps {
  color?: string | number;
  linewidth?: number;
  transparent?: boolean;
  opacity?: number;
  depthWrite?: boolean;
  depthTest?: boolean;
}

// ---------------------------------------------------------------------------
// Scene-node intrinsics
// ---------------------------------------------------------------------------

function GroupNode(props: GroupProps) {
  const node = useThreeNode(
    () => new THREE.Group(),
    (object, p) => applyCommonProps(object, p),
    props as unknown as Props,
  );
  return <SlotProvider target={node}>{props.children}</SlotProvider>;
}

function MeshNode(props: MeshProps) {
  const node = useThreeNode(
    () => new THREE.Mesh(),
    (mesh, p) => applyCommonProps(mesh, p),
    props as unknown as Props,
  );
  return <SlotProvider target={node}>{props.children}</SlotProvider>;
}

function LineSegmentsNode(props: LineSegmentsProps) {
  const node = useThreeNode(
    () => new THREE.LineSegments(),
    (object, p) => applyCommonProps(object, p),
    props as unknown as Props,
  );
  return <SlotProvider target={node}>{props.children}</SlotProvider>;
}

/**
 * three.js `Line`. Reached via `threeLine` because `<line>` is an SVG intrinsic
 * in React's DOM types and cannot be augmented (R3F does the same).
 */
function ThreeLineNode(props: ThreeLineProps) {
  const node = useThreeNode(
    () => new THREE.Line(),
    (object, p) => applyCommonProps(object, p),
    props as unknown as Props,
  );
  return <SlotProvider target={node}>{props.children}</SlotProvider>;
}

function AmbientLightNode(props: AmbientLightProps) {
  useThreeNode(
    () => new THREE.AmbientLight(),
    (light, p) => {
      applyCommonProps(light, p);
      if (p.intensity !== undefined) light.intensity = p.intensity as number;
      if (p.color !== undefined) light.color.set(p.color as string | number);
    },
    props as unknown as Props,
  );
  return null;
}

function DirectionalLightNode(props: DirectionalLightProps) {
  useThreeNode(
    () => new THREE.DirectionalLight(),
    (light, p) => {
      applyCommonProps(light, p);
      if (p.intensity !== undefined) light.intensity = p.intensity as number;
      if (p.color !== undefined) light.color.set(p.color as string | number);
      if (p.castShadow !== undefined) light.castShadow = p.castShadow as boolean;
      const mapSize = p["shadow-mapSize"] as [number, number] | undefined;
      if (mapSize) light.shadow.mapSize.set(mapSize[0], mapSize[1]);
    },
    props as unknown as Props,
  );
  return null;
}

// ---------------------------------------------------------------------------
// Geometry / material / attribute intrinsics
// ---------------------------------------------------------------------------

/**
 * Attach a geometry to the nearest Object3D slot, disposing whatever it
 * replaced. Keyed by a stable serialisation of `args` so the JSX's per-render
 * array literals do not rebuild the geometry every commit.
 */
function useGeometryAttachment(geometry: THREE.BufferGeometry, argsKey: string): void {
  const object = useObjectSlot();
  useLayoutEffect(() => {
    if (!object) return;
    const holder = object as THREE.Mesh;
    if (holder.geometry === geometry) return;
    holder.geometry?.dispose();
    holder.geometry = geometry;
  });
  useEffect(
    () => () => {
      if (object && (object as THREE.Mesh).geometry === geometry) {
        (object as THREE.Mesh).geometry.dispose();
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [argsKey],
  );
}

function defineGeometry<T extends THREE.BufferGeometry>(factory: (args: number[]) => T) {
  return function GeometryNode({ args }: GeometryProps) {
    // Stable identity for a given shape: `<boxGeometry args={[1,1,1]}/>` mints
    // a fresh array every render, but the geometry must survive it.
    const argsKey = args ? args.join(",") : "";
    const geometry = useMemo(
      () => factory(argsKey ? argsKey.split(",").map(Number) : []),
      [argsKey, factory],
    );
    useGeometryAttachment(geometry, argsKey);
    return <SlotProvider target={geometry}>{null}</SlotProvider>;
  };
}

const BoxGeometryNode = defineGeometry((args) => new THREE.BoxGeometry(...args));
const SphereGeometryNode = defineGeometry((args) => new THREE.SphereGeometry(...args));
const CylinderGeometryNode = defineGeometry((args) => new THREE.CylinderGeometry(...args));
const ConeGeometryNode = defineGeometry((args) => new THREE.ConeGeometry(...args));
const IcosahedronGeometryNode = defineGeometry((args) => new THREE.IcosahedronGeometry(...args));
const RingGeometryNode = defineGeometry((args) => new THREE.RingGeometry(...args));
const PlaneGeometryNode = defineGeometry((args) => new THREE.PlaneGeometry(...args));

function BufferGeometryNode({ children }: { children?: ReactNode }) {
  const geometry = useMemo(() => new THREE.BufferGeometry(), []);
  const object = useObjectSlot();
  useLayoutEffect(() => {
    if (!object) return;
    const holder = object as THREE.Mesh;
    if (holder.geometry === geometry) return;
    holder.geometry?.dispose();
    holder.geometry = geometry;
  });
  return <SlotProvider target={geometry}>{children}</SlotProvider>;
}

function BufferAttributeNode({ attach, args }: BufferAttributeProps) {
  const geometry = useGeometrySlot();
  useLayoutEffect(() => {
    if (!geometry || !args) return;
    const [array, itemSize] = args;
    // R3F maps `attach="attributes-position"` onto setAttribute("position").
    const name = (attach ?? "attributes-position").replace(/^attributes-/, "");
    geometry.setAttribute(name, new THREE.BufferAttribute(array as THREE.TypedArray, itemSize));
  });
  return null;
}

function ColorNode({ args }: ColorProps) {
  const state = useContext(LeanThreeContext);
  const colour = useMemo(() => new THREE.Color((args?.[0] as string | number) ?? 0x000000), [args]);
  useLayoutEffect(() => {
    if (!state || args?.[0] === undefined) return;
    state.scene.background = colour;
  });
  return null;
}

function defineMaterial<T extends THREE.Material>(
  factory: () => T,
  apply: (material: T, props: Props) => void,
) {
  return function MaterialNode(props: Props) {
    const material = useMemo(factory, []);
    const object = useObjectSlot();
    useLayoutEffect(() => {
      apply(material, props);
      if (!object) return;
      const holder = object as THREE.Mesh;
      if (holder.material === material) return;
      if (!Array.isArray(holder.material)) holder.material?.dispose();
      holder.material = material;
    });
    return null;
  };
}

const MeshStandardMaterialNode = defineMaterial(
  () => new THREE.MeshStandardMaterial(),
  (material, props) => {
    const p = props as StandardMaterialProps;
    if (p.color !== undefined) material.color.set(p.color);
    if (p.emissive !== undefined) material.emissive.set(p.emissive);
    if (p.emissiveIntensity !== undefined) material.emissiveIntensity = p.emissiveIntensity;
    if (p.transparent !== undefined) material.transparent = p.transparent;
    if (p.opacity !== undefined) material.opacity = p.opacity;
    if (p.depthWrite !== undefined) material.depthWrite = p.depthWrite;
    if (p.depthTest !== undefined) material.depthTest = p.depthTest;
    if (p.toneMapped !== undefined) material.toneMapped = p.toneMapped;
    material.needsUpdate = true;
  },
);

const MeshBasicMaterialNode = defineMaterial(
  () => new THREE.MeshBasicMaterial(),
  (material, props) => {
    const p = props as BasicMaterialProps;
    if (p.color !== undefined) material.color.set(p.color);
    if (p.transparent !== undefined) material.transparent = p.transparent;
    if (p.opacity !== undefined) material.opacity = p.opacity;
    if (p.depthWrite !== undefined) material.depthWrite = p.depthWrite;
    if (p.depthTest !== undefined) material.depthTest = p.depthTest;
    material.needsUpdate = true;
  },
);

const LineBasicMaterialNode = defineMaterial(
  () => new THREE.LineBasicMaterial(),
  (material, props) => {
    const p = props as LineMaterialProps;
    if (p.color !== undefined) material.color.set(p.color);
    if (p.linewidth !== undefined) material.linewidth = p.linewidth;
    if (p.transparent !== undefined) material.transparent = p.transparent;
    if (p.opacity !== undefined) material.opacity = p.opacity;
    if (p.depthWrite !== undefined) material.depthWrite = p.depthWrite;
    if (p.depthTest !== undefined) material.depthTest = p.depthTest;
    material.needsUpdate = true;
  },
);

// ---------------------------------------------------------------------------
// Grid — local replacement for drei's shader grid (same uniforms, same GLSL)
// ---------------------------------------------------------------------------

const GRID_VERTEX_SHADER = /* glsl */ `
  varying vec3 localPosition;
  varying vec4 worldPosition;

  uniform vec3 worldCamProjPosition;
  uniform vec3 worldPlanePosition;
  uniform float fadeDistance;
  uniform bool infiniteGrid;
  uniform bool followCamera;

  void main() {
    localPosition = position.xzy;
    if (infiniteGrid) localPosition *= 1.0 + fadeDistance;

    worldPosition = modelMatrix * vec4(localPosition, 1.0);
    if (followCamera) {
      worldPosition.xyz += (worldCamProjPosition - worldPlanePosition);
      localPosition = (inverse(modelMatrix) * worldPosition).xyz;
    }

    gl_Position = projectionMatrix * viewMatrix * worldPosition;
  }
`;

const GRID_FRAGMENT_SHADER = /* glsl */ `
  varying vec3 localPosition;
  varying vec4 worldPosition;

  uniform vec3 worldCamProjPosition;
  uniform float cellSize;
  uniform float sectionSize;
  uniform vec3 cellColor;
  uniform vec3 sectionColor;
  uniform float fadeDistance;
  uniform float fadeStrength;
  uniform float fadeFrom;
  uniform float cellThickness;
  uniform float sectionThickness;

  float getGrid(float size, float thickness) {
    vec2 r = localPosition.xz / size;
    vec2 grid = abs(fract(r - 0.5) - 0.5) / fwidth(r);
    float line = min(grid.x, grid.y) + 1.0 - thickness;
    return 1.0 - min(line, 1.0);
  }

  void main() {
    float g1 = getGrid(cellSize, cellThickness);
    float g2 = getGrid(sectionSize, sectionThickness);

    vec3 from = worldCamProjPosition * vec3(fadeFrom);
    float dist = distance(from, worldPosition.xyz);
    float d = 1.0 - min(dist / fadeDistance, 1.0);
    vec3 color = mix(cellColor, sectionColor, min(1.0, sectionThickness * g2));

    gl_FragColor = vec4(color, (g1 + g2) * pow(d, fadeStrength));
    gl_FragColor.a = mix(0.75 * gl_FragColor.a, gl_FragColor.a, g2);
    if (gl_FragColor.a <= 0.0) discard;
  }
`;

export interface GridProps {
  args?: [number, number];
  cellSize?: number;
  cellThickness?: number;
  cellColor?: string;
  sectionSize?: number;
  sectionThickness?: number;
  sectionColor?: string;
  fadeDistance?: number;
  fadeStrength?: number;
  fadeFrom?: number;
  infiniteGrid?: boolean;
  followCamera?: boolean;
  position?: [number, number, number];
  rotation?: [number, number, number];
}

export function Grid(props: GridProps) {
  const geometry = useMemo(
    () => new THREE.PlaneGeometry(props.args?.[0] ?? 20, props.args?.[1] ?? 20),
    [props.args],
  );
  // One material per Grid instance for its lifetime; the uniform values that
  // can change are synced from props below so the shader stays in step.
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: GRID_VERTEX_SHADER,
        fragmentShader: GRID_FRAGMENT_SHADER,
        transparent: true,
        side: THREE.BackSide,
        depthWrite: false,
        uniforms: {
          cellSize: { value: 0.5 },
          sectionSize: { value: 1 },
          cellColor: { value: new THREE.Color() },
          sectionColor: { value: new THREE.Color() },
          fadeDistance: { value: 100 },
          fadeStrength: { value: 1 },
          fadeFrom: { value: 1 },
          cellThickness: { value: 0.5 },
          sectionThickness: { value: 1 },
          infiniteGrid: { value: false },
          followCamera: { value: false },
          worldCamProjPosition: { value: new THREE.Vector3() },
          worldPlanePosition: { value: new THREE.Vector3() },
        },
      }),
    [],
  );
  useLayoutEffect(() => {
    const uniforms = material.uniforms;
    uniforms.cellSize.value = props.cellSize ?? 0.5;
    uniforms.sectionSize.value = props.sectionSize ?? 1;
    (uniforms.cellColor.value as THREE.Color).set(props.cellColor ?? "#000000");
    (uniforms.sectionColor.value as THREE.Color).set(props.sectionColor ?? "#2080ff");
    uniforms.fadeDistance.value = props.fadeDistance ?? 100;
    uniforms.fadeStrength.value = props.fadeStrength ?? 1;
    uniforms.fadeFrom.value = props.fadeFrom ?? 1;
    uniforms.cellThickness.value = props.cellThickness ?? 0.5;
    uniforms.sectionThickness.value = props.sectionThickness ?? 1;
    uniforms.infiniteGrid.value = props.infiniteGrid ?? false;
    uniforms.followCamera.value = props.followCamera ?? false;
  });

  const mesh = useThreeNode(
    () => new THREE.Mesh(geometry, material),
    (object, p) => {
      applyCommonProps(object, p);
      object.geometry = geometry;
      object.material = material;
    },
    props as unknown as Props,
  );

  useFrame((state) => {
    mesh.updateMatrixWorld();
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(
      new THREE.Vector3(0, 1, 0),
      new THREE.Vector3(0, 0, 0),
    );
    plane.applyMatrix4(mesh.matrixWorld);
    plane.projectPoint(state.camera.position, material.uniforms.worldCamProjPosition.value);
    material.uniforms.worldPlanePosition.value.set(0, 0, 0).applyMatrix4(mesh.matrixWorld);
  });

  return null;
}

// ---------------------------------------------------------------------------
// Html — local replacement for drei's Html
// ---------------------------------------------------------------------------

export interface HtmlProps {
  position?: [number, number, number];
  center?: boolean;
  distanceFactor?: number;
  children?: ReactNode;
}

/** DOM overlay projected from a scene point, rendered into the canvas host. */
export function Html({ position, center, children }: HtmlProps) {
  const node = useThreeNode(
    () => new THREE.Object3D(),
    (object, p) => applyCommonProps(object, p),
    { position } as Props,
  );
  const state = useContext(LeanThreeContext);
  const [element, setElement] = useState<HTMLDivElement | null>(null);

  const place = (dom: HTMLDivElement, eye: THREE.Camera) => {
    if (!state) return;
    const vector = new THREE.Vector3();
    node.getWorldPosition(vector);
    vector.project(eye);
    const rect = state.domElement.getBoundingClientRect();
    dom.style.transform =
      `translate3d(${(vector.x * 0.5 + 0.5) * rect.width}px, ${(-vector.y * 0.5 + 0.5) * rect.height}px, 0)`;
    if (center) {
      dom.style.marginLeft = `${-dom.offsetWidth / 2}px`;
      dom.style.marginTop = `${-dom.offsetHeight / 2}px`;
    }
  };

  // Project EVERY frame, not once: the camera moves (orbit drag, playback, a
  // gizmo being dragged) and the overlay has to stay glued to its object. A
  // one-shot projection reads fine on a static scene — which is exactly how the
  // first cut of this module passed its own browser spec — and then leaves the
  // label behind the moment the playhead moves. drei's Html registers with
  // useFrame for the same reason.
  useFrame((frameState) => {
    if (!element) return;
    place(element, frameState.camera);
  });

  useLayoutEffect(() => {
    if (!state || !element) return;
    // Place it before the first frame so it never flashes at the host origin.
    place(element, state.camera);
    const observer = new ResizeObserver(() => place(element, state.camera));
    observer.observe(element);
    return () => observer.disconnect();
  }, [state, element, node, center]);

  return (
    <div
      ref={setElement}
      style={{ position: "absolute", top: 0, left: 0, whiteSpace: "nowrap" }}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// OrbitControls — local replacement for drei's OrbitControls
// ---------------------------------------------------------------------------

export interface OrbitControlsProps {
  makeDefault?: boolean;
  enabled?: boolean;
  enableDamping?: boolean;
  dampingFactor?: number;
  minDistance?: number;
  maxDistance?: number;
  maxPolarAngle?: number;
  minPolarAngle?: number;
  target?: [number, number, number];
}

/**
 * Minimal orbit camera: drag to rotate, wheel to zoom, optional damping, with
 * the distance / polar-angle clamps the preview uses. Much smaller than
 * `three/examples/jsm`'s OrbitControls (which also ships no types in this
 * install). `makeDefault` is accepted for API parity and is a no-op because
 * this is the only control in the scene.
 */
export function OrbitControls({
  enabled = true,
  enableDamping = false,
  dampingFactor = 0.05,
  minDistance = 0,
  maxDistance = Infinity,
  maxPolarAngle = Math.PI / 2,
  minPolarAngle = 0,
  target,
}: OrbitControlsProps) {
  const state = useThree();
  // Held in a ref so the frame callback always reads current props without
  // re-subscribing on every render.
  const options = useRef({
    enabled,
    enableDamping,
    dampingFactor,
    minDistance,
    maxDistance,
    maxPolarAngle,
    minPolarAngle,
  });
  options.current = {
    enabled,
    enableDamping,
    dampingFactor,
    minDistance,
    maxDistance,
    maxPolarAngle,
    minPolarAngle,
  };

  useEffect(() => {
    const dom = state.gl.domElement;
    const camera = state.camera;
    const focus = new THREE.Vector3(...(target ?? [0, 0, 0]));
    const initial = camera.position.clone().sub(focus);
    let radius = initial.length();
    let theta = Math.atan2(initial.x, initial.z);
    let phi = Math.acos(THREE.MathUtils.clamp(initial.y / Math.max(radius, 1e-6), -1, 1));
    let velocityTheta = 0;
    let velocityPhi = 0;
    let activePointer: number | null = null;
    let lastX = 0;
    let lastY = 0;

    const onPointerDown = (event: PointerEvent) => {
      if (!options.current.enabled) return;
      activePointer = event.pointerId;
      lastX = event.clientX;
      lastY = event.clientY;
      velocityTheta = 0;
      velocityPhi = 0;
      dom.setPointerCapture(event.pointerId);
    };
    const onPointerMove = (event: PointerEvent) => {
      if (activePointer !== event.pointerId) return;
      velocityTheta = -(event.clientX - lastX) * 0.005;
      velocityPhi = -(event.clientY - lastY) * 0.005;
      lastX = event.clientX;
      lastY = event.clientY;
    };
    const endDrag = (event: PointerEvent) => {
      if (activePointer !== event.pointerId) return;
      activePointer = null;
      if (dom.hasPointerCapture(event.pointerId)) dom.releasePointerCapture(event.pointerId);
    };
    const onWheel = (event: WheelEvent) => {
      if (!options.current.enabled) return;
      event.preventDefault();
      radius = THREE.MathUtils.clamp(
        radius * (1 + event.deltaY * 0.001),
        Math.max(options.current.minDistance, 1e-3),
        options.current.maxDistance,
      );
    };

    dom.addEventListener("pointerdown", onPointerDown);
    dom.addEventListener("pointermove", onPointerMove);
    dom.addEventListener("pointerup", endDrag);
    dom.addEventListener("pointercancel", endDrag);
    dom.addEventListener("wheel", onWheel, { passive: false });

    const holder: { current: FrameCallback } = {
      current: (_loopState, _delta) => {
        if (!options.current.enabled) return;
        theta += velocityTheta;
        phi += velocityPhi;
        // Damping eases the camera to a stop after the drag ends.
        const decay = options.current.enableDamping ? 1 - options.current.dampingFactor : 0;
        velocityTheta *= decay;
        velocityPhi *= decay;
        phi = THREE.MathUtils.clamp(
          phi,
          options.current.minPolarAngle + 1e-3,
          options.current.maxPolarAngle - 1e-3,
        );
        const sinPhi = Math.sin(phi);
        camera.position.set(
          focus.x + radius * sinPhi * Math.sin(theta),
          focus.y + radius * Math.cos(phi),
          focus.z + radius * sinPhi * Math.cos(theta),
        );
        camera.lookAt(focus);
      },
    };
    state.frameCallbacks.add(holder);
    return () => {
      state.frameCallbacks.delete(holder);
      dom.removeEventListener("pointerdown", onPointerDown);
      dom.removeEventListener("pointermove", onPointerMove);
      dom.removeEventListener("pointerup", endDrag);
      dom.removeEventListener("pointercancel", endDrag);
      dom.removeEventListener("wheel", onWheel);
    };
  }, [state, target]);

  return null;
}

// ---------------------------------------------------------------------------
// The canvas
// ---------------------------------------------------------------------------

export interface LeanCanvasProps {
  children?: ReactNode;
  camera?: { position?: [number, number, number]; fov?: number };
  shadows?: boolean;
  style?: CSSProperties;
  onPointerMissed?: (event: MouseEvent) => void;
}

interface Session {
  raf: number;
  detach: () => void;
}

/**
 * Re-create the top-level child elements without changing anything about them.
 *
 * React skips re-rendering a component when the element object it receives is
 * referentially identical to the previous one, so re-pushing an unchanged
 * `children` into the scene root would silently replay no renders. Returning
 * fresh element objects (same props, same key) makes every scene render pass a
 * real pass, which is what StrictMode's render replay expects. This is the same
 * property stock R3F gets by re-rendering its own wrapper chain.
 */
function withFreshElements(children: ReactNode): ReactNode {
  if (Array.isArray(children)) {
    return children.map((child) => (isValidElement(child) ? cloneElement(child) : child));
  }
  return isValidElement(children) ? cloneElement(children) : children;
}

/**
 * Relays a failure raised inside the canvas' own React root to the MAIN tree,
 * so a user's error boundary / Suspense boundary wrapped OUTSIDE `<Canvas>`
 * still catches it. This is the part of R3F's Canvas that is easy to miss: the
 * scene children live in a second root, so without this relay a thrown error or
 * a suspending child would be swallowed inside that root and never reach the
 * boundary the author actually wrote. R3F does the same thing with its own
 * `ErrorBoundary` + `Block` pair.
 */
function SceneErrorBoundary({
  children,
  onError,
}: {
  children: ReactNode;
  onError: (error: unknown) => void;
}) {
  const report = useRef(onError);
  report.current = onError;
  return (
    <R3FStyleBoundary onReport={(error) => report.current(error)}>{children}</R3FStyleBoundary>
  );
}

type BoundaryProps = { children: ReactNode; onReport: (error: unknown) => void };

class R3FStyleBoundary extends Component<BoundaryProps, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }
  componentDidCatch(error: unknown): void {
    this.props.onReport(error);
  }
  render(): ReactNode {
    // Render nothing once failed: the failure is now the MAIN tree's problem,
    // and re-rendering children here could re-throw into this boundary.
    return this.state.failed ? null : this.props.children;
  }
}

function SceneBlock({ onBlock, onUnblock }: { onBlock: () => void; onUnblock: () => void }) {
  const handlers = useRef({ onBlock, onUnblock });
  handlers.current = { onBlock, onUnblock };
  useLayoutEffect(() => {
    // A promise that never settles: the main tree must stay suspended until the
    // pending scene component resolves on its own.
    handlers.current.onBlock();
    return () => handlers.current.onUnblock();
  }, []);
  return null;
}

const EMPTY_SIZE = { width: 0, height: 0, top: 0, left: 0 };

/**
 * Outer wrapper. `FiberProvider` publishes this component's fiber so the scene
 * canvas can re-create the React contexts an author wrapped AROUND `<Canvas>`
 * (theme, playback, anything) inside the canvas' own root — the one thing a
 * second root cannot do on its own. This is the same mechanism R3F uses.
 */
export function LeanSceneCanvas(props: LeanCanvasProps) {
  return (
    <FiberProvider>
      <SceneCanvas {...props} />
    </FiberProvider>
  );
}

function SceneCanvas({
  children,
  camera,
  shadows,
  style,
  onPointerMissed,
}: LeanCanvasProps) {
  // Re-creates every outer context provider inside the canvas' own root.
  const Bridge = useContextBridge();

  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef<LeanRootState | null>(null);
  const sceneRootRef = useRef<Root | null>(null);
  const sessionRef = useRef<Session | null>(null);
  // True once a teardown has been requested; the next mount clears it so the
  // deferred microtask below can tell a StrictMode replay from a real unmount.
  const disposedRef = useRef(true);
  const missedRef = useRef(onPointerMissed);
  missedRef.current = onPointerMissed;
  // Failures raised inside the scene root, relayed out to the main tree.
  const [relay, setRelay] = useState<{ error?: unknown; blocked?: boolean } | null>(null);

  // Stage 1: the renderer, camera, frame loop, pointer plumbing and the
  // scene's own React root. Mounted once per real mount.
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    const host = hostRef.current;
    if (!canvas || !container || !host) return;

    // Stage 1a: stop anything a previous (StrictMode-replayed) mount started.
    stopSession(sessionRef);

    // Stage 1b: the renderer/scene/camera survive StrictMode's mount→cleanup→
    // mount replay. Tearing down a live GL context to satisfy a dev-only
    // invariant would be both wasteful and visible as context churn.
    if (!stateRef.current) {
      const gl = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
      gl.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      gl.setClearColor(new THREE.Color("#1a1a2e"));
      if (shadows) {
        gl.shadowMap.enabled = true;
        gl.shadowMap.type = THREE.PCFSoftShadowMap;
      }
      const scene = new THREE.Scene();
      const perspective = new THREE.PerspectiveCamera(camera?.fov ?? 45, 1, 0.1, 1000);
      perspective.position.set(
        camera?.position?.[0] ?? 5,
        camera?.position?.[1] ?? 5,
        camera?.position?.[2] ?? 5,
      );
      perspective.lookAt(0, 0, 0);
      const root = new THREE.Group();
      root.name = "lean-scene-root";
      scene.add(root);
      stateRef.current = {
        camera: perspective,
        gl,
        raycaster: new THREE.Raycaster(),
        scene,
        root,
        size: { ...EMPTY_SIZE },
        domElement: canvas,
        invalidate: () => undefined,
        frameCallbacks: new Set(),
      };
    }
    const state = stateRef.current;

    // Stage 1c: size tracking. The container rect is re-read every frame so
    // `size.top/left` follow nested scrollers, like R3F's scroll-aware measure.
    let lastWidth = -1;
    let lastHeight = -1;
    const measure = () => {
      const rect = container.getBoundingClientRect();
      state.size.top = rect.top;
      state.size.left = rect.left;
      if (rect.width === lastWidth && rect.height === lastHeight) return;
      lastWidth = rect.width;
      lastHeight = rect.height;
      state.size.width = rect.width;
      state.size.height = rect.height;
      state.gl.setSize(Math.max(rect.width, 1), Math.max(rect.height, 1), false);
      state.camera.aspect = Math.max(rect.width, 1) / Math.max(rect.height, 1);
      state.camera.updateProjectionMatrix();
    };
    measure();

    // Stage 1d: pointer events. One raycast per DOM event, dispatched to the
    // nearest ancestor with a handler, with R3F's stopPropagation semantics.
    const dispatch = (event: PointerEvent | MouseEvent, name: HandlerName) => {
      const rect = canvas.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      const pointer = event as PointerEvent;
      const ndc = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      state.raycaster.setFromCamera(ndc, state.camera);
      const hits = state.raycaster.intersectObjects(state.root.children, true);
      const synthetic: LeanThreeEvent = {
        target: canvas,
        object: null,
        pointerId: pointer.pointerId ?? -1,
        buttons: event.buttons,
        movementX: pointer.movementX ?? 0,
        movementY: pointer.movementY ?? 0,
        clientX: event.clientX,
        clientY: event.clientY,
        stopped: false,
        stopPropagation: () => {
          synthetic.stopped = true;
        },
      };
      let handled = false;
      for (const hit of hits) {
        let object: THREE.Object3D | null = hit.object;
        while (object) {
          const handlers = object.userData.leanHandlers as Handlers | undefined;
          const handler = handlers?.[name];
          if (handler) {
            synthetic.object = object;
            handler(synthetic);
            handled = true;
          }
          if (synthetic.stopped) break;
          object = object.parent;
        }
        if (synthetic.stopped) break;
      }
      // R3F reports a miss only when nothing that had a handler was hit.
      if (!handled && name === "onClick") missedRef.current?.(event as MouseEvent);
    };

    const listeners: Array<[string, EventListener]> = [
      ["pointerdown", (event) => dispatch(event as PointerEvent, "onPointerDown")],
      ["pointermove", (event) => dispatch(event as PointerEvent, "onPointerMove")],
      ["pointerup", (event) => dispatch(event as PointerEvent, "onPointerUp")],
      ["click", (event) => dispatch(event as MouseEvent, "onClick")],
    ];
    for (const [name, listener] of listeners) canvas.addEventListener(name, listener);

    // Stage 1e: the frame loop — measure, run callbacks, render.
    let previous = performance.now();
    const loop = (now: number) => {
      const delta = (now - previous) / 1000;
      previous = now;
      measure();
      for (const holder of state.frameCallbacks) holder.current(state, delta);
      state.gl.render(state.scene, state.camera);
      sessionRef.current!.raf = requestAnimationFrame(loop);
    };
    const session: Session = {
      raf: requestAnimationFrame(loop),
      detach: () => {
        for (const [name, listener] of listeners) canvas.removeEventListener(name, listener);
      },
    };
    sessionRef.current = session;

    // Stage 1f: the scene's own React root. Not StrictMode-wrapped on purpose.
    if (!sceneRootRef.current) sceneRootRef.current = createRoot(host);

    disposedRef.current = false;
    return () => {
      disposedRef.current = true;
      queueMicrotask(() => {
        if (!disposedRef.current) return;
        // React DEACTIVATES (hides with `display: none`) rather than unmounts a
        // subtree whose Suspense boundary is showing its fallback, so the DOM
        // node is still connected. Tearing down there would destroy the GL
        // context and the scene root that the pending scene component needs
        // when it resolves — that is how the canvas survives a suspension.
        if (container.isConnected) return;
        const active = sessionRef.current;
        if (active) {
          cancelAnimationFrame(active.raf);
          active.detach();
          sessionRef.current = null;
        }
        sceneRootRef.current?.unmount();
        sceneRootRef.current = null;
        stateRef.current?.gl.dispose();
        stateRef.current = null;
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Stage 2: push the scene tree into the canvas' own root on every commit so
  // prop/state/frame changes reach the scene. The state object's identity never
  // changes, so scene components do not re-render on unrelated outer renders.
  //
  // The render is deferred to a microtask, exactly as R3F's Canvas does (its
  // `configure` is awaited): React coalesces back-to-back `root.render()` calls
  // made inside a single commit, which is precisely what StrictMode's effect
  // replay does — the scene tree would then mount once and never replay its
  // renders, even with fresh child elements. One microtask per pass keeps each
  // replay its own render pass.
  useLayoutEffect(() => {
    const state = stateRef.current;
    const root = sceneRootRef.current;
    if (!state || !root) return;
    queueMicrotask(() => {
      if (sceneRootRef.current !== root || stateRef.current !== state) return;
      root.render(
        <Bridge>
          <LeanThreeContext.Provider value={state}>
            <SlotContext.Provider value={state.root}>
              <SceneErrorBoundary onError={(error) => setRelay({ error })}>
                <Suspense
                  fallback={
                    <SceneBlock
                      onBlock={() => setRelay({ blocked: true })}
                      onUnblock={() => setRelay(null)}
                    />
                  }
                >
                  {withFreshElements(children)}
                </Suspense>
              </SceneErrorBoundary>
            </SlotContext.Provider>
          </LeanThreeContext.Provider>
        </Bridge>,
      );
    });
  });

  // Relay outward: a suspended or failed scene must surface through the
  // boundaries the author wrapped around <Canvas>, not vanish in this root.
  if (relay?.error !== undefined) throw relay.error;
  if (relay?.blocked) throw new Promise(() => undefined);

  return (
    <div
      ref={containerRef}
      style={{ position: "relative", width: "100%", height: "100%", overflow: "hidden", ...style }}
    >
      <canvas ref={canvasRef} style={{ display: "block", width: "100%", height: "100%" }} />
      {/* Host for the scene's own React root: Html overlays live here, layered
          over the canvas. pointer-events:none keeps them out of picking. */}
      <div ref={hostRef} style={{ position: "absolute", inset: 0, pointerEvents: "none" }} />
    </div>
  );
}

type HandlerName = "onPointerDown" | "onPointerMove" | "onPointerUp" | "onClick";
type Handlers = Partial<Record<HandlerName, (event: LeanThreeEvent) => void>>;

/** Stop a live frame loop + pointer listeners (StrictMode replay or dispose). */
function stopSession(sessionRef: { current: Session | null }): void {
  const session = sessionRef.current;
  if (!session) return;
  cancelAnimationFrame(session.raf);
  session.detach();
  sessionRef.current = null;
}

export default LeanSceneCanvas;

// ---------------------------------------------------------------------------
// The intrinsic catalogue, exported as real React components.

// ---------------------------------------------------------------------------
// The intrinsic catalogue, exported as real React components.
//
// These MUST be capitalized and imported by name: React's JSX compiler maps a
// lowercase tag like `<mesh>` to a DOM host element at runtime, and only a
// custom reconciler — exactly what R3F carries and this module avoids — can
// intercept it. A `declare module "react"` JSX augmentation changes nothing at
// runtime; it only satisfies the type checker, which is how this module's
// first cut silently rendered `<mesh>` as an unknown DOM node (proven by the
// real-WebGL browser spec: `triangles: 0`).
//
// Capitalized names also sidestep React's own DOM intrinsics: `Line` (not
// `line`, which is SVG) and `Color` (not `color`) are unambiguous here.
// ---------------------------------------------------------------------------

export const Mesh = MeshNode;
export const Group = GroupNode;
export const LineSegments = LineSegmentsNode;
export const Line = ThreeLineNode;
export const AmbientLight = AmbientLightNode;
export const DirectionalLight = DirectionalLightNode;
export const BoxGeometry = BoxGeometryNode;
export const SphereGeometry = SphereGeometryNode;
export const CylinderGeometry = CylinderGeometryNode;
export const ConeGeometry = ConeGeometryNode;
export const IcosahedronGeometry = IcosahedronGeometryNode;
export const RingGeometry = RingGeometryNode;
export const PlaneGeometry = PlaneGeometryNode;
export const BufferGeometry = BufferGeometryNode;
export const BufferAttribute = BufferAttributeNode;
export const Color = ColorNode;
export const MeshStandardMaterial = MeshStandardMaterialNode;
export const MeshBasicMaterial = MeshBasicMaterialNode;
export const LineBasicMaterial = LineBasicMaterialNode;
