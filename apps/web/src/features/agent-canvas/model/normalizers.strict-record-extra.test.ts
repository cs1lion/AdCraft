import { describe, expect, it } from "vitest";
import type { AgentCanvasVideoSkillRunV2, CanvasBindingMutationResponseV2, CanvasConnectedNodeCreateResponseV2, ActionableFailureV1, CanvasVariationDraftResponseV2, CanvasVariationMaterializeResponseV2, ChatTimelineListResponseV2, EditingExportRuntimeV2, CanvasEditingExportImportResponseV2, EditingNodeContentV2, DecisionBundleActionAcceptedV2, ProjectAssetSummaryV2, ProjectAssetListResponseV2, ProjectAssetStatusV2, ProjectAssetUploadResponseV2, ResolvedTextInputSnapshotV2, GuidedInteractionAcceptedV1, ProposalMaterializationErrorV2 } from "../../../types-v2.ts";
import { V2ContractValidationError } from "../../../api/v2ContractValidationError.ts";
import { normalizeProjectAssetSummaryV2, normalizeCanvasConnectedNodeCreateResponseV2, normalizeCanvasBindingMutationResponseV2, normalizeResolvedTextInputSnapshotV2, normalizeProposalMaterializationErrorV2, normalizeEditingExportRuntimeV2, normalizeEditingNodeContentV2, normalizeCanvasEditingExportImportResponseV2, normalizeCanvasVariationDraftResponseV2, normalizeCanvasVariationMaterializeResponseV2, normalizeProjectAssetUploadResponseV2, normalizeProjectAssetListResponseV2, normalizeDecisionBundleActionAcceptedV2, normalizeGuidedInteractionAcceptedV1, normalizeAgentCanvasVideoSkillRunV2, normalizeChatTimelineListResponseV2, normalizeCanvasNodeV2, normalizeCanvasBindingV2, normalizeEditingSkippedInputV2, normalizeCanvasNodeErrorV2, normalizeEditingManifestV2, normalizeEditingPreviewV2, normalizeCanvasVariationDraftV2, normalizeAgentPlacementHintV2, normalizeVideoSkillPublicDetailV2, normalizeGuidanceAdvancePreconditionV1, normalizeChatTimelineItemV2, normalizeActionableFailureV1 } from "./normalizers.ts";
// Frozen from the dirty working baseline BEFORE production edits. No strict-record helper is shared.
// Unchanged nested public normalizers are deliberately shared; selected nested functions are frozen too.
type JsonRecord = Record<string, unknown>;
const ASSET_MEDIA_TYPES = new Set<ProjectAssetSummaryV2["media_type"]>(["image", "video", "audio"]);

const ASSET_SOURCE_TYPES = new Set<ProjectAssetSummaryV2["source_type"]>([
  "upload",
  "generated",
  "recommended",
  "library",
  "editing_export",
  "derived",
]);

const PROJECT_ASSET_STATUSES = new Set<ProjectAssetStatusV2>(["ready", "unavailable"]);

const EDITING_EXPORT_STATUSES = new Set<EditingExportRuntimeV2["status"]>(["queued", "exporting", "completed", "failed", "cancelled"]);

const RESOLVED_TEXT_BINDING_KINDS = new Set<ResolvedTextInputSnapshotV2["binding_kind"]>(["text_context"]);

const RESOLVED_DOCUMENT_KINDS = new Set<ResolvedTextInputSnapshotV2["document_kind"]>(["text", "script"]);

function expectRecord(value: unknown, path: string): JsonRecord {
  if (!isRecord(value)) fail(path, "expected object");
  return value;
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function fail(path: string, message: string): never {
  throw new V2ContractValidationError(path, message);
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

function expectString(value: unknown, path: string) {
  if (typeof value !== "string") fail(path, "expected string");
  return value;
}

function nullableString(value: unknown, path: string) {
  if (value === null) return null;
  return expectString(value, path);
}

function expectLiteral<T extends string>(value: unknown, allowed: ReadonlySet<T>, path: string): T {
  const result = expectString(value, path);
  if (!allowed.has(result as T)) fail(path, `expected one of ${Array.from(allowed).join(", ")}`);
  return result as T;
}

function expectNonNegativeInteger(value: unknown, path: string) {
  const result = expectInteger(value, path);
  if (result < 0) fail(path, "expected non-negative integer");
  return result;
}

function expectInteger(value: unknown, path: string) {
  const result = expectFiniteNumber(value, path);
  if (!Number.isInteger(result)) fail(path, "expected integer");
  return result;
}

function expectFiniteNumber(value: unknown, path: string) {
  if (typeof value !== "number" || !Number.isFinite(value)) fail(path, "expected finite number");
  return value;
}

function nullableBrowserSafeUrl(value: unknown, path: string) {
  if (value === null) return null;
  const result = expectNonEmptyString(value, path);
  if (!result.startsWith("/api/") && !result.startsWith("https://") && !result.startsWith("http://")) {
    fail(path, "expected browser-safe URL");
  }
  return result;
}

function nullablePositiveInteger(value: unknown, path: string) {
  if (value === null) return null;
  return expectPositiveInteger(value, path);
}

function expectPositiveInteger(value: unknown, path: string) {
  const result = expectInteger(value, path);
  if (result <= 0) fail(path, "expected positive integer");
  return result;
}

function nullableNonNegativeNumber(value: unknown, path: string) {
  if (value === null) return null;
  const result = expectFiniteNumber(value, path);
  if (result < 0) fail(path, "expected non-negative number");
  return result;
}

function optionalUnknownRecord(value: unknown, path: string, defaultValue: JsonRecord = {}) {
  if (value === undefined) return defaultValue;
  return expectUnknownRecord(value, path);
}

function expectUnknownRecord(value: unknown, path: string) {
  if (!isRecord(value)) fail(path, "expected object");
  return value;
}

function expectIsoDateTimeString(value: unknown, path: string) {
  return expectNonEmptyString(value, path);
}

function expectArray(value: unknown, path: string) {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value;
}

function optionalStringArray(value: unknown, path: string, defaultValue: string[] = []) {
  if (value === undefined) return defaultValue;
  return expectStringArray(value, path);
}

function expectStringArray(value: unknown, path: string) {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value.map((item, index) => expectString(item, `${path}[${index}]`));
}

function expectBoolean(value: unknown, path: string) {
  if (typeof value !== "boolean") fail(path, "expected boolean");
  return value;
}

function nullableStringWithDefault(value: unknown, path: string) {
  return value === undefined ? null : nullableString(value, path);
}

function baselineProjectAssetSummaryV2(value: unknown, path = "asset"): ProjectAssetSummaryV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "asset_id",
      "version_id",
      "project_id",
      "workflow_id",
      "media_type",
      "source_type",
      "semantic_type",
      "display_name",
      "mime_type",
      "status",
      "size_bytes",
      "storage_key",
      "preview_url",
      "media_url",
      "width",
      "height",
      "duration_seconds",
      "checksum",
      "source_semantic_role",
      "source_node_id",
      "source_execution_id",
      "provider",
      "model_id",
      "prompt_provenance",
      "actual_media_facts",
      "generation_provenance",
      "quality_metadata",
      "created_at",
    ],
    path,
  );
  return {
    asset_id: expectNonEmptyString(record.asset_id, `${path}.asset_id`),
    version_id: record.version_id === undefined ? null : nullableString(record.version_id, `${path}.version_id`),
    project_id: record.project_id === undefined ? null : nullableString(record.project_id, `${path}.project_id`),
    workflow_id: record.workflow_id === undefined ? null : nullableString(record.workflow_id, `${path}.workflow_id`),
    media_type: expectLiteral(record.media_type, ASSET_MEDIA_TYPES, `${path}.media_type`),
    source_type: expectLiteral(record.source_type, ASSET_SOURCE_TYPES, `${path}.source_type`),
    semantic_type: record.semantic_type === undefined ? null : nullableString(record.semantic_type, `${path}.semantic_type`),
    display_name: expectNonEmptyString(record.display_name, `${path}.display_name`),
    mime_type: expectNonEmptyString(record.mime_type, `${path}.mime_type`),
    status: expectLiteral(record.status, PROJECT_ASSET_STATUSES, `${path}.status`),
    size_bytes: record.size_bytes === undefined ? 0 : expectNonNegativeInteger(record.size_bytes, `${path}.size_bytes`),
    storage_key: record.storage_key === undefined ? null : nullableString(record.storage_key, `${path}.storage_key`),
    preview_url: nullableBrowserSafeUrl(record.preview_url, `${path}.preview_url`),
    media_url: nullableBrowserSafeUrl(record.media_url, `${path}.media_url`),
    width: nullablePositiveInteger(record.width, `${path}.width`),
    height: nullablePositiveInteger(record.height, `${path}.height`),
    duration_seconds: nullableNonNegativeNumber(record.duration_seconds, `${path}.duration_seconds`),
    checksum: expectNonEmptyString(record.checksum, `${path}.checksum`),
    source_semantic_role: record.source_semantic_role === undefined
      ? null
      : nullableString(record.source_semantic_role, `${path}.source_semantic_role`),
    source_node_id: record.source_node_id === undefined ? null : nullableString(record.source_node_id, `${path}.source_node_id`),
    source_execution_id: record.source_execution_id === undefined
      ? null
      : nullableString(record.source_execution_id, `${path}.source_execution_id`),
    provider: record.provider === undefined ? null : nullableString(record.provider, `${path}.provider`),
    model_id: record.model_id === undefined ? null : nullableString(record.model_id, `${path}.model_id`),
    prompt_provenance: optionalUnknownRecord(record.prompt_provenance, `${path}.prompt_provenance`, {}),
    actual_media_facts: optionalUnknownRecord(record.actual_media_facts, `${path}.actual_media_facts`, {}),
    generation_provenance: optionalUnknownRecord(record.generation_provenance, `${path}.generation_provenance`, {}),
    quality_metadata: optionalUnknownRecord(record.quality_metadata, `${path}.quality_metadata`, {}),
    created_at: record.created_at === undefined || record.created_at === null
      ? null
      : expectIsoDateTimeString(record.created_at, `${path}.created_at`),
  };
}

function baselineCanvasConnectedNodeCreateResponseV2(
  value: unknown,
  path = "connectedNode",
): CanvasConnectedNodeCreateResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    ["workflow_id", "revision", "layout_revision", "node", "binding", "events_cursor"],
    path,
  );
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    layout_revision: expectPositiveInteger(record.layout_revision, `${path}.layout_revision`),
    node: normalizeCanvasNodeV2(record.node, `${path}.node`),
    binding: normalizeCanvasBindingV2(record.binding, `${path}.binding`),
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
  };
}

function baselineCanvasBindingMutationResponseV2(
  value: unknown,
  path = "bindingMutation",
): CanvasBindingMutationResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    ["workflow_id", "revision", "binding", "incoming_bindings", "events_cursor"],
    path,
  );
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    binding: normalizeCanvasBindingV2(record.binding, `${path}.binding`),
    incoming_bindings: expectArray(record.incoming_bindings, `${path}.incoming_bindings`)
      .map((item, index) => normalizeCanvasBindingV2(item, `${path}.incoming_bindings[${index}]`)),
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
  };
}

function baselineResolvedTextInputSnapshotV2(value: unknown, path = "resolvedInput"): ResolvedTextInputSnapshotV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "snapshot_type",
      "source_kind",
      "source_node_id",
      "source_node_revision",
      "binding_kind",
      "document_kind",
      "content",
      "content_hash",
      "binding_id",
      "input_role",
      "display_order",
    ],
    path,
  );
  return {
    snapshot_type: expectLiteral(record.snapshot_type, new Set<ResolvedTextInputSnapshotV2["snapshot_type"]>(["text"]), `${path}.snapshot_type`),
    source_kind: expectLiteral(record.source_kind, new Set<ResolvedTextInputSnapshotV2["source_kind"]>(["node_output"]), `${path}.source_kind`),
    source_node_id: expectNonEmptyString(record.source_node_id, `${path}.source_node_id`),
    source_node_revision: expectPositiveInteger(record.source_node_revision, `${path}.source_node_revision`),
    binding_kind: expectLiteral(record.binding_kind, RESOLVED_TEXT_BINDING_KINDS, `${path}.binding_kind`),
    document_kind: expectLiteral(record.document_kind, RESOLVED_DOCUMENT_KINDS, `${path}.document_kind`),
    content: expectString(record.content, `${path}.content`),
    content_hash: expectNonEmptyString(record.content_hash, `${path}.content_hash`),
    binding_id: nullableString(record.binding_id, `${path}.binding_id`),
    input_role: expectLiteral(
      record.input_role,
      new Set<ResolvedTextInputSnapshotV2["input_role"]>(["text_context"]),
      `${path}.input_role`,
    ),
    display_order: expectNonNegativeInteger(record.display_order, `${path}.display_order`),
  };
}

function baselineProposalMaterializationErrorV2(
  value: unknown,
  path: string,
): ProposalMaterializationErrorV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["code", "message", "actionable_failure"], path);
  return {
    code: expectNonEmptyString(record.code, `${path}.code`),
    message: expectNonEmptyString(record.message, `${path}.message`),
    actionable_failure: baselineNullableActionableFailureV1(
      record.actionable_failure,
      `${path}.actionable_failure`,
    ),
  };
}

function baselineEditingExportRuntimeV2(value: unknown, path = "editing.exportRuntime"): EditingExportRuntimeV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["export_id", "status", "manifest_revision", "fingerprint", "ready_video_node_ids", "skipped_inputs", "bgm_node_id", "output_asset_id", "error", "started_at", "finished_at"], path);
  return {
    export_id: expectNonEmptyString(record.export_id, `${path}.export_id`),
    status: expectLiteral(record.status, EDITING_EXPORT_STATUSES, `${path}.status`),
    manifest_revision: expectNonNegativeInteger(record.manifest_revision, `${path}.manifest_revision`),
    fingerprint: expectNonEmptyString(record.fingerprint, `${path}.fingerprint`),
    ready_video_node_ids: optionalStringArray(record.ready_video_node_ids, `${path}.ready_video_node_ids`, []),
    skipped_inputs: expectArray(record.skipped_inputs, `${path}.skipped_inputs`).map((item, index) =>
      normalizeEditingSkippedInputV2(item, `${path}.skipped_inputs[${index}]`),
    ),
    bgm_node_id: record.bgm_node_id === undefined ? null : nullableString(record.bgm_node_id, `${path}.bgm_node_id`),
    output_asset_id: record.output_asset_id === undefined ? null : nullableString(record.output_asset_id, `${path}.output_asset_id`),
    error: record.error === null ? null : normalizeCanvasNodeErrorV2(record.error, `${path}.error`),
    started_at: record.started_at === undefined ? null : nullableString(record.started_at, `${path}.started_at`),
    finished_at: record.finished_at === undefined ? null : nullableString(record.finished_at, `${path}.finished_at`),
  };
}

function baselineEditingNodeContentV2(value: unknown, path = "editing"): EditingNodeContentV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["manifest", "dirty", "preview", "last_successful_export", "active_export"], path);
  return {
    manifest: normalizeEditingManifestV2(record.manifest, `${path}.manifest`),
    dirty: expectBoolean(record.dirty, `${path}.dirty`),
    preview: normalizeEditingPreviewV2(record.preview, `${path}.preview`),
    last_successful_export:
      record.last_successful_export === null
        ? null
        : record.last_successful_export === undefined
          ? null
          : baselineEditingExportRuntimeV2(record.last_successful_export, `${path}.last_successful_export`),
    active_export:
      record.active_export === null
        ? null
        : record.active_export === undefined
          ? null
          : baselineEditingExportRuntimeV2(record.active_export, `${path}.active_export`),
  };
}

function baselineCanvasEditingExportImportResponseV2(
  value: unknown,
  path = "editingExportImport",
): CanvasEditingExportImportResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "workflow_id",
    "revision",
    "layout_revision",
    "node",
    "binding",
    "asset",
    "events_cursor",
    "replayed",
  ], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    revision: expectNonNegativeInteger(record.revision, `${path}.revision`),
    layout_revision: expectNonNegativeInteger(record.layout_revision, `${path}.layout_revision`),
    node: normalizeCanvasNodeV2(record.node, `${path}.node`),
    binding: normalizeCanvasBindingV2(record.binding, `${path}.binding`),
    asset: baselineProjectAssetSummaryV2(record.asset, `${path}.asset`),
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
    replayed: expectBoolean(record.replayed, `${path}.replayed`),
  };
}

function baselineCanvasVariationDraftResponseV2(
  value: unknown,
  path = "variationDraftResponse",
): CanvasVariationDraftResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "workflow_id",
    "workflow_revision",
    "node_id",
    "variation_draft",
  ], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    workflow_revision: expectPositiveInteger(record.workflow_revision, `${path}.workflow_revision`),
    node_id: expectNonEmptyString(record.node_id, `${path}.node_id`),
    variation_draft: normalizeCanvasVariationDraftV2(record.variation_draft, `${path}.variation_draft`),
  };
}

function baselineCanvasVariationMaterializeResponseV2(
  value: unknown,
  path = "variationMaterialize",
): CanvasVariationMaterializeResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "workflow_id",
    "workflow_revision",
    "source_node_id",
    "sibling_node",
    "copied_binding_ids",
    "run",
    "run_error",
    "placement_hint",
    "created_node_ids",
    "created_binding_ids",
    "placement_hints",
  ], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    workflow_revision: expectPositiveInteger(record.workflow_revision, `${path}.workflow_revision`),
    source_node_id: expectNonEmptyString(record.source_node_id, `${path}.source_node_id`),
    sibling_node: normalizeCanvasNodeV2(record.sibling_node, `${path}.sibling_node`),
    copied_binding_ids: optionalStringArray(record.copied_binding_ids, `${path}.copied_binding_ids`, []),
    run: record.run === null || record.run === undefined
      ? null
      : expectUnknownRecord(record.run, `${path}.run`),
    run_error: record.run_error === null || record.run_error === undefined
      ? null
      : normalizeCanvasNodeErrorV2(record.run_error, `${path}.run_error`),
    placement_hint: normalizeAgentPlacementHintV2(record.placement_hint, `${path}.placement_hint`),
    created_node_ids: optionalStringArray(record.created_node_ids, `${path}.created_node_ids`, []),
    created_binding_ids: optionalStringArray(
      record.created_binding_ids,
      `${path}.created_binding_ids`,
      [],
    ),
    placement_hints: expectArray(record.placement_hints ?? [], `${path}.placement_hints`)
      .map((item, index) => normalizeAgentPlacementHintV2(
        item,
        `${path}.placement_hints[${index}]`,
      )),
  };
}

function baselineProjectAssetUploadResponseV2(
  value: unknown,
  path = "assetUpload",
): ProjectAssetUploadResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "asset", "pending_handoff_id"], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    asset: baselineProjectAssetSummaryV2(record.asset, `${path}.asset`),
    pending_handoff_id: nullableStringWithDefault(record.pending_handoff_id, `${path}.pending_handoff_id`),
  };
}

function baselineProjectAssetListResponseV2(
  value: unknown,
  path = "assetList",
): ProjectAssetListResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "assets"], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    assets: expectArray(record.assets, `${path}.assets`).map((item, index) =>
      baselineProjectAssetSummaryV2(item, `${path}.assets[${index}]`),
    ),
  };
}

function baselineDecisionBundleActionAcceptedV2(
  value: unknown,
  path = "decisionBundleAccepted",
): DecisionBundleActionAcceptedV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "workflow_id",
    "bundle_id",
    "status",
    "revision",
    "requirement_revision_no",
    "turn_id",
    "events_cursor",
    "replayed",
  ], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    bundle_id: expectNonEmptyString(record.bundle_id, `${path}.bundle_id`),
    status: expectLiteral(record.status, new Set(["answered", "skipped"] as const), `${path}.status`),
    revision: expectPositiveInteger(record.revision, `${path}.revision`),
    requirement_revision_no: expectPositiveInteger(
      record.requirement_revision_no,
      `${path}.requirement_revision_no`,
    ),
    turn_id: expectNonEmptyString(record.turn_id, `${path}.turn_id`),
    events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`),
    replayed: record.replayed === undefined ? false : expectBoolean(record.replayed, `${path}.replayed`),
  };
}

function baselineGuidedInteractionAcceptedV1(value: unknown, path = "guidedInteractionAccepted"): GuidedInteractionAcceptedV1 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "interaction_id", "submission_id", "receipt_id", "created_node_ids", "created_binding_ids", "document_revisions", "continuation_id", "automatic_run_command_ids", "resulting_session_revision", "events_cursor", "replayed"], path);
  return { workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`), interaction_id: expectNonEmptyString(record.interaction_id, `${path}.interaction_id`), submission_id: expectNonEmptyString(record.submission_id, `${path}.submission_id`), receipt_id: expectNonEmptyString(record.receipt_id, `${path}.receipt_id`), created_node_ids: optionalStringArray(record.created_node_ids, `${path}.created_node_ids`, []), created_binding_ids: optionalStringArray(record.created_binding_ids, `${path}.created_binding_ids`, []), document_revisions: baselineDocumentRevisions(record.document_revisions, `${path}.document_revisions`), continuation_id: nullableStringWithDefault(record.continuation_id, `${path}.continuation_id`), automatic_run_command_ids: optionalStringArray(record.automatic_run_command_ids, `${path}.automatic_run_command_ids`, []), resulting_session_revision: expectPositiveInteger(record.resulting_session_revision, `${path}.resulting_session_revision`), events_cursor: expectNonNegativeInteger(record.events_cursor, `${path}.events_cursor`), replayed: record.replayed === undefined ? false : expectBoolean(record.replayed, `${path}.replayed`) };
}

function baselineAgentCanvasVideoSkillRunV2(
  value: unknown,
  path = "videoSkillRun",
): AgentCanvasVideoSkillRunV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(
    record,
    [
      "skill_run_id",
      "workflow_id",
      "skill_id",
      "skill_version",
      "source_skill_run_id",
      "status",
      "active_creative_direction_snapshot_id",
      "public_skill",
      "created_at",
      "updated_at",
    ],
    path,
  );
  return {
    skill_run_id: expectNonEmptyString(record.skill_run_id, `${path}.skill_run_id`),
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    skill_id: expectNonEmptyString(record.skill_id, `${path}.skill_id`),
    skill_version: expectNonEmptyString(record.skill_version, `${path}.skill_version`),
    source_skill_run_id: record.source_skill_run_id === undefined
      ? null
      : nullableString(record.source_skill_run_id, `${path}.source_skill_run_id`),
    status: expectLiteral(
      record.status ?? "active",
      new Set<AgentCanvasVideoSkillRunV2["status"]>(["active", "superseded"]),
      `${path}.status`,
    ),
    active_creative_direction_snapshot_id: nullableStringWithDefault(
      record.active_creative_direction_snapshot_id,
      `${path}.active_creative_direction_snapshot_id`,
    ),
    public_skill: record.public_skill === undefined || record.public_skill === null
      ? null
      : normalizeVideoSkillPublicDetailV2(record.public_skill, `${path}.public_skill`),
    created_at: expectIsoDateTimeString(record.created_at, `${path}.created_at`),
    updated_at: record.updated_at === undefined || record.updated_at === null
      ? null
      : expectIsoDateTimeString(record.updated_at, `${path}.updated_at`),
  };
}

function baselineChatTimelineListResponseV2(value: unknown, path = "chatTimeline"): ChatTimelineListResponseV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["workflow_id", "conversation_id", "guidance_advance_precondition", "items", "next_after_seq"], path);
  return {
    workflow_id: expectNonEmptyString(record.workflow_id, `${path}.workflow_id`),
    conversation_id: record.conversation_id === null
      ? null
      : expectNonEmptyString(record.conversation_id, `${path}.conversation_id`),
    guidance_advance_precondition: record.guidance_advance_precondition === undefined || record.guidance_advance_precondition === null
      ? null
      : normalizeGuidanceAdvancePreconditionV1(
        record.guidance_advance_precondition,
        `${path}.guidance_advance_precondition`,
      ),
    items: expectArray(record.items, `${path}.items`).map((item, index) => normalizeChatTimelineItemV2(item, `${path}.items[${index}]`)),
    next_after_seq: expectNonNegativeInteger(record.next_after_seq, `${path}.next_after_seq`),
  };
}

function baselineDocumentRevisions(value: unknown, path: string): Record<string, number> {
  if (value === undefined || value === null) return {};
  const record = expectRecord(value, path);
  const result: Record<string, number> = {};
  Object.entries(record).forEach(([key, revision]) => {
    if (!key.trim()) fail(path, "document revision key must not be empty");
    result[key] = expectPositiveInteger(revision, `${path}.${key}`);
  });
  return result;
}

function baselineNullableActionableFailureV1(value: unknown, path: string): ActionableFailureV1 | null {
  if (value === null || value === undefined) return null;
  return normalizeActionableFailureV1(value, path);
}

const node = { node_id: "n", workflow_id: "w", node_type: "text", creative_role: "general_text", role_contract_version: "ad-media-role-v1", title: "Title", status: "draft", summary_prompt: null, generation_prompt: null, structured_content: {}, parameters: {}, prompt_context_snapshot_id: null, output_asset_id: null, output_asset_version_id: null, position: { x: 0, y: 1 }, revision: 1, error: null, created_at: "now", updated_at: "now" };
const binding = { binding_id: "b", workflow_id: "w", source: { kind: "node_output", source_node_id: "n" }, target_node_id: "n2", input_role: "text_context", enabled: true, order: 0, label: null, metadata: {}, created_at: "now", updated_at: "now" };
const asset = { asset_id: "a", version_id: null, project_id: null, workflow_id: null, media_type: "image", source_type: "upload", semantic_type: null, display_name: "Image", mime_type: "image/png", status: "ready", size_bytes: 0, storage_key: null, preview_url: "/api/preview", media_url: "https://example.com/media", width: 1, height: 1, duration_seconds: null, checksum: "hash", source_semantic_role: null, source_node_id: null, source_execution_id: null, provider: null, model_id: null, prompt_provenance: {}, actual_media_facts: {}, generation_provenance: {}, quality_metadata: {}, created_at: null };
const draft = { source_node_id: "n", source_node_revision: 1, title: "Title", generation_prompt: "Prompt", variation_revision: 1, created_at: "now", updated_at: "now" };
const placement = { intent: "append_flow", anchor_node_id: null, group_key: null };
const exportRuntime = { export_id: "e", status: "queued", manifest_revision: 0, fingerprint: "hash", ready_video_node_ids: [], skipped_inputs: [], bgm_node_id: null, output_asset_id: null, error: null, started_at: null, finished_at: null };
const preview = { clips: [], bgm_binding_id: null, bgm_node_id: null, bgm_asset_id: null, estimated_duration_seconds: 1, warnings: [] };
const cases: Array<[string, (value: unknown, path?: string) => unknown, (value: unknown, path?: string) => unknown, JsonRecord]> = [
  ["asset summary", normalizeProjectAssetSummaryV2, baselineProjectAssetSummaryV2, asset],
  ["connected", normalizeCanvasConnectedNodeCreateResponseV2, baselineCanvasConnectedNodeCreateResponseV2, { workflow_id: "w", revision: 1, layout_revision: 1, node, binding, events_cursor: 0 }],
  ["binding mutation", normalizeCanvasBindingMutationResponseV2, baselineCanvasBindingMutationResponseV2, { workflow_id: "w", revision: 1, binding, incoming_bindings: [binding], events_cursor: 0 }],
  ["resolved text", normalizeResolvedTextInputSnapshotV2, baselineResolvedTextInputSnapshotV2, { snapshot_type: "text", source_kind: "node_output", source_node_id: "n", source_node_revision: 1, binding_kind: "text_context", document_kind: "text", content: "", content_hash: "hash", binding_id: null, input_role: "text_context", display_order: 0 }],
  ["materialization error", (value, path = "materializationError") => normalizeProposalMaterializationErrorV2(value, path), (value, path = "materializationError") => baselineProposalMaterializationErrorV2(value, path), { code: "error", message: "Error", actionable_failure: null }],
  ["export runtime", normalizeEditingExportRuntimeV2, baselineEditingExportRuntimeV2, exportRuntime],
  ["editing content", normalizeEditingNodeContentV2, baselineEditingNodeContentV2, { manifest: { video_entries: [], bgm: null, output: {}, manifest_revision: 1 }, dirty: true, preview, last_successful_export: exportRuntime, active_export: exportRuntime }],
  ["export import", normalizeCanvasEditingExportImportResponseV2, baselineCanvasEditingExportImportResponseV2, { workflow_id: "w", revision: 0, layout_revision: 0, node, binding, asset, events_cursor: 0, replayed: false }],
  ["draft response", normalizeCanvasVariationDraftResponseV2, baselineCanvasVariationDraftResponseV2, { workflow_id: "w", workflow_revision: 1, node_id: "n", variation_draft: draft }],
  ["materialize", normalizeCanvasVariationMaterializeResponseV2, baselineCanvasVariationMaterializeResponseV2, { workflow_id: "w", workflow_revision: 1, source_node_id: "n", sibling_node: node, copied_binding_ids: [], run: null, run_error: null, placement_hint: placement, created_node_ids: [], created_binding_ids: [], placement_hints: [placement] }],
  ["upload", normalizeProjectAssetUploadResponseV2, baselineProjectAssetUploadResponseV2, { workflow_id: "w", asset, pending_handoff_id: null }],
  ["asset list", normalizeProjectAssetListResponseV2, baselineProjectAssetListResponseV2, { workflow_id: "w", assets: [asset] }],
  ["decision accepted", normalizeDecisionBundleActionAcceptedV2, baselineDecisionBundleActionAcceptedV2, { workflow_id: "w", bundle_id: "b", status: "answered", revision: 1, requirement_revision_no: 1, turn_id: "t", events_cursor: 0, replayed: false }],
  ["interaction accepted", normalizeGuidedInteractionAcceptedV1, baselineGuidedInteractionAcceptedV1, { workflow_id: "w", interaction_id: "i", submission_id: "s", receipt_id: "r", created_node_ids: [], created_binding_ids: [], document_revisions: { doc: 1 }, continuation_id: null, automatic_run_command_ids: [], resulting_session_revision: 1, events_cursor: 0, replayed: false }],
  ["skill run", normalizeAgentCanvasVideoSkillRunV2, baselineAgentCanvasVideoSkillRunV2, { skill_run_id: "r", workflow_id: "w", skill_id: "s", skill_version: "1", source_skill_run_id: null, status: "active", active_creative_direction_snapshot_id: null, public_skill: null, created_at: "now", updated_at: null }],
  ["chat list", normalizeChatTimelineListResponseV2, baselineChatTimelineListResponseV2, { workflow_id: "w", conversation_id: null, guidance_advance_precondition: null, items: [], next_after_seq: 0 }],
];
function outcome(normalize: (value: unknown, path?: string) => unknown, value: unknown, path?: string) {
  try { return { result: normalize(value, path) }; }
  catch (error) {
    if (!(error instanceof V2ContractValidationError)) throw error;
    return { error: { name: error.name, path: error.path, reason: error.reason, message: error.message } };
  }
}
function compare(actual: (value: unknown, path?: string) => unknown, baseline: (value: unknown, path?: string) => unknown, value: unknown, path?: string) {
  const expected = outcome(baseline, value, path);
  const observed = outcome(actual, value, path);
  expect(observed).toStrictEqual(expected);
  if ("result" in observed && "result" in expected) {
    expect(Object.keys(observed.result as object)).toEqual(Object.keys(expected.result as object));
    expect(Object.getOwnPropertyDescriptors(observed.result)).toStrictEqual(Object.getOwnPropertyDescriptors(expected.result));
    expect(Object.getPrototypeOf(observed.result)).toBe(Object.prototype);
  }
}
const mutations = [undefined, null, "", " ", "unsupported", -1, 0, 1, 1.5, NaN, Infinity, true, false, [], {}, [null], "javascript:bad", "//example.com/unsafe", "/public/not-api"];
describe("additional strict record conversions match frozen working baselines", () => {
  for (const [name, actual, baseline, valid] of cases) {
    it(name + " preserves every field, default, full error path, order and own property", () => {
      expect(outcome(baseline, valid)).toHaveProperty("result");
      for (const path of [undefined, "root", "workflow.nodes[2].payload"]) {
        compare(actual, baseline, valid, path);
        for (const invalid of [null, undefined, [], "string", 1, true]) compare(actual, baseline, invalid, path);
        for (const key of Object.keys(valid)) {
          const missing = { ...valid }; delete missing[key]; compare(actual, baseline, missing, path);
          for (const mutation of mutations) compare(actual, baseline, { ...valid, [key]: mutation }, path);
        }
        const invalid = Object.fromEntries(Object.keys(valid).reverse().map((key) => [key, null]));
        compare(actual, baseline, invalid, path);
        for (const extras of [{ z_unknown: true, a_unknown: true }, { a_unknown: true, z_unknown: true }, { "2": true, "1": true }, { constructor: true }, { toString: true }, JSON.parse('{"__proto__": true}')]) {
          compare(actual, baseline, { ...valid, ...extras }, path);
          compare(actual, baseline, { ...invalid, ...extras }, path);
        }
        compare(actual, baseline, Object.create(valid), path);
        const hidden = { ...valid }; Object.defineProperty(hidden, "hiddenUnknown", { value: true }); Object.defineProperty(hidden, Symbol("unknown"), { value: true, enumerable: true });
        compare(actual, baseline, hidden, path);
        // Getter traces lock field/schema order for stable transport values (not stateful getters).
        const trace: string[] = []; const input = {};
        for (const key of Object.keys(valid).reverse()) Object.defineProperty(input, key, { enumerable: true, get: () => { trace.push(key); return valid[key]; } });
        actual(input, path);
        expect([...new Set(trace)]).toEqual(Object.keys(valid));
      }
    });
  }
  it("locks the selected private document revision validator through its exported parent", () => {
    const [, actual, baseline, valid] = cases[13];
    for (const value of [undefined, null, {}, { doc: 0 }, { doc: 1.5 }, { " ": 1 }, { first: -1, second: null }, JSON.parse('{"__proto__": 1}'), { constructor: 1 }]) {
      compare(actual, baseline, { ...valid, document_revisions: value }, "nested.accepted");
    }
  });
  it("checks nested invalid paths after valid outer fields and independently frozen selected children", () => {
    for (const [, actual, baseline, valid] of cases) {
      for (const [key, value] of Object.entries(valid)) {
        if (value && typeof value === "object") {
          if (Array.isArray(value)) {
            for (const item of [null, {}, { unknown: true }]) compare(actual, baseline, { ...valid, [key]: [item] }, "nested.parent");
          } else {
            for (const nestedKey of Object.keys(value)) {
              for (const mutation of [undefined, null, {}, [], -1, "unsupported"]) {
                compare(actual, baseline, { ...valid, [key]: { ...value, [nestedKey]: mutation } }, "nested.parent");
              }
            }
            compare(actual, baseline, { ...valid, [key]: { ...value, z: true, a: true } }, "nested.parent");
          }
        }
      }
    }
  });
});
