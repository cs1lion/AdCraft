import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import { normalizeStrictRecord } from './strictRecordFields.ts';
import { V2ContractValidationError } from '../../../api/v2ContractValidationError.ts';
// Independent closure frozen from the dirty working tree before edits, not HEAD.
// No current normalizer, descriptor helper or scalar validator is an oracle.
import type { ResolvedNodeParameterV2, CanvasPositionV2, PresentationStreamResetV1, GuidanceCompletionProjectionV2 } from "../../../types-v2.ts";
type JsonRecord = Record<string, unknown>;

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

function expectPositiveInteger(value: unknown, path: string) {
  const result = expectInteger(value, path);
  if (result <= 0) fail(path, "expected positive integer");
  return result;
}

function nullablePositiveInteger(value: unknown, path: string) {
  if (value === null) return null;
  return expectPositiveInteger(value, path);
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

function expectArray(value: unknown, path: string) {
  if (!Array.isArray(value)) fail(path, "expected array");
  return value;
}

function normalizeCanvasPositionV2(value: unknown, path: string): CanvasPositionV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["x", "y"], path);
  return {
    x: expectFiniteNumber(record.x, `${path}.x`),
    y: expectFiniteNumber(record.y, `${path}.y`),
  };
}

function normalizePresentationStreamResetV1(
  value: unknown,
  path: string,
): PresentationStreamResetV1 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["reason", "authoritative_id", "resource_kind"], path);
  return {
    reason: expectLiteral(
      record.reason,
      new Set<PresentationStreamResetV1["reason"]>(["cursor_expired", "store_recovered"]),
      `${path}.reason`,
    ),
    authoritative_id: nullableStringWithDefault(record.authoritative_id, `${path}.authoritative_id`),
    resource_kind: expectLiteral(
      record.resource_kind,
      new Set<PresentationStreamResetV1["resource_kind"]>(["message", "prompt", "workflow"]),
      `${path}.resource_kind`,
    ),
  };
}

function normalizeResolvedNodeParameterV2(value: unknown, path: string): ResolvedNodeParameterV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["name", "value", "source_kind", "source_id", "source_revision"], path);
  return {
    name: expectNonEmptyString(record.name, `${path}.name`),
    value: record.value,
    source_kind: expectLiteral(record.source_kind, new Set<ResolvedNodeParameterV2["source_kind"]>([
      "explicit_user", "bound_text", "node_parameter", "storyboard_plan", "style_advice", "installation_default",
    ]), `${path}.source_kind`),
    source_id: expectNonEmptyString(record.source_id, `${path}.source_id`),
    source_revision: record.source_revision === undefined || record.source_revision === null
      ? null
      : expectPositiveInteger(record.source_revision, `${path}.source_revision`),
  };
}

function normalizeGuidanceCompletionProjectionV2(
  value: unknown,
  path: string,
): GuidanceCompletionProjectionV2 {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, [
    "authoring",
    "delivery",
    "plan_document_id",
    "plan_revision",
    "editing_preparation",
    "editing_node_id",
    "preparation_receipt_id",
    "manifest_revision",
    "export_status",
    "export_id",
    "final_completion_receipt_id",
    "final_asset_id",
    "matching_node_ids",
    "matching_asset_ids",
  ], path);
  return {
    authoring: expectLiteral(
      record.authoring ?? "not_ready",
      new Set<GuidanceCompletionProjectionV2["authoring"]>(["not_ready", "ready"]),
      `${path}.authoring`,
    ),
    delivery: expectLiteral(
      record.delivery ?? "not_ready",
      new Set<GuidanceCompletionProjectionV2["delivery"]>(["not_ready", "ready"]),
      `${path}.delivery`,
    ),
    plan_document_id: nullableStringWithDefault(record.plan_document_id, `${path}.plan_document_id`),
    plan_revision: record.plan_revision === undefined
      ? null
      : nullablePositiveInteger(record.plan_revision, `${path}.plan_revision`),
    editing_preparation: expectLiteral(
      record.editing_preparation ?? "not_ready",
      new Set<GuidanceCompletionProjectionV2["editing_preparation"]>(["not_ready", "prepared"]),
      `${path}.editing_preparation`,
    ),
    editing_node_id: nullableStringWithDefault(record.editing_node_id, `${path}.editing_node_id`),
    preparation_receipt_id: nullableStringWithDefault(
      record.preparation_receipt_id,
      `${path}.preparation_receipt_id`,
    ),
    manifest_revision: record.manifest_revision === undefined
      ? null
      : nullablePositiveInteger(record.manifest_revision, `${path}.manifest_revision`),
    export_status: expectLiteral(
      record.export_status ?? "not_started",
      new Set<GuidanceCompletionProjectionV2["export_status"]>([
        "not_started",
        "queued",
        "exporting",
        "completed",
        "failed",
        "cancelled",
      ]),
      `${path}.export_status`,
    ),
    export_id: nullableStringWithDefault(record.export_id, `${path}.export_id`),
    final_completion_receipt_id: nullableStringWithDefault(
      record.final_completion_receipt_id,
      `${path}.final_completion_receipt_id`,
    ),
    final_asset_id: nullableStringWithDefault(record.final_asset_id, `${path}.final_asset_id`),
    matching_node_ids: optionalStringArray(record.matching_node_ids, `${path}.matching_node_ids`, []),
    matching_asset_ids: optionalStringArray(record.matching_asset_ids, `${path}.matching_asset_ids`, []),
  };
}

function normalizeGuidedChoiceOptionV1(value: unknown, path: string) {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["option_id", "title", "summary", "difference_tags", "recommended", "reference_preview"], path);
  return { option_id: expectNonEmptyString(record.option_id, `${path}.option_id`), title: expectNonEmptyString(record.title, `${path}.title`), summary: expectNonEmptyString(record.summary, `${path}.summary`), difference_tags: optionalStringArray(record.difference_tags, `${path}.difference_tags`, []), recommended: record.recommended === undefined ? false : expectBoolean(record.recommended, `${path}.recommended`), reference_preview: expectArray(record.reference_preview ?? [], `${path}.reference_preview`).map((item, index) => normalizeGuidedReferencePreviewV1(item, `${path}.reference_preview[${index}]`)) };
}

function normalizeGuidedReferencePreviewV1(value: unknown, path: string) {
  const record = expectRecord(value, path);
  forbidUnknownFields(record, ["source_kind", "source_id", "display_name", "media_type"], path);
  return { source_kind: expectLiteral(record.source_kind, new Set(["node", "image_asset"] as const), `${path}.source_kind`), source_id: expectNonEmptyString(record.source_id, `${path}.source_id`), display_name: expectNonEmptyString(record.display_name, `${path}.display_name`), media_type: expectLiteral(record.media_type, new Set(["text", "image", "video", "audio"] as const), `${path}.media_type`) };
}
type Normalizer = (value: unknown, path: string) => unknown;
type Fixture = Record<string, unknown>;
const preview = { source_kind: 'node', source_id: 'n', display_name: 'reference', media_type: 'image' };
const cases: Array<{ name: string; baseline: Normalizer; fixture: Fixture }> = [
  { name: 'normalizeCanvasPositionV2', baseline: normalizeCanvasPositionV2, fixture: { x: -1.5, y: 0 } },
  { name: 'normalizePresentationStreamResetV1', baseline: normalizePresentationStreamResetV1, fixture: { reason: 'cursor_expired', authoritative_id: null, resource_kind: 'message' } },
  { name: 'normalizeResolvedNodeParameterV2', baseline: normalizeResolvedNodeParameterV2, fixture: { name: 'duration', value: { arbitrary: [null, 1] }, source_kind: 'explicit_user', source_id: 's', source_revision: 1 } },
  { name: 'normalizeGuidanceCompletionProjectionV2', baseline: normalizeGuidanceCompletionProjectionV2, fixture: { authoring: 'ready', delivery: 'ready', plan_document_id: 'p', plan_revision: 1, editing_preparation: 'prepared', editing_node_id: 'n', preparation_receipt_id: 'r', manifest_revision: 1, export_status: 'completed', export_id: 'e', final_completion_receipt_id: 'c', final_asset_id: 'a', matching_node_ids: ['n'], matching_asset_ids: ['a'] } },
  { name: 'normalizeGuidedChoiceOptionV1', baseline: normalizeGuidedChoiceOptionV1, fixture: { option_id: 'o', title: 'title', summary: 'summary', difference_tags: ['tag'], recommended: true, reference_preview: [preview] } },
  { name: 'normalizeGuidedReferencePreviewV1', baseline: normalizeGuidedReferencePreviewV1, fixture: preview },
];
// Private actual functions use the same test-local instrumentation as round four.
// None of this source, helper or current nested validator feeds the frozen oracle.
const source = readFileSync('src/features/agent-canvas/model/normalizers.ts', 'utf8');
const sourceAst = ts.createSourceFile('normalizers.ts', source, ts.ScriptTarget.Latest, true);
const instrumentedSource = sourceAst.statements.filter(node => !ts.isImportDeclaration(node)).map(node => node.getText(sourceAst).replace(/^export /, '')).join('\n');
const compiled = ts.transpile(instrumentedSource + '\nreturn {' + cases.map(entry => entry.name).join(',') + '};', { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None });
const instrumented = new Function('V2ContractValidationError', 'normalizeStrictRecord', compiled)(V2ContractValidationError, normalizeStrictRecord) as Record<string, Normalizer>;
function outcome(fn: Normalizer, value: unknown, path: string) {
  try {
    const output = fn(value, path);
    return { ok: true, output, keys: Object.keys(output as object), descriptors: Object.getOwnPropertyDescriptors(output) };
  } catch (error) {
    if (!(error instanceof V2ContractValidationError)) throw error;
    return { ok: false, errorClass: error.constructor.name, name: error.name, message: error.message, path: error.path, reason: error.reason };
  }
}
// Locks transport contracts, not stateful getter read-count equivalence.
const mutations: unknown[] = [undefined, null, false, true, '', ' ', 'bad', 0, -1, 0.5, NaN, Infinity, -Infinity, [], [null], ['bad'], {}, { unknown: true }];
describe('fifth strict-record batch preserves independently frozen contracts', () => {
  for (const entry of cases) {
    const fn = instrumented[entry.name];
    it(`${entry.name}: valid success, every field, defaults, ordered errors and output properties`, () => {
      for (const path of ['private', 'transport.custom[2]', '']) {
        const compare = (value: unknown) => expect(outcome(fn, value, path)).toStrictEqual(outcome(entry.baseline, value, path));
        expect(outcome(entry.baseline, entry.fixture, path).ok).toBe(true);
        compare(entry.fixture);
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
          expect(outcome(entry.baseline, unknown, path).path).toBe(`${path}.${key}`);
          expect(outcome(entry.baseline, unknown, path).reason).toBe('unknown field'); compare(unknown);
        }
        const multi = { ...entry.fixture, z_unknown: true, a_unknown: true, [keys[0]]: undefined };
        expect(outcome(entry.baseline, multi, path).path).toBe(`${path}.z_unknown`); compare(multi);
        const defaults = { ...entry.fixture };
        for (const key of keys) if (outcome(entry.baseline, { ...entry.fixture, [key]: undefined }, path).ok) delete defaults[key];
        expect(outcome(entry.baseline, defaults, path).ok).toBe(true); compare(defaults);
        // Both missing required fields must fail at the first declared validator.
        const required = keys.filter(key => !outcome(entry.baseline, { ...entry.fixture, [key]: undefined }, path).ok);
        if (required.length > 1) {
          const invalid = { ...entry.fixture, [required[0]]: undefined, [required[1]]: undefined };
          expect(outcome(entry.baseline, invalid, path).path).toBe(`${path}.${required[0]}`); compare(invalid);
        }
      }
    });
    it(`${entry.name}: nested scalar, array and record paths`, () => {
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
  it('valid alternatives and nullish defaults retain success, exact descriptors and ordered keys', () => {
    const alternatives: Record<string, Fixture[]> = {
      normalizeCanvasPositionV2: [{ x: 0, y: -0 }, { x: Number.MAX_VALUE, y: -Number.MAX_VALUE }],
      normalizePresentationStreamResetV1: [{ reason: 'store_recovered', resource_kind: 'workflow', authoritative_id: 'w' }, { reason: 'cursor_expired', resource_kind: 'prompt' }],
      normalizeResolvedNodeParameterV2: ['explicit_user', 'bound_text', 'node_parameter', 'storyboard_plan', 'style_advice', 'installation_default'].map(source_kind => ({ name: 'n', source_kind, source_id: 's' })),
      normalizeGuidanceCompletionProjectionV2: [{}, { authoring: null, delivery: null, editing_preparation: null, export_status: null }, ...['not_started', 'queued', 'exporting', 'completed', 'failed', 'cancelled'].map(export_status => ({ export_status }))],
      normalizeGuidedChoiceOptionV1: [{ option_id: 'o', title: 't', summary: 's' }, { option_id: 'o', title: 't', summary: 's', reference_preview: null }],
      normalizeGuidedReferencePreviewV1: ['text', 'image', 'video', 'audio'].map(media_type => ({ ...preview, source_kind: 'image_asset', media_type })),
    };
    for (const entry of cases) for (const fixture of alternatives[entry.name]) {
      expect(outcome(entry.baseline, fixture, 'alternatives').ok).toBe(true);
      expect(outcome(instrumented[entry.name], fixture, 'alternatives')).toStrictEqual(outcome(entry.baseline, fixture, 'alternatives'));
    }
    // Non-own unknown keys remain ignored; arbitrary value is deliberately not normalized.
    const fixture = Object.assign(Object.create({ inherited_unknown: true }) as Fixture, cases[2].fixture);
    expect(outcome(instrumented.normalizeResolvedNodeParameterV2, fixture, 'identity')).toStrictEqual(outcome(normalizeResolvedNodeParameterV2, fixture, 'identity'));
    const value = cases[2].fixture.value;
    expect((instrumented.normalizeResolvedNodeParameterV2(cases[2].fixture, 'identity') as Fixture).value).toBe(value);
  });
});

