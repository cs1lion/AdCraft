import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import * as actual from './normalizers.ts';
import { normalizeStrictRecord } from './strictRecordFields.ts';
import { V2ContractValidationError } from '../../../api/v2ContractValidationError.ts';
import type { AgentActionReceiptV2, AgentWorkingDocumentPageV2, AgentWorkingDocumentV2, AgentOperationResultV2, AgentOperationFailureV2, AgentPlacementHintV2, CanvasBindingInputRoleV2, CanvasBindingSourceImageAssetV2, CanvasBindingSourceNodeV2, CanvasBindingSourceV2, CanvasBindingV2, CanvasLayoutPatchResponseV2, CanvasNodeErrorV2, CanvasNodeLatestAttemptV2, ActionableFailureV1, CreativeElementDecisionV2, CreativeGoalV2, DecisionBundleAnswerV2, DecisionBundleQuestionV2, DecisionBundleV2, ProviderModelCapabilityV2, GuidanceCompletionProjectionV2, GuidanceTopicKindV2, GuidanceTopicStateV2, GuidedProductionJourneyV2, GuidedSessionStateV2, GuidedInteractionV1, GuidanceAwaitingV1, ProposalActionDescriptorV2, AgentCapabilityIdV2 } from "../../../types-v2.ts";

// Selected bodies, scalar validators and enum sets frozen from the dirty working
// baseline before edits (not HEAD). UNCHANGED nested validators are explicitly
// shared below; selected nested functions always resolve to their frozen bodies.
// Test-only source instrumentation exposes private functions without adding
// production exports. It does not provide the differential oracle.
const productionSource = readFileSync('src/features/agent-canvas/model/normalizers.ts', 'utf8');
const sourceAst = ts.createSourceFile('normalizers.ts', productionSource, ts.ScriptTarget.Latest, true);
const instrumentedSource = sourceAst.statements.filter(node => !ts.isImportDeclaration(node)).map(node => node.getText(sourceAst).replace(/^export /, '')).join('\n');
const expose = ["normalizeCanvasNodeLatestAttemptV2", "normalizeCanvasBindingV2", "normalizeAgentWorkingDocumentPageV2", "normalizeProviderModelCapabilityV2", "normalizeAgentActionReceiptV2", "normalizeCanvasLayoutPatchResponseV2", "normalizeDecisionBundleV2", "normalizeGuidedSessionStateV2", "normalizeCanvasBindingSourceNodeV2", "normalizeCanvasBindingSourceImageAssetV2", "normalizeAgentOperationFailureV2", "normalizeAgentOperationResultV2", "normalizeCreativeGoalV2", "normalizeGuidanceTopicStateV2", "normalizeCreativeElementDecisionV2", "normalizeCanvasNodeErrorV2", "normalizeCanvasBindingSourceV2", "normalizeAgentWorkingDocumentV2", "normalizeProviderReferenceLimits", "normalizeAgentPlacementHintV2", "normalizeDecisionBundleQuestionV2", "normalizeDecisionBundleAnswerV2", "normalizeCreativeAuthorityStateV2", "normalizeGuidedStepCheckpointV2", "normalizeGuidanceCompletionProjectionV2", "normalizeGuidedProductionJourneyV2", "normalizeGuidedInteractionV1", "normalizeGuidanceAwaitingV1", "nullableActionableFailureV1"];
const compiled = ts.transpile(instrumentedSource + '\nreturn {' + expose.join(',') + '};', { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None });
type Normalizer = (value: unknown, path: string) => unknown;
const instrumented = new Function('V2ContractValidationError', 'normalizeStrictRecord', compiled)(V2ContractValidationError, normalizeStrictRecord) as Record<string, Normalizer>;
const normalizeCanvasNodeErrorV2 = instrumented.normalizeCanvasNodeErrorV2 as (value: unknown, path: string) => CanvasNodeErrorV2;
function normalizeCanvasBindingSourceV2(value: unknown, path = "binding.source"): CanvasBindingSourceV2 {
  const record = expectRecord(value, path);
  const kind = expectString(record.kind, `${path}.kind`);
  if (kind === "node_output") return normalizeCanvasBindingSourceNodeV2(record, path);
  if (kind === "image_asset") return normalizeCanvasBindingSourceImageAssetV2(record, path);
  fail(`${path}.kind`, "unsupported discriminator");
}
const normalizeAgentWorkingDocumentV2 = instrumented.normalizeAgentWorkingDocumentV2 as (value: unknown, path: string) => AgentWorkingDocumentV2;
const normalizeProviderReferenceLimits = instrumented.normalizeProviderReferenceLimits as (value: unknown, path: string) => ProviderModelCapabilityV2["reference_limits"];
const normalizeAgentPlacementHintV2 = instrumented.normalizeAgentPlacementHintV2 as (value: unknown, path: string) => AgentPlacementHintV2;
const normalizeDecisionBundleQuestionV2 = instrumented.normalizeDecisionBundleQuestionV2 as (value: unknown, path: string) => DecisionBundleQuestionV2;
const normalizeDecisionBundleAnswerV2 = instrumented.normalizeDecisionBundleAnswerV2 as (value: unknown, path: string) => DecisionBundleAnswerV2;
const normalizeCreativeAuthorityStateV2 = instrumented.normalizeCreativeAuthorityStateV2 as (value: unknown, path: string) => GuidedSessionStateV2["creative_authority"];
const normalizeGuidedStepCheckpointV2 = instrumented.normalizeGuidedStepCheckpointV2 as (value: unknown, path: string) => GuidedSessionStateV2["current_checkpoint"];
const normalizeGuidanceCompletionProjectionV2 = instrumented.normalizeGuidanceCompletionProjectionV2 as (value: unknown, path: string) => GuidanceCompletionProjectionV2;
const normalizeGuidedProductionJourneyV2 = instrumented.normalizeGuidedProductionJourneyV2 as (value: unknown, path: string) => GuidedProductionJourneyV2;
const normalizeGuidedInteractionV1 = instrumented.normalizeGuidedInteractionV1 as (value: unknown, path: string) => GuidedInteractionV1;
const normalizeGuidanceAwaitingV1 = instrumented.normalizeGuidanceAwaitingV1 as (value: unknown, path: string) => GuidanceAwaitingV1;
const nullableActionableFailureV1 = instrumented.nullableActionableFailureV1 as (value: unknown, path: string) => ActionableFailureV1 | null;
type JsonRecord = Record<string, unknown>;
const CANVAS_BINDING_ROLES = new Set<CanvasBindingInputRoleV2>([
  "text_context",
  "image_reference",
  "video_reference",
  "audio_reference",
]);
const PROVIDER_OUTPUT_TYPES = new Set<ProviderModelCapabilityV2["output_type"]>([
  "image",
  "video",
  "audio",
]);
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
const CREATIVE_ELEMENT_KINDS = new Set<CreativeElementDecisionV2["element_kind"]>(
  ["world_setting", "product", "character", "prop", "scene", "script", "storyboard", "video", "audio"],
);
const PROVIDER_INPUT_TYPES = new Set<ProviderModelCapabilityV2["accepted_input_types"][number]>(["text", "image", "video", "audio"]);
const RECEIPT_STATUSES = new Set<AgentActionReceiptV2["status"]>([
  "applied",
  "applied_with_run_error",
  "not_applied",
  "rejected",
  "superseded",
  "failed",
]);

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

function expectNonEmptyString(value: unknown, path: string) {
  const result = expectString(value, path);
  if (!result.trim()) fail(path, "expected non-empty string");
  return result;
}

function nullableStringWithDefault(value: unknown, path: string) {
  return value === undefined ? null : nullableString(value, path);
}

function expectLiteral<T extends string>(value: unknown, allowed: ReadonlySet<T>, path: string): T {
  const result = expectString(value, path);
  if (!allowed.has(result as T)) fail(path, `expected one of ${Array.from(allowed).join(", ")}`);
  return result as T;
}

function expectIsoDateTimeString(value: unknown, path: string) {
  return expectNonEmptyString(value, path);
}

function expectBoolean(value: unknown, path: string) {
  if (typeof value !== "boolean") fail(path, "expected boolean");
  return value;
}

function expectNonNegativeInteger(value: unknown, path: string) {
  const result = expectInteger(value, path);
  if (result < 0) fail(path, "expected non-negative integer");
  return result;
}

function nullableString(value: unknown, path: string) {
  if (value === null) return null;
  return expectString(value, path);
}

function expectRecordValue(value: unknown, path: string) {
  return expectRecord(value, path);
}

function expectArray(value: unknown, path: string) {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value;
}

function expectStringArray(value: unknown, path: string) {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value.map((item, index) => expectString(item, `${path}[${index}]`));
}

function optionalUnknownRecord(value: unknown, path: string, defaultValue: JsonRecord = {}) {
  if (value === undefined) return defaultValue;
  return expectUnknownRecord(value, path);
}

function optionalStringArray(value: unknown, path: string, defaultValue: string[] = []) {
  if (value === undefined) return defaultValue;
  return expectStringArray(value, path);
}

function expectTuple2Number(value: unknown, path: string, integer = false): [number, number] {
  const tuple = expectArray(value, path);
  if (tuple.length !== 2) fail(path, "expected two items");
  return [
    integer ? expectInteger(tuple[0], `${path}[0]`) : expectFiniteNumber(tuple[0], `${path}[0]`),
    integer ? expectInteger(tuple[1], `${path}[1]`) : expectFiniteNumber(tuple[1], `${path}[1]`),
  ];
}

function expectPositiveInteger(value: unknown, path: string) {
  const result = expectInteger(value, path);
  if (result <= 0) fail(path, "expected positive integer");
  return result;
}

function expectFiniteNumber(value: unknown, path: string) {
  if (typeof value !== "number" || !Number.isFinite(value)) fail(path, "expected finite number");
  return value;
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function fail(path: string, message: string): never {
  throw new V2ContractValidationError(path, message);
}

function expectString(value: unknown, path: string) {
  if (typeof value !== "string") fail(path, "expected string");
  return value;
}

function expectInteger(value: unknown, path: string) {
  const result = expectFiniteNumber(value, path);
  if (!Number.isInteger(result)) fail(path, "expected integer");
  return result;
}

function expectUnknownRecord(value: unknown, path: string) {
  if (!isRecord(value)) fail(path, "expected object");
  return value;
}

function normalizeCanvasNodeLatestAttemptV2(
  value: unknown,
  path = "latestAttempt",
): CanvasNodeLatestAttemptV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    ["execution_id", "member_id", "run_intent_snapshot_id", "status", "created_at", "updated_at", "error"],
    path,
  );
  return {
    execution_id: expectNonEmptyString(record.execution_id, `${path}.execution_id`),
    member_id: expectNonEmptyString(record.member_id, `${path}.member_id`),
    run_intent_snapshot_id: nullableStringWithDefault(
      record.run_intent_snapshot_id,
      `${path}.run_intent_snapshot_id`,
    ),
    status: expectLiteral(
      record.status,
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
      `${path}.status`,
    ),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
    error: record.error === null || record.error === undefined
      ? null
      : normalizeCanvasNodeErrorV2(record.error, `${path}.error`),
  };
}

function normalizeCanvasBindingV2(value: unknown, path = "binding"): CanvasBindingV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "binding_id",
      "workflow_id",
      "source",
      "target_node_id",
      "input_role",
      "enabled",
      "order",
      "label",
      "metadata",
      "created_at",
      "updated_at",
    ],
    path,
  );
  return {
    binding_id: expectNonEmptyString(record.binding_id, `${path}.binding_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    source: normalizeCanvasBindingSourceV2(record.source, `${path}.source`),
    target_node_id: expectNonEmptyString(record.target_node_id, `${path}.target_node_id`),
    input_role: expectLiteral(record.input_role, CANVAS_BINDING_ROLES, `${path}.input_role`),
    enabled: expectBoolean(record.enabled, `${path}.enabled`),
    order: expectNonNegativeInteger(record.order, `${path}.order`),
    label: nullableString(record.label, `${path}.label`),
    metadata: expectRecordValue(record.metadata, `${path}.metadata`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function normalizeAgentWorkingDocumentPageV2(
  value: unknown,
  path = "agentDocuments",
): AgentWorkingDocumentPageV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["items", "next_cursor"], path);
  return {
    items: expectArray(record.items ?? [], `${path}.items`).map((item, index) => (
      normalizeAgentWorkingDocumentV2(item, `${path}.items[${index}]`)
    )),
    next_cursor: nullableStringWithDefault(record.next_cursor, `${path}.next_cursor`),
  };
}

function normalizeProviderModelCapabilityV2(value: unknown, path = "capability"): ProviderModelCapabilityV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "provider",
      "model_id",
      "output_type",
      "accepted_input_types",
      "max_references",
      "reference_limits",
      "supported_parameters",
      "default_parameters",
      "supported_resolutions",
      "supported_aspect_ratios",
      "duration_range_seconds",
      "pixel_bounds",
      "available",
      "unavailable_reason",
      "supports_native_audio",
      "capability_revision",
    ],
    path,
  );
  return {
    provider: expectNonEmptyString(record.provider, `${path}.provider`),
    model_id: expectNonEmptyString(record.model_id, `${path}.model_id`),
    output_type: expectLiteral(record.output_type, PROVIDER_OUTPUT_TYPES, `${path}.output_type`),
    accepted_input_types: expectArray(record.accepted_input_types, `${path}.accepted_input_types`).map((item, index) =>
      expectLiteral(item, PROVIDER_INPUT_TYPES, `${path}.accepted_input_types[${index}]`),
    ),
    max_references: expectNonNegativeInteger(record.max_references, `${path}.max_references`),
    reference_limits: normalizeProviderReferenceLimits(record.reference_limits, `${path}.reference_limits`),
    supported_parameters: expectStringArray(record.supported_parameters, `${path}.supported_parameters`),
    default_parameters: optionalUnknownRecord(record.default_parameters, `${path}.default_parameters`, {}),
    supported_resolutions: optionalStringArray(record.supported_resolutions, `${path}.supported_resolutions`, []),
    supported_aspect_ratios: expectStringArray(record.supported_aspect_ratios, `${path}.supported_aspect_ratios`),
    duration_range_seconds: record.duration_range_seconds === null ? null : expectTuple2Number(record.duration_range_seconds, `${path}.duration_range_seconds`),
    pixel_bounds: record.pixel_bounds === null ? null : expectTuple2Number(record.pixel_bounds, `${path}.pixel_bounds`, true),
    available: expectBoolean(record.available, `${path}.available`),
    unavailable_reason: nullableString(record.unavailable_reason, `${path}.unavailable_reason`),
    supports_native_audio: record.supports_native_audio === undefined
      ? false
      : expectBoolean(record.supports_native_audio, `${path}.supports_native_audio`),
    capability_revision: expectPositiveInteger(record.capability_revision ?? 1, `${path}.capability_revision`),
  };
}

function normalizeAgentActionReceiptV2(
  value: unknown,
  path = "actionReceipt",
): AgentActionReceiptV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "receipt_id",
    "workflow_id",
    "plan_id",
    "action_id",
    "proposal_id",
    "proposal_option_id",
    "proposal_action",
    "actor_kind",
    "occurrence_id",
    "character_phase",
    "idempotency_key",
    "status",
    "summary",
    "created_node_ids",
    "updated_node_ids",
    "deleted_node_ids",
    "created_binding_ids",
    "deleted_binding_ids",
    "queued_execution_ids",
    "run_queue_errors",
    "operation_results",
    "workflow_revision",
    "before_workflow_revision",
    "placement_hints",
    "continuation_turn_id",
    "superseded_by",
    "error_code",
    "error_message",
    "created_at",
  ], path);
  return {
    receipt_id: expectNonEmptyString(record.receipt_id, `${path}.receipt_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    plan_id: nullableStringWithDefault(record.plan_id, `${path}.plan_id`),
    action_id: nullableStringWithDefault(record.action_id, `${path}.action_id`),
    proposal_id: nullableStringWithDefault(record.proposal_id, `${path}.proposal_id`),
    proposal_option_id: nullableStringWithDefault(record.proposal_option_id, `${path}.proposal_option_id`),
    proposal_action: record.proposal_action === undefined || record.proposal_action === null
      ? null
      : expectLiteral(record.proposal_action, PROPOSAL_ACTIONS, `${path}.proposal_action`),
    actor_kind: record.actor_kind === undefined
      ? "system"
      : expectLiteral(record.actor_kind, new Set(["agent", "user", "system"] as const), `${path}.actor_kind`),
    occurrence_id: nullableStringWithDefault(record.occurrence_id, `${path}.occurrence_id`),
    character_phase: record.character_phase === undefined || record.character_phase === null
      ? null
      : expectLiteral(record.character_phase, new Set(["main", "turnaround"] as const), `${path}.character_phase`),
    idempotency_key: nullableStringWithDefault(record.idempotency_key, `${path}.idempotency_key`),
    status: expectLiteral(record.status, RECEIPT_STATUSES, `${path}.status`),
    summary: expectNonEmptyString(record.summary, `${path}.summary`),
    created_node_ids: optionalStringArray(record.created_node_ids, `${path}.created_node_ids`, []),
    updated_node_ids: optionalStringArray(record.updated_node_ids, `${path}.updated_node_ids`, []),
    deleted_node_ids: optionalStringArray(record.deleted_node_ids, `${path}.deleted_node_ids`, []),
    created_binding_ids: optionalStringArray(record.created_binding_ids, `${path}.created_binding_ids`, []),
    deleted_binding_ids: optionalStringArray(record.deleted_binding_ids, `${path}.deleted_binding_ids`, []),
    queued_execution_ids: optionalStringArray(record.queued_execution_ids, `${path}.queued_execution_ids`, []),
    run_queue_errors: optionalStringArray(record.run_queue_errors, `${path}.run_queue_errors`, []),
    operation_results: expectArray(record.operation_results ?? [], `${path}.operation_results`)
      .map((item, index) => normalizeAgentOperationResultV2(item, `${path}.operation_results[${index}]`)),
    workflow_revision: expectPositiveInteger(record.workflow_revision, `${path}.workflow_revision`),
    before_workflow_revision: record.before_workflow_revision === undefined || record.before_workflow_revision === null
      ? null
      : expectPositiveInteger(record.before_workflow_revision, `${path}.before_workflow_revision`),
    placement_hints: expectArray(record.placement_hints ?? [], `${path}.placement_hints`)
      .map((item, index) => normalizeAgentPlacementHintV2(item, `${path}.placement_hints[${index}]`)),
    continuation_turn_id: nullableStringWithDefault(record.continuation_turn_id, `${path}.continuation_turn_id`),
    superseded_by: nullableStringWithDefault(record.superseded_by, `${path}.superseded_by`),
    error_code: nullableStringWithDefault(record.error_code, `${path}.error_code`),
    error_message: nullableStringWithDefault(record.error_message, `${path}.error_message`),
    created_at: record.created_at === undefined
      ? new Date(0).toISOString()
      : expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

function normalizeCanvasLayoutPatchResponseV2(
  value: unknown,
  path = "layoutPatch",
): CanvasLayoutPatchResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "workflow_id",
    "revision",
    "layout_revision",
    "positions",
  ], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    layout_revision: expectPositiveInteger(record.layout_revision, `${path}.layout_revision`),
    positions: expectArray(record.positions, `${path}.positions`).map((item, index) => {
      const positionPath = `${path}.positions[${index}]`;
      const position = expectRecord(item, positionPath);
      forbidUnknownFields(position, ["node_id", "x", "y"], positionPath);
      return {
        node_id: expectNonEmptyString(position.node_id, `${positionPath}.node_id`),
        x: expectFiniteNumber(position.x, `${positionPath}.x`),
        y: expectFiniteNumber(position.y, `${positionPath}.y`),
      };
    }),
  };
}

function normalizeDecisionBundleV2(value: unknown, path = "decisionBundle"): DecisionBundleV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "bundle_id",
    "workflow_id",
    "conversation_id",
    "source_turn_id",
    "replacement_bundle_id",
    "status",
    "revision",
    "title",
    "introduction",
    "questions",
    "answers",
    "requirement_revision_no",
    "created_at",
    "updated_at",
    "closed_at",
  ], path);
  return {
    bundle_id: expectNonEmptyString(record.bundle_id, `${path}.bundle_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    conversation_id: expectNonEmptyString(record.conversation_id, `${path}.conversation_id`),
    source_turn_id: expectNonEmptyString(record.source_turn_id, `${path}.source_turn_id`),
    replacement_bundle_id: nullableStringWithDefault(record.replacement_bundle_id, `${path}.replacement_bundle_id`),
    status: expectLiteral(
      record.status,
      new Set<DecisionBundleV2["status"]>(["open", "answered", "skipped", "superseded"]),
      `${path}.status`,
    ),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    title: expectNonEmptyString(record.title, `${path}.title`),
    introduction: expectNonEmptyString(record.introduction, `${path}.introduction`),
    questions: expectArray(record.questions ?? [], `${path}.questions`)
      .map((item, index) => normalizeDecisionBundleQuestionV2(item, `${path}.questions[${index}]`)),
    answers: expectArray(record.answers ?? [], `${path}.answers`)
      .map((item, index) => normalizeDecisionBundleAnswerV2(item, `${path}.answers[${index}]`)),
    requirement_revision_no: record.requirement_revision_no === undefined || record.requirement_revision_no === null
      ? null
      : expectPositiveInteger(record.requirement_revision_no, `${path}.requirement_revision_no`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
    closed_at: record.closed_at === undefined || record.closed_at === null
      ? null
      : expectIsoDateTimeString(record.closed_at, `${path}.closed_at`),
  };
}

function normalizeGuidedSessionStateV2(value: unknown, path = "creativeSession"): GuidedSessionStateV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "session_id",
    "workflow_id",
    "status",
    "response_locale",
    "goal",
    "creative_authority",
    "current_checkpoint",
    "narrative_direction",
    "element_decisions",
    "current_topic_id",
    "topics",
    "active_proposal_id",
    "active_style_skill_run_id",
    "completion",
    "journey",
    "interaction",
    "awaiting",
    "actionable_failure",
    "revision",
    "updated_at",
  ], path);
  return {
    session_id: expectNonEmptyString(record.session_id, `${path}.session_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    status: expectLiteral(
      record.status,
      new Set<GuidedSessionStateV2["status"]>(["active", "paused", "completed"]),
      `${path}.status`,
    ),
    // Older persisted sessions predate the additive field; new responses always provide it.
    response_locale: record.response_locale === undefined
      ? "und"
      : expectNonEmptyString(record.response_locale, `${path}.response_locale`),
    goal: normalizeCreativeGoalV2(record.goal, `${path}.goal`),
    creative_authority: record.creative_authority === undefined || record.creative_authority === null
      ? null
      : normalizeCreativeAuthorityStateV2(record.creative_authority, `${path}.creative_authority`),
    current_checkpoint: record.current_checkpoint === undefined || record.current_checkpoint === null
      ? null
      : normalizeGuidedStepCheckpointV2(record.current_checkpoint, `${path}.current_checkpoint`),
    narrative_direction: nullableStringWithDefault(record.narrative_direction, `${path}.narrative_direction`),
    element_decisions: expectArray(record.element_decisions ?? [], `${path}.element_decisions`)
      .map((item, index) => normalizeCreativeElementDecisionV2(item, `${path}.element_decisions[${index}]`)),
    current_topic_id: nullableStringWithDefault(record.current_topic_id, `${path}.current_topic_id`),
    topics: expectArray(record.topics ?? [], `${path}.topics`)
      .map((item, index) => normalizeGuidanceTopicStateV2(item, `${path}.topics[${index}]`)),
    active_proposal_id: nullableStringWithDefault(record.active_proposal_id, `${path}.active_proposal_id`),
    active_style_skill_run_id: nullableStringWithDefault(
      record.active_style_skill_run_id,
      `${path}.active_style_skill_run_id`,
    ),
    completion: normalizeGuidanceCompletionProjectionV2(record.completion ?? {}, `${path}.completion`),
    journey: normalizeGuidedProductionJourneyV2(record.journey, `${path}.journey`),
    interaction: record.interaction === undefined || record.interaction === null
      ? null
      : normalizeGuidedInteractionV1(record.interaction, `${path}.interaction`),
    awaiting: record.awaiting === undefined || record.awaiting === null
      ? null
      : normalizeGuidanceAwaitingV1(record.awaiting, `${path}.awaiting`),
    actionable_failure: nullableActionableFailureV1(
      record.actionable_failure,
      `${path}.actionable_failure`,
    ),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function normalizeCanvasBindingSourceNodeV2(value: unknown, path: string): CanvasBindingSourceNodeV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["kind", "source_node_id"], path);
  return {
    kind: expectLiteral(record.kind, new Set<CanvasBindingSourceNodeV2["kind"]>(["node_output"]), `${path}.kind`),
    source_node_id: expectNonEmptyString(record.source_node_id, `${path}.source_node_id`),
  };
}

function normalizeCanvasBindingSourceImageAssetV2(value: unknown, path: string): CanvasBindingSourceImageAssetV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["kind", "source_asset_id", "source_asset_version_id"], path);
  return {
    kind: expectLiteral(record.kind, new Set<CanvasBindingSourceImageAssetV2["kind"]>(["image_asset"]), `${path}.kind`),
    source_asset_id: expectNonEmptyString(record.source_asset_id, `${path}.source_asset_id`),
    source_asset_version_id: nullableStringWithDefault(
      record.source_asset_version_id,
      `${path}.source_asset_version_id`,
    ),
  };
}

function normalizeAgentOperationFailureV2(
  value: unknown,
  path: string,
): AgentOperationFailureV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "code",
    "message",
    "operation",
    "capability_id",
    "attempt_stage",
    "failure_stage",
    "elapsed_ms",
    "retryable",
    "actionable_failure",
    "validation_paths",
    "occurred_at",
  ], path);
  return {
    code: expectNonEmptyString(record.code, `${path}.code`),
    message: expectNonEmptyString(record.message, `${path}.message`),
    operation: expectNonEmptyString(record.operation, `${path}.operation`),
    capability_id: record.capability_id === null
      ? null
      : expectLiteral(record.capability_id, AGENT_CAPABILITY_IDS, `${path}.capability_id`),
    attempt_stage: expectLiteral(
      record.attempt_stage,
      new Set<AgentOperationFailureV2["attempt_stage"]>([
        "initial",
        "transport_retry",
        "structured_repair",
        "fallback",
      ]),
      `${path}.attempt_stage`,
    ),
    failure_stage: expectLiteral(
      record.failure_stage,
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
      `${path}.failure_stage`,
    ),
    elapsed_ms: expectNonNegativeInteger(record.elapsed_ms, `${path}.elapsed_ms`),
    retryable: expectBoolean(record.retryable, `${path}.retryable`),
    actionable_failure: nullableActionableFailureV1(
      record.actionable_failure,
      `${path}.actionable_failure`,
    ),
    validation_paths: expectStringArray(record.validation_paths, `${path}.validation_paths`),
    occurred_at: expectIsoDateTimeString(record.occurred_at, `${path}.occurred_at`),
  };
}

function normalizeAgentOperationResultV2(
  value: unknown,
  path: string,
): AgentOperationResultV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "operation_id",
    "node_id",
    "binding_id",
    "execution_id",
    "status",
    "error_code",
  ], path);
  return {
    operation_id: expectNonEmptyString(record.operation_id, `${path}.operation_id`),
    node_id: nullableStringWithDefault(record.node_id, `${path}.node_id`),
    binding_id: nullableStringWithDefault(record.binding_id, `${path}.binding_id`),
    execution_id: nullableStringWithDefault(record.execution_id, `${path}.execution_id`),
    status: expectLiteral(record.status, new Set(["applied", "queued", "failed"] as const), `${path}.status`),
    error_code: nullableStringWithDefault(record.error_code, `${path}.error_code`),
  };
}

function normalizeCreativeGoalV2(value: unknown, path: string): CreativeGoalV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "requested_output",
    "delivery_scope",
    "summary",
    "explicit_constraints",
  ], path);
  return {
    requested_output: expectLiteral(
      record.requested_output,
      new Set<CreativeGoalV2["requested_output"]>(["text", "script", "image", "video", "audio"]),
      `${path}.requested_output`,
    ),
    delivery_scope: expectLiteral(
      record.delivery_scope,
      new Set<CreativeGoalV2["delivery_scope"]>(["draft", "generated_media"]),
      `${path}.delivery_scope`,
    ),
    summary: expectNonEmptyString(record.summary, `${path}.summary`),
    explicit_constraints: optionalUnknownRecord(
      record.explicit_constraints,
      `${path}.explicit_constraints`,
      {},
    ),
  };
}

function normalizeGuidanceTopicStateV2(value: unknown, path: string): GuidanceTopicStateV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "topic_id",
    "topic_kind",
    "title",
    "status",
    "capability_id",
    "capability_display_name",
    "related_node_ids",
    "source_proposal_id",
    "revision",
  ], path);
  return {
    topic_id: expectNonEmptyString(record.topic_id, `${path}.topic_id`),
    topic_kind: expectLiteral(record.topic_kind, GUIDANCE_TOPIC_KINDS, `${path}.topic_kind`),
    title: expectNonEmptyString(record.title, `${path}.title`),
    status: expectLiteral(
      record.status,
      new Set<GuidanceTopicStateV2["status"]>(["proposed", "selected", "deferred", "excluded"]),
      `${path}.status`,
    ),
    capability_id: expectLiteral(record.capability_id, AGENT_CAPABILITY_IDS, `${path}.capability_id`),
    capability_display_name: expectNonEmptyString(
      record.capability_display_name,
      `${path}.capability_display_name`,
    ),
    related_node_ids: optionalStringArray(record.related_node_ids, `${path}.related_node_ids`, []),
    source_proposal_id: nullableStringWithDefault(record.source_proposal_id, `${path}.source_proposal_id`),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
  };
}

function normalizeCreativeElementDecisionV2(
  value: unknown,
  path: string,
): CreativeElementDecisionV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["element_kind", "presence", "authority", "requirements", "source"], path);
  return {
    element_kind: expectLiteral(
      record.element_kind,
      CREATIVE_ELEMENT_KINDS,
      `${path}.element_kind`,
    ),
    presence: expectLiteral(
      record.presence,
      new Set<CreativeElementDecisionV2["presence"]>(["include", "exclude", "unspecified"]),
      `${path}.presence`,
    ),
    authority: expectLiteral(
      record.authority,
      new Set<CreativeElementDecisionV2["authority"]>(["user", "agent"]),
      `${path}.authority`,
    ),
    requirements: optionalUnknownRecord(record.requirements, `${path}.requirements`, {}),
    source: expectLiteral(
      record.source,
      new Set<CreativeElementDecisionV2["source"]>([
        "explicit_user",
        "accepted_proposal",
        "delegated_to_agent",
      ]),
      `${path}.source`,
    ),
  };
}

const goal = { requested_output: "video", delivery_scope: "draft", summary: "goal", explicit_constraints: {} };
const topic = { topic_id: "t", topic_kind: "scene", title: "Scene", status: "proposed", capability_id: "scene_design", capability_display_name: "Scene", related_node_ids: ["n"], source_proposal_id: null, revision: 1 };
const element = { element_kind: "scene", presence: "include", authority: "user", requirements: {}, source: "explicit_user" };
const sourceNode = { kind: "node_output", source_node_id: "n" };
const sourceAsset = { kind: "image_asset", source_asset_id: "a", source_asset_version_id: null };
const result = { operation_id: "o", node_id: null, binding_id: null, execution_id: null, status: "applied", error_code: null };
const cases: Array<{ name: string; baseline: Normalizer; fixture: JsonRecord }> = [
  { name: "normalizeCanvasNodeLatestAttemptV2", baseline: normalizeCanvasNodeLatestAttemptV2, fixture: { execution_id: "e", member_id: "m", run_intent_snapshot_id: null, status: "queued", created_at: "date", updated_at: "date", error: null } },
  { name: "normalizeCanvasBindingV2", baseline: normalizeCanvasBindingV2, fixture: { binding_id: "b", workflow_id: "w", source: sourceNode, target_node_id: "n", input_role: "image_reference", enabled: true, order: 0, label: null, metadata: {}, created_at: "date", updated_at: "date" } },
  { name: "normalizeAgentWorkingDocumentPageV2", baseline: normalizeAgentWorkingDocumentPageV2, fixture: { items: [], next_cursor: null } },
  { name: "normalizeProviderModelCapabilityV2", baseline: normalizeProviderModelCapabilityV2, fixture: { provider: "p", model_id: "m", output_type: "video", accepted_input_types: ["image"], max_references: 1, reference_limits: { image: 1 }, supported_parameters: ["duration"], default_parameters: {}, supported_resolutions: ["720p"], supported_aspect_ratios: ["16:9"], duration_range_seconds: [1, 10], pixel_bounds: [1, 1024], available: true, unavailable_reason: null, supports_native_audio: false, capability_revision: 1 } },
  { name: "normalizeAgentActionReceiptV2", baseline: normalizeAgentActionReceiptV2, fixture: { receipt_id: "r", workflow_id: "w", plan_id: null, action_id: null, proposal_id: null, proposal_option_id: null, proposal_action: null, actor_kind: "system", occurrence_id: null, character_phase: null, idempotency_key: null, status: "applied", summary: "summary", created_node_ids: ["n"], updated_node_ids: [], deleted_node_ids: [], created_binding_ids: [], deleted_binding_ids: [], queued_execution_ids: [], run_queue_errors: [], operation_results: [result], workflow_revision: 1, before_workflow_revision: null, placement_hints: [], continuation_turn_id: null, superseded_by: null, error_code: null, error_message: null, created_at: "date" } },
  { name: "normalizeCanvasLayoutPatchResponseV2", baseline: normalizeCanvasLayoutPatchResponseV2, fixture: { workflow_id: "w", revision: 1, layout_revision: 1, positions: [{ node_id: "n", x: 1, y: 2 }] } },
  { name: "normalizeDecisionBundleV2", baseline: normalizeDecisionBundleV2, fixture: { bundle_id: "b", workflow_id: "w", conversation_id: "c", source_turn_id: "t", replacement_bundle_id: null, status: "open", revision: 1, title: "title", introduction: "intro", questions: [], answers: [], requirement_revision_no: null, created_at: "date", updated_at: "date", closed_at: null } },
  { name: "normalizeGuidedSessionStateV2", baseline: normalizeGuidedSessionStateV2, fixture: { session_id: "s", workflow_id: "w", status: "active", response_locale: "en", goal, creative_authority: null, current_checkpoint: null, narrative_direction: null, element_decisions: [element], current_topic_id: null, topics: [topic], active_proposal_id: null, active_style_skill_run_id: null, completion: {}, journey: { policy_version: "fixed_ad_production_v2", stage: "scene", stage_status: "waiting_user", stage_revision: 1, decisions: [], active_occurrence_id: null, active_action: null, suspended_action: null, transition_evidence: [] }, interaction: null, awaiting: null, actionable_failure: null, revision: 1, updated_at: "date" } },
  { name: "normalizeCanvasBindingSourceNodeV2", baseline: normalizeCanvasBindingSourceNodeV2, fixture: sourceNode },
  { name: "normalizeCanvasBindingSourceImageAssetV2", baseline: normalizeCanvasBindingSourceImageAssetV2, fixture: sourceAsset },
  { name: "normalizeAgentOperationFailureV2", baseline: normalizeAgentOperationFailureV2, fixture: { code: "c", message: "m", operation: "o", capability_id: null, attempt_stage: "initial", failure_stage: "provider", elapsed_ms: 0, retryable: false, actionable_failure: null, validation_paths: ["a.b"], occurred_at: "date" } },
  { name: "normalizeAgentOperationResultV2", baseline: normalizeAgentOperationResultV2, fixture: result },
  { name: "normalizeCreativeGoalV2", baseline: normalizeCreativeGoalV2, fixture: goal },
  { name: "normalizeGuidanceTopicStateV2", baseline: normalizeGuidanceTopicStateV2, fixture: topic },
  { name: "normalizeCreativeElementDecisionV2", baseline: normalizeCreativeElementDecisionV2, fixture: element },
];
const publicNormalizers = actual as unknown as Record<string, Normalizer>;
const paths = [undefined, "transport.custom[2]"];
function outcome(fn: Normalizer, value: unknown, path?: string) {
  try {
    const output = path === undefined ? (fn as (value: unknown) => unknown)(value) : fn(value, path);
    return { ok: true, output, keys: Object.keys(output as object), descriptors: Object.getOwnPropertyDescriptors(output) };
  } catch (error) {
    if (!(error instanceof V2ContractValidationError)) throw error;
    return { ok: false, name: error.name, message: error.message, path: error.path };
  }
}
// Transport JSON equivalence plus explicit undefined/nonfinite rejection probes.
// No claim about stateful getter read counts: each getter below is immutable.
const mutations: unknown[] = [undefined, null, true, false, "", " ", "bad", 0, -1, 0.5, NaN, Infinity, -Infinity, [], [null], ["bad"], {}, { unknown: true }];
describe("third strict-record batch preserves frozen transport contracts", () => {
  for (const entry of cases) {
    const fn = publicNormalizers[entry.name] ?? instrumented[entry.name];
    // Private functions require a path in the baseline and production alike.
    const casePaths = publicNormalizers[entry.name] ? paths : ["private", "transport.custom[2]"];
    it(`${entry.name}: baseline fixture succeeds before differential checks`, () => {
      for (const path of casePaths) {
        const baseline = outcome(entry.baseline, entry.fixture, path);
        expect(baseline.ok).toBe(true);
        expect(outcome(fn, entry.fixture, path)).toStrictEqual(baseline);
      }
    });
    it(`${entry.name}: each field, roots, unknown keys and validation order`, () => {
      for (const path of casePaths) {
        const compare = (value: unknown) => expect(outcome(fn, value, path)).toStrictEqual(outcome(entry.baseline, value, path));
        for (const root of mutations) compare(root);
        const keys = Object.keys(entry.fixture);
        for (const key of keys) {
          const missing = { ...entry.fixture }; delete missing[key]; compare(missing);
          for (const value of mutations) compare({ ...entry.fixture, [key]: value });
          const getters = { ...entry.fixture }; Object.defineProperty(getters, key, { enumerable: true, get: () => entry.fixture[key] }); compare(getters);
          if (Array.isArray(entry.fixture[key])) compare({ ...entry.fixture, [key]: [null] });
        }
        for (const key of ["unexpected", "__proto__", "constructor", "toString", "hasOwnProperty"]) {
          const unknown = { ...entry.fixture }; Object.defineProperty(unknown, key, { value: 1, enumerable: true }); compare(unknown);
          const invalid = { ...unknown, [keys[0]]: undefined };
          const baseline = outcome(entry.baseline, invalid, path);
          expect(baseline.ok).toBe(false);
          expect(baseline.path).toBe(`${path ?? defaultPath(entry.name)}.${key}`);
          compare(invalid);
        }
        const multi = { ...entry.fixture, z_unknown: true, a_unknown: true, [keys[0]]: undefined };
        expect(outcome(entry.baseline, multi, path).path).toBe(`${path ?? defaultPath(entry.name)}.z_unknown`);
        compare(multi);
        const allMissing: JsonRecord = {}; compare(allMissing);
        const defaults = { ...entry.fixture }; for (const key of keys) if (outcome(entry.baseline, { ...entry.fixture, [key]: undefined }, path).ok) delete defaults[key]; compare(defaults);
      }
    });
    it(`${entry.name}: nested paths, nested unknown keys and array entries`, () => {
      const walk = (value: unknown, replace: (value: unknown) => JsonRecord) => {
        if (!value || typeof value !== "object") return;
        const record = value as JsonRecord;
        for (const key of Object.keys(record)) {
          for (const mutation of [undefined, null, false, "bad", -1, [], { unknown: true }]) {
            const root = replace({ ...record, [key]: mutation });
            expect(outcome(fn, root, "nested")).toStrictEqual(outcome(entry.baseline, root, "nested"));
          }
          if (record[key] && typeof record[key] === "object") walk(record[key], replacement => replace(Array.isArray(value) ? Object.assign([...value], { [key]: replacement }) : { ...record, [key]: replacement }));
        }
        if (!Array.isArray(value)) {
          const root = replace({ ...record, nested_unknown: true });
          expect(outcome(fn, root, "nested")).toStrictEqual(outcome(entry.baseline, root, "nested"));
        }
      };
      for (const key of Object.keys(entry.fixture)) walk(entry.fixture[key], replacement => ({ ...entry.fixture, [key]: replacement }));
    });
  }
});
function defaultPath(name: string) {
  return ({ normalizeCanvasNodeLatestAttemptV2: "latestAttempt", normalizeCanvasBindingV2: "binding", normalizeAgentWorkingDocumentPageV2: "agentDocuments", normalizeProviderModelCapabilityV2: "capability", normalizeAgentActionReceiptV2: "actionReceipt", normalizeCanvasLayoutPatchResponseV2: "layoutPatch", normalizeDecisionBundleV2: "decisionBundle", normalizeGuidedSessionStateV2: "creativeSession" } as Record<string, string>)[name];
}
