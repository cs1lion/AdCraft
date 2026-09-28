/**
 * SceneScript type definitions for frontend 3D preview.
 * Mirrors apps/api/app/schemas/scene_script.py.
 * Keep in sync with backend schema.
 */

export interface SceneScriptScene {
  name: string;
  environment: "indoor" | "outdoor" | string;
  lighting: "warm" | "cool" | "soft" | "neutral" | string;
  duration: number;
  frame_rate: number;
}

export interface CharacterAppearance {
  color?: string;
  height?: number;
  scale?: number;
  /** Declared wardrobe palette (1-4 hex). Cross-node consistency for the
   *  same bound character asset is checked (V0.2 §5 服装). */
  palette?: string[] | null;
}

export interface CharacterKeyframe {
  frame: number;
  position: [number, number, number];
  rotation_y: number;
  action?: string;
}

export interface SceneCharacter {
  id: string;
  type: "lowpoly_human" | string;
  /** Bound character asset for identity consistency (mirrors SceneCharacter.character_asset_id). */
  character_asset_id?: string | null;
  appearance: CharacterAppearance;
  keyframes: CharacterKeyframe[];
}

export interface SceneProp {
  id: string;
  type: string;
  position: [number, number, number];
  scale?: number;
  rotation_y?: number;
  /** Character id carrying this prop: it follows the holder's hand every shot. */
  held_by?: string | null;
  /** Which hand carries it (defaults to the right when held). */
  held_side?: "left" | "right" | null;
  /** Bound prop asset (P0, 2026-09-15): the identity this prop is derived from. */
  prop_asset_id?: string | null;
  /** V3 ④ LOD 阶梯: the object's coarseness tier (``rough``/``standard``/``detailed``). Display-only: the preview collapses ``rough`` to a primitive; the gate and Blender converter keep the authored geometry. */
  lod_tier?: "rough" | "standard" | "detailed" | string | null;
}

export interface SceneEnvironment {
  id: string;
  type: string;
  position: [number, number, number];
  scale?: number;
  rotation_y?: number;
  /** Bound scene asset (P0, 2026-09-15): which design this environment is from. */
  scene_asset_id?: string | null;
  /** V3 ④ LOD 阶梯: the object's coarseness tier (display-only, mirrors SceneProp). */
  lod_tier?: "rough" | "standard" | "detailed" | string | null;
}

export interface CameraKeyframe {
  frame: number;
  position: [number, number, number];
  look_at: [number, number, number];
}

export interface SceneCamera {
  id: string;
  shot_type: "wide" | "medium" | "closeup" | "over_shoulder" | "pov" | "top_down" | string;
  keyframes: CameraKeyframe[];
}

export interface SceneShot {
  id: string;
  camera: string;
  start_frame: number;
  end_frame: number;
  description?: string;
  /** Reading id this shot enters with (V0.2 §13 第 5 问). */
  transition_intent?: string | null;
}

export interface SpeechBinding {
  character: string;
  speech_asset: string;
  mode: "bound" | "free";
}

export interface SceneScriptRoot {
  scene: SceneScriptScene;
  characters: SceneCharacter[];
  props: SceneProp[];
  environment: SceneEnvironment[];
  cameras: SceneCamera[];
  shots: SceneShot[];
  speech_bindings: SpeechBinding[];
}
