import { describe, expect, it } from "vitest";
import { normalizeAgentPlacementHintV2, normalizeCanvasVariationDraftV2, normalizeCanvasModelSummaryV2, normalizeVideoSkillPublicDetailV2, normalizeVideoSkillCatalogResponseV2, normalizeAgentExecutionSettingsV2, normalizeBindingCapabilityDecisionV2, normalizeEditingSkippedInputV2, normalizeEditingPreviewClipV2, normalizeEditingPreviewV2, normalizeAgentCanvasImageLibraryListResponseV2, normalizeCanvasRunCancelResponseV2, normalizeEditingExportAcceptedV2, normalizeEditingExportCancelResponseV2 } from "./normalizers.ts";
import type { AgentExecutionSettingsV2, AgentCanvasImageLibraryListResponseV2, AgentPlacementHintV2, BindingCapabilityDecisionV2, CanvasModelSelectionModeV2, CanvasModelSummaryV2, CanvasNodeStatusV2, CanvasVariationDraftV2, CanvasRunCancelResponseV2, EditingExportRuntimeV2, EditingExportAcceptedV2, EditingExportCancelResponseV2, EditingPreviewClipV2, EditingPreviewV2, EditingSkippedInputV2, ProviderModelCapabilityV2, VideoSkillCatalogResponseV2, VideoSkillCategoryV2, VideoSkillPreviewV2, VideoSkillPublicDetailV2 } from "../../../types-v2.ts";
import { V2ContractValidationError } from "../../../api/v2ContractValidationError.ts";
// Independent pre-refactor baseline and validators; no descriptor-helper imports.
type JsonRecord = Record<string, unknown>;

const CANVAS_NODE_STATUSES = new Set<CanvasNodeStatusV2>(["draft", "working", "ready", "failed"]);

const CANVAS_MODEL_SELECTION_MODES = new Set<CanvasModelSelectionModeV2>(["default", "explicit"]);

const CANVAS_MODEL_CAPABILITIES = new Set<CanvasModelSummaryV2["capability"]>(["text", "image", "video", "audio"]);

const CANVAS_MODEL_AVAILABILITIES = new Set<CanvasModelSummaryV2["availability"]>([
  "available",
  "unavailable",
  "unauthorized",
  "unsupported",
  "deprecated",
]);

const EDITING_EXPORT_STATUSES = new Set<EditingExportRuntimeV2["status"]>(["queued", "exporting", "completed", "failed", "cancelled"]);

const EDITING_SKIPPED_REASONS = new Set<EditingSkippedInputV2["reason"]>([
  "source_not_ready",
  "source_failed",
  "source_output_unavailable",
  "source_media_invalid",
]);

const PROVIDER_INPUT_TYPES = new Set<ProviderModelCapabilityV2["accepted_input_types"][number]>(["text", "image", "video", "audio"]);

const PLACEMENT_INTENTS = new Set<AgentPlacementHintV2["intent"]>([
  "append_flow",
  "after_anchor",
  "right_sibling",
  "near_selection",
]);

const AGENT_MEDIA_EXECUTION_MODES = new Set<AgentExecutionSettingsV2["media_execution_mode"]>([
  "manual",
  "automatic",
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

function nullableFiniteNumber(value: unknown, path: string) {
  if (value === null) return null;
  return expectFiniteNumber(value, path);
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

function expectUnknownRecord(value: unknown, path: string) {
  if (!isRecord(value)) fail(path, "expected object");
  return value;
}

function optionalUnknownRecord(value: unknown, path: string, defaultValue: JsonRecord = {}) {
  if (value === undefined) return defaultValue;
  return expectUnknownRecord(value, path);
}

function expectArray(value: unknown, path: string) {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value;
}

function expectIsoDateTimeString(value: unknown, path: string) {
  return expectNonEmptyString(value, path);
}

function baselineAgentPlacementHintV2(
  value: unknown,
  path = "placementHint",
): AgentPlacementHintV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["intent", "anchor_node_id", "group_key"], path);
  return {
    intent: expectLiteral(record.intent, PLACEMENT_INTENTS, `${path}.intent`),
    anchor_node_id: nullableStringWithDefault(record.anchor_node_id, `${path}.anchor_node_id`),
    group_key: nullableStringWithDefault(record.group_key, `${path}.group_key`),
  };
}

function baselineCanvasVariationDraftV2(
  value: unknown,
  path = "variationDraft",
): CanvasVariationDraftV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "source_node_id",
    "source_node_revision",
    "title",
    "generation_prompt",
    "model_id",
    "model_selection_mode",
    "model_ref",
    "parameters",
    "variation_revision",
    "created_at",
    "updated_at",
  ], path);
  return {
    source_node_id: expectNonEmptyString(record.source_node_id, `${path}.source_node_id`),
    source_node_revision: expectPositiveInteger(record.source_node_revision, `${path}.source_node_revision`),
    title: expectNonEmptyString(record.title, `${path}.title`),
    generation_prompt: expectNonEmptyString(record.generation_prompt, `${path}.generation_prompt`),
    model_id: nullableStringWithDefault(record.model_id, `${path}.model_id`),
    model_selection_mode: record.model_selection_mode === undefined
      ? "default"
      : expectLiteral(record.model_selection_mode, CANVAS_MODEL_SELECTION_MODES, `${path}.model_selection_mode`),
    model_ref: nullableStringWithDefault(record.model_ref, `${path}.model_ref`),
    parameters: optionalUnknownRecord(record.parameters, `${path}.parameters`, {}),
    variation_revision: expectPositiveInteger(record.variation_revision, `${path}.variation_revision`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function baselineCanvasModelSummaryV2(value: unknown, path = "model_summary"): CanvasModelSummaryV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    ["model_ref", "provider_id", "display_name", "capability", "availability", "unavailable_reason", "catalog_revision"],
    path,
  );
  return {
    model_ref: expectNonEmptyString(record.model_ref, `${path}.model_ref`),
    provider_id: expectNonEmptyString(record.provider_id, `${path}.provider_id`),
    display_name: expectNonEmptyString(record.display_name, `${path}.display_name`),
    capability: expectLiteral(record.capability, CANVAS_MODEL_CAPABILITIES, `${path}.capability`),
    availability: expectLiteral(record.availability, CANVAS_MODEL_AVAILABILITIES, `${path}.availability`),
    unavailable_reason: nullableString(record.unavailable_reason, `${path}.unavailable_reason`),
    catalog_revision: expectPositiveInteger(record.catalog_revision, `${path}.catalog_revision`),
  };
}

function baselineVideoSkillPreviewV2(value: unknown, path: string): VideoSkillPreviewV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["kind", "summary", "media_url"], path);
  return {
    kind: expectLiteral(
      record.kind,
      new Set<VideoSkillPreviewV2["kind"]>(["none", "image", "video"]),
      `${path}.kind`,
    ),
    summary: nullableStringWithDefault(record.summary, `${path}.summary`),
    media_url: nullablePublicPreviewUrl(record.media_url ?? null, `${path}.media_url`),
  };
}

function baselineVideoSkillCategoryV2(value: unknown, path: string): VideoSkillCategoryV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["category_id", "title", "display_order"], path);
  return {
    category_id: expectNonEmptyString(record.category_id, `${path}.category_id`),
    title: expectNonEmptyString(record.title, `${path}.title`),
    display_order: expectNonNegativeInteger(record.display_order, `${path}.display_order`),
  };
}

function baselineVideoSkillPublicDetailV2(
  value: unknown,
  path = "videoSkill",
): VideoSkillPublicDetailV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "skill_id",
      "version",
      "title",
      "summary",
      "category",
      "tags",
      "supported_use_cases",
      "preview",
      "display_order",
    ],
    path,
  );
  return {
    skill_id: expectNonEmptyString(record.skill_id, `${path}.skill_id`),
    version: expectNonEmptyString(record.version, `${path}.version`),
    title: expectNonEmptyString(record.title, `${path}.title`),
    summary: expectNonEmptyString(record.summary, `${path}.summary`),
    category: expectNonEmptyString(record.category, `${path}.category`),
    tags: optionalStringArray(record.tags, `${path}.tags`),
    supported_use_cases: optionalStringArray(
      record.supported_use_cases,
      `${path}.supported_use_cases`,
    ),
    preview: record.preview === undefined || record.preview === null
      ? null
      : baselineVideoSkillPreviewV2(record.preview, `${path}.preview`),
    display_order: expectNonNegativeInteger(record.display_order, `${path}.display_order`),
  };
}

function baselineVideoSkillCatalogResponseV2(
  value: unknown,
  path = "videoSkillCatalog",
): VideoSkillCatalogResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["catalog_version", "categories", "items", "next_cursor"], path);
  return {
    catalog_version: expectNonEmptyString(record.catalog_version, `${path}.catalog_version`),
    categories: expectArray(record.categories, `${path}.categories`).map((item, index) => (
      baselineVideoSkillCategoryV2(item, `${path}.categories[${index}]`)
    )),
    items: expectArray(record.items, `${path}.items`).map((item, index) => (
      baselineVideoSkillPublicDetailV2(item, `${path}.items[${index}]`)
    )),
    next_cursor: nullableStringWithDefault(record.next_cursor, `${path}.next_cursor`),
  };
}

function baselineAgentExecutionSettingsV2(
  value: unknown,
  path = "agentSettings",
): AgentExecutionSettingsV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    ["workflow_id", "media_execution_mode", "revision", "created_at", "updated_at"],
    path,
  );
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    media_execution_mode: expectLiteral(
      record.media_execution_mode,
      AGENT_MEDIA_EXECUTION_MODES,
      `${path}.media_execution_mode`,
    ),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function baselineBindingCapabilityDecisionV2(value: unknown, path = "bindingCapabilityDecision"): BindingCapabilityDecisionV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["accepted", "target_node_id", "selected_model_id", "required_input_types", "compatible_model_ids", "switch_model_required"], path);
  return {
    accepted: expectBoolean(record.accepted, `${path}.accepted`),
    target_node_id: expectNonEmptyString(record.target_node_id, `${path}.target_node_id`),
    selected_model_id: nullableString(record.selected_model_id, `${path}.selected_model_id`),
    required_input_types: expectArray(record.required_input_types, `${path}.required_input_types`).map((item, index) =>
      expectLiteral(item, PROVIDER_INPUT_TYPES, `${path}.required_input_types[${index}]`),
    ),
    compatible_model_ids: expectStringArray(record.compatible_model_ids, `${path}.compatible_model_ids`),
    switch_model_required: expectBoolean(record.switch_model_required, `${path}.switch_model_required`),
  };
}

function baselineEditingSkippedInputV2(value: unknown, path = "editing.skippedInput"): EditingSkippedInputV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["reference_id", "node_id", "asset_id", "reason"], path);
  return {
    reference_id: expectNonEmptyString(record.reference_id, `${path}.reference_id`),
    node_id: record.node_id === undefined ? null : nullableString(record.node_id, `${path}.node_id`),
    asset_id: record.asset_id === undefined ? null : nullableString(record.asset_id, `${path}.asset_id`),
    reason: expectLiteral(record.reason, EDITING_SKIPPED_REASONS, `${path}.reason`),
  };
}

function baselineEditingPreviewClipV2(value: unknown, path = "editing.previewClip"): EditingPreviewClipV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["reference_id", "binding_id", "node_id", "asset_id", "status", "display_order", "preview_url", "duration_seconds", "warning"], path);
  return {
    reference_id: expectNonEmptyString(record.reference_id, `${path}.reference_id`),
    binding_id: record.binding_id === undefined ? null : nullableString(record.binding_id, `${path}.binding_id`),
    node_id: record.node_id === undefined ? null : nullableString(record.node_id, `${path}.node_id`),
    asset_id: record.asset_id === undefined ? null : nullableString(record.asset_id, `${path}.asset_id`),
    status: expectLiteral(record.status, CANVAS_NODE_STATUSES, `${path}.status`),
    display_order: expectNonNegativeInteger(record.display_order, `${path}.display_order`),
    preview_url: nullableString(record.preview_url, `${path}.preview_url`),
    duration_seconds: nullableFiniteNumber(record.duration_seconds, `${path}.duration_seconds`),
    warning: nullableString(record.warning, `${path}.warning`),
  };
}

function baselineEditingPreviewV2(value: unknown, path = "editing.preview"): EditingPreviewV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["clips", "bgm_binding_id", "bgm_node_id", "bgm_asset_id", "estimated_duration_seconds", "warnings"], path);
  return {
    clips: expectArray(record.clips, `${path}.clips`).map((item, index) => baselineEditingPreviewClipV2(item, `${path}.clips[${index}]`)),
    bgm_binding_id: record.bgm_binding_id === undefined ? null : nullableString(record.bgm_binding_id, `${path}.bgm_binding_id`),
    bgm_node_id: record.bgm_node_id === undefined ? null : nullableString(record.bgm_node_id, `${path}.bgm_node_id`),
    bgm_asset_id: record.bgm_asset_id === undefined ? null : nullableString(record.bgm_asset_id, `${path}.bgm_asset_id`),
    estimated_duration_seconds: expectFiniteNumber(record.estimated_duration_seconds, `${path}.estimated_duration_seconds`),
    warnings: optionalStringArray(record.warnings, `${path}.warnings`, []),
  };
}

function baselineAgentCanvasImageLibraryListResponseV2(
  value: unknown,
  path = "imageLibrary",
): AgentCanvasImageLibraryListResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["items"], path);
  return {
    items: expectArray(record.items, `${path}.items`).map((item, index) =>
      expectUnknownRecord(item, `${path}.items[${index}]`),
    ),
  };
}

function baselineCanvasRunCancelResponseV2(
  value: unknown,
  path = "runCancel",
): CanvasRunCancelResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "execution_id", "status", "cancelled_node_ids", "events_cursor"], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    execution_id: expectNonEmptyString(record.execution_id, `${path}.execution_id`),
    status: expectLiteral(record.status, new Set<CanvasRunCancelResponseV2["status"]>(["cancelled"]), `${path}.status`),
    cancelled_node_ids: optionalStringArray(record.cancelled_node_ids, `${path}.cancelled_node_ids`, []),
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
  };
}

function baselineEditingExportAcceptedV2(
  value: unknown,
  path = "editingExportAccepted",
): EditingExportAcceptedV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "workflow_id",
      "node_id",
      "export_id",
      "status",
      "manifest_revision",
      "ready_video_node_ids",
      "skipped_inputs",
      "bgm_node_id",
      "events_cursor",
    ],
    path,
  );
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    export_id: expectNonEmptyString(record.export_id, `${path}.export_id`),
    status: expectLiteral(record.status, EDITING_EXPORT_STATUSES, `${path}.status`),
    manifest_revision: expectNonNegativeInteger(record.manifest_revision, `${path}.manifest_revision`),
    ready_video_node_ids: expectStringArray(record.ready_video_node_ids, `${path}.ready_video_node_ids`),
    skipped_inputs: expectArray(record.skipped_inputs, `${path}.skipped_inputs`).map((item, index) =>
      baselineEditingSkippedInputV2(item, `${path}.skipped_inputs[${index}]`),
    ),
    bgm_node_id: nullableString(record.bgm_node_id, `${path}.bgm_node_id`),
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
  };
}

function baselineEditingExportCancelResponseV2(
  value: unknown,
  path = "editingExportCancel",
): EditingExportCancelResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "node_id", "export_id", "status", "events_cursor"], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    export_id: expectNonEmptyString(record.export_id, `${path}.export_id`),
    status: expectLiteral(record.status, new Set<EditingExportCancelResponseV2["status"]>(["cancelled"]), `${path}.status`),
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
  };
}

const clip = { reference_id: "ref", binding_id: null, node_id: null, asset_id: null, status: "ready", display_order: 0, preview_url: null, duration_seconds: null, warning: null };
const skill = { skill_id: "skill", version: "1", title: "Title", summary: "Summary", category: "cat", tags: ["tag"], supported_use_cases: [], preview: { kind: "none", summary: null, media_url: null }, display_order: 0 };
const skipped = { reference_id: "ref", node_id: null, asset_id: null, reason: "source_not_ready" };
const cases: Array<[string, (value: unknown, path: string) => unknown, (value: unknown, path: string) => unknown, JsonRecord]> = [
  ["placement", normalizeAgentPlacementHintV2, baselineAgentPlacementHintV2, { intent: "append_flow", anchor_node_id: null, group_key: null }],
  ["variation", normalizeCanvasVariationDraftV2, baselineCanvasVariationDraftV2, { source_node_id: "node", source_node_revision: 1, title: "Title", generation_prompt: "Prompt", model_id: null, model_selection_mode: "default", model_ref: null, parameters: {}, variation_revision: 1, created_at: "now", updated_at: "now" }],
  ["model", normalizeCanvasModelSummaryV2, baselineCanvasModelSummaryV2, { model_ref: "m", provider_id: "p", display_name: "Model", capability: "video", availability: "available", unavailable_reason: null, catalog_revision: 1 }],
  ["skill", normalizeVideoSkillPublicDetailV2, baselineVideoSkillPublicDetailV2, skill],
  ["catalog", normalizeVideoSkillCatalogResponseV2, baselineVideoSkillCatalogResponseV2, { catalog_version: "1", categories: [{ category_id: "cat", title: "Category", display_order: 0 }], items: [skill], next_cursor: null }],
  ["settings", normalizeAgentExecutionSettingsV2, baselineAgentExecutionSettingsV2, { workflow_id: "w", media_execution_mode: "manual", revision: 1, created_at: "now", updated_at: "now" }],
  ["binding", normalizeBindingCapabilityDecisionV2, baselineBindingCapabilityDecisionV2, { accepted: true, target_node_id: "n", selected_model_id: null, required_input_types: ["image"], compatible_model_ids: ["m"], switch_model_required: false }],
  ["skipped", normalizeEditingSkippedInputV2, baselineEditingSkippedInputV2, skipped],
  ["clip", normalizeEditingPreviewClipV2, baselineEditingPreviewClipV2, clip],
  ["preview", normalizeEditingPreviewV2, baselineEditingPreviewV2, { clips: [clip], bgm_binding_id: null, bgm_node_id: null, bgm_asset_id: null, estimated_duration_seconds: 1, warnings: [] }],
  ["library", normalizeAgentCanvasImageLibraryListResponseV2, baselineAgentCanvasImageLibraryListResponseV2, { items: [{ arbitrary: true }] }],
  ["run cancel", normalizeCanvasRunCancelResponseV2, baselineCanvasRunCancelResponseV2, { workflow_id: "w", execution_id: "e", status: "cancelled", cancelled_node_ids: [], events_cursor: 0 }],
  ["export accepted", normalizeEditingExportAcceptedV2, baselineEditingExportAcceptedV2, { workflow_id: "w", node_id: "n", export_id: "e", status: "queued", manifest_revision: 0, ready_video_node_ids: [], skipped_inputs: [skipped], bgm_node_id: null, events_cursor: 0 }],
  ["export cancel", normalizeEditingExportCancelResponseV2, baselineEditingExportCancelResponseV2, { workflow_id: "w", node_id: "n", export_id: "e", status: "cancelled", events_cursor: 0 }],
];

function outcome(normalize: (value: unknown, path: string) => unknown, value: unknown, path: string) {
  try { return { result: normalize(value, path) }; }
  catch (error) {
    if (!(error instanceof V2ContractValidationError)) throw error;
    return { error: { name: error.name, path: error.path, reason: error.reason, message: error.message } };
  }
}

function compare(actual: (value: unknown, path: string) => unknown, baseline: (value: unknown, path: string) => unknown, value: unknown, path: string) {
  const expected = outcome(baseline, value, path);
  const observed = outcome(actual, value, path);
  expect(observed).toStrictEqual(expected);
  if ("result" in observed && "result" in expected) {
    expect(Object.getOwnPropertyDescriptors(observed.result)).toStrictEqual(Object.getOwnPropertyDescriptors(expected.result));
  }
}

describe("strict record refactor differential mutations", () => {
  for (const [name, actual, baseline, valid] of cases) {
    it(name + " preserves outputs, defaults and every field mutation", () => {
      for (const path of ["root", "workflow.nodes[2].payload"]) {
        compare(actual, baseline, valid, path);
        for (const invalid of [null, undefined, [], "string", 1, true]) compare(actual, baseline, invalid, path);
        for (const key of Object.keys(valid)) {
          const missing = { ...valid }; delete missing[key]; compare(actual, baseline, missing, path);
          for (const mutation of [undefined, null, "", " ", "unsupported", -1, 0, 1.5, NaN, Infinity, true, false, [], {}, [null]]) {
            compare(actual, baseline, { ...valid, [key]: mutation }, path);
          }
        }
        // All invalid fields: schema order, not input insertion order, wins.
        const invalid = Object.fromEntries(Object.keys(valid).reverse().map((key) => [key, null]));
        compare(actual, baseline, invalid, path);
        // Unknown fields win even when all declared fields are invalid.
        for (const extras of [{ z_unknown: true, a_unknown: true }, { a_unknown: true, z_unknown: true }, { "2": true, "1": true }, { constructor: true }, { toString: true }, JSON.parse('{"__proto__": true}')]) {
          compare(actual, baseline, { ...invalid, ...extras }, path);
        }
        const inherited = Object.create(valid); compare(actual, baseline, inherited, path);
        const hidden = { ...valid }; Object.defineProperty(hidden, "hiddenUnknown", { value: true }); Object.defineProperty(hidden, Symbol("unknown"), { value: true, enumerable: true });
        compare(actual, baseline, hidden, path);
      }
    });
  }
  it("mutates nested preview and category records with independent baselines", () => {
    for (const nested of [null, {}, { kind: "none", extra: true }, { kind: "invalid", summary: 4 }, { kind: "image", summary: "", media_url: "javascript:bad" }]) {
      compare(normalizeVideoSkillPublicDetailV2, baselineVideoSkillPublicDetailV2, { ...skill, preview: nested }, "nested.skill");
    }
    for (const nested of [null, {}, { category_id: "cat", title: 1, display_order: -1 }, { extra: true }, { category_id: "cat", title: "Category", display_order: 0, z: true, a: true }]) {
      compare(normalizeVideoSkillCatalogResponseV2, baselineVideoSkillCatalogResponseV2, { catalog_version: "1", categories: [nested], items: [skill], next_cursor: null }, "nested.catalog");
    }
  });
});
