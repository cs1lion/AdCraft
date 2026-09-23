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
  appearance: CharacterAppearance;
  keyframes: CharacterKeyframe[];
}

export interface SceneProp {
  id: string;
  type: string;
  position: [number, number, number];
  scale?: number;
  rotation_y?: number;
}

export interface SceneEnvironment {
  id: string;
  type: string;
  position: [number, number, number];
  scale?: number;
  rotation_y?: number;
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
