import type {
  AgentActionReceiptV2,
  AgentCanvasContinuationV2,
  AgentCanvasCreationModeV2,
  AgentCanvasProjectCreateResponseV2,
  AgentCanvasWorkflowV2,
  AgentCanvasChatTurnV2,
  AgentCanvasChatTimelineEntryV2,
  AgentCanvasChatTimelinePresentationItemV2,
  AgentCanvasChatTimelineResponseV2,
  AgentCanvasChatViewTimelineV2,
  AgentDocumentLinkedNodeRuntimeV2,
  AgentExecutionSettingsV2,
  AgentWorkingDocumentKindV2,
  AgentWorkingDocumentPageV2,
  AgentWorkingDocumentV2,
  AgentAnchorV2,
  AgentAnchorNodeSourceV3,
  AgentAnchorRoleSourceV3,
  AgentAnchorV3,
  AnchorAcceptanceEvidenceV1,
  AnchorRegistryContentV2,
  AnchorRegistryContentV3,
  AgentCommandOperationV2,
  AgentCommandPlanV2,
  ActiveStyleSkillSummaryV2,
  AgentCanvasImageLibraryListResponseV2,
  AgentCanvasVideoSkillRunV2,
  AgentCommandBindingKindV2,
  AgentNodeRefV2,
  AgentOperationResultV2,
  AgentOperationFailureV2,
  AgentPlacementHintV2,
  BindingCapabilityDecisionV2,
  CanvasBindingInputRoleV2,
  CanvasBindingMutationResponseV2,
  CanvasBindingSourceImageAssetV2,
  CanvasBindingSourceNodeV2,
  CanvasBindingSourceV2,
  CanvasBindingV2,
  CanvasConnectedNodeCreateResponseV2,
  CanvasConnectionPolicyV2,
  CanvasConnectionRoleRuleV2,
  CanvasCreativeRoleV2,
  CanvasExecutionStatusV2,
  CanvasPostReadyCheckpointStatusV2,
  CanvasPostReadyCheckpointV2,
  CanvasPostReadyEffectStatusV2,
  CanvasPostReadyEffectSummaryV2,
  CanvasPostReadyEffectTypeV2,
  CanvasMutationResponseV2,
  CanvasNodeScopeReportV2,
  CanvasScopeNeighbourV2,
  CanvasLayoutPatchResponseV2,
  CanvasNodeErrorV2,
  CanvasNodeLatestAttemptV2,
  ActionableFailureV1,
  CanvasNodeExecutionModeV2,
  NodePromptPreparationV1,
  PromptAssertionEvidenceV1,
  PromptAssertionSourceSnapshotV1,
  EditablePromptProjectionV1,
  RolePromptCompactionDecisionV2,
  ResolvedNodeParameterV2,
  CanvasModelSelectionModeV2,
  CanvasModelSummaryV2,
  CanvasNodeStatusV2,
  CanvasNodeTypeV2,
  CanvasNodeV2,
  CanvasParameterProvenanceV2,
  CanvasPositionV2,
  CanvasVariationDraftResponseV2,
  CanvasVariationDraftV2,
  CanvasVariationMaterializeResponseV2,
  CanvasRuntimeEventV2,
  CanvasRuntimeEventsResponseV2,
  CanvasRuntimeSnapshotV2,
  CanvasRunAcceptedV2,
  CanvasRunCancelResponseV2,
  ChatArtifactCardV2,
  ChatCapabilityActivityV2,
  ChatMessageV2,
  ChatProposalCardV2,
  ChatTimelineItemV2,
  ChatTimelineListResponseV2,
  ChatTimelinePresentationViewItemV2,
  ChatTurnAcceptedV2,
  CapabilityProposalOptionV2,
  ConceptProposalV2,
  CreationModeDecisionV2,
  CreativeElementDecisionV2,
  CreativeGoalV2,
  EditingExportRuntimeV2,
  EditingExportAcceptanceV2,
  EditingExportAcceptanceCheckV2,
  EditingExportAcceptedV2,
  EditingExportCancelResponseV2,
  CanvasEditingExportImportResponseV2,
  EditingBgmEntryV2,
  EditingManifestV2,
  EditingNodeContentV2,
  EditingOutputSettingsV2,
  EditingPreviewClipV2,
  EditingPreviewV2,
  EditingSkippedInputV2,
  EditingVideoEntryV2,
  DecisionBundleActionAcceptedV2,
  DecisionBundleAnswerV2,
  DecisionBundleQuestionV2,
  DecisionBundleV2,
  NodeRuntimePhaseV2,
  NodeRuntimeV2,
  ProposedDraftReferenceV2,
  ProposalApplicationSummaryV2,
  ProjectAssetSummaryV2,
  ProjectAssetListResponseV2,
  ProjectAssetStatusV2,
  ProjectAssetUploadResponseV2,
  ProviderModelCapabilityListV2,
  ProviderModelCapabilityV2,
  PresentationStreamEventV1,
  PresentationStreamEventTypeV1,
  PresentationStreamKindV1,
  PresentationStreamResetV1,
  ResolvedInputSnapshotV2,
  ResolvedMediaInputSnapshotV2,
  ResolvedTextInputSnapshotV2,
  GuidanceCompletionProjectionV2,
  GuidanceSessionActionV2,
  GuidanceTopicKindV2,
  GuidanceTopicStateV2,
  GuidedJourneyStageStatusV2,
  GuidedJourneyStageV2,
  GuidedProductionJourneyV2,
  GuidedSessionStateV2,
  GuidedInteractionV1,
  GuidedInteractionAcceptedV1,
  GuidedInteractionContentV1,
  GuidedInteractionActionV1,
  GuidedReferenceCandidateListResponseV2,
  GuidedReferenceCandidateV2,
  GuidanceAwaitingV1,
  GuidanceAdvancePreconditionV1,
  JourneyElementDecisionV2,
  JourneyActionProjectionV2,
  JourneyTransitionEvidenceV2,
  ProposalActionDescriptorV2,
  ProposalMaterializationErrorV2,
  ProposalMaterializationProjectionV2,
  AgentCapabilityIdV2,
  StorageAccessDescriptorV2,
  StoryboardNarrativeSegmentV2,
  StoryboardNodeRecordV2,
  StoryboardPlanGlobalParametersV2,
  StoryboardPlanRowV2,
  StoryboardProductionPlanContentV2,
  StoryboardProductionPlanContentV3,
  StoryboardPlannedNodeV3,
  StoryboardExcludedMediaV3,
  StoryboardVisualAnchorV3,
  StoryboardSegmentMaterializationV2,
  StoryboardSegmentMaterializationV3,
  StoryboardVisualAnchorV2,
  VideoParameterNormalizationV2,
  VideoSkillCatalogResponseV2,
  VideoSkillCategoryV2,
  VideoSkillPreviewV2,
  VideoSkillPublicDetailV2,
} from "../../../types-v2.ts";
import { V2ContractValidationError } from "../../../api/v2ContractValidationError.ts";

import { normalizeStrictRecord, type StrictRecordFieldsFor } from "./strictRecordFields.ts";

type JsonRecord = Record<string, unknown>;

const CANVAS_NODE_TYPES = new Set<CanvasNodeTypeV2>(["text", "script", "image", "video", "audio", "editing", "scene-3d", "voice-cast", "replica"]);
const COMMAND_NODE_TYPES = new Set<Exclude<CanvasNodeTypeV2, "editing">>(["text", "script", "image", "video", "audio"]);
const CANVAS_NODE_STATUSES = new Set<CanvasNodeStatusV2>(["draft", "working", "ready", "failed"]);
const CANVAS_NODE_EXECUTION_MODES = new Set<CanvasNodeExecutionModeV2>(["generative", "source_only"]);
const NODE_PROMPT_PREPARATION_STATUSES = new Set<NodePromptPreparationV1["status"]>([
  "queued",
  "working",
  "ready",
  "failed",
  "superseded",
  "not_applicable",
  "waiting_user",
]);
const PRESENTATION_STREAM_KINDS = new Set<PresentationStreamKindV1>(["assistant", "node_prompt"]);
const PRESENTATION_STREAM_EVENT_TYPES = new Set<PresentationStreamEventTypeV1>([
  "started",
  "delta",
  "committed",
  "failed",
  "superseded",
  "reset",
  "heartbeat",
]);
const CANVAS_MODEL_SELECTION_MODES = new Set<CanvasModelSelectionModeV2>(["default", "explicit"]);
const CANVAS_PARAMETER_ORIGINS = new Set<CanvasParameterProvenanceV2["origin"]>([
  "manual",
  "node_prompt",
  "binding",
  "user_explicit",
  "structured_content",
  "guidance_default",
  "role_default",
  "model_default",
  "provider_clamp",
]);
const CANVAS_MODEL_CAPABILITIES = new Set<CanvasModelSummaryV2["capability"]>(["text", "image", "video", "audio"]);
const CANVAS_MODEL_AVAILABILITIES = new Set<CanvasModelSummaryV2["availability"]>([
  "available",
  "unavailable",
  "unauthorized",
  "unsupported",
  "deprecated",
]);
const CANVAS_CREATIVE_ROLES = new Set<CanvasCreativeRoleV2>([
  "creative_brief",
  "world_setting",
  "script",
  "product",
  "prop",
  "character",
  "scene",
  "scene_3d_previs",
  // ADR 0017 分镜预演参考片段（video 节点承载导演台发布的镜头预演）。
  // 漏了它，发布返回的响应会被 normalizer 判 invalid，画布上片段节点不渲染
  // ——2026-10-03 实机发现（与下方 replica_blueprint 同一类坑）。
  "scene_3d_previs_clip",
  "storyboard_sequence",
  "storyboard_video",
  // 复刻蓝图节点（ReplicaTeardown 建蓝图时落这个角色）。漏了它，建蓝图返回的
  // mutation 响应会被 normalizer 判 invalid（"⚠ Invalid"toast），确认信息不
  // 出现，且库里已有的 replica 节点在画布上直接不渲染——2026-09-29 实机发现。
  "replica_blueprint",
  "voice_cast",
  "bgm",
  "general_text",
  "general_image",
  "general_video",
  "general_audio",
  "editing",
]);
const CANVAS_BINDING_ROLES = new Set<CanvasBindingInputRoleV2>([
  "text_context",
  "image_reference",
  "video_reference",
  "audio_reference",
]);
const SEMANTIC_REFERENCE_ROLES = new Set<
  NonNullable<ProposedDraftReferenceV2["semantic_reference_role"]>
>([
  "world_setting_reference",
  "subject_reference",
  "environment_reference",
  "product_reference",
  "prop_reference",
  "style_reference",
  "style_composition_reference",
  "storyboard_visual_reference",
]);
const AGENT_COMMAND_BINDING_KINDS = new Set<AgentCommandBindingKindV2>([
  "brief_context",
  "script_context",
  "image_reference",
  "video_reference",
  "audio_reference",
]);
const CANVAS_EXECUTION_STATUSES = new Set<CanvasExecutionStatusV2>([
  "queued",
  "running",
  "waiting",
  "completed",
  "partial_completed",
  "failed",
  "cancelled",
]);
const CANVAS_POST_READY_CHECKPOINT_STATUSES = new Set<CanvasPostReadyCheckpointStatusV2>([
  "pending",
  "completed",
  "failed",
]);
const CANVAS_POST_READY_EFFECT_TYPES = new Set<CanvasPostReadyEffectTypeV2>([
  "persist_script_document",
  "persist_text_document",
  "advance_storyboard_progression",
]);
const CANVAS_POST_READY_EFFECT_STATUSES = new Set<CanvasPostReadyEffectStatusV2>([
  "queued",
  "running",
  "completed",
  "failed",
]);
const NODE_RUNTIME_PHASES = new Set<NodeRuntimePhaseV2>([
  "waiting_for_input",
  "blocked_by_upstream",
  "queued",
  "running",
  "waiting_provider",
  "recovering",
  "publishing",
]);
const ASSET_MEDIA_TYPES = new Set<ProjectAssetSummaryV2["media_type"]>(["image", "video", "audio"]);
const PROVIDER_OUTPUT_TYPES = new Set<ProviderModelCapabilityV2["output_type"]>([
  "image",
  "video",
  "audio",
]);
const ASSET_SOURCE_TYPES = new Set<ProjectAssetSummaryV2["source_type"]>([
  "upload",
  "generated",
  "recommended",
  "library",
  "editing_export",
  "derived",
]);
const PROJECT_ASSET_STATUSES = new Set<ProjectAssetStatusV2>(["ready", "unavailable"]);
const AGENT_CAPABILITY_IDS = new Set<AgentCapabilityIdV2>([
  "world_setting",
  "product_design",
  "prop_design",
  "character_design",
  "scene_design",
  "script_authoring",
  "storyboard_design",
  "video_direction",
  "bgm_direction",
  "quick_media",
]);
const CHAT_MESSAGE_SPEAKERS = new Set<ChatMessageV2["speaker"]>(["user", "adcraft_video_agent"]);
const PROPOSAL_AVAILABILITIES = new Set<ConceptProposalV2["availability"]>(["open", "applied", "superseded"]);
const PROPOSAL_ACTIONS = new Set<ProposalActionDescriptorV2["action"]>([
  "select_option",
  "custom_direction",
  "revise_options",
  "defer_topic",
  "exclude_element",
  "delegate_choice",
  "reuse_direction",
  "revise_direction",
]);
const GUIDANCE_TOPIC_KINDS = new Set<GuidanceTopicKindV2>([
  "world_setting",
  "creative_direction",
  "product",
  "prop",
  "character",
  "scene",
  "script",
  "storyboard",
  "video",
  "audio",
]);
const GUIDED_JOURNEY_STAGES = new Set<GuidedJourneyStageV2>([
  "intake",
  "world_view",
  "product",
  "props",
  "character",
  "scene",
  "narrative_direction",
  "style_lock",
  "storyboard_plan",
  "storyboard_grids",
  "videos",
  "bgm",
  "editing",
  "completed",
]);
const GUIDED_JOURNEY_STAGE_STATUSES = new Set<GuidedJourneyStageStatusV2>([
  "ready",
  "working",
  "waiting_user",
  "blocked_external",
  "failed",
  "completed",
]);
const JOURNEY_DECISION_OUTCOMES = new Set<JourneyElementDecisionV2["outcome"]>([
  "include",
  "exclude",
  "delegate",
  "unresolved",
]);
const JOURNEY_DECISION_SOURCES = new Set<JourneyElementDecisionV2["source"]>([
  "user",
  "delegated",
  "system",
]);
const JOURNEY_ACTION_STATUSES = new Set<JourneyActionProjectionV2["status"]>([
  "reserved",
  "working",
  "waiting_user",
]);
const JOURNEY_EVIDENCE_KINDS = new Set<JourneyTransitionEvidenceV2["evidence_kind"]>([
  "creative_goal_validated",
  "clarification_completed",
  "world_view_selected",
  "world_view_delegated",
  "world_view_excluded",
  "product_materialized",
  "product_delegated",
  "product_excluded",
  "props_materialized",
  "props_delegated",
  "props_excluded",
  "character_materialized",
  "character_delegated",
  "character_excluded",
  "scene_materialized",
  "scene_delegated",
  "scene_excluded",
  "narrative_direction_accepted",
  "style_lock_accepted",
  "storyboard_plan_accepted",
  "storyboard_plan_excluded",
  "storyboard_grids_prepared",
  "storyboard_grids_excluded",
  "videos_prepared",
  "videos_excluded",
  "bgm_prepared",
  "bgm_delegated",
  "bgm_excluded",
  "editing_prepared",
  "editing_export_completed",
  "editing_excluded",
  "targeted_action_started",
  "targeted_action_finished",
  "stage_failed",
]);
const CREATIVE_ELEMENT_KIND_VALUES = {
  world_setting: true,
  product: true,
  character: true,
  prop: true,
  scene: true,
  script: true,
  storyboard: true,
  video: true,
  audio: true,
} as const satisfies Record<CreativeElementDecisionV2["element_kind"], true>;
const CREATIVE_ELEMENT_KINDS = new Set<CreativeElementDecisionV2["element_kind"]>(
  Object.keys(CREATIVE_ELEMENT_KIND_VALUES) as CreativeElementDecisionV2["element_kind"][],
);
const CAPABILITY_ACTIVITY_STATUSES = new Set<ChatCapabilityActivityV2["status"]>([
  "working",
  "completed",
  "failed",
  "superseded",
]);
const EDITING_EXPORT_STATUSES = new Set<EditingExportRuntimeV2["status"]>(["queued", "exporting", "completed", "failed", "cancelled"]);
const EDITING_SKIPPED_REASONS = new Set<EditingSkippedInputV2["reason"]>([
  "source_not_ready",
  "source_failed",
  "source_output_unavailable",
  "source_media_invalid",
]);
const EDITING_VIDEO_CODEC = new Set<EditingOutputSettingsV2["video_codec"]>(["h264"]);
const EDITING_AUDIO_CODEC = new Set<EditingOutputSettingsV2["audio_codec"]>(["aac"]);
const EDITING_CONTAINER = new Set<EditingOutputSettingsV2["container"]>(["mp4"]);
const EDITING_TRANSITIONS = new Set<EditingVideoEntryV2["transition"]>(["cut", "fade"]);
const EDITING_FIT_MODES = new Set<EditingVideoEntryV2["fit_mode"]>(["fit", "fill"]);
const RESOLVED_TEXT_BINDING_KINDS = new Set<ResolvedTextInputSnapshotV2["binding_kind"]>(["text_context"]);
const RESOLVED_DOCUMENT_KINDS = new Set<ResolvedTextInputSnapshotV2["document_kind"]>(["text", "script"]);
const RESOLVED_MEDIA_BINDING_KINDS = new Set<ResolvedMediaInputSnapshotV2["binding_kind"]>([
  "image_reference",
  "video_reference",
  "audio_reference",
]);
const PROVIDER_INPUT_TYPES = new Set<ProviderModelCapabilityV2["accepted_input_types"][number]>(["text", "image", "video", "audio"]);
const PLACEMENT_INTENTS = new Set<AgentPlacementHintV2["intent"]>([
  "append_flow",
  "after_anchor",
  "right_sibling",
  "near_selection",
]);
const COMMAND_PLAN_STATUSES = new Set<AgentCommandPlanV2["status"]>([
  "pending_confirmation",
  "applying",
  "applied",
  "rejected",
  "superseded",
  "failed",
]);
const COMMAND_RISKS = new Set<AgentCommandPlanV2["risk"]>([
  "reversible_authoring",
  "destructive_authoring",
  "external_effect",
]);
const RECEIPT_STATUSES = new Set<AgentActionReceiptV2["status"]>([
  "applied",
  "applied_with_run_error",
  "not_applied",
  "rejected",
  "superseded",
  "failed",
]);
const CREATION_MODES = new Set<AgentCanvasCreationModeV2>([
  "ordinary_conversation",
  "targeted_authoring",
  "quick_media",
  "guided_production",
]);
const AGENT_MEDIA_EXECUTION_MODES = new Set<AgentExecutionSettingsV2["media_execution_mode"]>([
  "manual",
  "automatic",
]);
const AGENT_WORKING_DOCUMENT_KINDS = new Set<AgentWorkingDocumentKindV2>([
  "anchor_registry",
  "storyboard_production_plan",
]);
const STORYBOARD_SEGMENT_MATERIALIZATION_STATUSES = new Set<StoryboardSegmentMaterializationV2["status"]>([
  "pending",
  "materialized",
]);

function fail(path: string, message: string): never {
  throw new V2ContractValidationError(path, message);
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function expectRecord(value: unknown, path: string): JsonRecord {
  if (!isRecord(value)) fail(path, "expected object");
  return value;
}

function forbidUnknownFields(record: JsonRecord, allowed: readonly string[], path: string) {
  const allowedSet = new Set(allowed);
  for (const key of Object.keys(record)) {
    if (!allowedSet.has(key)) fail(`${path}.${key}`, "unknown field");
  }
}

function expectString(value: unknown, path: string) {
  if (typeof value !== "string") fail(path, "expected string");
  return value;
}

function expectNonEmptyString(value: unknown, path: string) {
  const result = expectString(value, path);
  if (!result.trim()) fail(path, "expected non-empty string");
  return result;
}

function optionalString(value: unknown, path: string) {
  if (value === undefined) return undefined;
  return expectString(value, path);
}

function nullableString(value: unknown, path: string) {
  if (value === null) return null;
  return expectString(value, path);
}

function expectBoolean(value: unknown, path: string) {
  if (typeof value !== "boolean") fail(path, "expected boolean");
  return value;
}

function optionalBoolean(value: unknown, path: string) {
  if (value === undefined) return undefined;
  return expectBoolean(value, path);
}

function nullableBoolean(value: unknown, path: string) {
  if (value === null) return null;
  return expectBoolean(value, path);
}

function expectFiniteNumber(value: unknown, path: string) {
  if (typeof value !== "number" || !Number.isFinite(value)) fail(path, "expected finite number");
  return value;
}

function expectInteger(value: unknown, path: string) {
  const result = expectFiniteNumber(value, path);
  if (!Number.isInteger(result)) fail(path, "expected integer");
  return result;
}

function expectNonNegativeInteger(value: unknown, path: string) {
  const result = expectInteger(value, path);
  if (result < 0) fail(path, "expected non-negative integer");
  return result;
}

function expectPositiveInteger(value: unknown, path: string) {
  const result = expectInteger(value, path);
  if (result <= 0) fail(path, "expected positive integer");
  return result;
}

function nullableFiniteNumber(value: unknown, path: string) {
  if (value === null) return null;
  return expectFiniteNumber(value, path);
}

function nullablePositiveInteger(value: unknown, path: string) {
  if (value === null) return null;
  return expectPositiveInteger(value, path);
}

function nullableNonNegativeNumber(value: unknown, path: string) {
  if (value === null) return null;
  const result = expectFiniteNumber(value, path);
  if (result < 0) fail(path, "expected non-negative number");
  return result;
}

function nullableBrowserSafeUrl(value: unknown, path: string) {
  if (value === null) return null;
  const result = expectNonEmptyString(value, path);
  if (!result.startsWith("/api/") && !result.startsWith("https://") && !result.startsWith("http://")) {
    fail(path, "expected browser-safe URL");
  }
  return result;
}

function nullablePublicPreviewUrl(value: unknown, path: string) {
  if (value === null) return null;
  const result = expectNonEmptyString(value, path);
  const isSameOriginPath = result.startsWith("/") && !result.startsWith("//");
  if (!isSameOriginPath && !result.startsWith("https://") && !result.startsWith("http://")) {
    fail(path, "expected browser-safe URL");
  }
  return result;
}

function optionalNullableString(value: unknown, path: string) {
  if (value === undefined) return undefined;
  return nullableString(value, path);
}

function nullableStringWithDefault(value: unknown, path: string) {
  return value === undefined ? null : nullableString(value, path);
}

function normalizeNullableBoundedString(
  value: unknown,
  path: string,
  minLength: number,
  maxLength: number,
): string | null {
  if (value === undefined || value === null) return null;
  const result = expectString(value, path);
  if (result.length < minLength || result.length > maxLength) {
    fail(path, `expected string with ${minLength}-${maxLength} characters`);
  }
  return result;
}

function expectStringArray(value: unknown, path: string) {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value.map((item, index) => expectString(item, `${path}[${index}]`));
}

function optionalStringArray(value: unknown, path: string, defaultValue: string[] = []) {
  if (value === undefined) return defaultValue;
  return expectStringArray(value, path);
}

function expectLiteral<T extends string>(value: unknown, allowed: ReadonlySet<T>, path: string): T {
  const result = expectString(value, path);
  if (!allowed.has(result as T)) fail(path, `expected one of ${Array.from(allowed).join(", ")}`);
  return result as T;
}

function optionalNullableLiteral<T extends string>(value: unknown, allowed: ReadonlySet<T>, path: string): T | null | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  return expectLiteral(value, allowed, path);
}

function expectRecordValue(value: unknown, path: string) {
  return expectRecord(value, path);
}

function expectUnknownRecord(value: unknown, path: string) {
  if (!isRecord(value)) fail(path, "expected object");
  return value;
}

function optionalUnknownRecord(value: unknown, path: string, defaultValue: JsonRecord = {}) {
  if (value === undefined) return defaultValue;
  return expectUnknownRecord(value, path);
}

function expectNullableRecord(value: unknown, path: string) {
  if (value === null) return null;
  return expectRecord(value, path);
}

function expectArray(value: unknown, path: string) {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value;
}

function expectTuple2Number(value: unknown, path: string, integer = false): [number, number] {
  const tuple = expectArray(value, path);
  if (tuple.length !== 2) fail(path, "expected two items");
  return [
    integer ? expectInteger(tuple[0], `${path}[0]`) : expectFiniteNumber(tuple[0], `${path}[0]`),
    integer ? expectInteger(tuple[1], `${path}[1]`) : expectFiniteNumber(tuple[1], `${path}[1]`),
  ];
}

function expectIsoDateTimeString(value: unknown, path: string) {
  return expectNonEmptyString(value, path);
}

function normalizeCanvasPositionV2(value: unknown, path: string): CanvasPositionV2 {
  return normalizeStrictRecord(value, path, {
    x: expectFiniteNumber,
    y: expectFiniteNumber,
  } satisfies StrictRecordFieldsFor<CanvasPositionV2>);
}

export function normalizeAgentPlacementHintV2(
  value: unknown,
  path = "placementHint",
): AgentPlacementHintV2 {
  return normalizeStrictRecord(value, path, {
    intent: (value, fieldPath) => expectLiteral(value, PLACEMENT_INTENTS, fieldPath),
    anchor_node_id: nullableStringWithDefault,
    group_key: nullableStringWithDefault,
  } satisfies StrictRecordFieldsFor<AgentPlacementHintV2>);
}

export function normalizeCanvasVariationDraftV2(
  value: unknown,
  path = "variationDraft",
): CanvasVariationDraftV2 {
  return normalizeStrictRecord(value, path, {
    source_node_id: expectNonEmptyString,
    source_node_revision: expectPositiveInteger,
    title: expectNonEmptyString,
    generation_prompt: expectNonEmptyString,
    model_id: nullableStringWithDefault,
    model_selection_mode: (value, fieldPath) => value === undefined
      ? "default"
      : expectLiteral(value, CANVAS_MODEL_SELECTION_MODES, fieldPath),
    model_ref: nullableStringWithDefault,
    parameters: (value, fieldPath) => optionalUnknownRecord(value, fieldPath, {}),
    variation_revision: expectPositiveInteger,
    created_at: expectIsoDateTimeString,
    updated_at: expectIsoDateTimeString,
  } satisfies StrictRecordFieldsFor<CanvasVariationDraftV2>);
}

export function normalizeActionableFailureV1(value: unknown, path = "actionableFailure"): ActionableFailureV1 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["failure_class", "retry_scope", "user_action", "retryable"], path);
  const failureClass = expectLiteral(
    record.failure_class,
    new Set<ActionableFailureV1["failure_class"]>([
      "transient",
      "deterministic",
      "stale",
      "conflict",
      "external",
    ]),
    `${path}.failure_class`,
  );
  const retryScope = expectLiteral(
    record.retry_scope,
    new Set<ActionableFailureV1["retry_scope"]>([
      "none",
      "prompt_preparation",
      "turn",
      "execution",
      "provider_delivery",
    ]),
    `${path}.retry_scope`,
  );
  const userAction = expectLiteral(
    record.user_action,
    new Set<ActionableFailureV1["user_action"]>([
      "none",
      "retry",
      "revise",
      "regenerate",
      "redesign",
    ]),
    `${path}.user_action`,
  );
  const derivedRetryable = userAction === "retry" && retryScope !== "none";
  if (userAction === "retry") {
    if (retryScope === "none") fail(`${path}.retry_scope`, "retry requires one exact operation scope");
    if (failureClass !== "transient" && failureClass !== "external") {
      fail(`${path}.failure_class`, "only transient or external failures may be retried");
    }
  } else if (retryScope !== "none") {
    fail(`${path}.retry_scope`, "non-retry actions cannot carry a retry scope");
  }
  if (record.retryable !== undefined && expectBoolean(record.retryable, `${path}.retryable`) !== derivedRetryable) {
    fail(`${path}.retryable`, "retryable must be derived from the actionable disposition");
  }
  return {
    failure_class: failureClass,
    retry_scope: retryScope,
    user_action: userAction,
    retryable: derivedRetryable,
  };
}

function nullableActionableFailureV1(value: unknown, path: string): ActionableFailureV1 | null {
  if (value === null || value === undefined) return null;
  return normalizeActionableFailureV1(value, path);
}

export function normalizeCanvasNodeErrorV2(value: unknown, path = "error"): CanvasNodeErrorV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    ["code", "message", "retryable", "actionable_failure", "role_variant", "violation_category", "field_path"],
    path,
  );
  const retryable = expectBoolean(record.retryable, `${path}.retryable`);
  const actionableFailure = nullableActionableFailureV1(
    record.actionable_failure,
    `${path}.actionable_failure`,
  );
  if (actionableFailure && retryable !== actionableFailure.retryable) {
    fail(`${path}.retryable`, "retryable must match the actionable failure disposition");
  }
  return {
    code: expectNonEmptyString(record.code, `${path}.code`),
    message: expectNonEmptyString(record.message, `${path}.message`),
    retryable,
    actionable_failure: actionableFailure,
    role_variant: nullableStringWithDefault(record.role_variant, `${path}.role_variant`),
    violation_category: nullableStringWithDefault(record.violation_category, `${path}.violation_category`),
    field_path: nullableStringWithDefault(record.field_path, `${path}.field_path`),
  };
}

function normalizeAgentOperationFailureV2(
  value: unknown,
  path: string,
): AgentOperationFailureV2 {
  return normalizeStrictRecord(value, path, {
    code: expectNonEmptyString,
    message: expectNonEmptyString,
    operation: expectNonEmptyString,
    capability_id: (value, fieldPath) => value === null
      ? null
      : expectLiteral(value, AGENT_CAPABILITY_IDS, fieldPath),
    attempt_stage: (value, fieldPath) => expectLiteral(
      value,
      new Set<AgentOperationFailureV2["attempt_stage"]>([
        "initial",
        "transport_retry",
        "structured_repair",
        "fallback",
      ]),
      fieldPath,
    ),
    failure_stage: (value, fieldPath) => expectLiteral(
      value,
      new Set<AgentOperationFailureV2["failure_stage"]>([
        "routing",
        "proposal",
        "materialization",
        "safety",
        "model_capability",
        "provider",
        "asset_publication",
        "revision",
      ]),
      fieldPath,
    ),
    elapsed_ms: expectNonNegativeInteger,
    retryable: expectBoolean,
    actionable_failure: (value, fieldPath) => nullableActionableFailureV1(
      value,
      fieldPath,
    ),
    validation_paths: expectStringArray,
    occurred_at: expectIsoDateTimeString,
  } satisfies StrictRecordFieldsFor<AgentOperationFailureV2>);
}

function normalizePromptAssertionSourceSnapshotV1(
  value: unknown,
  path: string,
): PromptAssertionSourceSnapshotV1 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "schema_version",
    "source_kind",
    "binding_id",
    "binding_revision",
    "source_node_id",
    "source_node_revision",
    "asset_id",
    "asset_version_id",
    "reference_purpose",
    "document_id",
    "document_revision",
    "sequence_id",
  ], path);
  const nullableRevision = (field: string) => (
    record[field] === undefined || record[field] === null
      ? null
      : expectPositiveInteger(record[field], `${path}.${field}`)
  );
  return {
    schema_version: expectLiteral(record.schema_version, new Set(["1"]), `${path}.schema_version`),
    source_kind: expectLiteral(
      record.source_kind,
      new Set<PromptAssertionSourceSnapshotV1["source_kind"]>(["binding", "document", "sequence"]),
      `${path}.source_kind`,
    ),
    binding_id: nullableStringWithDefault(record.binding_id, `${path}.binding_id`),
    binding_revision: nullableRevision("binding_revision"),
    source_node_id: nullableStringWithDefault(record.source_node_id, `${path}.source_node_id`),
    source_node_revision: nullableRevision("source_node_revision"),
    asset_id: nullableStringWithDefault(record.asset_id, `${path}.asset_id`),
    asset_version_id: nullableStringWithDefault(record.asset_version_id, `${path}.asset_version_id`),
    reference_purpose: nullableStringWithDefault(record.reference_purpose, `${path}.reference_purpose`),
    document_id: nullableStringWithDefault(record.document_id, `${path}.document_id`),
    document_revision: nullableRevision("document_revision"),
    sequence_id: nullableStringWithDefault(record.sequence_id, `${path}.sequence_id`),
  };
}

function normalizePromptAssertionEvidenceV1(
  value: unknown,
  path: string,
): PromptAssertionEvidenceV1 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "schema_version",
    "policy_ref",
    "policy_version",
    "policy_digest",
    "recipe_id",
    "recipe_version",
    "assertion_ids",
    "assertion_block_digest",
    "prepared_prompt_digest",
    "source_snapshots",
    "document_revisions",
    "sequence_id",
    "character_identity_projection_digest",
    "scene_environment_projection_digest",
    "engine_owned_fields_digest",
    "evidence_digest",
  ], path);
  const preparedPromptDigest = expectNonEmptyString(
    record.prepared_prompt_digest,
    `${path}.prepared_prompt_digest`,
  );
  if (!/^[a-f0-9]{64}$/.test(preparedPromptDigest)) {
    fail(`${path}.prepared_prompt_digest`, "expected a 64 character lowercase hexadecimal digest");
  }
  const assertionIds = expectStringArray(record.assertion_ids, `${path}.assertion_ids`);
  if (!assertionIds.length) fail(`${path}.assertion_ids`, "expected at least one assertion identifier");
  return {
    schema_version: expectLiteral(record.schema_version, new Set(["1"]), `${path}.schema_version`),
    policy_ref: expectNonEmptyString(record.policy_ref, `${path}.policy_ref`),
    policy_version: expectNonEmptyString(record.policy_version, `${path}.policy_version`),
    policy_digest: requiredDigest(record.policy_digest, `${path}.policy_digest`),
    recipe_id: expectNonEmptyString(record.recipe_id, `${path}.recipe_id`),
    recipe_version: expectNonEmptyString(record.recipe_version, `${path}.recipe_version`),
    assertion_ids: assertionIds,
    assertion_block_digest: requiredDigest(
      record.assertion_block_digest,
      `${path}.assertion_block_digest`,
    ),
    prepared_prompt_digest: preparedPromptDigest,
    source_snapshots: expectArray(record.source_snapshots, `${path}.source_snapshots`)
      .map((item, index) => normalizePromptAssertionSourceSnapshotV1(
        item,
        `${path}.source_snapshots[${index}]`,
      )),
    document_revisions: normalizeDocumentRevisions(
      expectRecord(record.document_revisions, `${path}.document_revisions`),
      `${path}.document_revisions`,
    ),
    sequence_id: nullableStringWithDefault(record.sequence_id, `${path}.sequence_id`),
    character_identity_projection_digest: nullableDigest(
      record.character_identity_projection_digest,
      `${path}.character_identity_projection_digest`,
    ),
    scene_environment_projection_digest: nullableDigest(
      record.scene_environment_projection_digest,
      `${path}.scene_environment_projection_digest`,
    ),
    engine_owned_fields_digest: requiredDigest(
      record.engine_owned_fields_digest,
      `${path}.engine_owned_fields_digest`,
    ),
    evidence_digest: requiredDigest(record.evidence_digest, `${path}.evidence_digest`),
  };
}

function normalizeNodePromptPreparationV1(
  value: unknown,
  path: string,
): NodePromptPreparationV1 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "status",
      "operation_id",
      "presentation_stream_id",
      "attempt_no",
      "context_snapshot_id",
      "occurrence_id",
      "character_phase",
      "prompt_digest",
      "role_variant",
      "recipe_id",
      "recipe_version",
      "recipe_digest",
      "requirement_revision_id",
      "requirement_revision_no",
      "document_revisions",
      "binding_digest",
      "character_identity_projection_digest",
      "scene_environment_projection_digest",
      "style_projection_digest",
      "brief_digest",
      "parameter_origins",
      "compaction_policy_version",
      "compaction_policy_digest",
      "compaction_decisions",
      "assertion_evidence",
      "attempt_stage",
      "error",
      "updated_at",
    ],
    path,
  );
  const status = expectLiteral(record.status, NODE_PROMPT_PREPARATION_STATUSES, `${path}.status`);
  const operationId = nullableStringWithDefault(record.operation_id, `${path}.operation_id`);
  const presentationStreamId = nullableStringWithDefault(
    record.presentation_stream_id,
    `${path}.presentation_stream_id`,
  );
  const contextSnapshotId = nullableStringWithDefault(record.context_snapshot_id, `${path}.context_snapshot_id`);
  const occurrenceId = nullableStringWithDefault(record.occurrence_id, `${path}.occurrence_id`);
  const characterPhase = record.character_phase === undefined || record.character_phase === null
    ? null
    : expectLiteral(record.character_phase, new Set(["main", "turnaround"] as const), `${path}.character_phase`);
  const promptDigest = nullableStringWithDefault(record.prompt_digest, `${path}.prompt_digest`);
  if (operationId !== null && !operationId.trim()) fail(`${path}.operation_id`, "expected non-empty string");
  if (contextSnapshotId !== null && !contextSnapshotId.trim()) {
    fail(`${path}.context_snapshot_id`, "expected non-empty string");
  }
  if (promptDigest !== null && !/^[a-f0-9]{64}$/.test(promptDigest)) {
    fail(`${path}.prompt_digest`, "expected a 64 character lowercase hexadecimal digest");
  }
  const error = record.error === null || record.error === undefined
    ? null
    : normalizeCanvasNodeErrorV2(record.error, `${path}.error`);
  const documentRevisions = normalizeDocumentRevisions(record.document_revisions, `${path}.document_revisions`);
  const parameterOrigins = expectArray(record.parameter_origins ?? [], `${path}.parameter_origins`).map((item, index) => (
    normalizeResolvedNodeParameterV2(item, `${path}.parameter_origins[${index}]`)
  ));
  const compactionDecisions = expectArray(
    record.compaction_decisions ?? [],
    `${path}.compaction_decisions`,
  ).map((item, index) => (
    normalizeRolePromptCompactionDecisionV2(item, `${path}.compaction_decisions[${index}]`)
  ));
  const attemptNo = expectNonNegativeInteger(record.attempt_no, `${path}.attempt_no`);
  const characterIdentityProjectionDigest = nullableDigest(
    record.character_identity_projection_digest,
    `${path}.character_identity_projection_digest`,
  );
  const sceneEnvironmentProjectionDigest = nullableDigest(
    record.scene_environment_projection_digest,
    `${path}.scene_environment_projection_digest`,
  );
  const compactionPolicyVersion = nullableStringWithDefault(
    record.compaction_policy_version,
    `${path}.compaction_policy_version`,
  );
  const compactionPolicyDigest = nullableDigest(
    record.compaction_policy_digest,
    `${path}.compaction_policy_digest`,
  );
  if (status === "waiting_user") {
    if (
      [
        operationId,
        presentationStreamId,
        contextSnapshotId,
        occurrenceId,
        characterPhase,
        promptDigest,
        record.role_variant,
        record.recipe_id,
        record.recipe_version,
        record.recipe_digest,
        record.requirement_revision_id,
        record.requirement_revision_no,
        record.binding_digest,
        record.character_identity_projection_digest,
        record.scene_environment_projection_digest,
        record.style_projection_digest,
        record.brief_digest,
        compactionPolicyVersion,
        compactionPolicyDigest,
        record.assertion_evidence,
        record.attempt_stage,
        error,
      ].some((value) => value !== null && value !== undefined)
      || attemptNo !== 0
      || Object.keys(documentRevisions).length > 0
      || parameterOrigins.length > 0
      || compactionDecisions.length > 0
    ) {
      fail(`${path}.status`, "waiting_user prompt preparation cannot carry preparation context");
    }
  }
  if (status === "not_applicable" && (
    [
      operationId,
      presentationStreamId,
      contextSnapshotId,
      promptDigest,
      record.role_variant,
      record.recipe_id,
      record.recipe_version,
      record.recipe_digest,
      record.requirement_revision_id,
      record.binding_digest,
      characterIdentityProjectionDigest,
      sceneEnvironmentProjectionDigest,
      record.style_projection_digest,
      record.brief_digest,
      record.assertion_evidence,
      error,
    ].some((value) => value !== null && value !== undefined)
    || Object.keys(documentRevisions).length > 0
    || parameterOrigins.length > 0
  )) {
    fail(`${path}.status`, "not_applicable prompt preparation cannot have preparation data");
  }
  if (status === "failed" && !error) fail(`${path}.error`, "failed prompt preparation requires a safe error");
  if (status !== "failed" && status !== "superseded" && error) {
    fail(`${path}.error`, "only failed or superseded prompt preparation may expose an error");
  }
  if (status === "ready" && !promptDigest) {
    fail(`${path}.prompt_digest`, "ready prompt preparation requires a prompt digest");
  }
  return {
    status,
    operation_id: operationId,
    presentation_stream_id: presentationStreamId,
    attempt_no: attemptNo,
    context_snapshot_id: contextSnapshotId,
    occurrence_id: occurrenceId,
    character_phase: characterPhase,
    prompt_digest: promptDigest,
    role_variant: nullableStringWithDefault(record.role_variant, `${path}.role_variant`),
    recipe_id: nullableStringWithDefault(record.recipe_id, `${path}.recipe_id`),
    recipe_version: nullableStringWithDefault(record.recipe_version, `${path}.recipe_version`),
    recipe_digest: nullableDigest(record.recipe_digest, `${path}.recipe_digest`),
    requirement_revision_id: nullableStringWithDefault(
      record.requirement_revision_id,
      `${path}.requirement_revision_id`,
    ),
    requirement_revision_no: record.requirement_revision_no === undefined || record.requirement_revision_no === null
      ? null
      : expectPositiveInteger(record.requirement_revision_no, `${path}.requirement_revision_no`),
    document_revisions: documentRevisions,
    binding_digest: nullableDigest(record.binding_digest, `${path}.binding_digest`),
    character_identity_projection_digest: characterIdentityProjectionDigest,
    scene_environment_projection_digest: sceneEnvironmentProjectionDigest,
    style_projection_digest: nullableDigest(record.style_projection_digest, `${path}.style_projection_digest`),
    brief_digest: nullableDigest(record.brief_digest, `${path}.brief_digest`),
    parameter_origins: parameterOrigins,
    compaction_policy_version: compactionPolicyVersion,
    compaction_policy_digest: compactionPolicyDigest,
    compaction_decisions: compactionDecisions,
    assertion_evidence: record.assertion_evidence === undefined || record.assertion_evidence === null
      ? null
      : normalizePromptAssertionEvidenceV1(
          record.assertion_evidence,
          `${path}.assertion_evidence`,
        ),
    attempt_stage: nullableStringWithDefault(record.attempt_stage, `${path}.attempt_stage`),
    error,
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function normalizeRolePromptCompactionDecisionV2(
  value: unknown,
  path: string,
): RolePromptCompactionDecisionV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "block_id",
    "source_id",
    "source_digest",
    "precedence",
    "outcome",
    "retained_block_id",
    "retained_precedence",
    "reason",
  ], path);
  const precedence = expectNonNegativeInteger(record.precedence, `${path}.precedence`);
  if (precedence > 128) fail(`${path}.precedence`, "precedence cannot exceed 128");
  const retainedPrecedence = record.retained_precedence === undefined || record.retained_precedence === null
    ? null
    : expectNonNegativeInteger(record.retained_precedence, `${path}.retained_precedence`);
  if (retainedPrecedence !== null && retainedPrecedence > 128) {
    fail(`${path}.retained_precedence`, "precedence cannot exceed 128");
  }
  return {
    block_id: expectNonEmptyString(record.block_id, `${path}.block_id`),
    source_id: expectNonEmptyString(record.source_id, `${path}.source_id`),
    source_digest: requiredDigest(record.source_digest, `${path}.source_digest`),
    precedence,
    outcome: expectLiteral(
      record.outcome,
      new Set<RolePromptCompactionDecisionV2["outcome"]>(["preserved", "compacted"]),
      `${path}.outcome`,
    ),
    retained_block_id: nullableStringWithDefault(
      record.retained_block_id,
      `${path}.retained_block_id`,
    ),
    retained_precedence: retainedPrecedence,
    reason: expectLiteral(
      record.reason,
      new Set<RolePromptCompactionDecisionV2["reason"]>([
        "policy_disabled",
        "not_eligible",
        "ownership_unknown",
        "identity_unproven",
        "exact_duplicate",
        "preserved_authority",
      ]),
      `${path}.reason`,
    ),
  };
}

function normalizeEditablePromptProjectionV1(
  value: unknown,
  path: string,
): EditablePromptProjectionV1 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "text",
    "locale",
    "source",
    "revision",
    "brief_digest",
    "prompt_digest",
  ], path);
  const text = expectNonEmptyString(record.text, `${path}.text`);
  if (text.length > 32_768) fail(`${path}.text`, "editable prompt exceeds the length limit");
  return {
    text,
    locale: expectNonEmptyString(record.locale, `${path}.locale`),
    source: expectLiteral(
      record.source,
      new Set<EditablePromptProjectionV1["source"]>([
        "agent_authored",
        "deterministic_projection",
        "user_edited",
      ]),
      `${path}.source`,
    ),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    brief_digest: nullableDigest(record.brief_digest, `${path}.brief_digest`),
    prompt_digest: requiredDigest(record.prompt_digest, `${path}.prompt_digest`),
  };
}

function normalizePresentationStreamResetV1(
  value: unknown,
  path: string,
): PresentationStreamResetV1 {
  return normalizeStrictRecord(value, path, {
    reason: (value, fieldPath) => expectLiteral(
      value,
      new Set<PresentationStreamResetV1["reason"]>(["cursor_expired", "store_recovered"]),
      fieldPath,
    ),
    authoritative_id: nullableStringWithDefault,
    resource_kind: (value, fieldPath) => expectLiteral(
      value,
      new Set<PresentationStreamResetV1["resource_kind"]>(["message", "prompt", "workflow"]),
      fieldPath,
    ),
  } satisfies StrictRecordFieldsFor<PresentationStreamResetV1>);
}

function normalizePresentationDelta(value: unknown, path: string): string {
  const delta = expectNonEmptyString(value, path);
  if (new TextEncoder().encode(delta).length > 4_096) {
    fail(path, "presentation delta exceeds the UTF-8 byte limit");
  }
  const normalized = delta.trim();
  if (normalized.startsWith("{") || normalized.startsWith("[") || normalized.startsWith("```")) {
    fail(path, "structured or code-fenced output is not presentation text");
  }
  try {
    const parsed = JSON.parse(normalized);
    if (typeof parsed === "object" && parsed !== null) {
      fail(path, "structured output is not presentation text");
    }
  } catch {
    // Ordinary prose is expected to be non-JSON.
  }
  const lowered = normalized.toLowerCase();
  if ([
    "<system>",
    "tool_call",
    "reasoning",
    "authorization: bearer",
    "api_key",
    "provider_error",
    "traceback",
  ].some((marker) => lowered.includes(marker))) {
    fail(path, "hidden or transport content is not presentation text");
  }
  return delta;
}

export function normalizePresentationStreamEventV1(
  value: unknown,
  path = "presentationStreamEvent",
): PresentationStreamEventV1 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "schema_version",
      "stream_id",
      "workflow_id",
      "stream_kind",
      "event_type",
      "sequence_no",
      "turn_id",
      "node_id",
      "generation_id",
      "response_locale",
      "node_revision",
      "delta",
      "authoritative_id",
      "content_digest",
      "error_code",
      "reset",
    ],
    path,
  );
  const streamKind = expectLiteral(record.stream_kind, PRESENTATION_STREAM_KINDS, `${path}.stream_kind`);
  const eventType = expectLiteral(
    record.event_type,
    PRESENTATION_STREAM_EVENT_TYPES,
    `${path}.event_type`,
  );
  const turnId = nullableStringWithDefault(record.turn_id, `${path}.turn_id`);
  const nodeId = nullableStringWithDefault(record.node_id, `${path}.node_id`);
  const nodeRevision = record.node_revision === undefined || record.node_revision === null
    ? null
    : expectPositiveInteger(record.node_revision, `${path}.node_revision`);
  if (streamKind === "assistant" && !turnId) fail(`${path}.turn_id`, "assistant stream requires turn_id");
  if (streamKind === "node_prompt" && (!nodeId || nodeRevision === null)) {
    fail(`${path}.node_id`, "prompt stream requires node identity");
  }
  const delta = record.delta === undefined || record.delta === null
    ? null
    : normalizePresentationDelta(record.delta, `${path}.delta`);
  const authoritativeId = nullableStringWithDefault(record.authoritative_id, `${path}.authoritative_id`);
  const contentDigest = nullableStringWithDefault(record.content_digest, `${path}.content_digest`);
  if (contentDigest !== null && !/^[a-f0-9]{64}$/.test(contentDigest)) {
    fail(`${path}.content_digest`, "expected a 64 character lowercase hexadecimal digest");
  }
  const errorCode = nullableStringWithDefault(record.error_code, `${path}.error_code`);
  const reset = record.reset === undefined || record.reset === null
    ? null
    : normalizePresentationStreamResetV1(record.reset, `${path}.reset`);
  const schemaVersion = expectInteger(record.schema_version, `${path}.schema_version`);
  if (schemaVersion !== 1) fail(`${path}.schema_version`, "expected schema version 1");
  if (eventType === "delta") {
    if (!delta) fail(`${path}.delta`, "delta event requires presentation text");
    if (authoritativeId || contentDigest || errorCode) {
      fail(path, "delta events cannot expose terminal metadata");
    }
  } else if (delta !== null) {
    fail(`${path}.delta`, "only delta events may contain presentation text");
  }
  if (eventType === "committed" && !authoritativeId) {
    fail(`${path}.authoritative_id`, "committed events require authoritative identity");
  }
  if (eventType === "committed" && !contentDigest) {
    fail(`${path}.content_digest`, "committed events require content digest");
  }
  if (eventType === "failed" && !errorCode) fail(`${path}.error_code`, "failed event requires an error code");
  if (eventType === "reset" && !reset) fail(`${path}.reset`, "reset event requires reset details");
  if (eventType !== "reset" && reset) fail(`${path}.reset`, "only reset events may contain reset details");
  return {
    schema_version: 1,
    stream_id: expectNonEmptyString(record.stream_id, `${path}.stream_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    stream_kind: streamKind,
    event_type: eventType,
    sequence_no: expectPositiveInteger(record.sequence_no, `${path}.sequence_no`),
    turn_id: turnId,
    node_id: nodeId,
    generation_id: expectNonEmptyString(record.generation_id, `${path}.generation_id`),
    response_locale: nullableStringWithDefault(record.response_locale, `${path}.response_locale`),
    node_revision: nodeRevision,
    delta,
    authoritative_id: authoritativeId,
    content_digest: contentDigest,
    error_code: errorCode,
    reset,
  };
}

function nullableDigest(value: unknown, path: string): string | null {
  const digest = nullableStringWithDefault(value, path);
  if (digest !== null && !/^sha256:[a-f0-9]{64}$/.test(digest)) fail(path, "expected sha256 digest");
  return digest;
}

function requiredDigest(value: unknown, path: string): string {
  const digest = expectNonEmptyString(value, path);
  if (!/^sha256:[a-f0-9]{64}$/.test(digest)) fail(path, "expected sha256 digest");
  return digest;
}

function normalizeDocumentRevisions(value: unknown, path: string): Record<string, number> {
  if (value === undefined || value === null) return {};
  const record = expectRecord(value, path);
  const result: Record<string, number> = {};
  Object.entries(record).forEach(([key, revision]) => {
    if (!key.trim()) fail(path, "document revision key must not be empty");
    result[key] = expectPositiveInteger(revision, `${path}.${key}`);
  });
  return result;
}

function normalizeResolvedNodeParameterV2(value: unknown, path: string): ResolvedNodeParameterV2 {
  return normalizeStrictRecord(value, path, {
    name: expectNonEmptyString,
    value: (value) => value,
    source_kind: (value, fieldPath) => expectLiteral(value, new Set<ResolvedNodeParameterV2["source_kind"]>([
      "explicit_user", "bound_text", "node_parameter", "storyboard_plan", "style_advice", "installation_default",
    ]), fieldPath),
    source_id: expectNonEmptyString,
    source_revision: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectPositiveInteger(value, fieldPath),
  } satisfies StrictRecordFieldsFor<ResolvedNodeParameterV2>);
}

export function normalizeCanvasModelSummaryV2(value: unknown, path = "model_summary"): CanvasModelSummaryV2 {
  return normalizeStrictRecord(value, path, {
    model_ref: expectNonEmptyString,
    provider_id: expectNonEmptyString,
    display_name: expectNonEmptyString,
    capability: (value, fieldPath) => expectLiteral(value, CANVAS_MODEL_CAPABILITIES, fieldPath),
    availability: (value, fieldPath) => expectLiteral(value, CANVAS_MODEL_AVAILABILITIES, fieldPath),
    unavailable_reason: nullableString,
    catalog_revision: expectPositiveInteger,
  } satisfies StrictRecordFieldsFor<CanvasModelSummaryV2>);
}

function normalizeCanvasParameterScalarV2(
  value: unknown,
  path: string,
): CanvasParameterProvenanceV2["requested_value"] {
  if (typeof value === "string" || typeof value === "boolean") return value;
  return expectFiniteNumber(value, path);
}

function normalizeCanvasParameterProvenanceV2(
  value: unknown,
  path: string,
): CanvasParameterProvenanceV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "origin",
    "source_node_id",
    "binding_id",
    "source_revision",
    "requested_value",
    "effective_value",
    "normalization_code",
  ], path);
  const origin = expectLiteral(record.origin, CANVAS_PARAMETER_ORIGINS, `${path}.origin`);
  const sourceNodeId = nullableStringWithDefault(record.source_node_id, `${path}.source_node_id`);
  const bindingId = nullableStringWithDefault(record.binding_id, `${path}.binding_id`);
  const sourceRevision = record.source_revision === undefined
    ? null
    : nullablePositiveInteger(record.source_revision, `${path}.source_revision`);
  if (origin === "binding") {
    if (!sourceNodeId || !bindingId || sourceRevision === null) {
      fail(path, "binding origin requires source_node_id, binding_id, and source_revision");
    }
  } else if (sourceNodeId !== null || bindingId !== null || sourceRevision !== null) {
    fail(path, "only binding origin may include binding source identity");
  }
  return {
    origin,
    source_node_id: sourceNodeId,
    binding_id: bindingId,
    source_revision: sourceRevision,
    requested_value: normalizeCanvasParameterScalarV2(record.requested_value, `${path}.requested_value`),
    effective_value: normalizeCanvasParameterScalarV2(record.effective_value, `${path}.effective_value`),
    normalization_code: nullableStringWithDefault(record.normalization_code, `${path}.normalization_code`),
  };
}

function normalizeCanvasParameterProvenanceMapV2(
  value: unknown,
  path: string,
): Record<string, CanvasParameterProvenanceV2> {
  const record = optionalUnknownRecord(value, path, {});
  return Object.fromEntries(
    Object.entries(record).map(([field, provenance]) => [
      field,
      normalizeCanvasParameterProvenanceV2(provenance, `${path}.${field}`),
    ]),
  );
}

export function normalizeCanvasNodeLatestAttemptV2(
  value: unknown,
  path = "latestAttempt",
): CanvasNodeLatestAttemptV2 {
  return normalizeStrictRecord(value, path, {
    execution_id: expectNonEmptyString,
    member_id: expectNonEmptyString,
    run_intent_snapshot_id: (value, fieldPath) => nullableStringWithDefault(
      value,
      fieldPath,
    ),
    status: (value, fieldPath) => expectLiteral(
      value,
      new Set<CanvasNodeLatestAttemptV2["status"]>([
        "queued",
        "waiting",
        "blocked",
        "skipped_dependency",
        "running",
        "succeeded",
        "failed",
        "cancelled",
      ]),
      fieldPath,
    ),
    created_at: expectIsoDateTimeString,
    updated_at: expectIsoDateTimeString,
    error: (value, fieldPath) => value === null || value === undefined
      ? null
      : normalizeCanvasNodeErrorV2(value, fieldPath),
  } satisfies StrictRecordFieldsFor<CanvasNodeLatestAttemptV2>);
}

export function normalizeCanvasNodeV2(value: unknown, path = "node"): CanvasNodeV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "node_id",
      "workflow_id",
      "node_type",
      "creative_role",
      "role_contract_version",
      "title",
      "status",
      "execution_mode",
      "summary_prompt",
      "generation_prompt",
      "structured_content",
      "model_id",
      "model_selection_mode",
      "model_ref",
      "model_summary",
      "parameters",
      "metadata",
      "parameter_provenance",
      "prompt_context_snapshot_id",
      "output_asset_id",
      "output_asset_version_id",
      "latest_attempt",
      "position",
      "revision",
      "error",
      "authoring_origin",
      "intent_hint",
      "prompt_presentation",
      "prompt_preparation",
      "created_at",
      "updated_at",
    ],
    path,
  );
  const nodeType = expectLiteral(record.node_type, CANVAS_NODE_TYPES, `${path}.node_type`);
  const status = expectLiteral(record.status, CANVAS_NODE_STATUSES, `${path}.status`);
  const outputAssetId = nullableString(record.output_asset_id, `${path}.output_asset_id`);
  if (
    status === "ready"
    && ["image", "video", "audio", "editing"].includes(nodeType)
    && !outputAssetId
  ) {
    fail(`${path}.output_asset_id`, "ready media node requires an output asset");
  }
  const updatedAt = expectIsoDateTimeString(record.updated_at, `${path}.updated_at`);
  return {
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    node_type: nodeType,
    creative_role: expectLiteral(record.creative_role, CANVAS_CREATIVE_ROLES, `${path}.creative_role`),
    role_contract_version: expectLiteral(
      record.role_contract_version,
      new Set<CanvasNodeV2["role_contract_version"]>([
        "ad-media-role-v1",
        "ad-media-role-v2",
      ]),
      `${path}.role_contract_version`,
    ),
    title: expectNonEmptyString(record.title, `${path}.title`),
    status,
    execution_mode: record.execution_mode === undefined
      ? "generative"
      : expectLiteral(record.execution_mode, CANVAS_NODE_EXECUTION_MODES, `${path}.execution_mode`),
    summary_prompt: nullableString(record.summary_prompt, `${path}.summary_prompt`),
    generation_prompt: nullableString(record.generation_prompt, `${path}.generation_prompt`),
    structured_content: expectRecordValue(record.structured_content, `${path}.structured_content`),
    model_id: nullableStringWithDefault(record.model_id, `${path}.model_id`),
    model_selection_mode: record.model_selection_mode === undefined
      ? "default"
      : expectLiteral(record.model_selection_mode, CANVAS_MODEL_SELECTION_MODES, `${path}.model_selection_mode`),
    model_ref: nullableStringWithDefault(record.model_ref, `${path}.model_ref`),
    model_summary: record.model_summary === null || record.model_summary === undefined
      ? null
      : normalizeCanvasModelSummaryV2(record.model_summary, `${path}.model_summary`),
    parameters: expectRecordValue(record.parameters, `${path}.parameters`),
    metadata: optionalUnknownRecord(record.metadata, `${path}.metadata`, {}),
    parameter_provenance: normalizeCanvasParameterProvenanceMapV2(
      record.parameter_provenance,
      `${path}.parameter_provenance`,
    ),
    prompt_context_snapshot_id: nullableString(record.prompt_context_snapshot_id, `${path}.prompt_context_snapshot_id`),
    output_asset_id: outputAssetId,
    output_asset_version_id: nullableString(
      record.output_asset_version_id,
      `${path}.output_asset_version_id`,
    ),
    latest_attempt: record.latest_attempt === null || record.latest_attempt === undefined
      ? null
      : normalizeCanvasNodeLatestAttemptV2(record.latest_attempt, `${path}.latest_attempt`),
    position: normalizeCanvasPositionV2(record.position, `${path}.position`),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    error: record.error === null ? null : normalizeCanvasNodeErrorV2(record.error, `${path}.error`),
    authoring_origin: record.authoring_origin === undefined ? "user_free" : expectLiteral(record.authoring_origin, new Set(["user_free", "agent_guided", "template"]), `${path}.authoring_origin`),
    intent_hint: nullableStringWithDefault(record.intent_hint, `${path}.intent_hint`),
    prompt_presentation: record.prompt_presentation === undefined || record.prompt_presentation === null
      ? null
      : normalizeEditablePromptProjectionV1(
        record.prompt_presentation,
        `${path}.prompt_presentation`,
      ),
    prompt_preparation: record.prompt_preparation === undefined || record.prompt_preparation === null
      ? null
      : normalizeNodePromptPreparationV1(record.prompt_preparation, `${path}.prompt_preparation`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: updatedAt,
  };
}

function normalizeCanvasBindingSourceNodeV2(value: unknown, path: string): CanvasBindingSourceNodeV2 {
  return normalizeStrictRecord(value, path, {
    kind: (value, fieldPath) => expectLiteral(value, new Set<CanvasBindingSourceNodeV2["kind"]>(["node_output"]), fieldPath),
    source_node_id: expectNonEmptyString,
  } satisfies StrictRecordFieldsFor<CanvasBindingSourceNodeV2>);
}

function normalizeCanvasBindingSourceImageAssetV2(value: unknown, path: string): CanvasBindingSourceImageAssetV2 {
  return normalizeStrictRecord(value, path, {
    kind: (value, fieldPath) => expectLiteral(value, new Set<CanvasBindingSourceImageAssetV2["kind"]>(["image_asset"]), fieldPath),
    source_asset_id: expectNonEmptyString,
    source_asset_version_id: (value, fieldPath) => nullableStringWithDefault(
      value,
      fieldPath,
    ),
  } satisfies StrictRecordFieldsFor<CanvasBindingSourceImageAssetV2>);
}

export function normalizeCanvasBindingSourceV2(value: unknown, path = "binding.source"): CanvasBindingSourceV2 {
  const record = expectRecord(value, path);
  const kind = expectString(record.kind, `${path}.kind`);
  if (kind === "node_output") return normalizeCanvasBindingSourceNodeV2(record, path);
  if (kind === "image_asset") return normalizeCanvasBindingSourceImageAssetV2(record, path);
  fail(`${path}.kind`, "unsupported discriminator");
}

export function normalizeCanvasBindingV2(value: unknown, path = "binding"): CanvasBindingV2 {
  return normalizeStrictRecord(value, path, {
    binding_id: expectNonEmptyString,
    workflow_id: expectNonEmptyString,
    source: normalizeCanvasBindingSourceV2,
    target_node_id: expectNonEmptyString,
    input_role: (value, fieldPath) => expectLiteral(value, CANVAS_BINDING_ROLES, fieldPath),
    enabled: expectBoolean,
    order: expectNonNegativeInteger,
    label: nullableString,
    metadata: expectRecordValue,
    created_at: expectIsoDateTimeString,
    updated_at: expectIsoDateTimeString,
  } satisfies StrictRecordFieldsFor<CanvasBindingV2>);
}

export function normalizeProjectAssetSummaryV2(value: unknown, path = "asset"): ProjectAssetSummaryV2 {
  return normalizeStrictRecord(value, path, {
    asset_id: expectNonEmptyString,
    version_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    project_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    workflow_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    media_type: (value, fieldPath) => expectLiteral(value, ASSET_MEDIA_TYPES, fieldPath),
    source_type: (value, fieldPath) => expectLiteral(value, ASSET_SOURCE_TYPES, fieldPath),
    semantic_type: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    display_name: expectNonEmptyString,
    mime_type: expectNonEmptyString,
    status: (value, fieldPath) => expectLiteral(value, PROJECT_ASSET_STATUSES, fieldPath),
    size_bytes: (value, fieldPath) => value === undefined ? 0 : expectNonNegativeInteger(value, fieldPath),
    storage_key: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    preview_url: nullableBrowserSafeUrl,
    media_url: nullableBrowserSafeUrl,
    width: nullablePositiveInteger,
    height: nullablePositiveInteger,
    duration_seconds: nullableNonNegativeNumber,
    checksum: expectNonEmptyString,
    source_semantic_role: (value, fieldPath) => value === undefined
      ? null
      : nullableString(value, fieldPath),
    source_node_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    source_execution_id: (value, fieldPath) => value === undefined
      ? null
      : nullableString(value, fieldPath),
    provider: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    model_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    prompt_provenance: (value, fieldPath) => optionalUnknownRecord(value, fieldPath, {}),
    actual_media_facts: (value, fieldPath) => optionalUnknownRecord(value, fieldPath, {}),
    generation_provenance: (value, fieldPath) => optionalUnknownRecord(value, fieldPath, {}),
    quality_metadata: (value, fieldPath) => optionalUnknownRecord(value, fieldPath, {}),
    created_at: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectIsoDateTimeString(value, fieldPath),
  } satisfies StrictRecordFieldsFor<ProjectAssetSummaryV2>);
}

function normalizeVideoSkillPreviewV2(value: unknown, path: string): VideoSkillPreviewV2 {
  return normalizeStrictRecord(value, path, {
    kind: (value, fieldPath) => expectLiteral(
      value,
      new Set<VideoSkillPreviewV2["kind"]>(["none", "image", "video"]),
      fieldPath,
    ),
    summary: nullableStringWithDefault,
    media_url: (value, fieldPath) => nullablePublicPreviewUrl(value ?? null, fieldPath),
  } satisfies StrictRecordFieldsFor<VideoSkillPreviewV2>);
}

function normalizeVideoSkillCategoryV2(value: unknown, path: string): VideoSkillCategoryV2 {
  return normalizeStrictRecord(value, path, {
    category_id: expectNonEmptyString,
    title: expectNonEmptyString,
    display_order: expectNonNegativeInteger,
  } satisfies StrictRecordFieldsFor<VideoSkillCategoryV2>);
}

export function normalizeVideoSkillPublicDetailV2(
  value: unknown,
  path = "videoSkill",
): VideoSkillPublicDetailV2 {
  return normalizeStrictRecord(value, path, {
    skill_id: expectNonEmptyString,
    version: expectNonEmptyString,
    title: expectNonEmptyString,
    summary: expectNonEmptyString,
    category: expectNonEmptyString,
    tags: optionalStringArray,
    supported_use_cases: (value, fieldPath) => optionalStringArray(
      value,
      fieldPath,
    ),
    preview: (value, fieldPath) => value === undefined || value === null
      ? null
      : normalizeVideoSkillPreviewV2(value, fieldPath),
    display_order: expectNonNegativeInteger,
  } satisfies StrictRecordFieldsFor<VideoSkillPublicDetailV2>);
}

export function normalizeVideoSkillCatalogResponseV2(
  value: unknown,
  path = "videoSkillCatalog",
): VideoSkillCatalogResponseV2 {
  return normalizeStrictRecord(value, path, {
    catalog_version: expectNonEmptyString,
    categories: (value, fieldPath) => expectArray(value, fieldPath).map((item, index) => (
      normalizeVideoSkillCategoryV2(item, `${fieldPath}[${index}]`)
    )),
    items: (value, fieldPath) => expectArray(value, fieldPath).map((item, index) => (
      normalizeVideoSkillPublicDetailV2(item, `${fieldPath}[${index}]`)
    )),
    next_cursor: nullableStringWithDefault,
  } satisfies StrictRecordFieldsFor<VideoSkillCatalogResponseV2>);
}

function normalizeActiveStyleSkillSummaryV2(
  value: unknown,
  path: string,
): ActiveStyleSkillSummaryV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "skill_run_id",
      "skill_id",
      "skill_version",
      "title",
      "summary",
      "category",
      "creative_direction_snapshot_id",
    ],
    path,
  );
  return {
    skill_run_id: expectNonEmptyString(record.skill_run_id, `${path}.skill_run_id`),
    skill_id: expectNonEmptyString(record.skill_id, `${path}.skill_id`),
    skill_version: expectNonEmptyString(record.skill_version, `${path}.skill_version`),
    title: expectNonEmptyString(record.title, `${path}.title`),
    summary: expectNonEmptyString(record.summary, `${path}.summary`),
    category: expectNonEmptyString(record.category, `${path}.category`),
    creative_direction_snapshot_id: expectNonEmptyString(
      record.creative_direction_snapshot_id,
      `${path}.creative_direction_snapshot_id`,
    ),
  };
}

export function normalizeAgentCanvasWorkflowV2(value: unknown, path = "workflow"): AgentCanvasWorkflowV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "workflow_id",
      "project_id",
      "workflow_schema_version",
      "canvas_model",
      "revision",
      "layout_revision",
      "nodes",
      "bindings",
      "assets",
      "active_style_skill",
    ],
    path,
  );
  const schemaVersion = expectInteger(record.workflow_schema_version, `${path}.workflow_schema_version`);
  if (schemaVersion !== 2) fail(`${path}.workflow_schema_version`, "expected 2");
  const canvasModel = expectString(record.canvas_model, `${path}.canvas_model`);
  if (canvasModel !== "agent_canvas_v1") fail(`${path}.canvas_model`, "expected agent_canvas_v1");
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    project_id: expectNonEmptyString(record.project_id, `${path}.project_id`),
    workflow_schema_version: 2,
    canvas_model: "agent_canvas_v1",
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    layout_revision: record.layout_revision === undefined
      ? 1
      : expectPositiveInteger(record.layout_revision, `${path}.layout_revision`),
    nodes: expectArray(record.nodes, `${path}.nodes`).map((item, index) => normalizeCanvasNodeV2(item, `${path}.nodes[${index}]`)),
    bindings: expectArray(record.bindings, `${path}.bindings`).map((item, index) => normalizeCanvasBindingV2(item, `${path}.bindings[${index}]`)),
    assets: expectArray(record.assets, `${path}.assets`).map((item, index) => normalizeProjectAssetSummaryV2(item, `${path}.assets[${index}]`)),
    active_style_skill: record.active_style_skill === undefined || record.active_style_skill === null
      ? null
      : normalizeActiveStyleSkillSummaryV2(record.active_style_skill, `${path}.active_style_skill`),
  };
}

export function normalizeAgentCanvasProjectCreateResponseV2(
  value: unknown,
  path = "projectCreate",
): AgentCanvasProjectCreateResponseV2 {
  const record = expectRecord(value, path);
  const workflowPayload = { ...record };
  delete workflowPayload.active_style_skill_run_id;
  delete workflowPayload.guidance_session_id;
  return {
    ...normalizeAgentCanvasWorkflowV2(workflowPayload, path),
    active_style_skill_run_id: expectNonEmptyString(
      record.active_style_skill_run_id,
      `${path}.active_style_skill_run_id`,
    ),
    guidance_session_id: record.guidance_session_id === undefined
      ? null
      : nullableString(record.guidance_session_id, `${path}.guidance_session_id`),
  };
}

export function normalizeAgentExecutionSettingsV2(
  value: unknown,
  path = "agentSettings",
): AgentExecutionSettingsV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    media_execution_mode: (value, fieldPath) => expectLiteral(
      value,
      AGENT_MEDIA_EXECUTION_MODES,
      fieldPath,
    ),
    revision: expectPositiveInteger,
    created_at: expectIsoDateTimeString,
    updated_at: expectIsoDateTimeString,
  } satisfies StrictRecordFieldsFor<AgentExecutionSettingsV2>);
}

function normalizeAgentAnchorV2(value: unknown, path: string): AgentAnchorV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    ["alias", "anchor_type", "display_name", "summary", "source_kind", "source_id", "availability"],
    path,
  );
  const alias = expectNonEmptyString(record.alias, `${path}.alias`);
  if (!/^[A-Z][A-Z0-9]{1,15}$/.test(alias)) fail(`${path}.alias`, "invalid anchor alias");
  return {
    alias,
    anchor_type: expectLiteral(
      record.anchor_type,
      new Set<AgentAnchorV2["anchor_type"]>([
        "subject",
        "environment",
        "world_setting",
        "style",
        "composition",
      ]),
      `${path}.anchor_type`,
    ),
    display_name: expectNonEmptyString(record.display_name, `${path}.display_name`),
    summary: expectNonEmptyString(record.summary, `${path}.summary`),
    source_kind: expectLiteral(
      record.source_kind,
      new Set<AgentAnchorV2["source_kind"]>(["node", "image_asset", "skill_snapshot"]),
      `${path}.source_kind`,
    ),
    source_id: nullableStringWithDefault(record.source_id, `${path}.source_id`),
    availability: expectLiteral(
      record.availability,
      new Set<AgentAnchorV2["availability"]>(["pending", "available", "failed"]),
      `${path}.availability`,
    ),
  };
}

function normalizeAnchorRegistryContentV2(
  value: unknown,
  path: string,
): AnchorRegistryContentV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["anchors"], path);
  const anchors = expectArray(record.anchors ?? [], `${path}.anchors`);
  if (anchors.length > 256) fail(`${path}.anchors`, "expected at most 256 anchors");
  return {
    anchors: anchors.map((item, index) => normalizeAgentAnchorV2(item, `${path}.anchors[${index}]`)),
  };
}

function boundedNumber(
  value: unknown,
  path: string,
  minimum: number,
  maximum: number,
  exclusiveMinimum = false,
): number {
  const result = expectFiniteNumber(value, path);
  if ((exclusiveMinimum ? result <= minimum : result < minimum) || result > maximum) {
    fail(path, `expected value between ${exclusiveMinimum ? "more than " : ""}${minimum} and ${maximum}`);
  }
  return result;
}

function boundedInteger(value: unknown, path: string, minimum: number, maximum: number): number {
  const result = expectInteger(value, path);
  if (result < minimum || result > maximum) fail(path, `expected integer between ${minimum} and ${maximum}`);
  return result;
}

function normalizeStoryboardPlanGlobalParametersV2(
  value: unknown,
  path: string,
): StoryboardPlanGlobalParametersV2 {
  return normalizeStrictRecord(value, path, {
    aspect_ratio: expectNonEmptyString,
    total_duration_seconds: (value, fieldPath) => boundedNumber(
      value,
      fieldPath,
      0,
      3600,
      true,
    ),
    segment_count: (value, fieldPath) => boundedInteger(value, fieldPath, 1, 128),
  } satisfies StrictRecordFieldsFor<StoryboardPlanGlobalParametersV2>);
}

function normalizeStoryboardNarrativeSegmentV2(
  value: unknown,
  path: string,
): StoryboardNarrativeSegmentV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "sequence_id",
    "order",
    "start_seconds",
    "end_seconds",
    "narrative_goal",
    "start_state",
    "end_state",
    "continuity_from_previous",
    "terminal_policy",
  ], path);
  const startSeconds = boundedNumber(record.start_seconds, `${path}.start_seconds`, 0, 3600);
  const endSeconds = boundedNumber(record.end_seconds, `${path}.end_seconds`, 0, 3600, true);
  if (endSeconds <= startSeconds) fail(`${path}.end_seconds`, "expected a value after start_seconds");
  return {
    sequence_id: expectNonEmptyString(record.sequence_id, `${path}.sequence_id`),
    order: boundedInteger(record.order, `${path}.order`, 1, 128),
    start_seconds: startSeconds,
    end_seconds: endSeconds,
    narrative_goal: expectNonEmptyString(record.narrative_goal, `${path}.narrative_goal`),
    start_state: expectNonEmptyString(record.start_state, `${path}.start_state`),
    end_state: expectNonEmptyString(record.end_state, `${path}.end_state`),
    continuity_from_previous: nullableStringWithDefault(
      record.continuity_from_previous,
      `${path}.continuity_from_previous`,
    ),
    terminal_policy: record.terminal_policy === undefined || record.terminal_policy === null
      ? null
      : expectLiteral(
        record.terminal_policy,
        new Set<NonNullable<StoryboardNarrativeSegmentV2["terminal_policy"]>>(["continue", "close"]),
        `${path}.terminal_policy`,
      ),
  };
}

function normalizeStoryboardPlanRowV2(value: unknown, path: string): StoryboardPlanRowV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "shot_index",
    "sequence_id",
    "panel_index",
    "content_beat",
    "anchor_aliases",
    "camera_description",
  ], path);
  const aliases = optionalStringArray(record.anchor_aliases, `${path}.anchor_aliases`, []);
  if (aliases.length > 64) fail(`${path}.anchor_aliases`, "expected at most 64 aliases");
  return {
    shot_index: boundedInteger(record.shot_index, `${path}.shot_index`, 1, 1152),
    sequence_id: expectNonEmptyString(record.sequence_id, `${path}.sequence_id`),
    panel_index: boundedInteger(record.panel_index, `${path}.panel_index`, 1, 9),
    content_beat: expectNonEmptyString(record.content_beat, `${path}.content_beat`),
    anchor_aliases: aliases,
    camera_description: expectNonEmptyString(record.camera_description, `${path}.camera_description`),
  };
}

function normalizeStoryboardNodeRecordV2(value: unknown, path: string): StoryboardNodeRecordV2 {
  return normalizeStrictRecord(value, path, {
    sequence_id: nullableStringWithDefault,
    node_role: (value, fieldPath) => expectLiteral(
      value,
      new Set<StoryboardNodeRecordV2["node_role"]>([
        "storyboard_grid",
        "video_segment",
        "bgm",
        "editing",
      ]),
      fieldPath,
    ),
    node_id: expectNonEmptyString,
  } satisfies StrictRecordFieldsFor<StoryboardNodeRecordV2>);
}

function normalizeStoryboardSegmentMaterializationV2(
  value: unknown,
  path: string,
): StoryboardSegmentMaterializationV2 {
  return normalizeStrictRecord(value, path, {
    sequence_id: expectNonEmptyString,
    status: (value, fieldPath) => value === undefined
      ? "pending"
      : expectLiteral(value, STORYBOARD_SEGMENT_MATERIALIZATION_STATUSES, fieldPath),
    generation_prompt: nullableStringWithDefault,
  } satisfies StrictRecordFieldsFor<StoryboardSegmentMaterializationV2>);
}

function normalizeStoryboardVisualAnchorV2(
  value: unknown,
  path: string,
): StoryboardVisualAnchorV2 {
  return normalizeStrictRecord(value, path, {
    node_id: expectNonEmptyString,
    asset_id: expectNonEmptyString,
    node_revision: expectPositiveInteger,
    document_revision: expectPositiveInteger,
  } satisfies StrictRecordFieldsFor<StoryboardVisualAnchorV2>);
}

function normalizeStoryboardProductionPlanContentV2(
  value: unknown,
  path: string,
): StoryboardProductionPlanContentV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "narrative_outline",
    "global_parameters",
    "segments",
    "rows",
    "node_records",
    "materialized_panel_cursor",
    "segment_materializations",
    "visual_anchor",
  ], path);
  const segments = expectArray(record.segments, `${path}.segments`);
  const rows = expectArray(record.rows, `${path}.rows`);
  const nodeRecords = expectArray(record.node_records ?? [], `${path}.node_records`);
  const segmentMaterializations = expectArray(
    record.segment_materializations ?? [],
    `${path}.segment_materializations`,
  );
  if (segments.length > 128) fail(`${path}.segments`, "expected at most 128 segments");
  if (rows.length > 1152) fail(`${path}.rows`, "expected at most 1152 rows");
  if (nodeRecords.length > 384) fail(`${path}.node_records`, "expected at most 384 records");
  if (segmentMaterializations.length > 128) {
    fail(`${path}.segment_materializations`, "expected at most 128 materializations");
  }
  return {
    narrative_outline: expectNonEmptyString(record.narrative_outline, `${path}.narrative_outline`),
    global_parameters: normalizeStoryboardPlanGlobalParametersV2(
      record.global_parameters,
      `${path}.global_parameters`,
    ),
    segments: segments.map((item, index) => normalizeStoryboardNarrativeSegmentV2(
      item,
      `${path}.segments[${index}]`,
    )),
    rows: rows.map((item, index) => normalizeStoryboardPlanRowV2(item, `${path}.rows[${index}]`)),
    node_records: nodeRecords.map((item, index) => normalizeStoryboardNodeRecordV2(
      item,
      `${path}.node_records[${index}]`,
    )),
    materialized_panel_cursor: record.materialized_panel_cursor === undefined
      ? 0
      : boundedInteger(record.materialized_panel_cursor, `${path}.materialized_panel_cursor`, 0, 1152),
    segment_materializations: segmentMaterializations.map((item, index) => (
      normalizeStoryboardSegmentMaterializationV2(
        item,
        `${path}.segment_materializations[${index}]`,
      )
    )),
    visual_anchor: record.visual_anchor === undefined || record.visual_anchor === null
      ? null
      : normalizeStoryboardVisualAnchorV2(record.visual_anchor, `${path}.visual_anchor`),
  };
}

function normalizeAnchorRegistryContentV3(value: unknown, path: string): AnchorRegistryContentV3 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["schema_version", "anchors"], path);
  if (record.schema_version !== "3") fail(`${path}.schema_version`, "expected 3");
  const anchors = expectArray(record.anchors ?? [], `${path}.anchors`);
  return {
    schema_version: "3",
    anchors: anchors.map((item, index) => normalizeAgentAnchorV3(item, `${path}.anchors[${index}]`)),
  };
}

function normalizeAgentAnchorV3(value: unknown, path: string): AgentAnchorV3 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "alias", "identity_id", "semantic_role", "display_name", "summary", "lifecycle", "source", "role_sources", "acceptance_evidence",
  ], path);
  const source = normalizeAgentAnchorSourceV3(record.source, `${path}.source`);
  const roleSources = expectArray(record.role_sources ?? [], `${path}.role_sources`);
  if (roleSources.length > 8) fail(`${path}.role_sources`, "expected at most 8 role sources");
  const evidence = expectArray(record.acceptance_evidence, `${path}.acceptance_evidence`);
  if (!evidence.length) fail(`${path}.acceptance_evidence`, "expected at least one evidence record");
  return {
    alias: expectNonEmptyString(record.alias, `${path}.alias`),
    identity_id: expectNonEmptyString(record.identity_id, `${path}.identity_id`),
    semantic_role: expectLiteral(record.semantic_role, new Set<AgentAnchorV3["semantic_role"]>([
      "world_setting", "product", "prop", "character", "scene", "style", "composition",
    ]), `${path}.semantic_role`),
    display_name: expectNonEmptyString(record.display_name, `${path}.display_name`),
    summary: expectNonEmptyString(record.summary, `${path}.summary`),
    lifecycle: expectLiteral(record.lifecycle, new Set<AgentAnchorV3["lifecycle"]>([
      "planned", "active", "retired", "invalid",
    ]), `${path}.lifecycle`),
    source,
    role_sources: roleSources.map((item, index) => normalizeAgentAnchorRoleSourceV3(
      item,
      `${path}.role_sources[${index}]`,
    )),
    acceptance_evidence: evidence.map((item, index) => normalizeAnchorAcceptanceEvidenceV1(
      item,
      `${path}.acceptance_evidence[${index}]`,
    )),
  };
}

function normalizeAgentAnchorSourceV3(value: unknown, path: string): AgentAnchorV3["source"] {
  const record = expectRecord(value, path);
  const kind = record.source_kind === undefined ? "" : expectNonEmptyString(record.source_kind, `${path}.source_kind`);
  if (kind === "node") {
    return normalizeAgentAnchorNodeSourceV3(record, path);
  }
  if (kind === "image_asset_version") {
    forbidUnknownFields(record, ["source_kind", "workflow_id", "node_id", "node_revision", "asset_id", "asset_version_id"], path);
    return { source_kind: "image_asset_version", workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`), node_id: expectNonEmptyString(record.node_id, `${path}.node_id`), node_revision: expectPositiveInteger(record.node_revision, `${path}.node_revision`), asset_id: expectNonEmptyString(record.asset_id, `${path}.asset_id`), asset_version_id: expectNonEmptyString(record.asset_version_id, `${path}.asset_version_id`) };
  }
  if (kind === "skill_snapshot") {
    forbidUnknownFields(record, ["source_kind", "skill_id", "skill_version", "package_digest"], path);
    return { source_kind: "skill_snapshot", skill_id: expectNonEmptyString(record.skill_id, `${path}.skill_id`), skill_version: expectNonEmptyString(record.skill_version, `${path}.skill_version`), package_digest: nullableDigest(record.package_digest, `${path}.package_digest`) ?? (() => { fail(`${path}.package_digest`, "expected digest"); })() };
  }
  fail(`${path}.source_kind`, "expected node, image_asset_version, or skill_snapshot");
}

function normalizeAgentAnchorNodeSourceV3(
  value: unknown,
  path: string,
): AgentAnchorNodeSourceV3 {
  return normalizeStrictRecord(value, path, {
    source_kind: (value, fieldPath) => expectLiteral(value, new Set(["node"]), fieldPath),
    workflow_id: expectNonEmptyString,
    node_id: expectNonEmptyString,
    node_revision: expectPositiveInteger,
  } satisfies StrictRecordFieldsFor<AgentAnchorNodeSourceV3>);
}

function normalizeAgentAnchorRoleSourceV3(
  value: unknown,
  path: string,
): AgentAnchorRoleSourceV3 {
  return normalizeStrictRecord(value, path, {
    role: (value, fieldPath) => expectLiteral(value, new Set<AgentAnchorRoleSourceV3["role"]>([
      "product_main",
      "product_multiview",
      "character_main",
      "character_turnaround",
    ]), fieldPath),
    source: normalizeAgentAnchorNodeSourceV3,
  } satisfies StrictRecordFieldsFor<AgentAnchorRoleSourceV3>);
}

function normalizeAnchorAcceptanceEvidenceV1(value: unknown, path: string): AnchorAcceptanceEvidenceV1 {
  return normalizeStrictRecord(value, path, {
    evidence_id: expectNonEmptyString,
    actor: (value, fieldPath) => expectLiteral(value, new Set<AnchorAcceptanceEvidenceV1["actor"]>(["user", "agent", "system"]), fieldPath),
    decision: (value, fieldPath) => expectLiteral(value, new Set<AnchorAcceptanceEvidenceV1["decision"]>(["accepted", "delegated", "activated", "retired", "invalidated"]), fieldPath),
    action_id: expectNonEmptyString,
    requirement_revision_id: expectNonEmptyString,
    requirement_revision_no: expectPositiveInteger,
    node_revision: (value, fieldPath) => value === null || value === undefined ? null : expectPositiveInteger(value, fieldPath),
    asset_version_id: nullableStringWithDefault,
    document_revision: expectPositiveInteger,
    recorded_at: expectIsoDateTimeString,
  } satisfies StrictRecordFieldsFor<AnchorAcceptanceEvidenceV1>);
}

function normalizeStoryboardProductionPlanContentV3(value: unknown, path: string): StoryboardProductionPlanContentV3 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["schema_version", "narrative_outline", "creative_direction_snapshot_id", "requirement_revision_id", "requirement_revision_no", "global_parameters", "segments", "rows", "segment_materializations", "planned_nodes", "excluded_media", "visual_anchor"], path);
  if (record.schema_version !== undefined && record.schema_version !== "3") fail(`${path}.schema_version`, "expected 3");
  return {
    schema_version: "3",
    creative_direction_snapshot_id: normalizeNullableBoundedString(
      record.creative_direction_snapshot_id,
      `${path}.creative_direction_snapshot_id`,
      1,
      160,
    ),
    narrative_outline: expectNonEmptyString(record.narrative_outline, `${path}.narrative_outline`),
    requirement_revision_id: expectNonEmptyString(record.requirement_revision_id, `${path}.requirement_revision_id`),
    requirement_revision_no: expectPositiveInteger(record.requirement_revision_no, `${path}.requirement_revision_no`),
    global_parameters: normalizeStoryboardPlanGlobalParametersV2(record.global_parameters, `${path}.global_parameters`),
    segments: expectArray(record.segments, `${path}.segments`).map((item, index) => normalizeStoryboardNarrativeSegmentV2(item, `${path}.segments[${index}]`)),
    rows: expectArray(record.rows, `${path}.rows`).map((item, index) => normalizeStoryboardPlanRowV2(item, `${path}.rows[${index}]`)),
    segment_materializations: expectArray(
      record.segment_materializations ?? [],
      `${path}.segment_materializations`,
    ).map((item, index) => normalizeStoryboardSegmentMaterializationV3(
      item,
      `${path}.segment_materializations[${index}]`,
    )),
    planned_nodes: expectArray(record.planned_nodes ?? [], `${path}.planned_nodes`).map((item, index) => normalizeStoryboardPlannedNodeV3(item, `${path}.planned_nodes[${index}]`)),
    excluded_media: expectArray(record.excluded_media ?? [], `${path}.excluded_media`).map((item, index) => normalizeStoryboardExcludedMediaV3(item, `${path}.excluded_media[${index}]`)),
    visual_anchor: record.visual_anchor === null || record.visual_anchor === undefined ? null : normalizeStoryboardVisualAnchorV3(record.visual_anchor, `${path}.visual_anchor`),
  };
}

function normalizeStoryboardSegmentMaterializationV3(
  value: unknown,
  path: string,
): StoryboardSegmentMaterializationV3 {
  return normalizeStrictRecord(value, path, {
    sequence_id: expectNonEmptyString,
    materialization_id: expectNonEmptyString,
    status: (value, fieldPath) => value === undefined
      ? "pending"
      : expectLiteral(
        value,
        STORYBOARD_SEGMENT_MATERIALIZATION_STATUSES,
        fieldPath,
      ),
    generation_prompt: nullableStringWithDefault,
  } satisfies StrictRecordFieldsFor<StoryboardSegmentMaterializationV3>);
}

function normalizeStoryboardPlannedNodeV3(value: unknown, path: string): StoryboardPlannedNodeV3 {
  return normalizeStrictRecord(value, path, {
    sequence_id: nullableStringWithDefault,
    node_role: (value, fieldPath) => expectLiteral(value, new Set<StoryboardPlannedNodeV3["node_role"]>(["storyboard_grid", "video_segment", "bgm", "editing"]), fieldPath),
    node_id: expectNonEmptyString,
    node_revision: expectPositiveInteger,
    materialization_id: expectNonEmptyString,
  } satisfies StrictRecordFieldsFor<StoryboardPlannedNodeV3>);
}

function normalizeStoryboardExcludedMediaV3(value: unknown, path: string): StoryboardExcludedMediaV3 {
  return normalizeStrictRecord(value, path, {
    sequence_id: nullableStringWithDefault,
    node_role: (value, fieldPath) => expectLiteral(value, new Set<StoryboardExcludedMediaV3["node_role"]>(["video_segment", "bgm"]), fieldPath),
    node_id: expectNonEmptyString,
    node_revision: expectPositiveInteger,
    action_id: expectNonEmptyString,
  } satisfies StrictRecordFieldsFor<StoryboardExcludedMediaV3>);
}

function normalizeStoryboardVisualAnchorV3(value: unknown, path: string): StoryboardVisualAnchorV3 {
  return normalizeStrictRecord(value, path, {
    sequence_id: expectNonEmptyString,
    node_id: expectNonEmptyString,
    node_revision: expectPositiveInteger,
    asset_id: expectNonEmptyString,
    asset_version_id: expectNonEmptyString,
    acceptance_evidence_id: expectNonEmptyString,
  } satisfies StrictRecordFieldsFor<StoryboardVisualAnchorV3>);
}

function normalizeAgentDocumentLinkedNodeRuntimeV2(
  value: unknown,
  path: string,
): AgentDocumentLinkedNodeRuntimeV2 {
  return normalizeStrictRecord(value, path, {
    node_id: expectNonEmptyString,
    node_type: (value, fieldPath) => expectLiteral(value, CANVAS_NODE_TYPES, fieldPath),
    creative_role: expectNonEmptyString,
    status: (value, fieldPath) => expectLiteral(value, CANVAS_NODE_STATUSES, fieldPath),
    revision: expectPositiveInteger,
  } satisfies StrictRecordFieldsFor<AgentDocumentLinkedNodeRuntimeV2>);
}

export function normalizeAgentWorkingDocumentV2(
  value: unknown,
  path = "agentDocument",
): AgentWorkingDocumentV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "document_id",
    "workflow_id",
    "guidance_session_id",
    "kind",
    "title",
    "revision",
    "content_schema_version",
    "content_digest",
    "content",
    "created_by_agent_run_id",
    "updated_by_agent_run_id",
    "linked_nodes",
    "created_at",
    "updated_at",
  ], path);
  const kind = expectLiteral(record.kind, AGENT_WORKING_DOCUMENT_KINDS, `${path}.kind`);
  const digest = expectNonEmptyString(record.content_digest, `${path}.content_digest`);
  const contentSchemaVersion: 2 | 3 = record.content_schema_version === undefined
    ? 2
    : record.content_schema_version === 2 || record.content_schema_version === 3
      ? record.content_schema_version
      : fail(`${path}.content_schema_version`, "expected 2 or 3");
  if (!/^sha256:[0-9a-zA-Z_-]+$/.test(digest)) fail(`${path}.content_digest`, "invalid digest");
  const base = {
    document_id: expectNonEmptyString(record.document_id, `${path}.document_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    guidance_session_id: expectNonEmptyString(record.guidance_session_id, `${path}.guidance_session_id`),
    title: expectNonEmptyString(record.title, `${path}.title`),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    content_schema_version: contentSchemaVersion,
    content_digest: digest,
    created_by_agent_run_id: expectNonEmptyString(
      record.created_by_agent_run_id,
      `${path}.created_by_agent_run_id`,
    ),
    updated_by_agent_run_id: expectNonEmptyString(
      record.updated_by_agent_run_id,
      `${path}.updated_by_agent_run_id`,
    ),
    linked_nodes: expectArray(record.linked_nodes ?? [], `${path}.linked_nodes`).map((item, index) => (
      normalizeAgentDocumentLinkedNodeRuntimeV2(item, `${path}.linked_nodes[${index}]`)
    )),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
  return kind === "anchor_registry"
    ? {
        ...base,
        kind,
        content: base.content_schema_version === 3
          ? normalizeAnchorRegistryContentV3(record.content, `${path}.content`)
          : normalizeAnchorRegistryContentV2(record.content, `${path}.content`),
      }
    : {
        ...base,
        kind,
        content: base.content_schema_version === 3
          ? normalizeStoryboardProductionPlanContentV3(record.content, `${path}.content`)
          : normalizeStoryboardProductionPlanContentV2(record.content, `${path}.content`),
      };
}

export function normalizeAgentWorkingDocumentPageV2(
  value: unknown,
  path = "agentDocuments",
): AgentWorkingDocumentPageV2 {
  return normalizeStrictRecord(value, path, {
    items: (value, fieldPath) => expectArray(value ?? [], fieldPath).map((item, index) => (
      normalizeAgentWorkingDocumentV2(item, `${fieldPath}[${index}]`)
    )),
    next_cursor: nullableStringWithDefault,
  } satisfies StrictRecordFieldsFor<AgentWorkingDocumentPageV2>);
}

function normalizeCanvasConnectionRoleRuleV2(
  value: unknown,
  path: string,
): CanvasConnectionRoleRuleV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    ["source_node_type", "target_node_type", "roles", "default_role"],
    path,
  );
  const roles = expectArray(record.roles, `${path}.roles`).map((item, index) =>
    expectLiteral(item, CANVAS_BINDING_ROLES, `${path}.roles[${index}]`),
  );
  if (!roles.length) fail(`${path}.roles`, "expected at least one role");
  const defaultRole = expectLiteral(record.default_role, CANVAS_BINDING_ROLES, `${path}.default_role`);
  if (!roles.includes(defaultRole)) fail(`${path}.default_role`, "expected one of roles");
  return {
    source_node_type: expectLiteral(record.source_node_type, CANVAS_NODE_TYPES, `${path}.source_node_type`),
    target_node_type: expectLiteral(record.target_node_type, CANVAS_NODE_TYPES, `${path}.target_node_type`),
    roles,
    default_role: defaultRole,
  };
}

function normalizeNodeTypeMap(
  value: unknown,
  path: string,
): Record<CanvasNodeTypeV2, CanvasNodeTypeV2[]> {
  const record = expectRecord(value, path);
  const result = {} as Record<CanvasNodeTypeV2, CanvasNodeTypeV2[]>;
  for (const nodeType of CANVAS_NODE_TYPES) {
    result[nodeType] = expectArray(record[nodeType], `${path}.${nodeType}`).map((item, index) =>
      expectLiteral(item, CANVAS_NODE_TYPES, `${path}.${nodeType}[${index}]`),
    );
  }
  forbidUnknownFields(record, Array.from(CANVAS_NODE_TYPES), path);
  return result;
}

export function normalizeCanvasConnectionPolicyV2(
  value: unknown,
  path = "connectionPolicy",
): CanvasConnectionPolicyV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "policy_version",
      "target_node_types",
      "input_roles",
      "image_asset_targets",
      "binding_kind_by_source_type",
      "model_validation",
    ],
    path,
  );
  const imageAssetTargetsRecord = expectRecord(record.image_asset_targets, `${path}.image_asset_targets`);
  const imageAssetTargets: CanvasConnectionPolicyV2["image_asset_targets"] = {};
  for (const [key, rawRoles] of Object.entries(imageAssetTargetsRecord)) {
    const nodeType = expectLiteral(key, CANVAS_NODE_TYPES, `${path}.image_asset_targets.${key}`);
    imageAssetTargets[nodeType] = expectArray(rawRoles, `${path}.image_asset_targets.${key}`)
      .map((item, index) => expectLiteral(item, CANVAS_BINDING_ROLES, `${path}.image_asset_targets.${key}[${index}]`));
  }
  const bindingKindRecord = expectRecord(
    record.binding_kind_by_source_type,
    `${path}.binding_kind_by_source_type`,
  );
  const bindingKindBySourceType = {} as CanvasConnectionPolicyV2["binding_kind_by_source_type"];
  for (const nodeType of CANVAS_NODE_TYPES) {
    bindingKindBySourceType[nodeType] = expectLiteral(
      bindingKindRecord[nodeType],
      CANVAS_BINDING_ROLES,
      `${path}.binding_kind_by_source_type.${nodeType}`,
    );
  }
  forbidUnknownFields(bindingKindRecord, Array.from(CANVAS_NODE_TYPES), `${path}.binding_kind_by_source_type`);
  const modelValidationRecord = expectRecord(record.model_validation, `${path}.model_validation`);
  const modelValidation = Object.fromEntries(
    Object.entries(modelValidationRecord).map(([key, item]) => [
      key,
      expectString(item, `${path}.model_validation.${key}`),
    ]),
  );
  return {
    policy_version: expectLiteral(
      record.policy_version,
      new Set<CanvasConnectionPolicyV2["policy_version"]>(["agent_canvas_connection_policy_v1"]),
      `${path}.policy_version`,
    ),
    target_node_types: normalizeNodeTypeMap(record.target_node_types, `${path}.target_node_types`),
    input_roles: expectArray(record.input_roles, `${path}.input_roles`)
      .map((item, index) => normalizeCanvasConnectionRoleRuleV2(item, `${path}.input_roles[${index}]`)),
    image_asset_targets: imageAssetTargets,
    binding_kind_by_source_type: bindingKindBySourceType,
    model_validation: modelValidation,
  };
}

export function normalizeCanvasConnectedNodeCreateResponseV2(
  value: unknown,
  path = "connectedNode",
): CanvasConnectedNodeCreateResponseV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    revision: expectPositiveInteger,
    layout_revision: expectPositiveInteger,
    node: normalizeCanvasNodeV2,
    binding: normalizeCanvasBindingV2,
    events_cursor: expectNonNegativeInteger,
  } satisfies StrictRecordFieldsFor<CanvasConnectedNodeCreateResponseV2>);
}

export function normalizeCanvasBindingMutationResponseV2(
  value: unknown,
  path = "bindingMutation",
): CanvasBindingMutationResponseV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    revision: expectPositiveInteger,
    binding: normalizeCanvasBindingV2,
    incoming_bindings: (value, fieldPath) => expectArray(value, fieldPath)
      .map((item, index) => normalizeCanvasBindingV2(item, `${fieldPath}[${index}]`)),
    events_cursor: expectNonNegativeInteger,
  } satisfies StrictRecordFieldsFor<CanvasBindingMutationResponseV2>);
}

export function normalizeResolvedTextInputSnapshotV2(value: unknown, path = "resolvedInput"): ResolvedTextInputSnapshotV2 {
  return normalizeStrictRecord(value, path, {
    snapshot_type: (value, fieldPath) => expectLiteral(value, new Set<ResolvedTextInputSnapshotV2["snapshot_type"]>(["text"]), fieldPath),
    source_kind: (value, fieldPath) => expectLiteral(value, new Set<ResolvedTextInputSnapshotV2["source_kind"]>(["node_output"]), fieldPath),
    source_node_id: expectNonEmptyString,
    source_node_revision: expectPositiveInteger,
    binding_kind: (value, fieldPath) => expectLiteral(value, RESOLVED_TEXT_BINDING_KINDS, fieldPath),
    document_kind: (value, fieldPath) => expectLiteral(value, RESOLVED_DOCUMENT_KINDS, fieldPath),
    content: expectString,
    content_hash: expectNonEmptyString,
    binding_id: nullableString,
    input_role: (value, fieldPath) => expectLiteral(
      value,
      new Set<ResolvedTextInputSnapshotV2["input_role"]>(["text_context"]),
      fieldPath,
    ),
    display_order: expectNonNegativeInteger,
  } satisfies StrictRecordFieldsFor<ResolvedTextInputSnapshotV2>);
}

export function normalizeStorageAccessDescriptorV2(
  value: unknown,
  path = "accessDescriptor",
): StorageAccessDescriptorV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["descriptor_type", "asset_id", "media_url", "checksum"], path);
  if (record.descriptor_type !== "asset_content") {
    fail(`${path}.descriptor_type`, "expected asset_content");
  }
  return {
    descriptor_type: "asset_content",
    asset_id: expectNonEmptyString(record.asset_id, `${path}.asset_id`),
    media_url: nullableBrowserSafeUrl(record.media_url, `${path}.media_url`)
      ?? fail(`${path}.media_url`, "expected URL"),
    checksum: expectNonEmptyString(record.checksum, `${path}.checksum`),
  };
}

export function normalizeResolvedMediaInputSnapshotV2(value: unknown, path = "resolvedInput"): ResolvedMediaInputSnapshotV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "snapshot_type",
      "source_kind",
      "source_node_id",
      "source_node_revision",
      "binding_kind",
      "source_semantic_role",
      "asset_id",
      "media_type",
      "asset_checksum",
      "access_descriptor",
      "binding_id",
      "input_role",
      "display_order",
    ],
    path,
  );
  const sourceKind = expectLiteral(
    record.source_kind,
    new Set<ResolvedMediaInputSnapshotV2["source_kind"]>(["node_output", "image_asset"]),
    `${path}.source_kind`,
  );
  const sourceNodeId = nullableString(record.source_node_id, `${path}.source_node_id`);
  const sourceNodeRevision = record.source_node_revision === null
    ? null
    : expectPositiveInteger(record.source_node_revision, `${path}.source_node_revision`);
  if (sourceKind === "node_output" && (!sourceNodeId || sourceNodeRevision === null)) {
    fail(path, "node media source requires node identity");
  }
  if (sourceKind === "image_asset" && (sourceNodeId !== null || sourceNodeRevision !== null)) {
    fail(path, "image asset media source cannot include node identity");
  }
  return {
    snapshot_type: expectLiteral(record.snapshot_type, new Set<ResolvedMediaInputSnapshotV2["snapshot_type"]>(["media"]), `${path}.snapshot_type`),
    source_kind: sourceKind,
    source_node_id: sourceNodeId,
    source_node_revision: sourceNodeRevision,
    binding_kind: expectLiteral(record.binding_kind, RESOLVED_MEDIA_BINDING_KINDS, `${path}.binding_kind`),
    source_semantic_role: nullableString(record.source_semantic_role, `${path}.source_semantic_role`),
    asset_id: expectNonEmptyString(record.asset_id, `${path}.asset_id`),
    media_type: expectLiteral(record.media_type, ASSET_MEDIA_TYPES, `${path}.media_type`),
    asset_checksum: expectNonEmptyString(record.asset_checksum, `${path}.asset_checksum`),
    access_descriptor: normalizeStorageAccessDescriptorV2(record.access_descriptor, `${path}.access_descriptor`),
    binding_id: nullableString(record.binding_id, `${path}.binding_id`),
    input_role: expectLiteral(record.input_role, CANVAS_BINDING_ROLES, `${path}.input_role`),
    display_order: expectNonNegativeInteger(record.display_order, `${path}.display_order`),
  };
}

export function normalizeResolvedInputSnapshotV2(value: unknown, path = "resolvedInput"): ResolvedInputSnapshotV2 {
  const record = expectRecord(value, path);
  const snapshotType = expectString(record.snapshot_type, `${path}.snapshot_type`);
  if (snapshotType === "text") return normalizeResolvedTextInputSnapshotV2(record, path);
  if (snapshotType === "media") return normalizeResolvedMediaInputSnapshotV2(record, path);
  fail(`${path}.snapshot_type`, "unsupported discriminator");
}

function normalizeVideoParameterNormalizationV2(
  value: unknown,
  path: string,
): VideoParameterNormalizationV2 {
  return normalizeStrictRecord(value, path, {
    field: (value, fieldPath) => expectLiteral(
      value,
      new Set<VideoParameterNormalizationV2["field"]>([
        "duration_seconds",
        "resolution",
        "aspect_ratio",
        "generate_audio",
      ]),
      fieldPath,
    ),
    requested_value: normalizeCanvasParameterScalarV2,
    effective_value: normalizeCanvasParameterScalarV2,
    normalization_code: (value, fieldPath) => expectLiteral(
      value,
      new Set<VideoParameterNormalizationV2["normalization_code"]>([
        "duration_clamped_to_minimum",
        "duration_clamped_to_maximum",
        "resolution_reduced_to_supported",
      ]),
      fieldPath,
    ),
  } satisfies StrictRecordFieldsFor<VideoParameterNormalizationV2>);
}

export function normalizeNodeRuntimeV2(value: unknown, path = "runtime.node_runtime"): NodeRuntimeV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "node_id",
      "visible_status",
      "phase",
      "execution_id",
      "provider_task_id",
      "run_intent_snapshot_id",
      "parameter_compilation_snapshot_id",
      "input_manifest_id",
      "effective_parameters",
      "normalizations",
      "omitted_optional_inputs",
      "waiting_reason",
      "missing_required_source_node_ids",
      "waiting_for_node_ids",
      "blocked_by_node_ids",
      "attempt_no",
      "updated_at",
      "error",
    ],
    path,
  );
  const phase = optionalNullableLiteral(record.phase, NODE_RUNTIME_PHASES, `${path}.phase`);
  return {
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    visible_status: expectLiteral(record.visible_status, CANVAS_NODE_STATUSES, `${path}.visible_status`),
    phase: phase ?? null,
    execution_id: nullableString(record.execution_id, `${path}.execution_id`),
    provider_task_id: nullableString(record.provider_task_id, `${path}.provider_task_id`),
    run_intent_snapshot_id: nullableStringWithDefault(record.run_intent_snapshot_id, `${path}.run_intent_snapshot_id`),
    parameter_compilation_snapshot_id: nullableStringWithDefault(
      record.parameter_compilation_snapshot_id,
      `${path}.parameter_compilation_snapshot_id`,
    ),
    input_manifest_id: nullableStringWithDefault(record.input_manifest_id, `${path}.input_manifest_id`),
    effective_parameters: optionalUnknownRecord(record.effective_parameters, `${path}.effective_parameters`),
    normalizations: expectArray(record.normalizations ?? [], `${path}.normalizations`).map((item, index) => (
      typeof item === "string"
        ? item
        : normalizeVideoParameterNormalizationV2(item, `${path}.normalizations[${index}]`)
    )),
    omitted_optional_inputs: expectArray(record.omitted_optional_inputs ?? [], `${path}.omitted_optional_inputs`).map(
      (item, index) => expectRecordValue(item, `${path}.omitted_optional_inputs[${index}]`),
    ),
    waiting_reason: nullableStringWithDefault(record.waiting_reason, `${path}.waiting_reason`),
    missing_required_source_node_ids: optionalStringArray(
      record.missing_required_source_node_ids,
      `${path}.missing_required_source_node_ids`,
      [],
    ),
    waiting_for_node_ids: optionalStringArray(record.waiting_for_node_ids, `${path}.waiting_for_node_ids`, []),
    blocked_by_node_ids: optionalStringArray(record.blocked_by_node_ids, `${path}.blocked_by_node_ids`, []),
    attempt_no: expectNonNegativeInteger(record.attempt_no, `${path}.attempt_no`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
    error: record.error === null ? null : normalizeCanvasNodeErrorV2(record.error, `${path}.error`),
  };
}

export function normalizeCanvasRuntimeSnapshotV2(value: unknown, path = "runtime"): CanvasRuntimeSnapshotV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "workflow_id",
      "active_execution_id",
      "execution_status",
      "node_runtime",
      "queued_node_ids",
      "working_node_ids",
      "waiting_node_ids",
      "ready_node_ids",
      "failed_node_ids",
      "events_cursor",
      "updated_at",
    ],
    path,
  );
  const runtimeRecord = expectRecord(record.node_runtime, `${path}.node_runtime`);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    active_execution_id: nullableString(record.active_execution_id, `${path}.active_execution_id`),
    execution_status: optionalNullableLiteral(record.execution_status, CANVAS_EXECUTION_STATUSES, `${path}.execution_status`) ?? null,
    node_runtime: Object.fromEntries(
      Object.entries(runtimeRecord).map(([key, item]) => [key, normalizeNodeRuntimeV2(item, `${path}.node_runtime.${key}`)]),
    ),
    queued_node_ids: expectStringArray(record.queued_node_ids, `${path}.queued_node_ids`),
    working_node_ids: expectStringArray(record.working_node_ids, `${path}.working_node_ids`),
    waiting_node_ids: expectStringArray(record.waiting_node_ids, `${path}.waiting_node_ids`),
    ready_node_ids: expectStringArray(record.ready_node_ids, `${path}.ready_node_ids`),
    failed_node_ids: expectStringArray(record.failed_node_ids, `${path}.failed_node_ids`),
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function normalizeCanvasPostReadyEffectSummaryV2(
  value: unknown,
  path: string,
): CanvasPostReadyEffectSummaryV2 {
  return normalizeStrictRecord(value, path, {
    effect_id: expectNonEmptyString,
    effect_type: (value, fieldPath) => expectLiteral(value, CANVAS_POST_READY_EFFECT_TYPES, fieldPath),
    node_id: expectNonEmptyString,
    status: (value, fieldPath) => expectLiteral(value, CANVAS_POST_READY_EFFECT_STATUSES, fieldPath),
    attempt_no: expectNonNegativeInteger,
    error: (value, fieldPath) => value === null ? null : normalizeCanvasNodeErrorV2(value, fieldPath),
    updated_at: expectIsoDateTimeString,
  } satisfies StrictRecordFieldsFor<CanvasPostReadyEffectSummaryV2>);
}

export function normalizeCanvasPostReadyCheckpointV2(
  value: unknown,
  path = "postReadyCheckpoint",
): CanvasPostReadyCheckpointV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "checkpoint_id",
    "workflow_id",
    "execution_id",
    "execution_status",
    "status",
    "counts",
    "effects",
    "error",
    "updated_at",
  ], path);
  const counts = expectRecord(record.counts, `${path}.counts`);
  forbidUnknownFields(counts, ["total", "queued", "running", "completed", "failed"], `${path}.counts`);
  const normalizedCounts = {
    total: expectNonNegativeInteger(counts.total, `${path}.counts.total`),
    queued: expectNonNegativeInteger(counts.queued, `${path}.counts.queued`),
    running: expectNonNegativeInteger(counts.running, `${path}.counts.running`),
    completed: expectNonNegativeInteger(counts.completed, `${path}.counts.completed`),
    failed: expectNonNegativeInteger(counts.failed, `${path}.counts.failed`),
  };
  if (
    normalizedCounts.queued
    + normalizedCounts.running
    + normalizedCounts.completed
    + normalizedCounts.failed
    !== normalizedCounts.total
  ) {
    fail(`${path}.counts`, "effect counts must sum to total");
  }
  return {
    checkpoint_id: expectNonEmptyString(record.checkpoint_id, `${path}.checkpoint_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    execution_id: expectNonEmptyString(record.execution_id, `${path}.execution_id`),
    execution_status: expectLiteral(record.execution_status, CANVAS_EXECUTION_STATUSES, `${path}.execution_status`),
    status: expectLiteral(record.status, CANVAS_POST_READY_CHECKPOINT_STATUSES, `${path}.status`),
    counts: normalizedCounts,
    effects: expectArray(record.effects, `${path}.effects`).map((effect, index) => (
      normalizeCanvasPostReadyEffectSummaryV2(effect, `${path}.effects[${index}]`)
    )),
    error: record.error === null ? null : normalizeCanvasNodeErrorV2(record.error, `${path}.error`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

export function normalizeCanvasRuntimeEventV2(value: unknown, path = "event"): CanvasRuntimeEventV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "sequence_no",
      "workflow_id",
      "event_type",
      "project_id",
      "execution_id",
      "node_id",
      "asset_id",
      "binding_id",
      "conversation_id",
      "turn_id",
      "action_id",
      "trace_id",
      "span_id",
      "transition_key",
      "attempt",
      "created_at",
      "payload",
    ],
    path,
  );
  return {
    seq: expectNonNegativeInteger(record.sequence_no, `${path}.sequence_no`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    event_type: expectNonEmptyString(record.event_type, `${path}.event_type`),
    project_id: record.project_id === undefined ? null : nullableString(record.project_id, `${path}.project_id`),
    execution_id: record.execution_id === undefined ? null : nullableString(record.execution_id, `${path}.execution_id`),
    node_id: record.node_id === undefined ? null : nullableString(record.node_id, `${path}.node_id`),
    asset_id: record.asset_id === undefined ? null : nullableString(record.asset_id, `${path}.asset_id`),
    binding_id: record.binding_id === undefined ? null : nullableString(record.binding_id, `${path}.binding_id`),
    conversation_id: record.conversation_id === undefined
      ? null
      : nullableString(record.conversation_id, `${path}.conversation_id`),
    turn_id: record.turn_id === undefined ? null : nullableString(record.turn_id, `${path}.turn_id`),
    action_id: record.action_id === undefined ? null : nullableString(record.action_id, `${path}.action_id`),
    trace_id: record.trace_id === undefined ? null : nullableString(record.trace_id, `${path}.trace_id`),
    span_id: record.span_id === undefined ? null : nullableString(record.span_id, `${path}.span_id`),
    transition_key: nullableStringWithDefault(record.transition_key, `${path}.transition_key`),
    attempt: record.attempt === undefined || record.attempt === null
      ? null
      : expectNonNegativeInteger(record.attempt, `${path}.attempt`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    payload: record.payload === null || record.payload === undefined
      ? null
      : expectRecordValue(record.payload, `${path}.payload`),
  };
}

function normalizeProviderReferenceLimits(
  value: unknown,
  path: string,
): ProviderModelCapabilityV2["reference_limits"] {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["image", "video", "audio"], path);
  return Object.fromEntries(
    Object.entries(record).map(([mediaType, limit]) => [
      mediaType,
      expectNonNegativeInteger(limit, `${path}.${mediaType}`),
    ]),
  ) as ProviderModelCapabilityV2["reference_limits"];
}

export function normalizeProviderModelCapabilityV2(value: unknown, path = "capability"): ProviderModelCapabilityV2 {
  return normalizeStrictRecord(value, path, {
    provider: expectNonEmptyString,
    model_id: expectNonEmptyString,
    output_type: (value, fieldPath) => expectLiteral(value, PROVIDER_OUTPUT_TYPES, fieldPath),
    accepted_input_types: (value, fieldPath) => expectArray(value, fieldPath).map((item, index) =>
      expectLiteral(item, PROVIDER_INPUT_TYPES, `${fieldPath}[${index}]`),
    ),
    max_references: expectNonNegativeInteger,
    reference_limits: normalizeProviderReferenceLimits,
    supported_parameters: expectStringArray,
    default_parameters: (value, fieldPath) => optionalUnknownRecord(value, fieldPath, {}),
    supported_resolutions: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    supported_aspect_ratios: expectStringArray,
    duration_range_seconds: (value, fieldPath) => value === null ? null : expectTuple2Number(value, fieldPath),
    pixel_bounds: (value, fieldPath) => value === null ? null : expectTuple2Number(value, fieldPath, true),
    available: expectBoolean,
    unavailable_reason: nullableString,
    supports_native_audio: (value, fieldPath) => value === undefined
      ? false
      : expectBoolean(value, fieldPath),
    capability_revision: (value, fieldPath) => expectPositiveInteger(value ?? 1, fieldPath),
  } satisfies StrictRecordFieldsFor<ProviderModelCapabilityV2>);
}

export function normalizeProviderModelCapabilityListV2(value: unknown, path = "capabilities"): ProviderModelCapabilityListV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["items"], path);
  const items = expectArray(record.items, `${path}.items`);
  return items.map((item, index) => normalizeProviderModelCapabilityV2(item, `${path}[${index}]`));
}

export function normalizeBindingCapabilityDecisionV2(value: unknown, path = "bindingCapabilityDecision"): BindingCapabilityDecisionV2 {
  return normalizeStrictRecord(value, path, {
    accepted: expectBoolean,
    target_node_id: expectNonEmptyString,
    selected_model_id: nullableString,
    required_input_types: (value, fieldPath) => expectArray(value, fieldPath).map((item, index) =>
      expectLiteral(item, PROVIDER_INPUT_TYPES, `${fieldPath}[${index}]`),
    ),
    compatible_model_ids: expectStringArray,
    switch_model_required: expectBoolean,
  } satisfies StrictRecordFieldsFor<BindingCapabilityDecisionV2>);
}

function normalizeCapabilityProposalOptionV2(
  value: unknown,
  path: string,
): CapabilityProposalOptionV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["option_id", "title", "public_summary", "key_decisions"], path);
  const keyDecisions = record.key_decisions === undefined
    ? []
    : expectArray(record.key_decisions, `${path}.key_decisions`).map((item, index) => (
      expectNonEmptyString(item, `${path}.key_decisions[${index}]`)
    ));
  if (keyDecisions.length > 6) {
    fail(`${path}.key_decisions`, "expected between 0 and 6 decisions");
  }
  return {
    option_id: expectNonEmptyString(record.option_id, `${path}.option_id`),
    title: expectNonEmptyString(record.title, `${path}.title`),
    public_summary: expectNonEmptyString(record.public_summary, `${path}.public_summary`),
    key_decisions: keyDecisions,
  };
}

export function normalizeProposalMaterializationErrorV2(
  value: unknown,
  path: string,
): ProposalMaterializationErrorV2 {
  return normalizeStrictRecord(value, path, {
    code: expectNonEmptyString,
    message: expectNonEmptyString,
    actionable_failure: (value, fieldPath) => nullableActionableFailureV1(
      value,
      fieldPath,
    ),
  } satisfies StrictRecordFieldsFor<ProposalMaterializationErrorV2>);
}

function normalizeProposalMaterializationProjectionV2(
  value: unknown,
  path: string,
): ProposalMaterializationProjectionV2 {
  return normalizeStrictRecord(value, path, {
    materialization_id: expectNonEmptyString,
    option_id: expectNonEmptyString,
    turn_id: expectNonEmptyString,
    status: (value, fieldPath) => expectLiteral(
      value,
      new Set<ProposalMaterializationProjectionV2["status"]>(["queued", "working", "failed", "completed"]),
      fieldPath,
    ),
    attempt_no: expectPositiveInteger,
    retryable: expectBoolean,
    error: (value, fieldPath) => value === null
      ? null
      : normalizeProposalMaterializationErrorV2(value, fieldPath),
    created_at: expectIsoDateTimeString,
    updated_at: expectIsoDateTimeString,
  } satisfies StrictRecordFieldsFor<ProposalMaterializationProjectionV2>);
}

function normalizeProposedDraftReferenceV2(
  value: unknown,
  path: string,
): ProposedDraftReferenceV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "source_kind",
      "source_id",
      "binding_kind",
      "input_role",
      "required",
      "display_order",
      "semantic_reference_role",
      "occurrence_id",
      "character_phase",
      "display_name",
      "media_type",
    ],
    path,
  );
  const occurrenceId = nullableStringWithDefault(record.occurrence_id, `${path}.occurrence_id`);
  const characterPhase = record.character_phase === undefined || record.character_phase === null
    ? null
    : expectLiteral(
        record.character_phase,
        new Set(["main", "turnaround"] as const),
        `${path}.character_phase`,
      );
  if ((occurrenceId === null) !== (characterPhase === null)) {
    fail(path, "Character reference identity requires occurrence and phase");
  }
  return {
    source_kind: expectLiteral(
      record.source_kind,
      new Set<ProposedDraftReferenceV2["source_kind"]>(["node", "image_asset"]),
      `${path}.source_kind`,
    ),
    source_id: expectNonEmptyString(record.source_id, `${path}.source_id`),
    binding_kind: expectLiteral(record.binding_kind, CANVAS_BINDING_ROLES, `${path}.binding_kind`),
    input_role: expectLiteral(record.input_role, CANVAS_BINDING_ROLES, `${path}.input_role`),
    required: expectBoolean(record.required, `${path}.required`),
    display_order: expectNonNegativeInteger(record.display_order, `${path}.display_order`),
    semantic_reference_role:
      record.semantic_reference_role === undefined || record.semantic_reference_role === null
        ? null
        : expectLiteral(
            record.semantic_reference_role,
            SEMANTIC_REFERENCE_ROLES,
            `${path}.semantic_reference_role`,
          ),
    occurrence_id: occurrenceId,
    character_phase: characterPhase,
    display_name: expectNonEmptyString(record.display_name, `${path}.display_name`),
    media_type: expectLiteral(
      record.media_type,
      new Set<ProposedDraftReferenceV2["media_type"]>(["text", "image", "video", "audio"]),
      `${path}.media_type`,
    ),
  };
}

function normalizeProposalActionDescriptorV2(
  value: unknown,
  path: string,
): ProposalActionDescriptorV2 {
  return normalizeStrictRecord(value, path, {
    action_id: expectNonEmptyString,
    action: (value, fieldPath) => expectLiteral(value, PROPOSAL_ACTIONS, fieldPath),
    label: expectNonEmptyString,
    proposal_id: expectNonEmptyString,
    expected_session_revision: expectPositiveInteger,
    confirmation_required: expectBoolean,
    reason: expectNonEmptyString,
    option_id: nullableStringWithDefault,
    enabled: (value, fieldPath) => value === undefined ? true : expectBoolean(value, fieldPath),
    disabled_reason: nullableStringWithDefault,
  } satisfies StrictRecordFieldsFor<ProposalActionDescriptorV2>);
}

export function normalizeConceptProposalV2(
  value: unknown,
  path = "proposal",
): ConceptProposalV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "proposal_id",
      "workflow_id",
      "turn_id",
      "video_skill_run_id",
      "topic_id",
      "creative_direction_snapshot_id",
      "proposal_revision",
      "source_proposal_id",
      "proposal_kind",
      "capability_id",
      "capability_display_name",
      "options",
      "proposed_references",
      "occurrence_id",
      "occurrence_index",
      "occurrence_count",
      "character_phase",
      "target_node_id",
      "target_node_revision",
      "proposal_purpose",
      "availability",
      "application_count",
      "latest_application",
      "materialization",
      "guidance_session_id",
      "guidance_session_revision",
      "actions",
      "created_at",
      "updated_at",
    ],
    path,
  );
  const options = expectArray(record.options, `${path}.options`).map((item, index) => (
    normalizeCapabilityProposalOptionV2(item, `${path}.options[${index}]`)
  ));
  if (options.length < 1 || options.length > 3) fail(`${path}.options`, "expected between 1 and 3 options");
  return {
    proposal_id: expectNonEmptyString(record.proposal_id, `${path}.proposal_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    turn_id: expectNonEmptyString(record.turn_id, `${path}.turn_id`),
    video_skill_run_id: nullableStringWithDefault(record.video_skill_run_id, `${path}.video_skill_run_id`),
    topic_id: nullableStringWithDefault(record.topic_id, `${path}.topic_id`),
    creative_direction_snapshot_id: nullableStringWithDefault(
      record.creative_direction_snapshot_id,
      `${path}.creative_direction_snapshot_id`,
    ),
    proposal_revision: expectPositiveInteger(record.proposal_revision, `${path}.proposal_revision`),
    source_proposal_id: nullableStringWithDefault(record.source_proposal_id, `${path}.source_proposal_id`),
    proposal_kind: expectLiteral(
      record.proposal_kind,
      new Set<ConceptProposalV2["proposal_kind"]>([
        "world_setting",
        "script",
        "product",
        "prop",
        "character",
        "scene",
        "storyboard",
        "video",
        "bgm",
      ]),
      `${path}.proposal_kind`,
    ),
    capability_id: expectLiteral(record.capability_id, AGENT_CAPABILITY_IDS, `${path}.capability_id`),
    capability_display_name: expectNonEmptyString(
      record.capability_display_name,
      `${path}.capability_display_name`,
    ),
    options,
    proposed_references: expectArray(record.proposed_references ?? [], `${path}.proposed_references`)
      .map((item, index) => normalizeProposedDraftReferenceV2(item, `${path}.proposed_references[${index}]`)),
    occurrence_id: nullableStringWithDefault(record.occurrence_id, `${path}.occurrence_id`),
    occurrence_index: record.occurrence_index === undefined || record.occurrence_index === null
      ? null
      : expectPositiveInteger(record.occurrence_index, `${path}.occurrence_index`),
    occurrence_count: record.occurrence_count === undefined || record.occurrence_count === null
      ? null
      : expectPositiveInteger(record.occurrence_count, `${path}.occurrence_count`),
    character_phase: record.character_phase === undefined || record.character_phase === null
      ? null
      : expectLiteral(record.character_phase, new Set(["main"] as const), `${path}.character_phase`),
    target_node_id: nullableStringWithDefault(record.target_node_id, `${path}.target_node_id`),
    target_node_revision: record.target_node_revision === undefined || record.target_node_revision === null
      ? null
      : expectPositiveInteger(record.target_node_revision, `${path}.target_node_revision`),
    proposal_purpose: nullableStringWithDefault(record.proposal_purpose, `${path}.proposal_purpose`),
    availability: record.availability === undefined
      ? "open"
      : expectLiteral(record.availability, PROPOSAL_AVAILABILITIES, `${path}.availability`),
    application_count: record.application_count === undefined
      ? 0
      : expectNonNegativeInteger(record.application_count, `${path}.application_count`),
    latest_application: record.latest_application === undefined || record.latest_application === null
      ? null
      : normalizeProposalApplicationSummaryV2(record.latest_application, `${path}.latest_application`),
    materialization: record.materialization === undefined || record.materialization === null
      ? null
      : normalizeProposalMaterializationProjectionV2(record.materialization, `${path}.materialization`),
    guidance_session_id: expectNonEmptyString(record.guidance_session_id, `${path}.guidance_session_id`),
    guidance_session_revision: expectPositiveInteger(
      record.guidance_session_revision,
      `${path}.guidance_session_revision`,
    ),
    actions: expectArray(record.actions ?? [], `${path}.actions`).map((action, index) => (
      normalizeProposalActionDescriptorV2(action, `${path}.actions[${index}]`)
    )),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function normalizeProposalApplicationSummaryV2(
  value: unknown,
  path: string,
): ProposalApplicationSummaryV2 {
  return normalizeStrictRecord(value, path, {
    application_id: expectNonEmptyString,
    option_id: expectNonEmptyString,
    action: (value, fieldPath) => expectLiteral(
      value,
      new Set<ProposalApplicationSummaryV2["action"]>([
        "select_option",
        "custom_direction",
        "delegate_choice",
        "reuse_direction",
      ]),
      fieldPath,
    ),
    receipt_id: expectNonEmptyString,
    created_node_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    queued_execution_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    created_at: expectIsoDateTimeString,
  } satisfies StrictRecordFieldsFor<ProposalApplicationSummaryV2>);
}

function normalizeChatMessageV2(value: unknown, path: string): ChatMessageV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["item_type", "message_id", "conversation_id", "speaker", "text", "linked_node_ids", "script_node_id", "proposal_id", "metadata", "sequence", "created_at"], path);
  return {
    item_type: expectLiteral(record.item_type, new Set<ChatMessageV2["item_type"]>(["message"]), `${path}.item_type`),
    message_kind: "conversation",
    message_id: expectNonEmptyString(record.message_id, `${path}.message_id`),
    conversation_id: expectNonEmptyString(record.conversation_id, `${path}.conversation_id`),
    speaker: expectLiteral(record.speaker, CHAT_MESSAGE_SPEAKERS, `${path}.speaker`),
    text: expectString(record.text, `${path}.text`),
    linked_node_ids: optionalStringArray(record.linked_node_ids, `${path}.linked_node_ids`, []),
    script_node_id: record.script_node_id === undefined ? null : nullableString(record.script_node_id, `${path}.script_node_id`),
    proposal_id: record.proposal_id === undefined ? null : nullableString(record.proposal_id, `${path}.proposal_id`),
    capability_id: null,
    ...(record.metadata === undefined
      ? {}
      : { metadata: optionalUnknownRecord(record.metadata, `${path}.metadata`, {}) }),
    sequence: expectNonNegativeInteger(record.sequence, `${path}.sequence`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

function normalizeChatArtifactCardV2(value: unknown, path: string): ChatArtifactCardV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["item_type", "artifact_id", "artifact_kind", "node_id", "title", "summary", "action_label", "source_turn_id", "sequence", "created_at"], path);
  const actionLabel = record.action_label === undefined ? "View Script" : expectString(record.action_label, `${path}.action_label`);
  if (actionLabel !== "View Script") fail(`${path}.action_label`, "expected View Script");
  return {
    item_type: expectLiteral(record.item_type, new Set<ChatArtifactCardV2["item_type"]>(["artifact"]), `${path}.item_type`),
    artifact_id: expectNonEmptyString(record.artifact_id, `${path}.artifact_id`),
    artifact_kind: expectLiteral(record.artifact_kind, new Set<ChatArtifactCardV2["artifact_kind"]>(["script"]), `${path}.artifact_kind`),
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    title: expectNonEmptyString(record.title, `${path}.title`),
    summary: expectNonEmptyString(record.summary, `${path}.summary`),
    action_label: "View Script",
    source_turn_id: record.source_turn_id === undefined ? null : nullableString(record.source_turn_id, `${path}.source_turn_id`),
    sequence: expectNonNegativeInteger(record.sequence, `${path}.sequence`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

function normalizeChatProposalCardV2(value: unknown, path: string): ChatProposalCardV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["item_type", "proposal", "sequence", "created_at"], path);
  return {
    item_type: expectLiteral(record.item_type, new Set<ChatProposalCardV2["item_type"]>(["proposal"]), `${path}.item_type`),
    proposal: normalizeConceptProposalV2(record.proposal, `${path}.proposal`),
    sequence: expectNonNegativeInteger(record.sequence, `${path}.sequence`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

function normalizeChatCapabilityActivityV2(value: unknown, path: string): ChatCapabilityActivityV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "item_type", "activity_id", "turn_id", "capability_id", "capability_display_name", "operation", "status",
    "sequence", "started_at", "finished_at", "message", "error_code", "elapsed_ms", "attempt_stage",
    "retryable", "validation_paths", "operation_policy_id", "suggested_actions", "completion_mode", "warning_code",
    "actionable_failure",
  ], path);
  return {
    item_type: expectLiteral(record.item_type, new Set<ChatCapabilityActivityV2["item_type"]>(["expert_activity"]), `${path}.item_type`),
    activity_id: expectNonEmptyString(record.activity_id, `${path}.activity_id`),
    turn_id: expectNonEmptyString(record.turn_id, `${path}.turn_id`),
    capability_id: expectLiteral(record.capability_id, AGENT_CAPABILITY_IDS, `${path}.capability_id`),
    capability_display_name: expectNonEmptyString(
      record.capability_display_name,
      `${path}.capability_display_name`,
    ),
    status: expectLiteral(record.status, CAPABILITY_ACTIVITY_STATUSES, `${path}.status`),
    sequence: expectNonNegativeInteger(record.sequence, `${path}.sequence`),
    started_at: expectIsoDateTimeString(record.started_at, `${path}.started_at`),
    finished_at: record.finished_at === undefined ? null : nullableString(record.finished_at, `${path}.finished_at`),
    message: nullableStringWithDefault(record.message, `${path}.message`),
    error_code: nullableStringWithDefault(record.error_code, `${path}.error_code`),
    elapsed_ms: record.elapsed_ms === undefined || record.elapsed_ms === null
      ? null
      : expectNonNegativeInteger(record.elapsed_ms, `${path}.elapsed_ms`),
    attempt_stage: record.attempt_stage === undefined || record.attempt_stage === null
      ? null
      : expectLiteral(
        record.attempt_stage,
        new Set<NonNullable<ChatCapabilityActivityV2["attempt_stage"]>>([
          "initial", "transport_retry", "structured_repair", "fallback",
        ]),
        `${path}.attempt_stage`,
      ),
    retryable: record.retryable === undefined ? false : expectBoolean(record.retryable, `${path}.retryable`),
    validation_paths: optionalStringArray(record.validation_paths, `${path}.validation_paths`, []),
    suggested_actions: expectArray(record.suggested_actions ?? [], `${path}.suggested_actions`).map((action, index) => (
      expectLiteral(action, new Set<ChatCapabilityActivityV2["suggested_actions"][number]>(["retry", "revise_request"]), `${path}.suggested_actions[${index}]`)
    )),
    completion_mode: record.completion_mode === undefined || record.completion_mode === null
      ? null
      : expectLiteral(record.completion_mode, new Set(["deterministic_fallback"] as const), `${path}.completion_mode`),
    warning_code: record.warning_code === undefined || record.warning_code === null
      ? null
      : expectLiteral(record.warning_code, new Set(["specialist_materialization_fallback"] as const), `${path}.warning_code`),
    actionable_failure: nullableActionableFailureV1(
      record.actionable_failure,
      `${path}.actionable_failure`,
    ),
  };
}

function normalizeAgentNodeRefV2(value: unknown, path: string): AgentNodeRefV2 {
  const record = expectRecord(value, path);
  const kind = expectString(record.kind, `${path}.kind`);
  if (kind === "node_id") {
    forbidUnknownFields(record, ["kind", "node_id"], path);
    return {
      kind,
      node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    };
  }
  if (kind === "operation_result") {
    forbidUnknownFields(record, ["kind", "operation_id"], path);
    return {
      kind,
      operation_id: expectNonEmptyString(record.operation_id, `${path}.operation_id`),
    };
  }
  fail(`${path}.kind`, "unsupported node reference");
}

function normalizeAgentCommandOperationV2(
  value: unknown,
  path: string,
): AgentCommandOperationV2 {
  const record = expectRecord(value, path);
  const operationType = expectString(record.operation_type, `${path}.operation_type`);
  const operationId = expectNonEmptyString(record.operation_id, `${path}.operation_id`);
  if (operationType === "create_draft_node") {
    forbidUnknownFields(record, [
      "operation_type",
      "operation_id",
      "node_type",
      "creative_role",
      "title",
      "summary_prompt",
      "generation_prompt",
      "structured_content",
      "model_selection_mode",
      "model_ref",
      "parameters",
      "source_asset_id",
      "video_skill_run_id",
      "placement_hint",
    ], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      node_type: expectLiteral(record.node_type, COMMAND_NODE_TYPES, `${path}.node_type`),
      creative_role: expectLiteral(record.creative_role, CANVAS_CREATIVE_ROLES, `${path}.creative_role`),
      title: expectNonEmptyString(record.title, `${path}.title`),
      summary_prompt: nullableStringWithDefault(record.summary_prompt, `${path}.summary_prompt`),
      generation_prompt: nullableStringWithDefault(record.generation_prompt, `${path}.generation_prompt`),
      structured_content: optionalUnknownRecord(record.structured_content, `${path}.structured_content`, {}),
      model_selection_mode: record.model_selection_mode === undefined
        ? "default"
        : expectLiteral(record.model_selection_mode, CANVAS_MODEL_SELECTION_MODES, `${path}.model_selection_mode`),
      model_ref: nullableStringWithDefault(record.model_ref, `${path}.model_ref`),
      parameters: optionalUnknownRecord(record.parameters, `${path}.parameters`, {}),
      source_asset_id: nullableStringWithDefault(record.source_asset_id, `${path}.source_asset_id`),
      video_skill_run_id: nullableStringWithDefault(record.video_skill_run_id, `${path}.video_skill_run_id`),
      placement_hint: normalizeAgentPlacementHintV2(record.placement_hint, `${path}.placement_hint`),
    };
  }
  if (operationType === "patch_editable_node") {
    forbidUnknownFields(record, [
      "operation_type",
      "operation_id",
      "node",
      "title",
      "summary_prompt",
      "generation_prompt",
      "structured_content",
      "model_selection_mode",
      "model_ref",
      "parameters",
    ], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      node: normalizeAgentNodeRefV2(record.node, `${path}.node`),
      title: nullableStringWithDefault(record.title, `${path}.title`),
      summary_prompt: nullableStringWithDefault(record.summary_prompt, `${path}.summary_prompt`),
      generation_prompt: nullableStringWithDefault(record.generation_prompt, `${path}.generation_prompt`),
      structured_content: record.structured_content === undefined
        ? null
        : expectNullableRecord(record.structured_content, `${path}.structured_content`),
      model_selection_mode: record.model_selection_mode === undefined || record.model_selection_mode === null
        ? null
        : expectLiteral(record.model_selection_mode, CANVAS_MODEL_SELECTION_MODES, `${path}.model_selection_mode`),
      model_ref: nullableStringWithDefault(record.model_ref, `${path}.model_ref`),
      parameters: record.parameters === undefined
        ? null
        : expectNullableRecord(record.parameters, `${path}.parameters`),
    };
  }
  if (operationType === "create_binding") {
    forbidUnknownFields(record, [
      "operation_type",
      "operation_id",
      "source",
      "target",
      "binding_kind",
      "required",
      "display_order",
    ], path);
    const source = expectRecord(record.source, `${path}.source`);
    return {
      operation_type: operationType,
      operation_id: operationId,
      source: source.kind === "image_asset"
        ? {
            kind: "image_asset",
            asset_id: expectNonEmptyString(source.asset_id, `${path}.source.asset_id`),
          }
        : normalizeAgentNodeRefV2(source, `${path}.source`),
      target: normalizeAgentNodeRefV2(record.target, `${path}.target`),
      binding_kind: expectLiteral(record.binding_kind, AGENT_COMMAND_BINDING_KINDS, `${path}.binding_kind`),
      required: record.required === undefined
        ? true
        : expectBoolean(record.required, `${path}.required`),
      display_order: record.display_order === undefined
        ? 0
        : expectNonNegativeInteger(record.display_order, `${path}.display_order`),
    };
  }
  if (operationType === "patch_binding") {
    forbidUnknownFields(record, [
      "operation_type",
      "operation_id",
      "binding_id",
      "required",
      "enabled",
      "display_order",
    ], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      binding_id: expectNonEmptyString(record.binding_id, `${path}.binding_id`),
      required: record.required === undefined ? null : nullableBoolean(record.required, `${path}.required`),
      enabled: record.enabled === undefined ? null : nullableBoolean(record.enabled, `${path}.enabled`),
      display_order: record.display_order === undefined || record.display_order === null
        ? null
        : expectNonNegativeInteger(record.display_order, `${path}.display_order`),
    };
  }
  if (operationType === "delete_binding") {
    forbidUnknownFields(record, ["operation_type", "operation_id", "binding_id"], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      binding_id: expectNonEmptyString(record.binding_id, `${path}.binding_id`),
    };
  }
  if (operationType === "delete_node") {
    forbidUnknownFields(record, ["operation_type", "operation_id", "node"], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      node: normalizeAgentNodeRefV2(record.node, `${path}.node`),
    };
  }
  if (operationType === "materialize_sibling_draft") {
    forbidUnknownFields(record, [
      "operation_type",
      "operation_id",
      "source_node",
      "title",
      "generation_prompt",
      "model_selection_mode",
      "model_ref",
      "parameters",
      "placement_hint",
    ], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      source_node: normalizeAgentNodeRefV2(record.source_node, `${path}.source_node`),
      title: expectNonEmptyString(record.title, `${path}.title`),
      generation_prompt: expectNonEmptyString(record.generation_prompt, `${path}.generation_prompt`),
      model_selection_mode: record.model_selection_mode === undefined
        ? "default"
        : expectLiteral(record.model_selection_mode, CANVAS_MODEL_SELECTION_MODES, `${path}.model_selection_mode`),
      model_ref: nullableStringWithDefault(record.model_ref, `${path}.model_ref`),
      parameters: optionalUnknownRecord(record.parameters, `${path}.parameters`, {}),
      placement_hint: normalizeAgentPlacementHintV2(record.placement_hint, `${path}.placement_hint`),
    };
  }
  if (operationType === "request_node_run") {
    forbidUnknownFields(record, ["operation_type", "operation_id", "node"], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      node: normalizeAgentNodeRefV2(record.node, `${path}.node`),
    };
  }
  if (operationType === "update_topic_status") {
    forbidUnknownFields(record, [
      "operation_type",
      "operation_id",
      "skill_run_id",
      "topic_id",
      "status",
      "related_nodes",
    ], path);
    return {
      operation_type: operationType,
      operation_id: operationId,
      skill_run_id: expectNonEmptyString(record.skill_run_id, `${path}.skill_run_id`),
      topic_id: expectNonEmptyString(record.topic_id, `${path}.topic_id`),
      status: expectLiteral(
        record.status,
        new Set(["resolved", "skipped", "not_required"] as const),
        `${path}.status`,
      ),
      related_nodes: expectArray(record.related_nodes ?? [], `${path}.related_nodes`)
        .map((item, index) => normalizeAgentNodeRefV2(item, `${path}.related_nodes[${index}]`)),
    };
  }
  fail(`${path}.operation_type`, "unsupported command operation");
}

export function normalizeAgentCommandPlanV2(
  value: unknown,
  path = "commandPlan",
): AgentCommandPlanV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "plan_id",
    "workflow_id",
    "conversation_id",
    "source_turn_id",
    "context_snapshot_id",
    "base_workflow_revision",
    "expires_at",
    "operations",
    "continuation_requested",
    "risk",
    "confirmation_required",
    "target_summary",
    "operation_fingerprint",
    "idempotency_key",
    "status",
    "supersedes_plan_id",
    "replacement_plan_id",
    "actor",
    "created_at",
    "updated_at",
  ], path);
  const operations = expectArray(record.operations, `${path}.operations`)
    .map((item, index) => normalizeAgentCommandOperationV2(item, `${path}.operations[${index}]`));
  if (operations.length < 1 || operations.length > 8) {
    fail(`${path}.operations`, "expected between 1 and 8 operations");
  }
  return {
    plan_id: expectNonEmptyString(record.plan_id, `${path}.plan_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    conversation_id: expectNonEmptyString(record.conversation_id, `${path}.conversation_id`),
    source_turn_id: expectNonEmptyString(record.source_turn_id, `${path}.source_turn_id`),
    context_snapshot_id: expectNonEmptyString(record.context_snapshot_id, `${path}.context_snapshot_id`),
    base_workflow_revision: expectPositiveInteger(record.base_workflow_revision, `${path}.base_workflow_revision`),
    expires_at: expectIsoDateTimeString(record.expires_at, `${path}.expires_at`),
    operations,
    continuation_requested: record.continuation_requested === undefined
      ? false
      : expectBoolean(record.continuation_requested, `${path}.continuation_requested`),
    risk: expectLiteral(record.risk, COMMAND_RISKS, `${path}.risk`),
    confirmation_required: expectBoolean(record.confirmation_required, `${path}.confirmation_required`),
    target_summary: record.target_summary === undefined
      ? ""
      : expectString(record.target_summary, `${path}.target_summary`),
    operation_fingerprint: expectNonEmptyString(record.operation_fingerprint, `${path}.operation_fingerprint`),
    idempotency_key: expectNonEmptyString(record.idempotency_key, `${path}.idempotency_key`),
    status: expectLiteral(record.status, COMMAND_PLAN_STATUSES, `${path}.status`),
    supersedes_plan_id: nullableStringWithDefault(record.supersedes_plan_id, `${path}.supersedes_plan_id`),
    replacement_plan_id: nullableStringWithDefault(record.replacement_plan_id, `${path}.replacement_plan_id`),
    actor: record.actor === undefined
      ? "agent"
      : expectLiteral(record.actor, new Set(["agent", "user", "system"] as const), `${path}.actor`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function normalizeAgentOperationResultV2(
  value: unknown,
  path: string,
): AgentOperationResultV2 {
  return normalizeStrictRecord(value, path, {
    operation_id: expectNonEmptyString,
    node_id: nullableStringWithDefault,
    binding_id: nullableStringWithDefault,
    execution_id: nullableStringWithDefault,
    status: (value, fieldPath) => expectLiteral(value, new Set(["applied", "queued", "failed"] as const), fieldPath),
    error_code: nullableStringWithDefault,
  } satisfies StrictRecordFieldsFor<AgentOperationResultV2>);
}

function normalizeAgentCanvasContinuationV2(
  value: unknown,
  path: string,
): AgentCanvasContinuationV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "continuation_id",
    "workflow_id",
    "conversation_id",
    "source_turn_id",
    "continuation_turn_id",
    "operation",
    "occurrence_id",
    "character_phase",
    "action_owner",
    "payload_digest",
    "delivery_status",
    "status",
    "attempt_count",
    "next_attempt_at",
    "max_attempts",
    "lease_owner",
    "lease_generation",
    "lease_expires_at",
    "last_error_code",
    "last_error_message",
    "created_at",
    "updated_at",
  ], path);
  const deliveryStatus = record.delivery_status ?? record.status;
  return {
    continuation_id: expectNonEmptyString(record.continuation_id, `${path}.continuation_id`),
    delivery_status: expectLiteral(
      deliveryStatus,
      new Set<AgentCanvasContinuationV2["delivery_status"]>([
        "queued",
        "leased",
        "retry_wait",
        "completed",
        "failed",
        "superseded",
      ]),
      `${path}.delivery_status`,
    ),
    attempt_count: record.attempt_count === undefined
      ? 0
      : expectNonNegativeInteger(record.attempt_count, `${path}.attempt_count`),
    next_attempt_at: record.next_attempt_at === undefined || record.next_attempt_at === null
      ? null
      : expectIsoDateTimeString(record.next_attempt_at, `${path}.next_attempt_at`),
    source_turn_id: nullableStringWithDefault(record.source_turn_id, `${path}.source_turn_id`),
    continuation_turn_id: nullableStringWithDefault(
      record.continuation_turn_id,
      `${path}.continuation_turn_id`,
    ),
    occurrence_id: nullableStringWithDefault(record.occurrence_id, `${path}.occurrence_id`),
    character_phase: record.character_phase === undefined || record.character_phase === null
      ? null
      : expectLiteral(record.character_phase, new Set(["main", "turnaround"] as const), `${path}.character_phase`),
    action_owner: record.action_owner === undefined || record.action_owner === null
      ? null
      : expectLiteral(
          record.action_owner,
          new Set(["guided_journey", "targeted_authoring", "quick_media"] as const),
          `${path}.action_owner`,
        ),
    max_attempts: record.max_attempts === undefined || record.max_attempts === null
      ? null
      : expectPositiveInteger(record.max_attempts, `${path}.max_attempts`),
    last_error_code: nullableStringWithDefault(record.last_error_code, `${path}.last_error_code`),
    last_error_message: nullableStringWithDefault(record.last_error_message, `${path}.last_error_message`),
  };
}

export function normalizeAgentActionReceiptV2(
  value: unknown,
  path = "actionReceipt",
): AgentActionReceiptV2 {
  return normalizeStrictRecord(value, path, {
    receipt_id: expectNonEmptyString,
    workflow_id: expectNonEmptyString,
    plan_id: nullableStringWithDefault,
    action_id: nullableStringWithDefault,
    proposal_id: nullableStringWithDefault,
    proposal_option_id: nullableStringWithDefault,
    proposal_action: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectLiteral(value, PROPOSAL_ACTIONS, fieldPath),
    actor_kind: (value, fieldPath) => value === undefined
      ? "system"
      : expectLiteral(value, new Set(["agent", "user", "system"] as const), fieldPath),
    occurrence_id: nullableStringWithDefault,
    character_phase: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectLiteral(value, new Set(["main", "turnaround"] as const), fieldPath),
    idempotency_key: nullableStringWithDefault,
    status: (value, fieldPath) => expectLiteral(value, RECEIPT_STATUSES, fieldPath),
    summary: expectNonEmptyString,
    created_node_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    updated_node_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    deleted_node_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    created_binding_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    deleted_binding_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    queued_execution_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    run_queue_errors: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    operation_results: (value, fieldPath) => expectArray(value ?? [], fieldPath)
      .map((item, index) => normalizeAgentOperationResultV2(item, `${fieldPath}[${index}]`)),
    workflow_revision: expectPositiveInteger,
    before_workflow_revision: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectPositiveInteger(value, fieldPath),
    placement_hints: (value, fieldPath) => expectArray(value ?? [], fieldPath)
      .map((item, index) => normalizeAgentPlacementHintV2(item, `${fieldPath}[${index}]`)),
    continuation_turn_id: nullableStringWithDefault,
    superseded_by: nullableStringWithDefault,
    error_code: nullableStringWithDefault,
    error_message: nullableStringWithDefault,
    created_at: (value, fieldPath) => value === undefined
      ? new Date(0).toISOString()
      : expectIsoDateTimeString(value, fieldPath),
  } satisfies StrictRecordFieldsFor<AgentActionReceiptV2>);
}

function normalizeChatCommandPlanCardV2(value: unknown, path: string): ChatTimelineItemV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["item_type", "command_plan", "sequence", "created_at"], path);
  return {
    item_type: "command_plan",
    command_plan: normalizeAgentCommandPlanV2(record.command_plan, `${path}.command_plan`),
    sequence: expectNonNegativeInteger(record.sequence, `${path}.sequence`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

function normalizeChatActionReceiptCardV2(value: unknown, path: string): ChatTimelineItemV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["item_type", "action_receipt", "sequence", "created_at"], path);
  return {
    item_type: "action_receipt",
    action_receipt: normalizeAgentActionReceiptV2(record.action_receipt, `${path}.action_receipt`),
    sequence: expectNonNegativeInteger(record.sequence, `${path}.sequence`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

export function normalizeChatTimelineItemV2(value: unknown, path = "chatItem"): ChatTimelineItemV2 {
  const record = expectRecord(value, path);
  const itemType = expectString(record.item_type, `${path}.item_type`);
  if (itemType === "message") return normalizeChatMessageV2(record, path);
  if (itemType === "artifact") return normalizeChatArtifactCardV2(record, path);
  if (itemType === "proposal") return normalizeChatProposalCardV2(record, path);
  if (itemType === "expert_activity") return normalizeChatCapabilityActivityV2(record, path);
  if (itemType === "command_plan") return normalizeChatCommandPlanCardV2(record, path);
  if (itemType === "action_receipt") return normalizeChatActionReceiptCardV2(record, path);
  if (itemType === "proposal_pointer") {
    forbidUnknownFields(record, ["item_type", "proposal_id", "sequence", "created_at"], path);
    return {
      item_type: "proposal_pointer",
      proposal_id: expectNonEmptyString(record.proposal_id, `${path}.proposal_id`),
      sequence: expectNonNegativeInteger(record.sequence, `${path}.sequence`),
      created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    };
  }
  fail(`${path}.item_type`, "unsupported discriminator");
}

export function normalizeChatTimelineListResponseV2(value: unknown, path = "chatTimeline"): ChatTimelineListResponseV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    conversation_id: (value, fieldPath) => value === null
      ? null
      : expectNonEmptyString(value, fieldPath),
    guidance_advance_precondition: (value, fieldPath) => value === undefined || value === null
      ? null
      : normalizeGuidanceAdvancePreconditionV1(
        value,
        fieldPath,
      ),
    items: (value, fieldPath) => expectArray(value, fieldPath).map((item, index) => normalizeChatTimelineItemV2(item, `${fieldPath}[${index}]`)),
    next_after_seq: expectNonNegativeInteger,
  } satisfies StrictRecordFieldsFor<ChatTimelineListResponseV2>);
}

function normalizeChatTimelinePresentationViewItemsV2(
  entries: AgentCanvasChatTimelinePresentationItemV2[],
  path: string,
): ChatTimelinePresentationViewItemV2[] {
  return entries.map((entry, index) => {
    const {
      presentation_key,
      presentation_revision,
      source_entry_ids,
      message_key,
      message_args,
      response_locale,
      ...rawEntry
    } = entry;
    // Keep the raw and projected entry adapters identical so every timeline card
    // follows one conversion path regardless of backend generation.
    const [item] = normalizeAgentCanvasChatTimelineV2({
      workflow_id: rawEntry.workflow_id,
      conversation_id: rawEntry.conversation_id,
      guidance_session: null,
      continuations: [],
      current_session_actions: [],
      items: [rawEntry],
      next_cursor: 0,
    }, `${path}[${index}].entry`).items;
    if (!item) fail(`${path}[${index}]`, "presentation entry has no visible timeline item");
    return {
      presentation_key,
      presentation_revision,
      source_entry_ids,
      message_key,
      message_args,
      response_locale,
      item,
    };
  });
}

export function normalizeAgentCanvasChatTimelineV2(
  value: unknown,
  path = "chatTimeline",
): AgentCanvasChatViewTimelineV2 {
  const persisted = normalizeAgentCanvasChatTimelineResponseV2(value, path);
  return {
    workflow_id: persisted.workflow_id,
    conversation_id: persisted.conversation_id,
    guidanceSession: persisted.guidance_session,
    guidanceAdvancePrecondition: persisted.guidance_advance_precondition,
    continuations: persisted.continuations,
    current_session_actions: persisted.current_session_actions,
    next_cursor: persisted.next_cursor,
    presentationItems: persisted.presentation_items === null
      ? null
      : normalizeChatTimelinePresentationViewItemsV2(
        persisted.presentation_items,
        `${path}.presentation_items`,
      ),
    items: persisted.items.flatMap((entry): ChatTimelineItemV2[] => {
      if (entry.entry_type === "message") {
        if (!entry.speaker) fail(`${path}.items`, "persisted message requires speaker");
        return [{
          item_type: "message" as const,
          message_kind: "conversation" as const,
          message_id: entry.entry_id,
          conversation_id: entry.conversation_id,
          speaker: entry.speaker,
          text: entry.content,
          linked_node_ids: optionalStringArray(
            entry.metadata.linked_node_ids,
            `${path}.items.metadata.linked_node_ids`,
            [],
          ),
          script_node_id: typeof entry.metadata.script_node_id === "string"
            ? entry.metadata.script_node_id
            : null,
          proposal_id: typeof entry.metadata.proposal_id === "string"
            ? entry.metadata.proposal_id
            : null,
          capability_id: entry.metadata.capability_id === undefined
            ? null
            : expectLiteral(
              entry.metadata.capability_id,
              AGENT_CAPABILITY_IDS,
              `${path}.items.metadata.capability_id`,
            ),
          ...(Object.keys(entry.metadata).length > 0 ? { metadata: entry.metadata } : {}),
          sequence: entry.sequence_no,
          created_at: entry.created_at,
        }];
      }
      if (entry.entry_type === "command_plan") {
        if (!entry.command_plan) fail(`${path}.items.command_plan`, "command plan entry requires a plan");
        return [{
          item_type: "command_plan" as const,
          command_plan: entry.command_plan,
          sequence: entry.sequence_no,
          created_at: entry.created_at,
        }];
      }
      if (entry.entry_type === "action_receipt") {
        if (!entry.action_receipt) fail(`${path}.items.action_receipt`, "receipt entry requires a receipt");
        return [{
          item_type: "action_receipt" as const,
          action_receipt: entry.action_receipt,
          sequence: entry.sequence_no,
          created_at: entry.created_at,
        }];
      }
      if (entry.entry_type === "concept_proposal") {
        const proposalId = typeof entry.metadata.proposal_id === "string"
          ? entry.metadata.proposal_id
          : "";
        if (!proposalId) fail(`${path}.items.metadata.proposal_id`, "proposal entry requires proposal identity");
        return [{
          item_type: "proposal_pointer",
          proposal_id: proposalId,
          sequence: entry.sequence_no,
          created_at: entry.created_at,
        }];
      }
      if (entry.entry_type === "decision_bundle") {
        const bundleId = typeof entry.metadata.bundle_id === "string"
          ? entry.metadata.bundle_id
          : "";
        if (!bundleId) fail(`${path}.items.metadata.bundle_id`, "decision bundle entry requires identity");
        return [{
          item_type: "decision_bundle_pointer",
          bundle_id: bundleId,
          sequence: entry.sequence_no,
          created_at: entry.created_at,
        }];
      }
      if (entry.entry_type === "expert_activity") {
        const capabilityId = expectLiteral(
          entry.metadata.capability_id,
          AGENT_CAPABILITY_IDS,
          `${path}.items.metadata.capability_id`,
        );
        const rawStatus = entry.metadata.status ?? "working";
        const status = expectLiteral(
          rawStatus,
          new Set(["working", "completed", "failed", "superseded"] as const),
          `${path}.items.metadata.status`,
        );
        const capabilityDisplayName = expectNonEmptyString(
          entry.metadata.capability_display_name,
          `${path}.items.metadata.capability_display_name`,
        );
        const elapsedMs = entry.metadata.elapsed_ms === undefined || entry.metadata.elapsed_ms === null
          ? null
          : expectNonNegativeInteger(entry.metadata.elapsed_ms, `${path}.items.metadata.elapsed_ms`);
        const attemptStage = entry.metadata.attempt_stage === undefined || entry.metadata.attempt_stage === null
          ? null
          : expectLiteral(
            entry.metadata.attempt_stage,
            new Set<NonNullable<ChatCapabilityActivityV2["attempt_stage"]>>([
              "initial", "transport_retry", "structured_repair", "fallback",
            ]),
            `${path}.items.metadata.attempt_stage`,
          );
        const suggestedActions = expectArray(
          entry.metadata.suggested_actions ?? [],
          `${path}.items.metadata.suggested_actions`,
        ).map((action, index) => expectLiteral(
          action,
          new Set<ChatCapabilityActivityV2["suggested_actions"][number]>(["retry", "revise_request"]),
          `${path}.items.metadata.suggested_actions[${index}]`,
        ));
        const publicMessage = typeof entry.metadata.message === "string"
          ? entry.metadata.message
          : typeof entry.metadata.error_message === "string"
            ? entry.metadata.error_message
            : entry.content.trim() && entry.content.trim() !== capabilityDisplayName
              ? entry.content
              : null;
        return [{
          item_type: "expert_activity",
          activity_id: typeof entry.metadata.activity_id === "string"
            ? entry.metadata.activity_id
            : entry.entry_id,
          turn_id: typeof entry.metadata.turn_id === "string"
            ? entry.metadata.turn_id
            : entry.entry_id,
          capability_id: capabilityId,
          capability_display_name: capabilityDisplayName,
          status,
          sequence: entry.sequence_no,
          started_at: typeof entry.metadata.started_at === "string"
            ? entry.metadata.started_at
            : entry.created_at,
          finished_at: typeof entry.metadata.finished_at === "string"
            ? entry.metadata.finished_at
            : status === "working" ? null : entry.created_at,
          message: status === "failed" ? publicMessage : null,
          error_code: typeof entry.metadata.error_code === "string"
            ? entry.metadata.error_code
            : null,
          elapsed_ms: elapsedMs,
          attempt_stage: attemptStage,
          retryable: entry.metadata.retryable === true,
          validation_paths: optionalStringArray(
            entry.metadata.validation_paths,
            `${path}.items.metadata.validation_paths`,
            [],
          ),
          suggested_actions: suggestedActions,
          completion_mode: entry.metadata.completion_mode === "deterministic_fallback"
            ? "deterministic_fallback"
            : null,
          warning_code: entry.metadata.warning_code === "specialist_materialization_fallback"
            ? "specialist_materialization_fallback"
            : null,
          actionable_failure: entry.actionable_failure,
        }];
      }
      if (entry.entry_type === "agent_document_reference") {
        const metadata = entry.metadata;
        const metadataType = expectNonEmptyString(
          metadata.type,
          `${path}.items.metadata.type`,
        );
        if (metadataType !== "agent_document_reference") {
          fail(`${path}.items.metadata.type`, "expected agent_document_reference");
        }
        return [{
          item_type: "agent_document",
          document_id: expectNonEmptyString(
            metadata.document_id,
            `${path}.items.metadata.document_id`,
          ),
          document_kind: expectLiteral(
            metadata.document_kind,
            AGENT_WORKING_DOCUMENT_KINDS,
            `${path}.items.metadata.document_kind`,
          ),
          revision: expectPositiveInteger(
            metadata.revision,
            `${path}.items.metadata.revision`,
          ),
          content_digest: expectNonEmptyString(
            metadata.content_digest,
            `${path}.items.metadata.content_digest`,
          ),
          title: expectNonEmptyString(metadata.title, `${path}.items.metadata.title`),
          sequence: entry.sequence_no,
          created_at: entry.created_at,
        }];
      }
      if (entry.entry_type === "planning_progress") {
        return [{
          item_type: "message",
          message_kind: "planning_progress",
          message_id: entry.entry_id,
          conversation_id: entry.conversation_id,
          speaker: "adcraft_video_agent",
          text: entry.content,
          linked_node_ids: [],
          script_node_id: null,
          proposal_id: typeof entry.metadata.proposal_id === "string"
            ? entry.metadata.proposal_id
            : null,
          capability_id: entry.metadata.capability_id === undefined
            ? null
            : expectLiteral(
              entry.metadata.capability_id,
              AGENT_CAPABILITY_IDS,
              `${path}.items.metadata.capability_id`,
            ),
          sequence: entry.sequence_no,
          created_at: entry.created_at,
        }];
      }
      if (entry.entry_type !== "script_artifact") return [];
      const nodeId = typeof entry.metadata.script_node_id === "string"
        ? entry.metadata.script_node_id
        : typeof entry.metadata.node_id === "string"
          ? entry.metadata.node_id
          : "";
      if (!nodeId) fail(`${path}.items.metadata.node_id`, "script artifact requires node identity");
      return [{
        item_type: "artifact" as const,
        artifact_id: entry.entry_id,
        artifact_kind: "script" as const,
        node_id: nodeId,
        title: typeof entry.metadata.title === "string" ? entry.metadata.title : "Script",
        summary: typeof entry.metadata.summary === "string"
          ? entry.metadata.summary
          : entry.content,
        action_label: "View Script" as const,
        source_turn_id: typeof entry.metadata.source_turn_id === "string"
          ? entry.metadata.source_turn_id
          : null,
        sequence: entry.sequence_no,
        created_at: entry.created_at,
      }];
    }),
  };
}

export function normalizeEditingOutputSettingsV2(value: unknown, path = "editing.output"): EditingOutputSettingsV2 {
  const record = value === undefined ? {} : expectRecord(value, path);
  forbidUnknownFields(record, ["resolution", "aspect_ratio", "fps", "video_codec", "audio_codec", "container"], path);
  const fps = record.fps === undefined ? null : nullableFiniteNumber(record.fps, `${path}.fps`);
  if (fps !== null && fps <= 0) fail(`${path}.fps`, "expected positive number");
  if (fps !== null && fps > 120) fail(`${path}.fps`, "expected number <= 120");
  return {
    resolution: record.resolution === undefined ? null : nullableString(record.resolution, `${path}.resolution`),
    aspect_ratio: record.aspect_ratio === undefined ? null : nullableString(record.aspect_ratio, `${path}.aspect_ratio`),
    fps,
    video_codec: record.video_codec === undefined ? "h264" : expectLiteral(record.video_codec, EDITING_VIDEO_CODEC, `${path}.video_codec`),
    audio_codec: record.audio_codec === undefined ? "aac" : expectLiteral(record.audio_codec, EDITING_AUDIO_CODEC, `${path}.audio_codec`),
    container: record.container === undefined ? "mp4" : expectLiteral(record.container, EDITING_CONTAINER, `${path}.container`),
  };
}

function editingOptionalSource(
  record: JsonRecord,
  path: string,
): { binding_id: string | null; asset_id: string | null } {
  const bindingId = record.binding_id === undefined || record.binding_id === null
    ? null
    : expectNonEmptyString(record.binding_id, `${path}.binding_id`);
  const assetId = record.asset_id === undefined || record.asset_id === null
    ? null
    : expectNonEmptyString(record.asset_id, `${path}.asset_id`);
  if ((bindingId === null) === (assetId === null)) {
    fail(path, "expected exactly one Binding or Asset reference");
  }
  return { binding_id: bindingId, asset_id: assetId };
}

function editingNumberInRange(
  value: unknown,
  path: string,
  defaultValue: number,
  minimum: number,
  maximum: number,
): number {
  const normalized = value === undefined ? defaultValue : expectFiniteNumber(value, path);
  if (normalized < minimum || normalized > maximum) {
    fail(path, `expected value between ${minimum} and ${maximum}`);
  }
  return normalized;
}

export function normalizeEditingVideoEntryV2(
  value: unknown,
  path = "editing.videoEntry",
): EditingVideoEntryV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "binding_id",
    "asset_id",
    "enabled",
    "timeline_start_seconds",
    "trim_start_seconds",
    "trim_end_seconds",
    "volume",
    "preserve_native_audio",
    "transition",
    "transition_duration_seconds",
    "fit_mode",
  ], path);
  const source = editingOptionalSource(record, path);
  const trimStart = editingNumberInRange(
    record.trim_start_seconds,
    `${path}.trim_start_seconds`,
    0,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const trimEnd = record.trim_end_seconds === undefined
    ? null
    : nullableFiniteNumber(record.trim_end_seconds, `${path}.trim_end_seconds`);
  if (trimEnd !== null && trimEnd <= trimStart) {
    fail(`${path}.trim_end_seconds`, "expected value after trim_start_seconds");
  }
  const transition = record.transition === undefined
    ? "cut"
    : expectLiteral(record.transition, EDITING_TRANSITIONS, `${path}.transition`);
  const transitionDuration = editingNumberInRange(
    record.transition_duration_seconds,
    `${path}.transition_duration_seconds`,
    0,
    0,
    5,
  );
  if (transition === "cut" && transitionDuration !== 0) {
    fail(`${path}.transition_duration_seconds`, "cut transitions cannot have a duration");
  }
  const timelineStart = record.timeline_start_seconds === undefined
    ? undefined
    : editingNumberInRange(
      record.timeline_start_seconds,
      `${path}.timeline_start_seconds`,
      0,
      0,
      Number.MAX_SAFE_INTEGER,
    );
  return {
    ...source,
    enabled: record.enabled === undefined ? true : expectBoolean(record.enabled, `${path}.enabled`),
    ...(timelineStart === undefined ? {} : { timeline_start_seconds: timelineStart }),
    trim_start_seconds: trimStart,
    trim_end_seconds: trimEnd,
    volume: editingNumberInRange(record.volume, `${path}.volume`, 1, 0, 1),
    preserve_native_audio: record.preserve_native_audio === undefined
      ? true
      : expectBoolean(record.preserve_native_audio, `${path}.preserve_native_audio`),
    transition,
    transition_duration_seconds: transitionDuration,
    fit_mode: record.fit_mode === undefined
      ? "fill"
      : expectLiteral(record.fit_mode, EDITING_FIT_MODES, `${path}.fit_mode`),
  };
}

export function normalizeEditingBgmEntryV2(
  value: unknown,
  path = "editing.bgm",
): EditingBgmEntryV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "binding_id",
    "asset_id",
    "enabled",
    "trim_start_seconds",
    "trim_end_seconds",
    "volume",
    "fade_in_seconds",
    "fade_out_seconds",
  ], path);
  const source = editingOptionalSource(record, path);
  const trimStart = editingNumberInRange(
    record.trim_start_seconds,
    `${path}.trim_start_seconds`,
    0,
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const trimEnd = record.trim_end_seconds === undefined
    ? null
    : nullableFiniteNumber(record.trim_end_seconds, `${path}.trim_end_seconds`);
  if (trimEnd !== null && trimEnd <= trimStart) {
    fail(`${path}.trim_end_seconds`, "expected value after trim_start_seconds");
  }
  return {
    ...source,
    enabled: record.enabled === undefined ? true : expectBoolean(record.enabled, `${path}.enabled`),
    trim_start_seconds: trimStart,
    trim_end_seconds: trimEnd,
    volume: editingNumberInRange(record.volume, `${path}.volume`, 0.2, 0, 1),
    fade_in_seconds: editingNumberInRange(record.fade_in_seconds, `${path}.fade_in_seconds`, 0, 0, 30),
    fade_out_seconds: editingNumberInRange(record.fade_out_seconds, `${path}.fade_out_seconds`, 0, 0, 30),
  };
}

export function normalizeEditingManifestV2(value: unknown, path = "editing.manifest"): EditingManifestV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "video_entries",
    "bgm",
    "output",
    "manifest_revision",
    "timeline_duration_seconds",
  ], path);
  const videoEntries = (record.video_entries === undefined
    ? []
    : expectArray(record.video_entries, `${path}.video_entries`)
  ).map((item, index) => normalizeEditingVideoEntryV2(item, `${path}.video_entries[${index}]`));
  const sourceKeys = videoEntries.map((entry) => (
    entry.binding_id ? `binding:${entry.binding_id}` : `asset:${entry.asset_id}`
  ));
  if (new Set(sourceKeys).size !== sourceKeys.length) {
    fail(`${path}.video_entries`, "input references must be unique");
  }
  const bgm = record.bgm === undefined || record.bgm === null
    ? null
    : normalizeEditingBgmEntryV2(record.bgm, `${path}.bgm`);
  const bgmKey = bgm
    ? bgm.binding_id
      ? `binding:${bgm.binding_id}`
      : `asset:${bgm.asset_id}`
    : null;
  if (bgmKey && sourceKeys.includes(bgmKey)) {
    fail(`${path}.bgm`, "BGM input cannot also be a video input");
  }
  const timelineDuration = record.timeline_duration_seconds === undefined
    ? undefined
    : editingNumberInRange(
      record.timeline_duration_seconds,
      `${path}.timeline_duration_seconds`,
      0,
      0.001,
      Number.MAX_SAFE_INTEGER,
    );
  return {
    video_entries: videoEntries,
    bgm,
    output: normalizeEditingOutputSettingsV2(record.output, `${path}.output`),
    manifest_revision: record.manifest_revision === undefined
      ? 1
      : expectPositiveInteger(record.manifest_revision, `${path}.manifest_revision`),
    ...(timelineDuration === undefined ? {} : { timeline_duration_seconds: timelineDuration }),
  };
}

export function normalizeEditingSkippedInputV2(value: unknown, path = "editing.skippedInput"): EditingSkippedInputV2 {
  return normalizeStrictRecord(value, path, {
    reference_id: expectNonEmptyString,
    node_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    asset_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    reason: (value, fieldPath) => expectLiteral(value, EDITING_SKIPPED_REASONS, fieldPath),
  } satisfies StrictRecordFieldsFor<EditingSkippedInputV2>);
}

export function normalizeEditingPreviewClipV2(value: unknown, path = "editing.previewClip"): EditingPreviewClipV2 {
  return normalizeStrictRecord(value, path, {
    reference_id: expectNonEmptyString,
    binding_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    node_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    asset_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    status: (value, fieldPath) => expectLiteral(value, CANVAS_NODE_STATUSES, fieldPath),
    display_order: expectNonNegativeInteger,
    preview_url: nullableString,
    duration_seconds: nullableFiniteNumber,
    warning: nullableString,
  } satisfies StrictRecordFieldsFor<EditingPreviewClipV2>);
}

export function normalizeEditingPreviewV2(value: unknown, path = "editing.preview"): EditingPreviewV2 {
  return normalizeStrictRecord(value, path, {
    clips: (value, fieldPath) => expectArray(value, fieldPath).map((item, index) => normalizeEditingPreviewClipV2(item, `${fieldPath}[${index}]`)),
    bgm_binding_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    bgm_node_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    bgm_asset_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    estimated_duration_seconds: expectFiniteNumber,
    warnings: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
  } satisfies StrictRecordFieldsFor<EditingPreviewV2>);
}

export function normalizeEditingExportAcceptanceCheckV2(value: unknown, path = "editing.exportAcceptanceCheck"): EditingExportAcceptanceCheckV2 {
  return normalizeStrictRecord(value, path, {
    check: expectNonEmptyString,
    status: (value, fieldPath) => expectLiteral(value, new Set(["pass", "warn", "fail", "skipped"]), fieldPath),
    detail: (value, fieldPath) => value === undefined ? "" : expectString(value, fieldPath),
  } satisfies StrictRecordFieldsFor<EditingExportAcceptanceCheckV2>);
}

export function normalizeEditingExportAcceptanceV2(value: unknown, path = "editing.exportAcceptance"): EditingExportAcceptanceV2 {
  return normalizeStrictRecord(value, path, {
    checks: (value, fieldPath) => expectArray(value, fieldPath).map((item, index) =>
      normalizeEditingExportAcceptanceCheckV2(item, `${fieldPath}[${index}]`),
    ),
    ran_at: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
  } satisfies StrictRecordFieldsFor<EditingExportAcceptanceV2>);
}

export function normalizeEditingExportRuntimeV2(value: unknown, path = "editing.exportRuntime"): EditingExportRuntimeV2 {
  return normalizeStrictRecord(value, path, {
    export_id: expectNonEmptyString,
    status: (value, fieldPath) => expectLiteral(value, EDITING_EXPORT_STATUSES, fieldPath),
    manifest_revision: expectNonNegativeInteger,
    fingerprint: expectNonEmptyString,
    ready_video_node_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    skipped_inputs: (value, fieldPath) => expectArray(value, fieldPath).map((item, index) =>
      normalizeEditingSkippedInputV2(item, `${fieldPath}[${index}]`),
    ),
    bgm_node_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    output_asset_id: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    error: (value, fieldPath) => value === null ? null : normalizeCanvasNodeErrorV2(value, fieldPath),
    started_at: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    finished_at: (value, fieldPath) => value === undefined ? null : nullableString(value, fieldPath),
    acceptance: (value, fieldPath) => value === undefined || value === null ? null : normalizeEditingExportAcceptanceV2(value, `${fieldPath}.acceptance`),
  } satisfies StrictRecordFieldsFor<EditingExportRuntimeV2>);
}

export function normalizeEditingNodeContentV2(value: unknown, path = "editing"): EditingNodeContentV2 {
  return normalizeStrictRecord(value, path, {
    manifest: normalizeEditingManifestV2,
    dirty: expectBoolean,
    preview: normalizeEditingPreviewV2,
    last_successful_export: (value, fieldPath) => value === null
        ? null
        : value === undefined
          ? null
          : normalizeEditingExportRuntimeV2(value, fieldPath),
    active_export: (value, fieldPath) => value === null
        ? null
        : value === undefined
          ? null
          : normalizeEditingExportRuntimeV2(value, fieldPath),
  } satisfies StrictRecordFieldsFor<EditingNodeContentV2>);
}

export function normalizeCanvasMutationResponseV2(
  value: unknown,
  path = "mutation",
): CanvasMutationResponseV2 {
  const record = expectRecord(value, path);
  // scope_report is part of the contract (ADR 0009 决策 2): the mutation
  // response TELLS the author what the edit affected. Rejecting it as an
  // unknown field is how the answer used to die in the API client.
  forbidUnknownFields(record, ["workflow", "node", "binding", "scope_report"], path);
  return {
    workflow: normalizeAgentCanvasWorkflowV2(record.workflow, `${path}.workflow`),
    node: record.node === null || record.node === undefined
      ? null
      : normalizeCanvasNodeV2(record.node, `${path}.node`),
    binding: record.binding === null || record.binding === undefined
      ? null
      : normalizeCanvasBindingV2(record.binding, `${path}.binding`),
    scope_report: normalizeCanvasNodeScopeReportV2(
      record.scope_report,
      `${path}.scope_report`,
    ),
  };
}

/**
 * The scope report is a free-form diagnostic dict: normalize its known keys
 * and keep unknown ones as-is (the backend may add detail; the surface shows
 * the documented fields). A malformed value degrades to null rather than
 * failing the whole mutation response.
 */
function normalizeCanvasNodeScopeReportV2(
  value: unknown,
  path: string,
): CanvasNodeScopeReportV2 | null {
  if (value === null || value === undefined) return null;
  if (!isRecord(value)) {
    fail(path, "expected object or null");
  }
  const record = value as JsonRecord;
  const report: CanvasNodeScopeReportV2 = {};
  if (Array.isArray(record.edited_keys)) {
    report.edited_keys = record.edited_keys.filter(
      (entry): entry is string => typeof entry === "string",
    );
  }
  if (Array.isArray(record.content_areas)) {
    report.content_areas = record.content_areas.filter(
      (entry): entry is string => typeof entry === "string",
    );
  }
  if (Array.isArray(record.dirty_reasons)) {
    report.dirty_reasons = record.dirty_reasons.filter(
      (entry): entry is string => typeof entry === "string",
    );
  }
  if (Array.isArray(record.notes)) {
    report.notes = record.notes.filter(
      (entry): entry is string => typeof entry === "string",
    );
  }
  if (Array.isArray(record.affected_neighbours)) {
    report.affected_neighbours = record.affected_neighbours.flatMap((entry) => {
      if (!isRecord(entry)) return [];
      const neighbour: CanvasScopeNeighbourV2 = {};
      if (typeof entry.node_id === "string") neighbour.node_id = entry.node_id;
      if (typeof entry.relation === "string") neighbour.relation = entry.relation;
      if (typeof entry.reason === "string") neighbour.reason = entry.reason;
      return [neighbour];
    });
  }
  return report;
}

export function normalizeCanvasEditingExportImportResponseV2(
  value: unknown,
  path = "editingExportImport",
): CanvasEditingExportImportResponseV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    revision: expectNonNegativeInteger,
    layout_revision: expectNonNegativeInteger,
    node: normalizeCanvasNodeV2,
    binding: normalizeCanvasBindingV2,
    asset: normalizeProjectAssetSummaryV2,
    events_cursor: expectNonNegativeInteger,
    replayed: expectBoolean,
  } satisfies StrictRecordFieldsFor<CanvasEditingExportImportResponseV2>);
}

export function normalizeCanvasVariationDraftResponseV2(
  value: unknown,
  path = "variationDraftResponse",
): CanvasVariationDraftResponseV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    workflow_revision: expectPositiveInteger,
    node_id: expectNonEmptyString,
    variation_draft: normalizeCanvasVariationDraftV2,
  } satisfies StrictRecordFieldsFor<CanvasVariationDraftResponseV2>);
}

export function normalizeCanvasVariationMaterializeResponseV2(
  value: unknown,
  path = "variationMaterialize",
): CanvasVariationMaterializeResponseV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    workflow_revision: expectPositiveInteger,
    source_node_id: expectNonEmptyString,
    sibling_node: normalizeCanvasNodeV2,
    copied_binding_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    run: (value, fieldPath) => value === null || value === undefined
      ? null
      : expectUnknownRecord(value, fieldPath),
    run_error: (value, fieldPath) => value === null || value === undefined
      ? null
      : normalizeCanvasNodeErrorV2(value, fieldPath),
    placement_hint: normalizeAgentPlacementHintV2,
    created_node_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    created_binding_ids: (value, fieldPath) => optionalStringArray(
      value,
      fieldPath,
      [],
    ),
    placement_hints: (value, fieldPath) => expectArray(value ?? [], fieldPath)
      .map((item, index) => normalizeAgentPlacementHintV2(
        item,
        `${fieldPath}[${index}]`,
      )),
  } satisfies StrictRecordFieldsFor<CanvasVariationMaterializeResponseV2>);
}

export function normalizeCanvasLayoutPatchResponseV2(
  value: unknown,
  path = "layoutPatch",
): CanvasLayoutPatchResponseV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    revision: expectPositiveInteger,
    layout_revision: expectPositiveInteger,
    positions: (value, fieldPath) => expectArray(value, fieldPath).map((item, index) => {
      const positionPath = `${fieldPath}[${index}]`;
      const position = expectRecord(item, positionPath);
      forbidUnknownFields(position, ["node_id", "x", "y"], positionPath);
      return {
        node_id: expectNonEmptyString(position.node_id, `${positionPath}.node_id`),
        x: expectFiniteNumber(position.x, `${positionPath}.x`),
        y: expectFiniteNumber(position.y, `${positionPath}.y`),
      };
    }),
  } satisfies StrictRecordFieldsFor<CanvasLayoutPatchResponseV2>);
}

export function normalizeProjectAssetUploadResponseV2(
  value: unknown,
  path = "assetUpload",
): ProjectAssetUploadResponseV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    asset: normalizeProjectAssetSummaryV2,
    pending_handoff_id: nullableStringWithDefault,
  } satisfies StrictRecordFieldsFor<ProjectAssetUploadResponseV2>);
}

export function normalizeProjectAssetListResponseV2(
  value: unknown,
  path = "assetList",
): ProjectAssetListResponseV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    assets: (value, fieldPath) => expectArray(value, fieldPath).map((item, index) =>
      normalizeProjectAssetSummaryV2(item, `${fieldPath}[${index}]`),
    ),
  } satisfies StrictRecordFieldsFor<ProjectAssetListResponseV2>);
}

export function normalizeAgentCanvasImageLibraryListResponseV2(
  value: unknown,
  path = "imageLibrary",
): AgentCanvasImageLibraryListResponseV2 {
  return normalizeStrictRecord(value, path, {
    items: (value, fieldPath) => expectArray(value, fieldPath).map((item, index) =>
      expectUnknownRecord(item, `${fieldPath}[${index}]`),
    ),
  } satisfies StrictRecordFieldsFor<AgentCanvasImageLibraryListResponseV2>);
}

function normalizeCreativeGoalV2(value: unknown, path: string): CreativeGoalV2 {
  return normalizeStrictRecord(value, path, {
    requested_output: (value, fieldPath) => expectLiteral(
      value,
      new Set<CreativeGoalV2["requested_output"]>(["text", "script", "image", "video", "audio"]),
      fieldPath,
    ),
    delivery_scope: (value, fieldPath) => expectLiteral(
      value,
      new Set<CreativeGoalV2["delivery_scope"]>(["draft", "generated_media"]),
      fieldPath,
    ),
    summary: expectNonEmptyString,
    explicit_constraints: (value, fieldPath) => optionalUnknownRecord(
      value,
      fieldPath,
      {},
    ),
  } satisfies StrictRecordFieldsFor<CreativeGoalV2>);
}

function normalizeCreativeElementDecisionV2(
  value: unknown,
  path: string,
): CreativeElementDecisionV2 {
  return normalizeStrictRecord(value, path, {
    element_kind: (value, fieldPath) => expectLiteral(
      value,
      CREATIVE_ELEMENT_KINDS,
      fieldPath,
    ),
    presence: (value, fieldPath) => expectLiteral(
      value,
      new Set<CreativeElementDecisionV2["presence"]>(["include", "exclude", "unspecified"]),
      fieldPath,
    ),
    authority: (value, fieldPath) => expectLiteral(
      value,
      new Set<CreativeElementDecisionV2["authority"]>(["user", "agent"]),
      fieldPath,
    ),
    requirements: (value, fieldPath) => optionalUnknownRecord(value, fieldPath, {}),
    source: (value, fieldPath) => expectLiteral(
      value,
      new Set<CreativeElementDecisionV2["source"]>([
        "explicit_user",
        "accepted_proposal",
        "delegated_to_agent",
      ]),
      fieldPath,
    ),
  } satisfies StrictRecordFieldsFor<CreativeElementDecisionV2>);
}

function normalizeGuidanceTopicStateV2(value: unknown, path: string): GuidanceTopicStateV2 {
  return normalizeStrictRecord(value, path, {
    topic_id: expectNonEmptyString,
    topic_kind: (value, fieldPath) => expectLiteral(value, GUIDANCE_TOPIC_KINDS, fieldPath),
    title: expectNonEmptyString,
    status: (value, fieldPath) => expectLiteral(
      value,
      new Set<GuidanceTopicStateV2["status"]>(["proposed", "selected", "deferred", "excluded"]),
      fieldPath,
    ),
    capability_id: (value, fieldPath) => expectLiteral(value, AGENT_CAPABILITY_IDS, fieldPath),
    capability_display_name: (value, fieldPath) => expectNonEmptyString(
      value,
      fieldPath,
    ),
    related_node_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    source_proposal_id: nullableStringWithDefault,
    revision: expectPositiveInteger,
  } satisfies StrictRecordFieldsFor<GuidanceTopicStateV2>);
}

function normalizeGuidanceCompletionProjectionV2(
  value: unknown,
  path: string,
): GuidanceCompletionProjectionV2 {
  return normalizeStrictRecord(value, path, {
    authoring: (value, fieldPath) => expectLiteral(
      value ?? "not_ready",
      new Set<GuidanceCompletionProjectionV2["authoring"]>(["not_ready", "ready"]),
      fieldPath,
    ),
    delivery: (value, fieldPath) => expectLiteral(
      value ?? "not_ready",
      new Set<GuidanceCompletionProjectionV2["delivery"]>(["not_ready", "ready"]),
      fieldPath,
    ),
    plan_document_id: nullableStringWithDefault,
    plan_revision: (value, fieldPath) => value === undefined
      ? null
      : nullablePositiveInteger(value, fieldPath),
    editing_preparation: (value, fieldPath) => expectLiteral(
      value ?? "not_ready",
      new Set<GuidanceCompletionProjectionV2["editing_preparation"]>(["not_ready", "prepared"]),
      fieldPath,
    ),
    editing_node_id: nullableStringWithDefault,
    preparation_receipt_id: nullableStringWithDefault,
    manifest_revision: (value, fieldPath) => value === undefined
      ? null
      : nullablePositiveInteger(value, fieldPath),
    export_status: (value, fieldPath) => expectLiteral(
      value ?? "not_started",
      new Set<GuidanceCompletionProjectionV2["export_status"]>([
        "not_started",
        "queued",
        "exporting",
        "completed",
        "failed",
        "cancelled",
      ]),
      fieldPath,
    ),
    export_id: nullableStringWithDefault,
    final_completion_receipt_id: nullableStringWithDefault,
    final_asset_id: nullableStringWithDefault,
    matching_node_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    matching_asset_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
  } satisfies StrictRecordFieldsFor<GuidanceCompletionProjectionV2>);
}

export function normalizeDecisionBundleV2(value: unknown, path = "decisionBundle"): DecisionBundleV2 {
  return normalizeStrictRecord(value, path, {
    bundle_id: expectNonEmptyString,
    workflow_id: expectNonEmptyString,
    conversation_id: expectNonEmptyString,
    source_turn_id: expectNonEmptyString,
    replacement_bundle_id: nullableStringWithDefault,
    status: (value, fieldPath) => expectLiteral(
      value,
      new Set<DecisionBundleV2["status"]>(["open", "answered", "skipped", "superseded"]),
      fieldPath,
    ),
    revision: expectPositiveInteger,
    title: expectNonEmptyString,
    introduction: expectNonEmptyString,
    questions: (value, fieldPath) => expectArray(value ?? [], fieldPath)
      .map((item, index) => normalizeDecisionBundleQuestionV2(item, `${fieldPath}[${index}]`)),
    answers: (value, fieldPath) => expectArray(value ?? [], fieldPath)
      .map((item, index) => normalizeDecisionBundleAnswerV2(item, `${fieldPath}[${index}]`)),
    requirement_revision_no: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectPositiveInteger(value, fieldPath),
    created_at: expectIsoDateTimeString,
    updated_at: expectIsoDateTimeString,
    closed_at: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectIsoDateTimeString(value, fieldPath),
  } satisfies StrictRecordFieldsFor<DecisionBundleV2>);
}

function normalizeDecisionBundleQuestionV2(value: unknown, path: string): DecisionBundleQuestionV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "question_id",
    "prompt",
    "selection_mode",
    "allow_custom_answer",
    "allow_skip",
    "options",
  ], path);
  return {
    question_id: expectNonEmptyString(record.question_id, `${path}.question_id`),
    prompt: expectNonEmptyString(record.prompt, `${path}.prompt`),
    selection_mode: expectLiteral(
      record.selection_mode,
      new Set<DecisionBundleQuestionV2["selection_mode"]>(["single", "multiple"]),
      `${path}.selection_mode`,
    ),
    allow_custom_answer: expectBoolean(record.allow_custom_answer, `${path}.allow_custom_answer`),
    allow_skip: expectBoolean(record.allow_skip, `${path}.allow_skip`),
    options: expectArray(record.options ?? [], `${path}.options`).map((item, index) => {
      const optionPath = `${path}.options[${index}]`;
      const option = expectRecord(item, optionPath);
      forbidUnknownFields(option, ["option_id", "label", "description", "effects"], optionPath);
      expectArray(option.effects ?? [], `${optionPath}.effects`).forEach((effect, effectIndex) => {
        const effectRecord = expectRecord(effect, `${optionPath}.effects[${effectIndex}]`);
        expectNonEmptyString(effectRecord.effect_type, `${optionPath}.effects[${effectIndex}].effect_type`);
      });
      return {
        option_id: expectNonEmptyString(option.option_id, `${optionPath}.option_id`),
        label: expectNonEmptyString(option.label, `${optionPath}.label`),
        description: expectNonEmptyString(option.description, `${optionPath}.description`),
      };
    }),
  };
}

function normalizeDecisionBundleAnswerV2(value: unknown, path: string): DecisionBundleAnswerV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["question_id", "selected_option_ids", "custom_answer", "skipped"], path);
  const selectedOptionIds = optionalStringArray(record.selected_option_ids, `${path}.selected_option_ids`, []);
  const customAnswer = record.custom_answer === undefined || record.custom_answer === null
    ? null
    : expectNonEmptyString(record.custom_answer, `${path}.custom_answer`);
  const skipped = record.skipped === undefined ? false : expectBoolean(record.skipped, `${path}.skipped`);
  if (Number(selectedOptionIds.length > 0) + Number(customAnswer !== null) + Number(skipped) !== 1) {
    fail(path, "expected exactly one answer form");
  }
  return {
    question_id: expectNonEmptyString(record.question_id, `${path}.question_id`),
    selected_option_ids: selectedOptionIds,
    custom_answer: customAnswer,
    skipped,
  };
}

export function normalizeDecisionBundleActionAcceptedV2(
  value: unknown,
  path = "decisionBundleAccepted",
): DecisionBundleActionAcceptedV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    bundle_id: expectNonEmptyString,
    status: (value, fieldPath) => expectLiteral(value, new Set(["answered", "skipped"] as const), fieldPath),
    revision: expectPositiveInteger,
    requirement_revision_no: (value, fieldPath) => expectPositiveInteger(
      value,
      fieldPath,
    ),
    turn_id: expectNonEmptyString,
    events_cursor: expectNonNegativeInteger,
    replayed: (value, fieldPath) => value === undefined ? false : expectBoolean(value, fieldPath),
  } satisfies StrictRecordFieldsFor<DecisionBundleActionAcceptedV2>);
}

export function normalizeGuidedSessionStateV2(value: unknown, path = "creativeSession"): GuidedSessionStateV2 {
  return normalizeStrictRecord(value, path, {
    session_id: expectNonEmptyString,
    workflow_id: expectNonEmptyString,
    status: (value, fieldPath) => expectLiteral(
      value,
      new Set<GuidedSessionStateV2["status"]>(["active", "paused", "completed"]),
      fieldPath,
    ),
    response_locale: (value, fieldPath) => value === undefined
      ? "und"
      : expectNonEmptyString(value, fieldPath),
    goal: normalizeCreativeGoalV2,
    creative_authority: (value, fieldPath) => value === undefined || value === null
      ? null
      : normalizeCreativeAuthorityStateV2(value, fieldPath),
    current_checkpoint: (value, fieldPath) => value === undefined || value === null
      ? null
      : normalizeGuidedStepCheckpointV2(value, fieldPath),
    narrative_direction: nullableStringWithDefault,
    element_decisions: (value, fieldPath) => expectArray(value ?? [], fieldPath)
      .map((item, index) => normalizeCreativeElementDecisionV2(item, `${fieldPath}[${index}]`)),
    current_topic_id: nullableStringWithDefault,
    topics: (value, fieldPath) => expectArray(value ?? [], fieldPath)
      .map((item, index) => normalizeGuidanceTopicStateV2(item, `${fieldPath}[${index}]`)),
    active_proposal_id: nullableStringWithDefault,
    active_style_skill_run_id: (value, fieldPath) => nullableStringWithDefault(
      value,
      fieldPath,
    ),
    completion: (value, fieldPath) => normalizeGuidanceCompletionProjectionV2(value ?? {}, fieldPath),
    journey: normalizeGuidedProductionJourneyV2,
    interaction: (value, fieldPath) => value === undefined || value === null
      ? null
      : normalizeGuidedInteractionV1(value, fieldPath),
    awaiting: (value, fieldPath) => value === undefined || value === null
      ? null
      : normalizeGuidanceAwaitingV1(value, fieldPath),
    actionable_failure: (value, fieldPath) => nullableActionableFailureV1(
      value,
      fieldPath,
    ),
    revision: expectPositiveInteger,
    updated_at: expectIsoDateTimeString,
  } satisfies StrictRecordFieldsFor<GuidedSessionStateV2>);
}

export function normalizeGuidanceAdvancePreconditionV1(
  value: unknown,
  path = "guidanceAdvancePrecondition",
): GuidanceAdvancePreconditionV1 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "schema_version",
    "workflow_id",
    "workflow_revision",
    "session_id",
    "session_revision",
    "session_status",
    "journey_stage",
    "journey_stage_status",
    "journey_stage_revision",
    "source_id",
    "requirement_revision_id",
    "requirement_digest",
    "active_action_digest",
    "owner_state_digest",
    "authority_digest",
  ], path);
  const digest = (field: "requirement_digest" | "active_action_digest" | "owner_state_digest") => {
    const value = expectNonEmptyString(record[field], `${path}.${field}`);
    if (!/^[a-f0-9]{64}$/.test(value)) fail(`${path}.${field}`, "expected a 64 character lowercase hexadecimal digest");
    return value;
  };
  const authorityDigest = expectNonEmptyString(record.authority_digest, `${path}.authority_digest`);
  if (!/^sha256:[a-f0-9]{64}$/.test(authorityDigest)) {
    fail(`${path}.authority_digest`, "expected sha256 digest");
  }
  return {
    schema_version: expectLiteral(record.schema_version, new Set(["1"] as const), `${path}.schema_version`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    workflow_revision: expectPositiveInteger(record.workflow_revision, `${path}.workflow_revision`),
    session_id: expectNonEmptyString(record.session_id, `${path}.session_id`),
    session_revision: expectPositiveInteger(record.session_revision, `${path}.session_revision`),
    session_status: expectLiteral(
      record.session_status,
      new Set<GuidanceAdvancePreconditionV1["session_status"]>(["active", "paused", "completed"]),
      `${path}.session_status`,
    ),
    journey_stage: expectLiteral(record.journey_stage, GUIDED_JOURNEY_STAGES, `${path}.journey_stage`),
    journey_stage_status: expectLiteral(
      record.journey_stage_status,
      GUIDED_JOURNEY_STAGE_STATUSES,
      `${path}.journey_stage_status`,
    ),
    journey_stage_revision: expectPositiveInteger(
      record.journey_stage_revision,
      `${path}.journey_stage_revision`,
    ),
    source_id: expectNonEmptyString(record.source_id, `${path}.source_id`),
    requirement_revision_id: expectNonEmptyString(record.requirement_revision_id, `${path}.requirement_revision_id`),
    requirement_digest: digest("requirement_digest"),
    active_action_digest: digest("active_action_digest"),
    owner_state_digest: digest("owner_state_digest"),
    authority_digest: authorityDigest,
  };
}

function normalizeGuidedInteractionV1(value: unknown, path: string): GuidedInteractionV1 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["interaction_id", "workflow_id", "session_id", "checkpoint_id", "kind", "status", "response_locale", "expected_session_revision", "revision", "title", "context", "content", "allowed_actions", "submit_path", "created_at", "updated_at"], path);
  const kind = expectLiteral(record.kind, new Set<GuidedInteractionV1["kind"]>(["clarification_questionnaire", "product_source", "reference_source", "concept_choice", "media_review"]), `${path}.kind`);
  const content = normalizeGuidedInteractionContentV1(record.content, kind, `${path}.content`);
  const allowedActions = expectArray(record.allowed_actions, `${path}.allowed_actions`).map((action, index) => expectLiteral(action, new Set<GuidedInteractionActionV1>(["answer", "select_source", "select", "custom", "skip", "revise", "defer", "exclude", "delegate", "accept", "retry", "replace", "use_reference", "skip_reference"]), `${path}.allowed_actions[${index}]`));
  if (
    kind === "reference_source"
    && (allowedActions.length !== 2
      || !allowedActions.includes("use_reference")
      || !allowedActions.includes("skip_reference"))
  ) {
    fail(
      `${path}.allowed_actions`,
      "reference source requires use_reference and skip_reference actions",
    );
  }
  return {
    interaction_id: expectNonEmptyString(record.interaction_id, `${path}.interaction_id`), workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`), session_id: expectNonEmptyString(record.session_id, `${path}.session_id`), checkpoint_id: expectNonEmptyString(record.checkpoint_id, `${path}.checkpoint_id`), kind,
    status: expectLiteral(record.status, new Set<GuidedInteractionV1["status"]>(["open", "submitted", "closed", "superseded"]), `${path}.status`), response_locale: expectNonEmptyString(record.response_locale, `${path}.response_locale`), expected_session_revision: expectPositiveInteger(record.expected_session_revision, `${path}.expected_session_revision`), revision: expectPositiveInteger(record.revision, `${path}.revision`), title: expectNonEmptyString(record.title, `${path}.title`), context: expectNonEmptyString(record.context, `${path}.context`), content,
    allowed_actions: allowedActions,
    submit_path: expectNonEmptyString(record.submit_path, `${path}.submit_path`), created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`), updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function normalizeGuidedInteractionContentV1(value: unknown, kind: GuidedInteractionV1["kind"], path: string): GuidedInteractionContentV1 {
  const record = expectRecord(value, path);
  const contentKind = record.content_kind === undefined
    ? kind === "clarification_questionnaire" ? "questionnaire" : kind
    : expectNonEmptyString(record.content_kind, `${path}.content_kind`);
  if (contentKind === "questionnaire") {
    forbidUnknownFields(record, ["content_kind", "questions"], path);
    const questions = expectArray(record.questions, `${path}.questions`).map((item, index) => normalizeGuidedQuestionV1(item, `${path}.questions[${index}]`));
    if (kind !== "clarification_questionnaire" || questions.length < 1 || questions.length > 4) fail(path, "invalid questionnaire interaction content");
    return { content_kind: "questionnaire", questions };
  }
  if (contentKind === "product_source") {
    forbidUnknownFields(record, [
      "content_kind",
      "input_kind",
      "question_id",
      "prompt",
      "expected_guidance_revision",
      "min_asset_count",
      "max_asset_count",
    ], path);
    if (kind !== "product_source") fail(path, "invalid Product source interaction content");
    const inputKind = expectLiteral(record.input_kind, new Set(["main", "multiview"] as const), `${path}.input_kind`);
    const minAssetCount = expectPositiveInteger(record.min_asset_count, `${path}.min_asset_count`);
    const maxAssetCount = expectPositiveInteger(record.max_asset_count, `${path}.max_asset_count`);
    const expectedCounts = inputKind === "main" ? [1, 1] : [2, 8];
    if (minAssetCount !== expectedCounts[0] || maxAssetCount !== expectedCounts[1]) {
      fail(path, "invalid Product source asset count contract");
    }
    return {
      content_kind: "product_source",
      input_kind: inputKind,
      question_id: expectNonEmptyString(record.question_id, `${path}.question_id`),
      prompt: expectNonEmptyString(record.prompt, `${path}.prompt`),
      expected_guidance_revision: expectPositiveInteger(
        record.expected_guidance_revision,
        `${path}.expected_guidance_revision`,
      ),
      min_asset_count: minAssetCount,
      max_asset_count: maxAssetCount,
    };
  }
  if (contentKind === "concept_choice") {
    forbidUnknownFields(record, [
      "content_kind",
      "proposal_id",
      "stage",
      "stage_revision",
      "action_id",
      "occurrence_id",
      "occurrence_index",
      "occurrence_count",
      "character_phase",
      "capability_id",
      "options",
      "allow_custom",
      "allow_exclusion",
    ], path);
    const options = expectArray(record.options, `${path}.options`).map((item, index) => normalizeGuidedChoiceOptionV1(item, `${path}.options[${index}]`));
    if (kind !== "concept_choice" || options.length !== 3) fail(path, "expected exactly three concept options");
    if (new Set(options.map((option) => option.option_id)).size !== options.length) {
      fail(`${path}.options`, "option IDs must be unique");
    }
    if (options.filter((option) => option.recommended).length !== 1) {
      fail(`${path}.options`, "expected exactly one recommended option");
    }
    const stage = expectLiteral(record.stage, GUIDED_JOURNEY_STAGES, `${path}.stage`);
    const allowCustom = expectBoolean(record.allow_custom, `${path}.allow_custom`);
    if (!allowCustom) fail(`${path}.allow_custom`, "expected true");
    const allowExclusion = expectBoolean(record.allow_exclusion, `${path}.allow_exclusion`);
    if (allowExclusion && !new Set<GuidedJourneyStageV2>(["world_view", "props", "character", "bgm"]).has(stage)) {
      fail(`${path}.allow_exclusion`, "exclusion is not allowed for this journey stage");
    }
    return {
      content_kind: "concept_choice",
      proposal_id: nullableStringWithDefault(record.proposal_id, `${path}.proposal_id`),
      stage,
      stage_revision: expectPositiveInteger(record.stage_revision, `${path}.stage_revision`),
      action_id: expectNonEmptyString(record.action_id, `${path}.action_id`),
      occurrence_id: nullableStringWithDefault(record.occurrence_id, `${path}.occurrence_id`),
      occurrence_index: record.occurrence_index === undefined || record.occurrence_index === null
        ? null
        : expectPositiveInteger(record.occurrence_index, `${path}.occurrence_index`),
      occurrence_count: record.occurrence_count === undefined || record.occurrence_count === null
        ? null
        : expectPositiveInteger(record.occurrence_count, `${path}.occurrence_count`),
      character_phase: record.character_phase === undefined || record.character_phase === null
        ? null
        : expectLiteral(record.character_phase, new Set(["main"] as const), `${path}.character_phase`),
      capability_id: expectNonEmptyString(record.capability_id, `${path}.capability_id`),
      options,
      allow_custom: true,
      allow_exclusion: allowExclusion,
    };
  }
  if (contentKind === "reference_source") {
    forbidUnknownFields(record, [
      "content_kind",
      "reference_kind",
      "target_node_id",
      "target_node_revision",
      "occurrence_id",
      "question",
      "use_reference_label",
      "skip_reference_label",
      "expected_guidance_revision",
    ], path);
    if (kind !== "reference_source") fail(path, "invalid reference source interaction content");
    const referenceKind = expectLiteral(
      record.reference_kind,
      new Set(["character_main", "scene_main"] as const),
      `${path}.reference_kind`,
    );
    const occurrenceId = nullableStringWithDefault(record.occurrence_id, `${path}.occurrence_id`);
    if (referenceKind === "character_main" && !occurrenceId) {
      fail(`${path}.occurrence_id`, "Character reference checkpoints require an occurrence identity");
    }
    if (referenceKind === "scene_main" && occurrenceId) {
      fail(`${path}.occurrence_id`, "Scene reference checkpoints cannot carry character scope");
    }
    return {
      content_kind: "reference_source",
      reference_kind: referenceKind,
      target_node_id: expectNonEmptyString(record.target_node_id, `${path}.target_node_id`),
      target_node_revision: expectPositiveInteger(record.target_node_revision, `${path}.target_node_revision`),
      occurrence_id: occurrenceId,
      question: expectNonEmptyString(record.question, `${path}.question`),
      use_reference_label: expectNonEmptyString(record.use_reference_label, `${path}.use_reference_label`),
      skip_reference_label: expectNonEmptyString(record.skip_reference_label, `${path}.skip_reference_label`),
      expected_guidance_revision: expectPositiveInteger(
        record.expected_guidance_revision,
        `${path}.expected_guidance_revision`,
      ),
    };
  }
  if (contentKind === "media_review") {
    forbidUnknownFields(record, ["content_kind", "node_id", "node_revision", "asset_id", "asset_version_id", "summary"], path);
    if (kind !== "media_review") fail(path, "invalid media review interaction content");
    return { content_kind: "media_review", node_id: expectNonEmptyString(record.node_id, `${path}.node_id`), node_revision: expectPositiveInteger(record.node_revision, `${path}.node_revision`), asset_id: expectNonEmptyString(record.asset_id, `${path}.asset_id`), asset_version_id: expectNonEmptyString(record.asset_version_id, `${path}.asset_version_id`), summary: expectNonEmptyString(record.summary, `${path}.summary`) };
  }
  fail(`${path}.content_kind`, "unknown guided interaction content");
}

function normalizeGuidedQuestionV1(value: unknown, path: string) {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["question_id", "prompt", "input_kind", "options", "allow_custom", "allow_skip", "required"], path);
  const options = expectArray(record.options, `${path}.options`).map((item, index) => normalizeGuidedChoiceOptionV1(item, `${path}.options[${index}]`));
  if (options.length < 2 || options.length > 4) fail(`${path}.options`, "expected 2-4 options");
  return { question_id: expectNonEmptyString(record.question_id, `${path}.question_id`), prompt: expectNonEmptyString(record.prompt, `${path}.prompt`), input_kind: "single_select" as const, options, allow_custom: record.allow_custom === undefined ? false : expectBoolean(record.allow_custom, `${path}.allow_custom`), allow_skip: record.allow_skip === undefined ? false : expectBoolean(record.allow_skip, `${path}.allow_skip`), required: record.required === undefined ? true : expectBoolean(record.required, `${path}.required`) };
}

function normalizeGuidedChoiceOptionV1(value: unknown, path: string) {
  return normalizeStrictRecord(value, path, {
    option_id: expectNonEmptyString,
    title: expectNonEmptyString,
    summary: expectNonEmptyString,
    difference_tags: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    recommended: (value, fieldPath) => value === undefined ? false : expectBoolean(value, fieldPath),
    reference_preview: (value, fieldPath) => expectArray(value ?? [], fieldPath).map((item, index) => normalizeGuidedReferencePreviewV1(item, `${fieldPath}[${index}]`)),
  } satisfies StrictRecordFieldsFor<Extract<GuidedInteractionContentV1, { content_kind: "concept_choice" }>["options"][number]>);
}

function normalizeGuidedReferencePreviewV1(value: unknown, path: string) {
  return normalizeStrictRecord(value, path, {
    source_kind: (value, fieldPath) => expectLiteral(value, new Set(["node", "image_asset"] as const), fieldPath),
    source_id: expectNonEmptyString,
    display_name: expectNonEmptyString,
    media_type: (value, fieldPath) => expectLiteral(value, new Set(["text", "image", "video", "audio"] as const), fieldPath),
  } satisfies StrictRecordFieldsFor<Extract<GuidedInteractionContentV1, { content_kind: "concept_choice" }>["options"][number]["reference_preview"][number]>);
}

function normalizeGuidanceAwaitingV1(value: unknown, path: string): GuidanceAwaitingV1 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["awaiting_id", "workflow_id", "session_id", "checkpoint_id", "kind", "requires_user_action", "resume_policy", "interaction_id", "node_ids", "stage", "stage_revision", "created_at"], path);
  const kind = expectLiteral(record.kind, new Set<GuidanceAwaitingV1["kind"]>(["clarification", "concept_selection", "product_source", "reference_source", "media_review", "manual_node_run", "milestone_idle"]), `${path}.kind`);
  const requiresUserAction = expectBoolean(record.requires_user_action, `${path}.requires_user_action`);
  const resumePolicy = expectLiteral(record.resume_policy, new Set<GuidanceAwaitingV1["resume_policy"]>(["submit_interaction", "node_terminal", "next_user_message", "explicit_resume"]), `${path}.resume_policy`);
  const interactionId = nullableStringWithDefault(record.interaction_id, `${path}.interaction_id`);
  const nodeIds = optionalStringArray(record.node_ids, `${path}.node_ids`, []);
  if (
    kind === "product_source"
    && (!requiresUserAction || resumePolicy !== "submit_interaction" || !interactionId || nodeIds.length !== 0)
  ) {
    fail(path, "invalid Product source awaiting authority");
  }
  if (
    kind === "reference_source"
    && (!requiresUserAction || resumePolicy !== "submit_interaction" || !interactionId || nodeIds.length !== 0)
  ) {
    fail(path, "invalid reference source awaiting authority");
  }
  return {
    awaiting_id: expectNonEmptyString(record.awaiting_id, `${path}.awaiting_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    session_id: expectNonEmptyString(record.session_id, `${path}.session_id`),
    checkpoint_id: expectNonEmptyString(record.checkpoint_id, `${path}.checkpoint_id`),
    kind,
    requires_user_action: requiresUserAction,
    resume_policy: resumePolicy,
    interaction_id: interactionId,
    node_ids: nodeIds,
    stage: expectLiteral(record.stage, GUIDED_JOURNEY_STAGES, `${path}.stage`),
    stage_revision: expectPositiveInteger(record.stage_revision, `${path}.stage_revision`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

export function normalizeGuidedInteractionAcceptedV1(value: unknown, path = "guidedInteractionAccepted"): GuidedInteractionAcceptedV1 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    interaction_id: expectNonEmptyString,
    submission_id: expectNonEmptyString,
    receipt_id: expectNonEmptyString,
    created_node_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    created_binding_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    document_revisions: normalizeDocumentRevisions,
    continuation_id: nullableStringWithDefault,
    automatic_run_command_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    resulting_session_revision: expectPositiveInteger,
    events_cursor: expectNonNegativeInteger,
    replayed: (value, fieldPath) => value === undefined ? false : expectBoolean(value, fieldPath),
  } satisfies StrictRecordFieldsFor<GuidedInteractionAcceptedV1>);
}

function normalizeGuidedProductionJourneyV2(
  value: unknown,
  path: string,
): GuidedProductionJourneyV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "policy_version",
    "journey_policy_id",
    "journey_policy_revision",
    "planning_wave_id",
    "stage",
    "stage_status",
    "stage_revision",
    "decisions",
    "active_occurrence_id",
    "active_action",
    "suspended_action",
    "transition_evidence",
  ], path);
  const decisions = expectArray(record.decisions ?? [], `${path}.decisions`)
    .map((item, index) => normalizeJourneyElementDecisionV2(item, `${path}.decisions[${index}]`));
  if (new Set(decisions.map((item) => item.decision_id)).size !== decisions.length) {
    fail(`${path}.decisions`, "decision IDs must be unique");
  }
  if (new Set(decisions.map((item) => item.occurrence_id)).size !== decisions.length) {
    fail(`${path}.decisions`, "occurrence IDs must be unique");
  }
  const stage = expectLiteral(record.stage, GUIDED_JOURNEY_STAGES, `${path}.stage`);
  const stageRevision = expectPositiveInteger(record.stage_revision, `${path}.stage_revision`);
  const activeAction = record.active_action === undefined || record.active_action === null
    ? null
    : normalizeJourneyActionProjectionV2(record.active_action, `${path}.active_action`);
  const suspendedAction = record.suspended_action === undefined || record.suspended_action === null
    ? null
    : normalizeJourneyActionProjectionV2(record.suspended_action, `${path}.suspended_action`);
  [activeAction, suspendedAction].forEach((action) => {
    if (action && (action.stage !== stage || action.stage_revision !== stageRevision)) {
      fail(path, "journey action does not belong to the current stage revision");
    }
  });
  const result: GuidedProductionJourneyV2 = {
    policy_version: expectLiteral(
      record.policy_version,
      new Set(["fixed_ad_production_v2"] as const),
      `${path}.policy_version`,
    ),
    stage,
    stage_status: expectLiteral(record.stage_status, GUIDED_JOURNEY_STAGE_STATUSES, `${path}.stage_status`),
    stage_revision: stageRevision,
    decisions,
    active_occurrence_id: nullableStringWithDefault(record.active_occurrence_id, `${path}.active_occurrence_id`),
    active_action: activeAction,
    suspended_action: suspendedAction,
    transition_evidence: expectArray(record.transition_evidence ?? [], `${path}.transition_evidence`)
      .map((item, index) => normalizeJourneyTransitionEvidenceV2(item, `${path}.transition_evidence[${index}]`)),
  };
  // Legacy sessions omit the policy metadata entirely; preserve that absence
  // instead of inventing null keys, while accepting explicit null projections.
  if (Object.prototype.hasOwnProperty.call(record, "journey_policy_id")) {
    result.journey_policy_id = record.journey_policy_id === null
      ? null
      : expectLiteral(
        record.journey_policy_id,
        new Set(["proposal_submit_auto_result_v1"] as const),
        `${path}.journey_policy_id`,
      );
  }
  if (Object.prototype.hasOwnProperty.call(record, "journey_policy_revision")) {
    if (record.journey_policy_revision === null) {
      result.journey_policy_revision = null;
    } else {
      const policyRevision = expectInteger(
        record.journey_policy_revision,
        `${path}.journey_policy_revision`,
      );
      if (policyRevision < 1 || policyRevision > 32) {
        fail(`${path}.journey_policy_revision`, "journey policy revision must be between 1 and 32");
      }
      result.journey_policy_revision = policyRevision;
    }
  }
  if (Object.prototype.hasOwnProperty.call(record, "planning_wave_id")) {
    result.planning_wave_id = record.planning_wave_id === null
      ? null
      : expectNonEmptyString(record.planning_wave_id, `${path}.planning_wave_id`);
    if (result.planning_wave_id && result.planning_wave_id.length > 160) {
      fail(`${path}.planning_wave_id`, "planning wave id cannot exceed 160 characters");
    }
  }
  return result;
}

function normalizeJourneyElementDecisionV2(value: unknown, path: string): JourneyElementDecisionV2 {
  return normalizeStrictRecord(value, path, {
    decision_id: expectNonEmptyString,
    element_kind: expectNonEmptyString,
    occurrence_id: expectNonEmptyString,
    occurrence_index: expectPositiveInteger,
    outcome: (value, fieldPath) => expectLiteral(value, JOURNEY_DECISION_OUTCOMES, fieldPath),
    source: (value, fieldPath) => expectLiteral(value, JOURNEY_DECISION_SOURCES, fieldPath),
    source_revision: expectPositiveInteger,
    requirements: (value, fieldPath) => expectRecordValue(value ?? {}, fieldPath),
  } satisfies StrictRecordFieldsFor<JourneyElementDecisionV2>);
}

function normalizeJourneyActionProjectionV2(value: unknown, path: string): JourneyActionProjectionV2 {
  return normalizeStrictRecord(value, path, {
    action_id: expectNonEmptyString,
    action_kind: expectNonEmptyString,
    stage: (value, fieldPath) => expectLiteral(value, GUIDED_JOURNEY_STAGES, fieldPath),
    stage_revision: expectPositiveInteger,
    status: (value, fieldPath) => expectLiteral(value, JOURNEY_ACTION_STATUSES, fieldPath),
    turn_id: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectNonEmptyString(value, fieldPath),
    occurrence_id: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectNonEmptyString(value, fieldPath),
    character_phase: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectLiteral(value, new Set(["main", "turnaround"] as const), fieldPath),
  } satisfies StrictRecordFieldsFor<JourneyActionProjectionV2>);
}

function normalizeJourneyTransitionEvidenceV2(
  value: unknown,
  path: string,
): JourneyTransitionEvidenceV2 {
  return normalizeStrictRecord(value, path, {
    evidence_id: expectNonEmptyString,
    evidence_kind: (value, fieldPath) => expectLiteral(value, JOURNEY_EVIDENCE_KINDS, fieldPath),
    source_id: expectNonEmptyString,
    source_revision: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectPositiveInteger(value, fieldPath),
    stage: (value, fieldPath) => expectLiteral(value, GUIDED_JOURNEY_STAGES, fieldPath),
    stage_revision: expectPositiveInteger,
    occurrence_id: nullableStringWithDefault,
    character_phase: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectLiteral(value, new Set(["main", "turnaround"] as const), fieldPath),
    actor: (value, fieldPath) => value === undefined
      ? "system"
      : expectLiteral(value, JOURNEY_DECISION_SOURCES, fieldPath),
    recorded_at: expectIsoDateTimeString,
  } satisfies StrictRecordFieldsFor<JourneyTransitionEvidenceV2>);
}

function normalizeGuidanceSessionActionV2(
  value: unknown,
  path: string,
): GuidanceSessionActionV2 {
  return normalizeStrictRecord(value, path, {
    action_id: expectNonEmptyString,
    logical_key: expectNonEmptyString,
    action: (value, fieldPath) => expectLiteral(
      value,
      new Set<GuidanceSessionActionV2["action"]>([
        "stop_guidance",
        "resume_guidance",
        "set_creative_authority",
      ]),
      fieldPath,
    ),
    state: (value, fieldPath) => expectLiteral(
      value,
      new Set<GuidanceSessionActionV2["state"]>(["pending", "applying", "applied", "superseded", "failed"]),
      fieldPath,
    ),
    creating_turn_id: expectNonEmptyString,
    expected_session_revision: expectPositiveInteger,
    label: expectNonEmptyString,
    workflow_id: expectNonEmptyString,
    confirmation_required: expectBoolean,
    reason: expectNonEmptyString,
    authority: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectLiteral(value, new Set(["user", "director"] as const), fieldPath),
  } satisfies StrictRecordFieldsFor<GuidanceSessionActionV2>);
}

function normalizeCreativeAuthorityStateV2(
  value: unknown,
  path: string,
): GuidedSessionStateV2["creative_authority"] {
  return normalizeStrictRecord(value, path, {
    authority: (value, fieldPath) => expectLiteral(value, new Set(["user", "director"] as const), fieldPath),
    source: (value, fieldPath) => expectLiteral(
      value,
      new Set(["explicit_user", "explicit_delegation", "director_inference"] as const),
      fieldPath,
    ),
    decided_at_turn_id: expectNonEmptyString,
    revision: expectPositiveInteger,
  } satisfies StrictRecordFieldsFor<GuidedSessionStateV2["creative_authority"]>);
}

function normalizeGuidedStepCheckpointV2(
  value: unknown,
  path: string,
): GuidedSessionStateV2["current_checkpoint"] {
  return normalizeStrictRecord(value, path, {
    checkpoint_id: expectNonEmptyString,
    workflow_id: expectNonEmptyString,
    session_revision: expectPositiveInteger,
    stage_kind: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectLiteral(
        value,
        new Set([
          "world_setting", "narrative_direction", "product", "prop", "character", "scene",
          "script", "storyboard", "video", "bgm", "editing",
        ] as const),
        fieldPath,
      ),
    status: (value, fieldPath) => expectLiteral(
      value,
      new Set(["pending", "waiting_user", "completed", "failed", "superseded"] as const),
      fieldPath,
    ),
    trigger: (value, fieldPath) => expectLiteral(
      value,
      new Set(["user_message", "proposal_action", "continuation", "recovery"] as const),
      fieldPath,
    ),
    action_id: nullableStringWithDefault,
  } satisfies StrictRecordFieldsFor<GuidedSessionStateV2["current_checkpoint"]>);
}

function normalizeCreationModeDecisionV2(
  value: unknown,
  path: string,
): CreationModeDecisionV2 {
  return normalizeStrictRecord(value, path, {
    mode: (value, fieldPath) => expectLiteral(value, CREATION_MODES, fieldPath),
    reason: expectNonEmptyString,
    target_node_id: nullableStringWithDefault,
    target_asset_id: nullableStringWithDefault,
  } satisfies StrictRecordFieldsFor<CreationModeDecisionV2>);
}

function normalizeAgentCanvasChatTimelineEntryV2(
  value: unknown,
  path: string,
  additionalAllowedFields: readonly string[] = [],
): AgentCanvasChatTimelineEntryV2 {
  const entry = expectRecord(value, path);
  forbidUnknownFields(
    entry,
    [
      "entry_id",
      "workflow_id",
      "conversation_id",
      "sequence_no",
      "entry_type",
      "speaker",
      "content",
      "metadata",
      "command_plan",
      "action_receipt",
      "actionable_failure",
      "created_at",
      ...additionalAllowedFields,
    ],
    path,
  );
  const entryType = expectString(entry.entry_type, `${path}.entry_type`);
  if (
    entryType !== "message"
    && entryType !== "script_artifact"
    && entryType !== "concept_proposal"
    && entryType !== "expert_activity"
    && entryType !== "planning_progress"
    && entryType !== "command_plan"
    && entryType !== "action_receipt"
    && entryType !== "agent_document_reference"
    && entryType !== "decision_bundle"
  ) {
    fail(`${path}.entry_type`, "invalid timeline entry type");
  }
  const speaker = entry.speaker === null
    ? null
    : expectLiteral(entry.speaker, CHAT_MESSAGE_SPEAKERS, `${path}.speaker`);
  if (entryType === "message" && speaker === null) {
    fail(`${path}.speaker`, "message requires speaker");
  }
  return {
    entry_id: expectNonEmptyString(entry.entry_id, `${path}.entry_id`),
    workflow_id: expectNonEmptyString(entry.workflow_id, `${path}.workflow_id`),
    conversation_id: expectNonEmptyString(entry.conversation_id, `${path}.conversation_id`),
    sequence_no: expectPositiveInteger(entry.sequence_no, `${path}.sequence_no`),
    entry_type: entryType,
    speaker,
    content: expectString(entry.content, `${path}.content`),
    metadata: optionalUnknownRecord(entry.metadata, `${path}.metadata`, {}),
    command_plan: entry.command_plan === null || entry.command_plan === undefined
      ? null
      : normalizeAgentCommandPlanV2(entry.command_plan, `${path}.command_plan`),
    action_receipt: entry.action_receipt === null || entry.action_receipt === undefined
      ? null
      : normalizeAgentActionReceiptV2(entry.action_receipt, `${path}.action_receipt`),
    actionable_failure: nullableActionableFailureV1(
      entry.actionable_failure,
      `${path}.actionable_failure`,
    ),
    created_at: expectIsoDateTimeString(entry.created_at, `${path}.created_at`),
  };
}

function normalizeAgentCanvasChatTimelinePresentationItemV2(
  value: unknown,
  path: string,
): AgentCanvasChatTimelinePresentationItemV2 {
  const entry = normalizeAgentCanvasChatTimelineEntryV2(value, path, [
    "presentation_key",
    "presentation_revision",
    "source_entry_ids",
    "message_key",
    "message_args",
    "response_locale",
  ]);
  const record = expectRecord(value, path);
  const sourceEntryIds = expectArray(record.source_entry_ids, `${path}.source_entry_ids`)
    .map((sourceEntryId, index) => expectNonEmptyString(
      sourceEntryId,
      `${path}.source_entry_ids[${index}]`,
    ));
  if (sourceEntryIds.length === 0) {
    fail(`${path}.source_entry_ids`, "expected at least one source entry");
  }
  return {
    ...entry,
    presentation_key: expectNonEmptyString(record.presentation_key, `${path}.presentation_key`),
    presentation_revision: expectPositiveInteger(record.presentation_revision, `${path}.presentation_revision`),
    source_entry_ids: sourceEntryIds,
    message_key: record.message_key === undefined || record.message_key === null
      ? null
      : expectNonEmptyString(record.message_key, `${path}.message_key`),
    message_args: optionalUnknownRecord(record.message_args, `${path}.message_args`, {}),
    response_locale: record.response_locale === undefined
      ? "und"
      : expectNonEmptyString(record.response_locale, `${path}.response_locale`),
  };
}

export function normalizeAgentCanvasChatTimelineResponseV2(
  value: unknown,
  path = "chatTimeline",
): AgentCanvasChatTimelineResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "workflow_id",
    "conversation_id",
    "guidance_session",
    "guidance_advance_precondition",
    "continuations",
    "current_session_actions",
    "items",
    "presentation_items",
    "next_cursor",
  ], path);
  const currentSessionActions = expectArray(
    record.current_session_actions ?? [],
    `${path}.current_session_actions`,
  ).map((item, index) => normalizeGuidanceSessionActionV2(
    item,
    `${path}.current_session_actions[${index}]`,
  ));
  if (currentSessionActions.length > 2) {
    fail(`${path}.current_session_actions`, "expected at most 2 actions");
  }
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    conversation_id: record.conversation_id === null
      ? null
      : expectNonEmptyString(record.conversation_id, `${path}.conversation_id`),
    guidance_session: record.guidance_session === undefined || record.guidance_session === null
      ? null
      : normalizeGuidedSessionStateV2(record.guidance_session, `${path}.guidance_session`),
    guidance_advance_precondition: record.guidance_advance_precondition === undefined || record.guidance_advance_precondition === null
      ? null
      : normalizeGuidanceAdvancePreconditionV1(
        record.guidance_advance_precondition,
        `${path}.guidance_advance_precondition`,
      ),
    continuations: expectArray(record.continuations ?? [], `${path}.continuations`)
      .map((item, index) => normalizeAgentCanvasContinuationV2(item, `${path}.continuations[${index}]`)),
    current_session_actions: currentSessionActions,
    items: expectArray(record.items ?? [], `${path}.items`).map((item, index) => (
      normalizeAgentCanvasChatTimelineEntryV2(item, `${path}.items[${index}]`)
    )),
    presentation_items: record.presentation_items === undefined
      ? null
      : expectArray(record.presentation_items, `${path}.presentation_items`).map((item, index) => (
        normalizeAgentCanvasChatTimelinePresentationItemV2(
          item,
          `${path}.presentation_items[${index}]`,
        )
      )),
    next_cursor: expectNonNegativeInteger(record.next_cursor, `${path}.next_cursor`),
  };
}

export function normalizeChatTurnAcceptedV2(
  value: unknown,
  path = "chatAccepted",
): ChatTurnAcceptedV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "workflow_id",
      "conversation_id",
      "message_id",
      "turn_id",
      "status",
      "events_cursor",
      "retry_of_turn_id",
      "retry_attempt_no",
      "replayed",
      "presentation_stream_id",
    ],
    path,
  );
  if (record.status !== "queued") fail(`${path}.status`, "expected queued");
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    conversation_id: expectNonEmptyString(record.conversation_id, `${path}.conversation_id`),
    message_id: record.message_id === null
      ? null
      : expectNonEmptyString(record.message_id, `${path}.message_id`),
    turn_id: expectNonEmptyString(record.turn_id, `${path}.turn_id`),
    status: "queued",
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
    retry_of_turn_id: record.retry_of_turn_id === undefined
      ? null
      : nullableString(record.retry_of_turn_id, `${path}.retry_of_turn_id`),
    retry_attempt_no: record.retry_attempt_no === undefined
      ? 1
      : expectPositiveInteger(record.retry_attempt_no, `${path}.retry_attempt_no`),
    replayed: record.replayed === undefined
      ? false
      : expectBoolean(record.replayed, `${path}.replayed`),
    presentation_stream_id: nullableStringWithDefault(
      record.presentation_stream_id,
      `${path}.presentation_stream_id`,
    ),
  };
}

export function normalizeAgentCanvasChatTurnV2(
  value: unknown,
  path = "chatTurn",
): AgentCanvasChatTurnV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "turn_id",
      "workflow_id",
      "conversation_id",
      "status",
      "turn_kind",
      "request",
      "error_code",
      "error_message",
      "creation_mode",
      "guidance_session_revision",
      "continuation",
      "retry_of_turn_id",
      "retry_attempt_no",
      "retryable",
      "actionable_failure",
      "operation_stage",
      "operation_failure",
      "created_at",
      "updated_at",
    ],
    path,
  );
  const status = expectString(record.status, `${path}.status`);
  if (!["queued", "running", "completed", "failed", "superseded"].includes(status)) {
    fail(`${path}.status`, "invalid chat turn status");
  }
  const turnKind = expectString(record.turn_kind, `${path}.turn_kind`);
  if (
    turnKind !== "message"
    && turnKind !== "proposal_action"
    && turnKind !== "command_action"
    && turnKind !== "guided_action"
    && turnKind !== "capability"
    && turnKind !== "next_action"
    && turnKind !== "guidance_advance"
  ) {
    fail(`${path}.turn_kind`, "invalid chat turn kind");
  }
  const retryable = record.retryable === undefined
    ? false
    : expectBoolean(record.retryable, `${path}.retryable`);
  if (status === "superseded" && retryable) {
    fail(`${path}.retryable`, "superseded turns are terminal and non-retryable");
  }
  const actionableFailure = nullableActionableFailureV1(
    record.actionable_failure,
    `${path}.actionable_failure`,
  );
  if (actionableFailure && retryable !== actionableFailure.retryable) {
    fail(`${path}.retryable`, "retryable must match the actionable failure disposition");
  }
  return {
    turn_id: expectNonEmptyString(record.turn_id, `${path}.turn_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    conversation_id: expectNonEmptyString(record.conversation_id, `${path}.conversation_id`),
    status: status as AgentCanvasChatTurnV2["status"],
    turn_kind: turnKind,
    request: expectUnknownRecord(record.request, `${path}.request`),
    error_code: nullableString(record.error_code, `${path}.error_code`),
    error_message: nullableString(record.error_message, `${path}.error_message`),
    creation_mode: record.creation_mode === undefined || record.creation_mode === null
      ? null
      : normalizeCreationModeDecisionV2(record.creation_mode, `${path}.creation_mode`),
    guidance_session_revision: record.guidance_session_revision === undefined
      || record.guidance_session_revision === null
      ? null
      : expectPositiveInteger(record.guidance_session_revision, `${path}.guidance_session_revision`),
    continuation: record.continuation === undefined || record.continuation === null
      ? null
      : normalizeAgentCanvasContinuationV2(record.continuation, `${path}.continuation`),
    retry_of_turn_id: record.retry_of_turn_id === undefined
      ? null
      : nullableString(record.retry_of_turn_id, `${path}.retry_of_turn_id`),
    retry_attempt_no: record.retry_attempt_no === undefined
      ? 1
      : expectPositiveInteger(record.retry_attempt_no, `${path}.retry_attempt_no`),
    retryable,
    actionable_failure: actionableFailure,
    operation_stage: record.operation_stage === undefined
      ? null
      : nullableString(record.operation_stage, `${path}.operation_stage`),
    operation_failure: record.operation_failure === undefined || record.operation_failure === null
      ? null
      : normalizeAgentOperationFailureV2(record.operation_failure, `${path}.operation_failure`),
    created_at: expectNonEmptyString(record.created_at, `${path}.created_at`),
    updated_at: expectNonEmptyString(record.updated_at, `${path}.updated_at`),
  };
}

export function normalizeAgentCanvasVideoSkillRunV2(
  value: unknown,
  path = "videoSkillRun",
): AgentCanvasVideoSkillRunV2 {
  return normalizeStrictRecord(value, path, {
    skill_run_id: expectNonEmptyString,
    workflow_id: expectNonEmptyString,
    skill_id: expectNonEmptyString,
    skill_version: expectNonEmptyString,
    source_skill_run_id: (value, fieldPath) => value === undefined
      ? null
      : nullableString(value, fieldPath),
    status: (value, fieldPath) => expectLiteral(
      value ?? "active",
      new Set<AgentCanvasVideoSkillRunV2["status"]>(["active", "superseded"]),
      fieldPath,
    ),
    active_creative_direction_snapshot_id: (value, fieldPath) => nullableStringWithDefault(
      value,
      fieldPath,
    ),
    public_skill: (value, fieldPath) => value === undefined || value === null
      ? null
      : normalizeVideoSkillPublicDetailV2(value, fieldPath),
    created_at: expectIsoDateTimeString,
    updated_at: (value, fieldPath) => value === undefined || value === null
      ? null
      : expectIsoDateTimeString(value, fieldPath),
  } satisfies StrictRecordFieldsFor<AgentCanvasVideoSkillRunV2>);
}

export function normalizeCanvasRunAcceptedV2(
  value: unknown,
  path = "runAccepted",
): CanvasRunAcceptedV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "workflow_id",
      "execution_id",
      "status",
      "accepted_node_ids",
      "joined_node_ids",
      "skipped",
      "waiting_node_ids",
      "run_intent_snapshot_ids",
      "events_cursor",
    ],
    path,
  );
  const runIntentSnapshotIdsRecord = expectRecord(
    record.run_intent_snapshot_ids ?? {},
    `${path}.run_intent_snapshot_ids`,
  );
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    execution_id: expectNonEmptyString(record.execution_id, `${path}.execution_id`),
    status: expectLiteral(record.status, CANVAS_EXECUTION_STATUSES, `${path}.status`),
    accepted_node_ids: expectStringArray(record.accepted_node_ids, `${path}.accepted_node_ids`),
    joined_node_ids: expectStringArray(record.joined_node_ids, `${path}.joined_node_ids`),
    skipped: expectArray(record.skipped, `${path}.skipped`).map((item, index) => {
      const skipped = expectRecord(item, `${path}.skipped[${index}]`);
      forbidUnknownFields(skipped, ["node_id", "reason"], `${path}.skipped[${index}]`);
      return {
        node_id: expectNonEmptyString(skipped.node_id, `${path}.skipped[${index}].node_id`),
        reason: expectNonEmptyString(skipped.reason, `${path}.skipped[${index}].reason`),
      };
    }),
    waiting_node_ids: expectStringArray(record.waiting_node_ids, `${path}.waiting_node_ids`),
    run_intent_snapshot_ids: Object.fromEntries(
      Object.entries(runIntentSnapshotIdsRecord).map(([nodeId, snapshotId]) => [
        nodeId,
        expectNonEmptyString(snapshotId, `${path}.run_intent_snapshot_ids.${nodeId}`),
      ]),
    ),
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
  };
}

export function normalizeCanvasRunCancelResponseV2(
  value: unknown,
  path = "runCancel",
): CanvasRunCancelResponseV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    execution_id: expectNonEmptyString,
    status: (value, fieldPath) => expectLiteral(value, new Set<CanvasRunCancelResponseV2["status"]>(["cancelled"]), fieldPath),
    cancelled_node_ids: (value, fieldPath) => optionalStringArray(value, fieldPath, []),
    events_cursor: expectNonNegativeInteger,
  } satisfies StrictRecordFieldsFor<CanvasRunCancelResponseV2>);
}

export function normalizeCanvasRuntimeEventsResponseV2(
  value: unknown,
  path = "events",
): CanvasRuntimeEventsResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["items", "next_cursor"], path);
  return {
    workflow_id: null,
    events: expectArray(record.items, `${path}.items`).map((item, index) =>
      normalizeCanvasRuntimeEventV2(item, `${path}.items[${index}]`),
    ),
    next_cursor: expectNonNegativeInteger(record.next_cursor, `${path}.next_cursor`),
  };
}

export function normalizeEditingExportAcceptedV2(
  value: unknown,
  path = "editingExportAccepted",
): EditingExportAcceptedV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    node_id: expectNonEmptyString,
    export_id: expectNonEmptyString,
    status: (value, fieldPath) => expectLiteral(value, EDITING_EXPORT_STATUSES, fieldPath),
    manifest_revision: expectNonNegativeInteger,
    ready_video_node_ids: expectStringArray,
    skipped_inputs: (value, fieldPath) => expectArray(value, fieldPath).map((item, index) =>
      normalizeEditingSkippedInputV2(item, `${fieldPath}[${index}]`),
    ),
    bgm_node_id: nullableString,
    events_cursor: expectNonNegativeInteger,
  } satisfies StrictRecordFieldsFor<EditingExportAcceptedV2>);
}

export function normalizeEditingExportCancelResponseV2(
  value: unknown,
  path = "editingExportCancel",
): EditingExportCancelResponseV2 {
  return normalizeStrictRecord(value, path, {
    workflow_id: expectNonEmptyString,
    node_id: expectNonEmptyString,
    export_id: expectNonEmptyString,
    status: (value, fieldPath) => expectLiteral(value, new Set<EditingExportCancelResponseV2["status"]>(["cancelled"]), fieldPath),
    events_cursor: expectNonNegativeInteger,
  } satisfies StrictRecordFieldsFor<EditingExportCancelResponseV2>);
}


// Read-only, role-filtered guided reference candidates for one Main Draft.
const GUIDED_REFERENCE_KINDS = new Set<GuidedReferenceCandidateV2["reference_kind"]>([
  "character_main",
  "scene_main",
]);
const GUIDED_REFERENCE_SCOPES = new Set<GuidedReferenceCandidateListResponseV2["scope"]>([
  "project",
  "mine",
  "recommended",
]);

function isBrowserSafeUrl(value: string): boolean {
  return value.startsWith("/api/") || value.startsWith("https://") || value.startsWith("http://");
}

function normalizeGuidedReferenceCandidateV2(
  value: unknown,
  scope: GuidedReferenceCandidateListResponseV2["scope"],
  path: string,
): GuidedReferenceCandidateV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "entity_id",
    "member_id",
    "asset_id",
    "asset_version_id",
    "media_type",
    "display_name",
    "preview_url",
    "content_url",
    "reference_kind",
    "semantic_reference_role",
    "reference_purpose",
    "selectable",
  ], path);
  const itemReferenceKind = expectLiteral(
    record.reference_kind,
    GUIDED_REFERENCE_KINDS,
    `${path}.reference_kind`,
  );
  const expectedRole = itemReferenceKind === "character_main"
    ? "character_reference"
    : "scene_reference";
  const expectedPurpose = itemReferenceKind === "character_main"
    ? "identity_guidance"
    : "environment_guidance";
  const semanticReferenceRole = expectLiteral(
    record.semantic_reference_role,
    new Set(["character_reference", "scene_reference"]),
    `${path}.semantic_reference_role`,
  );
  const referencePurpose = expectLiteral(
    record.reference_purpose,
    new Set(["identity_guidance", "environment_guidance"]),
    `${path}.reference_purpose`,
  );
  if (semanticReferenceRole !== expectedRole || referencePurpose !== expectedPurpose) {
    fail(
      `${path}.semantic_reference_role`,
      "Reference candidate role and purpose do not match its kind.",
    );
  }
  const entityId = nullableStringWithDefault(record.entity_id, `${path}.entity_id`);
  const memberId = nullableStringWithDefault(record.member_id, `${path}.member_id`);
  if (scope === "project" && (entityId !== null || memberId !== null)) {
    fail(`${path}.entity_id`, "Project references cannot carry catalog provenance.");
  }
  if (scope !== "project" && (entityId === null || memberId === null)) {
    fail(`${path}.entity_id`, "Catalog references require entity and member provenance.");
  }
  const mediaType = expectLiteral(
    record.media_type,
    new Set(["image"] as const),
    `${path}.media_type`,
  );
  const previewUrl = expectNonEmptyString(record.preview_url, `${path}.preview_url`);
  if (!isBrowserSafeUrl(previewUrl)) fail(`${path}.preview_url`, "URLs must be browser-safe");
  const contentUrl = expectNonEmptyString(record.content_url, `${path}.content_url`);
  if (!isBrowserSafeUrl(contentUrl)) fail(`${path}.content_url`, "URLs must be browser-safe");
  const assetId = expectNonEmptyString(record.asset_id, `${path}.asset_id`);
  const assetVersionId = expectNonEmptyString(record.asset_version_id, `${path}.asset_version_id`);
  return {
    entity_id: entityId,
    member_id: memberId,
    asset_id: assetId,
    asset_version_id: assetVersionId,
    media_type: mediaType,
    display_name: expectNonEmptyString(record.display_name, `${path}.display_name`),
    preview_url: previewUrl,
    content_url: contentUrl,
    reference_kind: itemReferenceKind,
    semantic_reference_role: semanticReferenceRole,
    reference_purpose: referencePurpose,
    selectable: record.selectable === undefined
      ? true
      : expectBoolean(record.selectable, `${path}.selectable`),
  };
}

export function normalizeGuidedReferenceCandidateListResponseV2(
  value: unknown,
  path = "referenceCandidates",
): GuidedReferenceCandidateListResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "reference_kind", "scope", "items", "next_cursor"], path);
  const referenceKind = expectLiteral(
    record.reference_kind,
    GUIDED_REFERENCE_KINDS,
    `${path}.reference_kind`,
  );
  const scope = expectLiteral(record.scope, GUIDED_REFERENCE_SCOPES, `${path}.scope`);
  const items = expectArray(record.items, `${path}.items`).map((item, index) => (
    normalizeGuidedReferenceCandidateV2(item, scope, `${path}.items[${index}]`)
  ));
  if (items.length > 100) fail(`${path}.items`, "a candidate page cannot exceed 100 items");
  const uniqueKeys = new Set(items.map((item) => `${item.asset_id}:${item.asset_version_id}`));
  if (uniqueKeys.size !== items.length) {
    fail(`${path}.items`, "Reference candidates must be unique by exact AssetVersion identity");
  }
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    reference_kind: referenceKind,
    scope,
    items,
    next_cursor: record.next_cursor === null || record.next_cursor === undefined
      ? null
      : expectNonEmptyString(record.next_cursor, `${path}.next_cursor`),
  };
}