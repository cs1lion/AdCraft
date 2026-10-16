import { describe, expect, it } from "vitest";

import {
  normalizeCanvasVariationDraftResponseV2,
  normalizeCanvasVariationDraftV2,
  normalizeCanvasVariationMaterializeResponseV2,
  normalizeEditingExportAcceptanceCheckV2,
  normalizeEditingExportAcceptanceV2,
} from "./normalizers.ts";

// These five normalizers back the variation-draft and export-acceptance halves of
// the contract. What they lock down: a draft is never partially defaulted (a
// missing required field is an error, not a silently empty string), an unknown
// field is rejected rather than dropped, and nullable fields are null rather
// than "" so the UI can tell "absent" from "present but empty".

const draft = {
  source_node_id: "node_1",
  source_node_revision: 3,
  title: "Draft",
  generation_prompt: "make it warmer",
  variation_revision: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("normalizeCanvasVariationDraftV2", () => {
  it("fills the documented defaults for absent optional fields", () => {
    const result = normalizeCanvasVariationDraftV2(draft);
    expect(result.model_id).toBeNull();
    expect(result.model_ref).toBeNull();
    expect(result.model_selection_mode).toBe("default");
    expect(result.parameters).toEqual({});
  });

  it("keeps supplied values", () => {
    const result = normalizeCanvasVariationDraftV2({
      ...draft,
      model_id: "doubao-seed-2",
      model_selection_mode: "explicit",
      model_ref: "provider/doubao",
      parameters: { temperature: 0.4 },
    });
    expect(result.model_id).toBe("doubao-seed-2");
    expect(result.model_selection_mode).toBe("explicit");
    expect(result.parameters).toEqual({ temperature: 0.4 });
  });

  it("rejects an unknown field instead of dropping it", () => {
    expect(() => normalizeCanvasVariationDraftV2({ ...draft, sneaky: 1 })).toThrow(/sneaky/i);
  });

  it("requires the fields the backend always sends", () => {
    const { title: _title, ...withoutTitle } = draft;
    expect(() => normalizeCanvasVariationDraftV2(withoutTitle)).toThrow(/title/i);
  });

  it("rejects a model_selection_mode outside the enum", () => {
    expect(() =>
      normalizeCanvasVariationDraftV2({ ...draft, model_selection_mode: "whatever" }),
    ).toThrow(/model_selection_mode/i);
  });

  it("rejects a non-positive revision", () => {
    expect(() => normalizeCanvasVariationDraftV2({ ...draft, variation_revision: 0 })).toThrow(
      /variation_revision/i,
    );
  });
});

describe("normalizeCanvasVariationDraftResponseV2", () => {
  it("nests the draft", () => {
    const result = normalizeCanvasVariationDraftResponseV2({
      workflow_id: "wf_1",
      workflow_revision: 7,
      node_id: "node_1",
      variation_draft: draft,
    });
    expect(result.workflow_revision).toBe(7);
    expect(result.variation_draft.source_node_id).toBe("node_1");
  });

  it("propagates a nested failure with the field path", () => {
    expect(() =>
      normalizeCanvasVariationDraftResponseV2({
        workflow_id: "wf_1",
        workflow_revision: 7,
        node_id: "node_1",
        variation_draft: { ...draft, title: "" },
      }),
    ).toThrow(/variation_draft\.title/i);
  });
});

describe("normalizeCanvasVariationMaterializeResponseV2", () => {
  const siblingNode = {
    node_id: "node_2",
    workflow_id: "wf_1",
    node_type: "image",
    creative_role: "character",
    role_contract_version: "ad-media-role-v1",
    title: "Variation",
    status: "draft",
    execution_mode: "generative",
    summary_prompt: "A variation.",
    generation_prompt: null,
    structured_content: {},
    model_id: null,
    parameters: {},
    parameter_provenance: {},
    prompt_context_snapshot_id: null,
    output_asset_id: "asset-output-1",
    output_asset_version_id: "asset-version-output-1",
    latest_attempt: null,
    position: { x: 480, y: 220 },
    revision: 5,
    error: null,
    created_at: "2026-07-28T10:06:00Z",
    updated_at: "2026-07-28T10:07:00Z",
  };
  const base = {
    workflow_id: "wf_1",
    workflow_revision: 7,
    source_node_id: "node_1",
    sibling_node: siblingNode,
    placement_hint: { intent: "after_anchor", anchor_node_id: "node_1" },
  };

  it("treats run and run_error as nullable rather than empty", () => {
    const result = normalizeCanvasVariationMaterializeResponseV2(base);
    expect(result.run).toBeNull();
    expect(result.run_error).toBeNull();
    expect(result.copied_binding_ids).toEqual([]);
    expect(result.placement_hints).toEqual([]);
  });

  it("defaults placement_hints to an empty array when absent", () => {
    const result = normalizeCanvasVariationMaterializeResponseV2(base);
    expect(Array.isArray(result.placement_hints)).toBe(true);
  });

  it("rejects an unknown field", () => {
    expect(() => normalizeCanvasVariationMaterializeResponseV2({ ...base, extra: true })).toThrow(
      /extra/i,
    );
  });
});

describe("normalizeEditingExportAcceptanceCheckV2", () => {
  it("defaults an absent detail to an empty string", () => {
    const result = normalizeEditingExportAcceptanceCheckV2({ check: "audio_present", status: "pass" });
    expect(result.detail).toBe("");
  });

  it("rejects a status outside the four documented values", () => {
    expect(() =>
      normalizeEditingExportAcceptanceCheckV2({ check: "audio_present", status: "maybe" }),
    ).toThrow(/status/i);
  });
});

describe("normalizeEditingExportAcceptanceV2", () => {
  it("normalizes each check with its index in the path", () => {
    const result = normalizeEditingExportAcceptanceV2({
      checks: [
        { check: "audio_present", status: "pass" },
        { check: "duration", status: "warn", detail: "short" },
      ],
    });
    expect(result.checks).toHaveLength(2);
    expect(result.checks[1].detail).toBe("short");
  });

  it("reports the failing check by index", () => {
    expect(() =>
      normalizeEditingExportAcceptanceV2({
        checks: [
          { check: "audio_present", status: "pass" },
          { check: "duration", status: "nope" },
        ],
      }),
    ).toThrow(/checks\[1\]/i);
  });

  it("treats an absent ran_at as null", () => {
    const result = normalizeEditingExportAcceptanceV2({ checks: [] });
    expect(result.ran_at).toBeNull();
  });
});

describe("mutation checks", () => {
  // Removing the forbidUnknownFields call must turn the unknown-field tests red.
  it("locks the unknown-field rejection on the draft", () => {
    expect(() => normalizeCanvasVariationDraftV2({ ...draft, sneaky: 1 })).toThrow(/sneaky/i);
  });

  // Replacing `record.detail === undefined ? "" : ...` with a bare expectString
  // must turn the default-detail test red.
  it("locks the detail default", () => {
    const result = normalizeEditingExportAcceptanceCheckV2({ check: "audio_present", status: "pass" });
    expect(result.detail).toBe("");
  });
});
