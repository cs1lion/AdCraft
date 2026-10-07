import { describe, expect, it } from "vitest";

import manifest from "./agent-canvas-contract-manifest.json" with { type: "json" };
import {
  agentCanvasContractMismatches,
  untrackedBackendSchemas,
} from "./check-agent-canvas-backend-contract.mjs";

function openApi() {
  const schemas = Object.fromEntries(Object.entries(manifest.schemas).map(([name, contract]) => [
    name,
    {
      properties: Object.fromEntries(contract.properties.map((property) => [
        property,
        // `?? {}` because a schema added to the manifest with properties only --
        // the three Scene* ones -- has no `enums` key at all, and every pre-existing
        // entry happened to have one.
        contract.enums?.[property]
          ? { anyOf: [{ type: "string", enum: [...contract.enums[property]] }, { type: "null" }] }
          : { type: "string" },
      ])),
    },
  ]));
  return { components: { schemas } };
}

describe("Agent Canvas backend contract parity", () => {
  it("tracks prompt preparation and accepted-turn schemas", () => {
    expect(manifest.schemas.NodePromptPreparationV1).toEqual(expect.objectContaining({
      properties: expect.arrayContaining(["presentation_stream_id"]),
      enums: expect.objectContaining({
        status: expect.arrayContaining(["not_applicable"]),
      }),
    }));
    expect(manifest.schemas.ChatTurnAcceptedV2).toEqual(expect.objectContaining({
      properties: expect.arrayContaining(["presentation_stream_id"]),
    }));
    expect(manifest.schemas.ChatTurnV2.enums.status).toEqual(expect.arrayContaining(["superseded"]));
  });

  it("accepts the tracked canonical response fields and enum values", () => {
    expect(agentCanvasContractMismatches(openApi(), manifest)).toEqual([]);
  });

  it("reports backend fields and enum values that the strict frontend contract has not consumed", () => {
    const backend = openApi();
    backend.components.schemas.ChatTurnV2.properties.new_backend_field = { type: "string" };
    backend.components.schemas.ChatTurnV2.properties.turn_kind.anyOf[0].enum.push("new_turn_kind");

    expect(agentCanvasContractMismatches(backend, manifest)).toEqual([
      "ChatTurnV2 properties differ: backend-only [new_backend_field]; frontend-only []",
      "ChatTurnV2.turn_kind enum differs: backend-only [new_turn_kind]; frontend-only []",
    ]);
  });

  it("resolves referenced backend enums before comparing strict values", () => {
    const backend = openApi();
    backend.components.schemas.ChatTurnV2.properties.status = {
      anyOf: [
        { $ref: "#/components/schemas/ChatTurnStatusV2" },
        { type: "null" },
      ],
    };
    backend.components.schemas.ChatTurnStatusV2 = {
      type: "string",
      enum: ["queued", "running", "completed", "failed", "superseded"],
    };

    expect(agentCanvasContractMismatches(backend, manifest)).toEqual([]);
  });

  it("treats a backend const as a single-value enum", () => {
    const backend = openApi();
    backend.components.schemas.ChatTurnAcceptedV2.properties.status = {
      type: "string",
      const: "queued",
    };

    expect(agentCanvasContractMismatches(backend, manifest)).toEqual([]);
  });

  it("tracks every backend parameter provenance origin", () => {
    const expected = {
      properties: [
        "origin",
        "source_node_id",
        "binding_id",
        "source_revision",
        "requested_value",
        "effective_value",
        "normalization_code",
      ],
      enums: {
        origin: [
          "manual",
          "node_prompt",
          "binding",
          "user_explicit",
          "structured_content",
          "guidance_default",
          "role_default",
          "model_default",
          "provider_clamp",
        ],
      },
    };
    const backendSchema = {
      components: {
        schemas: {
          CanvasParameterProvenanceV2: {
            properties: Object.fromEntries(expected.properties.map((property) => [
              property,
              property === "origin"
                ? { type: "string", enum: [...expected.enums.origin] }
                : { type: "string" },
            ])),
          },
        },
      },
    };

    expect(manifest.schemas.CanvasParameterProvenanceV2).toEqual(expected);
    expect(agentCanvasContractMismatches(backendSchema, {
      schemas: { CanvasParameterProvenanceV2: expected },
    })).toEqual([]);
  });
});

// The gate iterates the manifest, so a schema it does not list is invisible to it.
// SceneScript shipped with a green gate for exactly this reason: `SceneProp` and
// friends were never tracked, so adding `keyframes` could not turn it red. These
// tests pin the two ways that hole reopens -- an untyped backend schema, and a
// schema nobody added to the manifest.
describe("Agent Canvas contract gate coverage", () => {
  it("fails on a schema the backend publishes with no properties", () => {
    // A bare `dict[str, Any]` is OpenAPI's `{type: object}` with no `properties`,
    // so the property diff would compare two empty lists and pass. SceneScript is
    // typed this way across 23 scene_3d endpoints.
    const backend = {
      components: { schemas: { SceneScriptRoot: { type: "object" } } },
    };

    const [mismatch] = agentCanvasContractMismatches(backend, {
      schemas: { SceneScriptRoot: { properties: ["scene", "props"] } },
    });
    // Also reports the empty-vs-expected property diff, which is the false green in
    // its most literal form: the gate noticed nothing was comparable and still
    // produced two complaints instead of a clean pass.
    expect(mismatch).toContain("SceneScriptRoot exposes no properties");
    expect(mismatch).toContain("Type it in the backend");
  });

  it("reports Scene* schemas the manifest does not track", () => {
    const backend = {
      components: {
        schemas: {
          ChatTurnV2: { properties: {} },
          SceneOperationsRequest: { properties: { scene_script: {} } },
          SomethingUnrelated: { properties: {} },
        },
      },
    };

    // Only Scene* is reported: the backend has 533 schemas and most are unrelated
    // to the canvas, so flagging all of them would be noise nobody acts on.
    expect(untrackedBackendSchemas(backend, { schemas: { ChatTurnV2: { properties: [] } } }))
      .toEqual(["SceneOperationsRequest"]);
  });

  it("tracks the Scene* schemas the canvas endpoints exchange", () => {
    // Named here because the gap doc requires the manifest to cover the SceneScript
    // boundary, and this is what makes "covered" checkable rather than aspirational.
    for (const schemaName of ["SceneOperationsRequest", "SceneOperationsResponse"]) {
      expect(manifest.schemas[schemaName]).toBeDefined();
      expect(manifest.schemas[schemaName].properties).toContain("scene_script");
    }
  });
});
