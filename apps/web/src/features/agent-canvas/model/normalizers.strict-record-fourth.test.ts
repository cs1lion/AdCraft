import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import * as actual from './normalizers.ts';
import { normalizeStrictRecord, type StrictRecordFieldsFor } from './strictRecordFields.ts';
import { V2ContractValidationError } from '../../../api/v2ContractValidationError.ts';
import type {
  AgentCanvasCreationModeV2,
  AgentDocumentLinkedNodeRuntimeV2,
  AgentAnchorNodeSourceV3,
  AgentAnchorRoleSourceV3,
  AnchorAcceptanceEvidenceV1,
  CanvasExecutionStatusV2,
  CanvasPostReadyCheckpointStatusV2,
  CanvasPostReadyCheckpointV2,
  CanvasPostReadyEffectStatusV2,
  CanvasPostReadyEffectSummaryV2,
  CanvasPostReadyEffectTypeV2,
  CanvasNodeErrorV2,
  ActionableFailureV1,
  CanvasNodeStatusV2,
  CanvasNodeTypeV2,
  CanvasParameterProvenanceV2,
  CreationModeDecisionV2,
  ProposalApplicationSummaryV2,
  GuidanceSessionActionV2,
  GuidedJourneyStageStatusV2,
  GuidedJourneyStageV2,
  GuidedProductionJourneyV2,
  GuidedSessionStateV2,
  JourneyElementDecisionV2,
  JourneyActionProjectionV2,
  JourneyTransitionEvidenceV2,
  ProposalActionDescriptorV2,
  ProposalMaterializationErrorV2,
  ProposalMaterializationProjectionV2,
  StoryboardNodeRecordV2,
  StoryboardPlanGlobalParametersV2,
  StoryboardPlannedNodeV3,
  StoryboardExcludedMediaV3,
  StoryboardVisualAnchorV3,
  StoryboardSegmentMaterializationV2,
  StoryboardSegmentMaterializationV3,
  StoryboardVisualAnchorV2,
  VideoParameterNormalizationV2,
} from "../../../types-v2.ts";

// Frozen dependency closure copied from the dirty working tree before edits, not HEAD.
// Selected children call their own frozen bodies; no current normalizer is an oracle.
// All scalar validators/enums and nested validators below are also frozen.
type JsonRecord = Record<string, unknown>;

const CANVAS_NODE_TYPES = new Set<CanvasNodeTypeV2>(["text", "script", "image", "video", "audio", "editing", "scene-3d", "voice-cast", "replica"]);

const CANVAS_NODE_STATUSES = new Set<CanvasNodeStatusV2>(["draft", "working", "ready", "failed"]);

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

const CREATION_MODES = new Set<AgentCanvasCreationModeV2>([
  "ordinary_conversation",
  "targeted_authoring",
  "quick_media",
  "guided_production",
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

function nullableString(value: unknown, path: string) {
  if (value === null) return null;
  return expectString(value, path);
}

function expectBoolean(value: unknown, path: string) {
  if (typeof value !== "boolean") fail(path, "expected boolean");
  return value;
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

function nullableStringWithDefault(value: unknown, path: string) {
  return value === undefined ? null : nullableString(value, path);
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

function expectRecordValue(value: unknown, path: string) {
  return expectRecord(value, path);
}

function expectArray(value: unknown, path: string) {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value;
}

function expectIsoDateTimeString(value: unknown, path: string) {
  return expectNonEmptyString(value, path);
}

function normalizeActionableFailureV1(value: unknown, path = "actionableFailure"): ActionableFailureV1 {
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

function normalizeCanvasNodeErrorV2(value: unknown, path = "error"): CanvasNodeErrorV2 {
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

function normalizeCanvasParameterScalarV2(
  value: unknown,
  path: string,
): CanvasParameterProvenanceV2["requested_value"] {
  if (typeof value === "string" || typeof value === "boolean") return value;
  return expectFiniteNumber(value, path);
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
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["aspect_ratio", "total_duration_seconds", "segment_count"], path);
  return {
    aspect_ratio: expectNonEmptyString(record.aspect_ratio, `${path}.aspect_ratio`),
    total_duration_seconds: boundedNumber(
      record.total_duration_seconds,
      `${path}.total_duration_seconds`,
      0,
      3600,
      true,
    ),
    segment_count: boundedInteger(record.segment_count, `${path}.segment_count`, 1, 128),
  };
}

function normalizeStoryboardNodeRecordV2(value: unknown, path: string): StoryboardNodeRecordV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["sequence_id", "node_role", "node_id"], path);
  return {
    sequence_id: nullableStringWithDefault(record.sequence_id, `${path}.sequence_id`),
    node_role: expectLiteral(
      record.node_role,
      new Set<StoryboardNodeRecordV2["node_role"]>([
        "storyboard_grid",
        "video_segment",
        "bgm",
        "editing",
      ]),
      `${path}.node_role`,
    ),
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
  };
}

function normalizeStoryboardSegmentMaterializationV2(
  value: unknown,
  path: string,
): StoryboardSegmentMaterializationV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["sequence_id", "status", "generation_prompt"], path);
  return {
    sequence_id: expectNonEmptyString(record.sequence_id, `${path}.sequence_id`),
    status: record.status === undefined
      ? "pending"
      : expectLiteral(record.status, STORYBOARD_SEGMENT_MATERIALIZATION_STATUSES, `${path}.status`),
    generation_prompt: nullableStringWithDefault(
      record.generation_prompt,
      `${path}.generation_prompt`,
    ),
  };
}

function normalizeStoryboardVisualAnchorV2(
  value: unknown,
  path: string,
): StoryboardVisualAnchorV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["node_id", "asset_id", "node_revision", "document_revision"], path);
  return {
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    asset_id: expectNonEmptyString(record.asset_id, `${path}.asset_id`),
    node_revision: expectPositiveInteger(record.node_revision, `${path}.node_revision`),
    document_revision: expectPositiveInteger(record.document_revision, `${path}.document_revision`),
  };
}

function normalizeAgentAnchorNodeSourceV3(
  value: unknown,
  path: string,
): AgentAnchorNodeSourceV3 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["source_kind", "workflow_id", "node_id", "node_revision"], path);
  return {
    source_kind: expectLiteral(record.source_kind, new Set(["node"]), `${path}.source_kind`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    node_revision: expectPositiveInteger(record.node_revision, `${path}.node_revision`),
  };
}

function normalizeAgentAnchorRoleSourceV3(
  value: unknown,
  path: string,
): AgentAnchorRoleSourceV3 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["role", "source"], path);
  return {
    role: expectLiteral(record.role, new Set<AgentAnchorRoleSourceV3["role"]>([
      "product_main",
      "product_multiview",
      "character_main",
      "character_turnaround",
    ]), `${path}.role`),
    source: normalizeAgentAnchorNodeSourceV3(record.source, `${path}.source`),
  };
}

function normalizeAnchorAcceptanceEvidenceV1(value: unknown, path: string): AnchorAcceptanceEvidenceV1 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["evidence_id", "actor", "decision", "action_id", "requirement_revision_id", "requirement_revision_no", "node_revision", "asset_version_id", "document_revision", "recorded_at"], path);
  return {
    evidence_id: expectNonEmptyString(record.evidence_id, `${path}.evidence_id`),
    actor: expectLiteral(record.actor, new Set<AnchorAcceptanceEvidenceV1["actor"]>(["user", "agent", "system"]), `${path}.actor`),
    decision: expectLiteral(record.decision, new Set<AnchorAcceptanceEvidenceV1["decision"]>(["accepted", "delegated", "activated", "retired", "invalidated"]), `${path}.decision`),
    action_id: expectNonEmptyString(record.action_id, `${path}.action_id`),
    requirement_revision_id: expectNonEmptyString(record.requirement_revision_id, `${path}.requirement_revision_id`),
    requirement_revision_no: expectPositiveInteger(record.requirement_revision_no, `${path}.requirement_revision_no`),
    node_revision: record.node_revision === null || record.node_revision === undefined ? null : expectPositiveInteger(record.node_revision, `${path}.node_revision`),
    asset_version_id: nullableStringWithDefault(record.asset_version_id, `${path}.asset_version_id`),
    document_revision: expectPositiveInteger(record.document_revision, `${path}.document_revision`),
    recorded_at: expectIsoDateTimeString(record.recorded_at, `${path}.recorded_at`),
  };
}

function normalizeStoryboardSegmentMaterializationV3(
  value: unknown,
  path: string,
): StoryboardSegmentMaterializationV3 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    ["sequence_id", "materialization_id", "status", "generation_prompt"],
    path,
  );
  return {
    sequence_id: expectNonEmptyString(record.sequence_id, `${path}.sequence_id`),
    materialization_id: expectNonEmptyString(record.materialization_id, `${path}.materialization_id`),
    status: record.status === undefined
      ? "pending"
      : expectLiteral(
        record.status,
        STORYBOARD_SEGMENT_MATERIALIZATION_STATUSES,
        `${path}.status`,
      ),
    generation_prompt: nullableStringWithDefault(
      record.generation_prompt,
      `${path}.generation_prompt`,
    ),
  };
}

function normalizeStoryboardPlannedNodeV3(value: unknown, path: string): StoryboardPlannedNodeV3 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["sequence_id", "node_role", "node_id", "node_revision", "materialization_id"], path);
  return { sequence_id: nullableStringWithDefault(record.sequence_id, `${path}.sequence_id`), node_role: expectLiteral(record.node_role, new Set<StoryboardPlannedNodeV3["node_role"]>(["storyboard_grid", "video_segment", "bgm", "editing"]), `${path}.node_role`), node_id: expectNonEmptyString(record.node_id, `${path}.node_id`), node_revision: expectPositiveInteger(record.node_revision, `${path}.node_revision`), materialization_id: expectNonEmptyString(record.materialization_id, `${path}.materialization_id`) };
}

function normalizeStoryboardExcludedMediaV3(value: unknown, path: string): StoryboardExcludedMediaV3 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["sequence_id", "node_role", "node_id", "node_revision", "action_id"], path);
  return { sequence_id: nullableStringWithDefault(record.sequence_id, `${path}.sequence_id`), node_role: expectLiteral(record.node_role, new Set<StoryboardExcludedMediaV3["node_role"]>(["video_segment", "bgm"]), `${path}.node_role`), node_id: expectNonEmptyString(record.node_id, `${path}.node_id`), node_revision: expectPositiveInteger(record.node_revision, `${path}.node_revision`), action_id: expectNonEmptyString(record.action_id, `${path}.action_id`) };
}

function normalizeStoryboardVisualAnchorV3(value: unknown, path: string): StoryboardVisualAnchorV3 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["sequence_id", "node_id", "node_revision", "asset_id", "asset_version_id", "acceptance_evidence_id"], path);
  return { sequence_id: expectNonEmptyString(record.sequence_id, `${path}.sequence_id`), node_id: expectNonEmptyString(record.node_id, `${path}.node_id`), node_revision: expectPositiveInteger(record.node_revision, `${path}.node_revision`), asset_id: expectNonEmptyString(record.asset_id, `${path}.asset_id`), asset_version_id: expectNonEmptyString(record.asset_version_id, `${path}.asset_version_id`), acceptance_evidence_id: expectNonEmptyString(record.acceptance_evidence_id, `${path}.acceptance_evidence_id`) };
}

function normalizeAgentDocumentLinkedNodeRuntimeV2(
  value: unknown,
  path: string,
): AgentDocumentLinkedNodeRuntimeV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["node_id", "node_type", "creative_role", "status", "revision"], path);
  return {
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    node_type: expectLiteral(record.node_type, CANVAS_NODE_TYPES, `${path}.node_type`),
    creative_role: expectNonEmptyString(record.creative_role, `${path}.creative_role`),
    status: expectLiteral(record.status, CANVAS_NODE_STATUSES, `${path}.status`),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
  };
}

function normalizeVideoParameterNormalizationV2(
  value: unknown,
  path: string,
): VideoParameterNormalizationV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    ["field", "requested_value", "effective_value", "normalization_code"],
    path,
  );
  return {
    field: expectLiteral(
      record.field,
      new Set<VideoParameterNormalizationV2["field"]>([
        "duration_seconds",
        "resolution",
        "aspect_ratio",
        "generate_audio",
      ]),
      `${path}.field`,
    ),
    requested_value: normalizeCanvasParameterScalarV2(record.requested_value, `${path}.requested_value`),
    effective_value: normalizeCanvasParameterScalarV2(record.effective_value, `${path}.effective_value`),
    normalization_code: expectLiteral(
      record.normalization_code,
      new Set<VideoParameterNormalizationV2["normalization_code"]>([
        "duration_clamped_to_minimum",
        "duration_clamped_to_maximum",
        "resolution_reduced_to_supported",
      ]),
      `${path}.normalization_code`,
    ),
  };
}

function normalizeCanvasPostReadyEffectSummaryV2(
  value: unknown,
  path: string,
): CanvasPostReadyEffectSummaryV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "effect_id",
    "effect_type",
    "node_id",
    "status",
    "attempt_no",
    "error",
    "updated_at",
  ], path);
  return {
    effect_id: expectNonEmptyString(record.effect_id, `${path}.effect_id`),
    effect_type: expectLiteral(record.effect_type, CANVAS_POST_READY_EFFECT_TYPES, `${path}.effect_type`),
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    status: expectLiteral(record.status, CANVAS_POST_READY_EFFECT_STATUSES, `${path}.status`),
    attempt_no: expectNonNegativeInteger(record.attempt_no, `${path}.attempt_no`),
    error: record.error === null ? null : normalizeCanvasNodeErrorV2(record.error, `${path}.error`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function normalizeCanvasPostReadyCheckpointV2(
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

function normalizeProposalMaterializationErrorV2(
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
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "materialization_id",
    "option_id",
    "turn_id",
    "status",
    "attempt_no",
    "retryable",
    "error",
    "created_at",
    "updated_at",
  ], path);
  return {
    materialization_id: expectNonEmptyString(record.materialization_id, `${path}.materialization_id`),
    option_id: expectNonEmptyString(record.option_id, `${path}.option_id`),
    turn_id: expectNonEmptyString(record.turn_id, `${path}.turn_id`),
    status: expectLiteral(
      record.status,
      new Set<ProposalMaterializationProjectionV2["status"]>(["queued", "working", "failed", "completed"]),
      `${path}.status`,
    ),
    attempt_no: expectPositiveInteger(record.attempt_no, `${path}.attempt_no`),
    retryable: expectBoolean(record.retryable, `${path}.retryable`),
    error: record.error === null
      ? null
      : normalizeProposalMaterializationErrorV2(record.error, `${path}.error`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function normalizeProposalActionDescriptorV2(
  value: unknown,
  path: string,
): ProposalActionDescriptorV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "action_id",
    "action",
    "label",
    "proposal_id",
    "expected_session_revision",
    "confirmation_required",
    "reason",
    "option_id",
    "enabled",
    "disabled_reason",
  ], path);
  return {
    action_id: expectNonEmptyString(record.action_id, `${path}.action_id`),
    action: expectLiteral(record.action, PROPOSAL_ACTIONS, `${path}.action`),
    label: expectNonEmptyString(record.label, `${path}.label`),
    proposal_id: expectNonEmptyString(record.proposal_id, `${path}.proposal_id`),
    expected_session_revision: expectPositiveInteger(
      record.expected_session_revision,
      `${path}.expected_session_revision`,
    ),
    confirmation_required: expectBoolean(record.confirmation_required, `${path}.confirmation_required`),
    reason: expectNonEmptyString(record.reason, `${path}.reason`),
    option_id: nullableStringWithDefault(record.option_id, `${path}.option_id`),
    enabled: record.enabled === undefined ? true : expectBoolean(record.enabled, `${path}.enabled`),
    disabled_reason: nullableStringWithDefault(record.disabled_reason, `${path}.disabled_reason`),
  };
}

function normalizeProposalApplicationSummaryV2(
  value: unknown,
  path: string,
): ProposalApplicationSummaryV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "application_id",
    "option_id",
    "action",
    "receipt_id",
    "created_node_ids",
    "queued_execution_ids",
    "created_at",
  ], path);
  return {
    application_id: expectNonEmptyString(record.application_id, `${path}.application_id`),
    option_id: expectNonEmptyString(record.option_id, `${path}.option_id`),
    action: expectLiteral(
      record.action,
      new Set<ProposalApplicationSummaryV2["action"]>([
        "select_option",
        "custom_direction",
        "delegate_choice",
        "reuse_direction",
      ]),
      `${path}.action`,
    ),
    receipt_id: expectNonEmptyString(record.receipt_id, `${path}.receipt_id`),
    created_node_ids: optionalStringArray(record.created_node_ids, `${path}.created_node_ids`, []),
    queued_execution_ids: optionalStringArray(record.queued_execution_ids, `${path}.queued_execution_ids`, []),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
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
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "decision_id",
    "element_kind",
    "occurrence_id",
    "occurrence_index",
    "outcome",
    "source",
    "source_revision",
    "requirements",
  ], path);
  return {
    decision_id: expectNonEmptyString(record.decision_id, `${path}.decision_id`),
    element_kind: expectNonEmptyString(record.element_kind, `${path}.element_kind`),
    occurrence_id: expectNonEmptyString(record.occurrence_id, `${path}.occurrence_id`),
    occurrence_index: expectPositiveInteger(record.occurrence_index, `${path}.occurrence_index`),
    outcome: expectLiteral(record.outcome, JOURNEY_DECISION_OUTCOMES, `${path}.outcome`),
    source: expectLiteral(record.source, JOURNEY_DECISION_SOURCES, `${path}.source`),
    source_revision: expectPositiveInteger(record.source_revision, `${path}.source_revision`),
    requirements: expectRecordValue(record.requirements ?? {}, `${path}.requirements`),
  };
}

function normalizeJourneyActionProjectionV2(value: unknown, path: string): JourneyActionProjectionV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "action_id",
    "action_kind",
    "stage",
    "stage_revision",
    "status",
    "turn_id",
    "occurrence_id",
    "character_phase",
  ], path);
  return {
    action_id: expectNonEmptyString(record.action_id, `${path}.action_id`),
    action_kind: expectNonEmptyString(record.action_kind, `${path}.action_kind`),
    stage: expectLiteral(record.stage, GUIDED_JOURNEY_STAGES, `${path}.stage`),
    stage_revision: expectPositiveInteger(record.stage_revision, `${path}.stage_revision`),
    status: expectLiteral(record.status, JOURNEY_ACTION_STATUSES, `${path}.status`),
    turn_id: record.turn_id === undefined || record.turn_id === null
      ? null
      : expectNonEmptyString(record.turn_id, `${path}.turn_id`),
    occurrence_id: record.occurrence_id === undefined || record.occurrence_id === null
      ? null
      : expectNonEmptyString(record.occurrence_id, `${path}.occurrence_id`),
    character_phase: record.character_phase === undefined || record.character_phase === null
      ? null
      : expectLiteral(record.character_phase, new Set(["main", "turnaround"] as const), `${path}.character_phase`),
  };
}

function normalizeJourneyTransitionEvidenceV2(
  value: unknown,
  path: string,
): JourneyTransitionEvidenceV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "evidence_id",
    "evidence_kind",
    "source_id",
    "source_revision",
    "stage",
    "stage_revision",
    "occurrence_id",
    "character_phase",
    "actor",
    "recorded_at",
  ], path);
  return {
    evidence_id: expectNonEmptyString(record.evidence_id, `${path}.evidence_id`),
    evidence_kind: expectLiteral(record.evidence_kind, JOURNEY_EVIDENCE_KINDS, `${path}.evidence_kind`),
    source_id: expectNonEmptyString(record.source_id, `${path}.source_id`),
    source_revision: record.source_revision === undefined || record.source_revision === null
      ? null
      : expectPositiveInteger(record.source_revision, `${path}.source_revision`),
    stage: expectLiteral(record.stage, GUIDED_JOURNEY_STAGES, `${path}.stage`),
    stage_revision: expectPositiveInteger(record.stage_revision, `${path}.stage_revision`),
    occurrence_id: nullableStringWithDefault(record.occurrence_id, `${path}.occurrence_id`),
    character_phase: record.character_phase === undefined || record.character_phase === null
      ? null
      : expectLiteral(record.character_phase, new Set(["main", "turnaround"] as const), `${path}.character_phase`),
    actor: record.actor === undefined
      ? "system"
      : expectLiteral(record.actor, JOURNEY_DECISION_SOURCES, `${path}.actor`),
    recorded_at: expectIsoDateTimeString(record.recorded_at, `${path}.recorded_at`),
  };
}

function normalizeGuidanceSessionActionV2(
  value: unknown,
  path: string,
): GuidanceSessionActionV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "action_id",
    "logical_key",
    "action",
    "state",
    "creating_turn_id",
    "expected_session_revision",
    "label",
    "workflow_id",
    "confirmation_required",
    "reason",
    "authority",
  ], path);
  return {
    action_id: expectNonEmptyString(record.action_id, `${path}.action_id`),
    logical_key: expectNonEmptyString(record.logical_key, `${path}.logical_key`),
    action: expectLiteral(
      record.action,
      new Set<GuidanceSessionActionV2["action"]>([
        "stop_guidance",
        "resume_guidance",
        "set_creative_authority",
      ]),
      `${path}.action`,
    ),
    state: expectLiteral(
      record.state,
      new Set<GuidanceSessionActionV2["state"]>(["pending", "applying", "applied", "superseded", "failed"]),
      `${path}.state`,
    ),
    creating_turn_id: expectNonEmptyString(record.creating_turn_id, `${path}.creating_turn_id`),
    expected_session_revision: expectPositiveInteger(
      record.expected_session_revision,
      `${path}.expected_session_revision`,
    ),
    label: expectNonEmptyString(record.label, `${path}.label`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    confirmation_required: expectBoolean(record.confirmation_required, `${path}.confirmation_required`),
    reason: expectNonEmptyString(record.reason, `${path}.reason`),
    authority: record.authority === undefined || record.authority === null
      ? null
      : expectLiteral(record.authority, new Set(["user", "director"] as const), `${path}.authority`),
  };
}

function normalizeCreativeAuthorityStateV2(
  value: unknown,
  path: string,
): GuidedSessionStateV2["creative_authority"] {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["authority", "source", "decided_at_turn_id", "revision"], path);
  return {
    authority: expectLiteral(record.authority, new Set(["user", "director"] as const), `${path}.authority`),
    source: expectLiteral(
      record.source,
      new Set(["explicit_user", "explicit_delegation", "director_inference"] as const),
      `${path}.source`,
    ),
    decided_at_turn_id: expectNonEmptyString(record.decided_at_turn_id, `${path}.decided_at_turn_id`),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
  };
}

function normalizeGuidedStepCheckpointV2(
  value: unknown,
  path: string,
): GuidedSessionStateV2["current_checkpoint"] {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "checkpoint_id",
    "workflow_id",
    "session_revision",
    "stage_kind",
    "status",
    "trigger",
    "action_id",
  ], path);
  return {
    checkpoint_id: expectNonEmptyString(record.checkpoint_id, `${path}.checkpoint_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    session_revision: expectPositiveInteger(record.session_revision, `${path}.session_revision`),
    stage_kind: record.stage_kind === undefined || record.stage_kind === null
      ? null
      : expectLiteral(
        record.stage_kind,
        new Set([
          "world_setting", "narrative_direction", "product", "prop", "character", "scene",
          "script", "storyboard", "video", "bgm", "editing",
        ] as const),
        `${path}.stage_kind`,
      ),
    status: expectLiteral(
      record.status,
      new Set(["pending", "waiting_user", "completed", "failed", "superseded"] as const),
      `${path}.status`,
    ),
    trigger: expectLiteral(
      record.trigger,
      new Set(["user_message", "proposal_action", "continuation", "recovery"] as const),
      `${path}.trigger`,
    ),
    action_id: nullableStringWithDefault(record.action_id, `${path}.action_id`),
  };
}

function normalizeCreationModeDecisionV2(
  value: unknown,
  path: string,
): CreationModeDecisionV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    ["mode", "reason", "target_node_id", "target_asset_id"],
    path,
  );
  return {
    mode: expectLiteral(record.mode, CREATION_MODES, `${path}.mode`),
    reason: expectNonEmptyString(record.reason, `${path}.reason`),
    target_node_id: nullableStringWithDefault(record.target_node_id, `${path}.target_node_id`),
    target_asset_id: nullableStringWithDefault(record.target_asset_id, `${path}.target_asset_id`),
  };
}

type Normalizer = (value: unknown, path: string) => unknown;
type Fixture = Record<string, unknown>;
const source = readFileSync('src/features/agent-canvas/model/normalizers.ts', 'utf8');
const sourceAst = ts.createSourceFile('normalizers.ts', source, ts.ScriptTarget.Latest, true);
// Actual public exports use the real module import; private access is test-local
// TypeScript source instrumentation, never a production export or oracle.
const instrumentedSource = sourceAst.statements.filter(node => !ts.isImportDeclaration(node)).map(node => node.getText(sourceAst).replace(/^export /, '')).join('\n');
const nodeSource = { source_kind: 'node', workflow_id: 'w', node_id: 'n', node_revision: 1 };
const cases: Array<{ name: string; baseline: Normalizer; fixture: Fixture }> = [
  { name: 'normalizeStoryboardPlanGlobalParametersV2', baseline: normalizeStoryboardPlanGlobalParametersV2, fixture: { aspect_ratio: '16:9', total_duration_seconds: 10, segment_count: 1 } },
  { name: 'normalizeStoryboardNodeRecordV2', baseline: normalizeStoryboardNodeRecordV2, fixture: { sequence_id: null, node_role: 'video_segment', node_id: 'n' } },
  { name: 'normalizeStoryboardSegmentMaterializationV2', baseline: normalizeStoryboardSegmentMaterializationV2, fixture: { sequence_id: 's', status: 'pending', generation_prompt: null } },
  { name: 'normalizeStoryboardVisualAnchorV2', baseline: normalizeStoryboardVisualAnchorV2, fixture: { node_id: 'n', asset_id: 'a', node_revision: 1, document_revision: 1 } },
  { name: 'normalizeAgentAnchorNodeSourceV3', baseline: normalizeAgentAnchorNodeSourceV3, fixture: nodeSource },
  { name: 'normalizeAgentAnchorRoleSourceV3', baseline: normalizeAgentAnchorRoleSourceV3, fixture: { role: 'character_main', source: nodeSource } },
  { name: 'normalizeAnchorAcceptanceEvidenceV1', baseline: normalizeAnchorAcceptanceEvidenceV1, fixture: { evidence_id: 'e', actor: 'user', decision: 'accepted', action_id: 'a', requirement_revision_id: 'r', requirement_revision_no: 1, node_revision: null, asset_version_id: null, document_revision: 1, recorded_at: 'date' } },
  { name: 'normalizeStoryboardSegmentMaterializationV3', baseline: normalizeStoryboardSegmentMaterializationV3, fixture: { sequence_id: 's', materialization_id: 'm', status: 'pending', generation_prompt: null } },
  { name: 'normalizeStoryboardPlannedNodeV3', baseline: normalizeStoryboardPlannedNodeV3, fixture: { sequence_id: null, node_role: 'bgm', node_id: 'n', node_revision: 1, materialization_id: 'm' } },
  { name: 'normalizeStoryboardExcludedMediaV3', baseline: normalizeStoryboardExcludedMediaV3, fixture: { sequence_id: null, node_role: 'bgm', node_id: 'n', node_revision: 1, action_id: 'a' } },
  { name: 'normalizeStoryboardVisualAnchorV3', baseline: normalizeStoryboardVisualAnchorV3, fixture: { sequence_id: 's', node_id: 'n', node_revision: 1, asset_id: 'a', asset_version_id: 'v', acceptance_evidence_id: 'e' } },
  { name: 'normalizeAgentDocumentLinkedNodeRuntimeV2', baseline: normalizeAgentDocumentLinkedNodeRuntimeV2, fixture: { node_id: 'n', node_type: 'image', creative_role: 'character', status: 'draft', revision: 1 } },
  { name: 'normalizeVideoParameterNormalizationV2', baseline: normalizeVideoParameterNormalizationV2, fixture: { field: 'duration_seconds', requested_value: 0, effective_value: 1, normalization_code: 'duration_clamped_to_minimum' } },
  { name: 'normalizeCanvasPostReadyEffectSummaryV2', baseline: normalizeCanvasPostReadyEffectSummaryV2, fixture: { effect_id: 'e', effect_type: 'persist_script_document', node_id: 'n', status: 'queued', attempt_no: 0, error: { code: 'c', message: 'm', retryable: false }, updated_at: 'date' } },
  { name: 'normalizeProposalMaterializationProjectionV2', baseline: normalizeProposalMaterializationProjectionV2, fixture: { materialization_id: 'm', option_id: 'o', turn_id: 't', status: 'queued', attempt_no: 1, retryable: true, error: null, created_at: 'date', updated_at: 'date' } },
  { name: 'normalizeProposalActionDescriptorV2', baseline: normalizeProposalActionDescriptorV2, fixture: { action_id: 'a', action: 'select_option', label: 'l', proposal_id: 'p', expected_session_revision: 1, confirmation_required: false, reason: 'r', option_id: null, enabled: true, disabled_reason: null } },
  { name: 'normalizeProposalApplicationSummaryV2', baseline: normalizeProposalApplicationSummaryV2, fixture: { application_id: 'a', option_id: 'o', action: 'select_option', receipt_id: 'r', created_node_ids: ['n'], queued_execution_ids: [], created_at: 'date' } },
  { name: 'normalizeJourneyElementDecisionV2', baseline: normalizeJourneyElementDecisionV2, fixture: { decision_id: 'd', element_kind: 'scene', occurrence_id: 'o', occurrence_index: 1, outcome: [...JOURNEY_DECISION_OUTCOMES][0], source: [...JOURNEY_DECISION_SOURCES][0], source_revision: 1, requirements: {} } },
  { name: 'normalizeJourneyActionProjectionV2', baseline: normalizeJourneyActionProjectionV2, fixture: { action_id: 'a', action_kind: 'kind', stage: [...GUIDED_JOURNEY_STAGES][0], stage_revision: 1, status: [...JOURNEY_ACTION_STATUSES][0], turn_id: null, occurrence_id: null, character_phase: null } },
  { name: 'normalizeJourneyTransitionEvidenceV2', baseline: normalizeJourneyTransitionEvidenceV2, fixture: { evidence_id: 'e', evidence_kind: [...JOURNEY_EVIDENCE_KINDS][0], source_id: 's', source_revision: null, stage: [...GUIDED_JOURNEY_STAGES][0], stage_revision: 1, occurrence_id: null, character_phase: null, actor: 'system', recorded_at: 'date' } },
  { name: 'normalizeGuidanceSessionActionV2', baseline: normalizeGuidanceSessionActionV2, fixture: { action_id: 'a', logical_key: 'k', action: 'stop_guidance', state: 'pending', creating_turn_id: 't', expected_session_revision: 1, label: 'l', workflow_id: 'w', confirmation_required: false, reason: 'r', authority: null } },
  { name: 'normalizeCreativeAuthorityStateV2', baseline: normalizeCreativeAuthorityStateV2, fixture: { authority: 'user', source: 'explicit_user', decided_at_turn_id: 't', revision: 1 } },
  { name: 'normalizeGuidedStepCheckpointV2', baseline: normalizeGuidedStepCheckpointV2, fixture: { checkpoint_id: 'c', workflow_id: 'w', session_revision: 1, stage_kind: null, status: 'pending', trigger: 'user_message', action_id: null } },
  { name: 'normalizeCreationModeDecisionV2', baseline: normalizeCreationModeDecisionV2, fixture: { mode: [...CREATION_MODES][0], reason: 'r', target_node_id: null, target_asset_id: null } },
];
const exposed = [...cases.map(entry => entry.name), 'normalizeGuidedProductionJourneyV2'];
const compiled = ts.transpile(instrumentedSource + '\nreturn {' + exposed.join(',') + '};', { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None });
const instrumented = new Function('V2ContractValidationError', 'normalizeStrictRecord', compiled)(V2ContractValidationError, normalizeStrictRecord) as Record<string, Normalizer>;
const publicNormalizers = actual as unknown as Record<string, Normalizer>;
function outcome(fn: Normalizer, value: unknown, path?: string) {
  try {
    const output = path === undefined ? (fn as (value: unknown) => unknown)(value) : fn(value, path);
    return { ok: true, output, keys: Object.keys(output as object), descriptors: Object.getOwnPropertyDescriptors(output) };
  } catch (error) {
    if (!(error instanceof V2ContractValidationError)) throw error;
    return { ok: false, errorClass: error.constructor.name, name: error.name, message: error.message, path: error.path, reason: error.reason };
  }
}
// Locks transport contracts, not read-count equivalence for stateful getters.
const mutations: unknown[] = [undefined, null, false, true, '', ' ', 'bad', 0, -1, 0.5, NaN, Infinity, -Infinity, [], [null], ['bad'], {}, { unknown: true }];
describe('fourth strict-record batch preserves independently frozen contracts', () => {
  for (const entry of cases) {
    const fn = publicNormalizers[entry.name] ?? instrumented[entry.name];
    it(`${entry.name}: valid fixture, output keys and descriptors`, () => {
      for (const path of ['private', 'transport.custom[2]']) {
        const baseline = outcome(entry.baseline, entry.fixture, path);
        expect(baseline.ok).toBe(true);
        expect(outcome(fn, entry.fixture, path)).toStrictEqual(baseline);
      }
    });
    it(`${entry.name}: every field, defaults, missing/null and unknown-first errors`, () => {
      for (const path of ['private', 'transport.custom[2]']) {
        const compare = (value: unknown) => expect(outcome(fn, value, path)).toStrictEqual(outcome(entry.baseline, value, path));
        mutations.forEach(compare);
        const keys = Object.keys(entry.fixture);
        for (const key of keys) {
          const missing = { ...entry.fixture }; delete missing[key]; compare(missing);
          for (const value of mutations) compare({ ...entry.fixture, [key]: value });
          const getter = { ...entry.fixture }; Object.defineProperty(getter, key, { enumerable: true, get: () => entry.fixture[key] }); compare(getter);
        }
        for (const key of ['unexpected', '__proto__', 'constructor', 'toString', 'hasOwnProperty']) {
          const unknown = { ...entry.fixture, [keys[0]]: undefined };
          Object.defineProperty(unknown, key, { value: 1, enumerable: true });
          const baseline = outcome(entry.baseline, unknown, path);
          expect(baseline.ok).toBe(false);
          expect(baseline.path).toBe(`${path}.${key}`);
          expect(baseline.reason).toBe('unknown field');
          compare(unknown);
        }
        const multi = { ...entry.fixture, z_unknown: true, a_unknown: true, [keys[0]]: undefined };
        expect(outcome(entry.baseline, multi, path).path).toBe(`${path}.z_unknown`); compare(multi);
        const defaults = { ...entry.fixture };
        for (const key of keys) if (outcome(entry.baseline, { ...entry.fixture, [key]: undefined }, path).ok) delete defaults[key];
        expect(outcome(entry.baseline, defaults, path).ok).toBe(true); compare(defaults);
        compare({});
      }
    });
    it(`${entry.name}: nested scalar/record/array paths`, () => {
      const walk = (value: unknown, replace: (value: unknown) => Fixture) => {
        if (!value || typeof value !== 'object') return;
        const record = value as Fixture;
        for (const key of Object.keys(record)) {
          for (const mutation of mutations) {
            const root = replace(Array.isArray(value) ? Object.assign([...value], { [key]: mutation }) : { ...record, [key]: mutation });
            expect(outcome(fn, root, 'nested')).toStrictEqual(outcome(entry.baseline, root, 'nested'));
          }
          walk(record[key], replacement => replace(Array.isArray(value) ? Object.assign([...value], { [key]: replacement }) : { ...record, [key]: replacement }));
        }
        if (!Array.isArray(value)) {
          const root = replace({ ...record, nested_unknown: true });
          expect(outcome(fn, root, 'nested')).toStrictEqual(outcome(entry.baseline, root, 'nested'));
        }
      };
      for (const key of Object.keys(entry.fixture)) walk(entry.fixture[key], replacement => ({ ...entry.fixture, [key]: replacement }));
    });
  }
  it('public checkpoint import preserves default/custom paths and nested selected effect', () => {
    const effect = cases.find(entry => entry.name === 'normalizeCanvasPostReadyEffectSummaryV2')!.fixture;
    const fixture = { checkpoint_id: 'c', workflow_id: 'w', execution_id: 'e', execution_status: 'queued', status: 'pending', counts: { total: 1, queued: 1, running: 0, completed: 0, failed: 0 }, effects: [effect], error: null, updated_at: 'date' };
    for (const path of [undefined, 'transport.custom[2]']) {
      expect(outcome(normalizeCanvasPostReadyCheckpointV2, fixture, path).ok).toBe(true);
      expect(outcome(actual.normalizeCanvasPostReadyCheckpointV2, fixture, path)).toStrictEqual(outcome(normalizeCanvasPostReadyCheckpointV2, fixture, path));
      for (const key of Object.keys(effect)) for (const value of mutations) {
        const root = { ...fixture, effects: [{ ...effect, [key]: value }] };
        expect(outcome(actual.normalizeCanvasPostReadyCheckpointV2, root, path)).toStrictEqual(outcome(normalizeCanvasPostReadyCheckpointV2, root, path));
      }
    }
  });
  it('private journey parent: selected frozen children and custom nested paths', () => {
    const action = cases.find(entry => entry.name === 'normalizeJourneyActionProjectionV2')!.fixture;
    const decision = cases.find(entry => entry.name === 'normalizeJourneyElementDecisionV2')!.fixture;
    const evidence = cases.find(entry => entry.name === 'normalizeJourneyTransitionEvidenceV2')!.fixture;
    const fixture = { policy_version: 'fixed_ad_production_v2', stage: action.stage, stage_status: 'waiting_user', stage_revision: 1, decisions: [decision], active_occurrence_id: null, active_action: action, suspended_action: action, transition_evidence: [evidence] };
    for (const path of ['journey', 'transport.custom[2]']) {
      expect(outcome(normalizeGuidedProductionJourneyV2, fixture, path).ok).toBe(true);
      expect(outcome(instrumented.normalizeGuidedProductionJourneyV2, fixture, path)).toStrictEqual(outcome(normalizeGuidedProductionJourneyV2, fixture, path));
      for (const [key, child] of [['decisions', decision], ['transition_evidence', evidence]] as const) {
        for (const field of Object.keys(child)) for (const value of mutations) {
          const root = { ...fixture, [key]: [{ ...child, [field]: value }] };
          expect(outcome(instrumented.normalizeGuidedProductionJourneyV2, root, path)).toStrictEqual(outcome(normalizeGuidedProductionJourneyV2, root, path));
        }
      }
      for (const field of Object.keys(action)) for (const value of mutations) {
        const root = { ...fixture, active_action: { ...action, [field]: value } };
        expect(outcome(instrumented.normalizeGuidedProductionJourneyV2, root, path)).toStrictEqual(outcome(normalizeGuidedProductionJourneyV2, root, path));
      }
    }
  });
});
