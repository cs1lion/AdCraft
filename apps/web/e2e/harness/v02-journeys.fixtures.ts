/**
 * Shared fixtures for the V0.2 E2E journeys (J1 asset-to-canvas,
 * J2 dialogue-to-proposal).
 *
 * Pure data builders only — no React, no DOM — so both the Playwright spec
 * (which composes the mocked HTTP responses from the same shapes the harness
 * pages seed) and the mock pages (which mount the real components on these
 * shapes) read ONE definition. A fixture that drifts between the two halves
 * would make the harness prove its own imagination instead of the product.
 *
 * Everything here mirrors the v2 contracts in src/types-v2.ts and the
 * SceneScript contract in src/types/scene-script.ts.
 */

import { AGENT_CANVAS_ROLE_CONTRACT_VERSION } from "../../src/features/agent-canvas/model/nodeDefaults.ts";
import type { SceneScriptRoot } from "../../src/types/scene-script.ts";
import type {
  AgentCanvasWorkflowV2,
  CanvasBindingV2,
  CanvasNodeV2,
  ProjectAssetSummaryV2,
} from "../../src/types-v2.ts";

export const TIMESTAMP = "2026-09-27T00:00:00Z";

export const J1_WORKFLOW_ID = "workflow-j1";
export const J2_WORKFLOW_ID = "workflow-j2";

/** The scene-3d previs node both journeys act on. */
export const SCENE_NODE_ID = "scene-previs-1";
/** The two shots of the seeded SceneScript (6 s at 30 fps). */
export const SHOT_1_ID = "shot1";
export const SHOT_2_ID = "shot2";

/** The scene-design board image that gets bound to the scene-3d card (J1). */
export const SCENE_BOARD_ASSET_ID = "asset-scene-board";
/** A still dropped on the canvas pane to create an asset-backed node (J1). */
export const SCENE_STILL_ASSET_ID = "asset-scene-still";

/** The dialogue line the spec types into the lip-sync panel (J2). */
export const DIALOGUE_LINE = "就是这里，信号源在墙后面。";
export const DIALOGUE_CHARACTER_ID = "char_a";

/**
 * The seeded SceneScript: one character, one camera, two shots — the minimum
 * that lets the lip-sync advisory name a boundary shot (shot1's cut) and the
 * transition picker form the shot1 → shot2 pair.
 */
export function sceneScript(): SceneScriptRoot {
  return {
    scene: {
      name: "地下研究所 B2",
      environment: "indoor",
      lighting: "cool",
      duration: 6,
      frame_rate: 30,
    },
    characters: [
      {
        id: DIALOGUE_CHARACTER_ID,
        type: "lowpoly_human",
        appearance: { color: "#E74C3C", height: 1.7, scale: 1 },
        keyframes: [
          { frame: 0, position: [0, 0, 0], rotation_y: 90, action: "stand" },
          { frame: 60, position: [2, 2, 0], rotation_y: 90, action: "walk" },
        ],
      },
    ],
    props: [],
    environment: [],
    cameras: [
      {
        id: "cam1",
        shot_type: "wide",
        keyframes: [{ frame: 0, position: [8, -10, 5], look_at: [0, 0, 1] }],
      },
    ],
    shots: [
      { id: SHOT_1_ID, camera: "cam1", start_frame: 0, end_frame: 89, description: "wide" },
      { id: SHOT_2_ID, camera: "cam1", start_frame: 90, end_frame: 179, description: "wide" },
    ],
    speech_bindings: [],
  };
}

/** A full project asset summary (the asset browser reads these). */
export function projectAsset(
  assetId: string,
  workflowId: string,
  semanticType: string | null,
  displayName: string,
  overrides: Partial<ProjectAssetSummaryV2> = {},
): ProjectAssetSummaryV2 {
  return {
    asset_id: assetId,
    version_id: `version-${assetId}`,
    project_id: "project-1",
    workflow_id: workflowId,
    media_type: "image",
    source_type: "generated",
    semantic_type: semanticType,
    display_name: displayName,
    mime_type: "image/png",
    status: "ready",
    size_bytes: 2048,
    storage_key: null,
    // No preview rendition: the drag gesture is what matters, and a null
    // preview keeps the harness off the media path entirely.
    preview_url: null,
    media_url: null,
    width: 1280,
    height: 720,
    duration_seconds: null,
    checksum: `${assetId}-checksum`,
    source_semantic_role: semanticType,
    source_node_id: null,
    source_execution_id: null,
    provider: null,
    model_id: null,
    prompt_provenance: {},
    actual_media_facts: {},
    generation_provenance: {},
    quality_metadata: {},
    created_at: TIMESTAMP,
    ...overrides,
  };
}

/** The scene-3d previs node both journeys act on. */
export function sceneNode(
  workflowId: string,
  overrides: Partial<CanvasNodeV2> = {},
): CanvasNodeV2 {
  return {
    node_id: SCENE_NODE_ID,
    workflow_id: workflowId,
    node_type: "scene-3d",
    creative_role: "scene_3d_previs",
    role_contract_version: AGENT_CANVAS_ROLE_CONTRACT_VERSION,
    title: "走廊对峙预演",
    status: "ready",
    execution_mode: "generative",
    summary_prompt: null,
    generation_prompt: "一条走廊，两个角色对峙",
    structured_content: { scene_script: sceneScript(), narration: "低沉的风声" },
    model_id: null,
    model_selection_mode: "default",
    model_ref: null,
    model_summary: null,
    parameters: {},
    metadata: {},
    parameter_provenance: {},
    prompt_context_snapshot_id: null,
    output_asset_id: null,
    output_asset_version_id: null,
    latest_attempt: null,
    position: { x: 0, y: 0 },
    revision: 1,
    error: null,
    authoring_origin: "user_free",
    intent_hint: null,
    prompt_presentation: null,
    prompt_preparation: null,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    ...overrides,
  };
}

/** The image node the J1 pane drop creates (the backend's echo of the request). */
export function assetBackedImageNode(workflowId: string): CanvasNodeV2 {
  return {
    node_id: "image-still-1",
    workflow_id: workflowId,
    node_type: "image",
    creative_role: "general_image",
    role_contract_version: AGENT_CANVAS_ROLE_CONTRACT_VERSION,
    title: "反应堆静帧",
    status: "ready",
    execution_mode: "source_only",
    summary_prompt: null,
    generation_prompt: null,
    structured_content: { source_asset_id: SCENE_STILL_ASSET_ID },
    model_id: null,
    model_selection_mode: "default",
    model_ref: null,
    model_summary: null,
    parameters: {},
    metadata: {},
    parameter_provenance: {},
    prompt_context_snapshot_id: null,
    output_asset_id: SCENE_STILL_ASSET_ID,
    output_asset_version_id: `version-${SCENE_STILL_ASSET_ID}`,
    latest_attempt: null,
    position: { x: 480, y: 240 },
    revision: 1,
    error: null,
    authoring_origin: "user_free",
    intent_hint: null,
    prompt_presentation: null,
    prompt_preparation: null,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
  };
}

/** The image_asset binding the J1 card drop creates (the backend's echo). */
export function sceneBoardBinding(workflowId: string): CanvasBindingV2 {
  return {
    binding_id: "binding-scene-board-1",
    workflow_id: workflowId,
    source: {
      kind: "image_asset",
      source_asset_id: SCENE_BOARD_ASSET_ID,
      source_asset_version_id: `version-${SCENE_BOARD_ASSET_ID}`,
    },
    target_node_id: SCENE_NODE_ID,
    input_role: "image_reference",
    enabled: true,
    order: 0,
    label: null,
    metadata: {},
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
  };
}

/** J1 workflow: the scene previs plus the two project assets. */
export function j1Workflow(overrides: Partial<AgentCanvasWorkflowV2> = {}): AgentCanvasWorkflowV2 {
  return {
    workflow_id: J1_WORKFLOW_ID,
    project_id: "project-1",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 1,
    layout_revision: 1,
    nodes: [sceneNode(J1_WORKFLOW_ID)],
    bindings: [],
    assets: [
      projectAsset(SCENE_BOARD_ASSET_ID, J1_WORKFLOW_ID, "scene_board", "走廊场景板"),
      projectAsset(SCENE_STILL_ASSET_ID, J1_WORKFLOW_ID, "reference", "反应堆静帧"),
    ],
    active_style_skill: null,
    ...overrides,
  };
}

/** J2 workflow: just the scene previs (the workbench is the whole stage). */
export function j2Workflow(overrides: Partial<AgentCanvasWorkflowV2> = {}): AgentCanvasWorkflowV2 {
  return {
    workflow_id: J2_WORKFLOW_ID,
    project_id: "project-1",
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: 1,
    layout_revision: 1,
    nodes: [sceneNode(J2_WORKFLOW_ID)],
    bindings: [],
    assets: [],
    active_style_skill: null,
    ...overrides,
  };
}
