import type {
  AgentCanvasAssetMediaTypeV2,
  CanvasCreativeRoleV2,
  CanvasNodeCreateRequestV2,
  CanvasNodeTypeV2,
  CanvasPositionV2,
  CanvasRoleContractVersionV2,
} from "../../../types-v2.ts";

export const AGENT_CANVAS_ROLE_CONTRACT_VERSION: CanvasRoleContractVersionV2 = "ad-media-role-v2";

export type AgentCanvasVisibleNodeTypeV2 = CanvasNodeTypeV2;

export const AGENT_CANVAS_VISIBLE_NODE_TYPES: readonly AgentCanvasVisibleNodeTypeV2[] = [
  "text",
  "script",
  "image",
  "video",
  "audio",
  "editing",
  "scene-3d",
  "voice-cast",
  "replica",
];

export function isAgentCanvasVisibleNodeType(
  nodeType: CanvasNodeTypeV2,
): nodeType is AgentCanvasVisibleNodeTypeV2 {
  return AGENT_CANVAS_VISIBLE_NODE_TYPES.includes(nodeType);
}

export const AGENT_CANVAS_NODE_LABELS: Record<CanvasNodeTypeV2, string> = {
  text: "Text",
  script: "Script",
  image: "Image",
  video: "Video",
  audio: "Audio",
  editing: "Editing",
  "scene-3d": "3D Previs",
  "voice-cast": "Voice Cast",
  replica: "Replica",
};

const DEFAULT_CREATIVE_ROLES: Record<CanvasNodeTypeV2, CanvasCreativeRoleV2> = {
  text: "general_text",
  script: "script",
  image: "general_image",
  video: "general_video",
  audio: "bgm",
  editing: "editing",
  "scene-3d": "scene_3d_previs",
  "voice-cast": "voice_cast",
  replica: "replica_blueprint",
};

function bgmContent(summary: string, durationSeconds = 30): Record<string, unknown> {
  return {
    music_summary: summary,
    duration_seconds: Math.max(0.1, durationSeconds),
    pace: "Moderate",
    energy_curve: "Balanced progression supporting the advertisement",
    instrumentation: "Contemporary instrumental arrangement",
    mood: "Cinematic and brand appropriate",
    instrumental_only: true,
    no_vocals: true,
  };
}

export function createDefaultCanvasNodeRequest(
  nodeType: AgentCanvasVisibleNodeTypeV2,
  position: CanvasPositionV2,
): CanvasNodeCreateRequestV2 {
  return {
    node_type: nodeType,
    creative_role: DEFAULT_CREATIVE_ROLES[nodeType],
    role_contract_version: AGENT_CANVAS_ROLE_CONTRACT_VERSION,
    title: AGENT_CANVAS_NODE_LABELS[nodeType],
    summary_prompt: null,
    generation_prompt: null,
    model_selection_mode: "default",
    model_ref: null,
    ...(nodeType === "text"
      ? { structured_content: { content: "" } }
      : nodeType === "audio"
        ? { structured_content: bgmContent("Original background music for the advertisement") }
        : nodeType === "replica"
          ? { structured_content: emptyReplicaBlueprintContent() }
          : {}),
    position,
  };
}

/** 空白复刻蓝图骨架（与后端 ReplicaBlueprintContentV2 默认值一致）。 */
export function emptyReplicaBlueprintContent(): Record<string, unknown> {
  return {
    blueprint_version: "replica-blueprint-v1",
    source_video_asset_id: "",
    duration_seconds: 0,
    aspect: "",
    replica_goal: "",
    whole_piece_reading: "",
    format_name: "short-video",
    slots: [],
    beats: [],
    anchor_events: [],
    shots: [],
    rhythm_avg_shot_seconds: 0,
    rhythm_cut_points_seconds: [],
    rhythm_energy_curve: "",
    systems_captions: "",
    systems_music: "",
    systems_graphics: [],
    systems_sfx: [],
    constraints: [],
    instantiated_script_node_id: null,
  };
}

export function sourceAssetSemanticRole(
  mediaType: AgentCanvasAssetMediaTypeV2,
): CanvasCreativeRoleV2 {
  if (mediaType === "image") return "general_image";
  return mediaType === "video" ? "general_video" : "general_audio";
}

export function sourceAssetStructuredContent(
  mediaType: AgentCanvasAssetMediaTypeV2,
  displayName: string,
  durationSeconds: number | null,
): Record<string, unknown> {
  return mediaType === "audio"
    ? bgmContent(displayName, durationSeconds ?? 30)
    : {};
}

/**
 * The create request for a library asset dropped on the canvas (V0.2 §2.1:
 * 素材 → 拖到画布 → 创建镜头). The node type IS the asset's media type —
 * the backend's ``validate_asset_backed_node`` refuses anything else. Kept
 * here (not in the drop module) so the role/contract maps stay in one place.
 */
export function assetBackedCanvasNodeRequest(
  asset: {
    assetId: string;
    mediaType: AgentCanvasAssetMediaTypeV2;
    displayName: string;
    durationSeconds?: number | null;
  },
  position: CanvasPositionV2,
): CanvasNodeCreateRequestV2 {
  return {
    node_type: asset.mediaType,
    creative_role: sourceAssetSemanticRole(asset.mediaType),
    role_contract_version: AGENT_CANVAS_ROLE_CONTRACT_VERSION,
    title: asset.displayName,
    summary_prompt: null,
    generation_prompt: null,
    model_selection_mode: "default",
    model_ref: null,
    structured_content: sourceAssetStructuredContent(
      asset.mediaType,
      asset.displayName,
      asset.durationSeconds ?? null,
    ),
    position,
    source_asset_id: asset.assetId,
  };
}
