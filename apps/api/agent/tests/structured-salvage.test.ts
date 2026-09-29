/**
 * Structured-output salvage — the two live breakages from 2026-09-29.
 *
 * The chat intent contract (additionalProperties: false) rejected a model
 * answer that echoed the prompt's context fields back, and scene-script
 * generation died on prose-wrapped / trailing-comma JSON.  Both are now
 * salvaged locally, before any provider-billed repair call.
 */

import { describe, expect, it } from "vitest";

import { salvageExtraFields, salvageJsonObject } from "../src/structured-salvage.js";

describe("salvageExtraFields", () => {
  it("prunes context fields the model echoed back (the live chat failure)", () => {
    const answer = {
      intent: "greeting",
      reply: "你好！",
      // echoed prompt context, forbidden by additionalProperties: false
      session_exists: true,
      mentioned_node_ids: ["node_1"],
      mentioned_image_asset_ids: [],
    };
    const salvaged = salvageExtraFields(answer, [
      { path: "session_exists", code: "extra_forbidden" },
      { path: "mentioned_node_ids", code: "extra_forbidden" },
      { path: "mentioned_image_asset_ids", code: "extra_forbidden" },
    ]);
    expect(salvaged).toEqual({ intent: "greeting", reply: "你好！" });
  });

  it("prunes nested extras and tolerates $-prefixed paths", () => {
    const salvaged = salvageExtraFields(
      { keep: 1, nested: { keep: 2, drop: 3 } },
      [
        { path: "$.nested.drop", code: "extra_forbidden" },
        { path: "$.absent", code: "extra_forbidden" },
      ],
    );
    expect(salvaged).toEqual({ keep: 1, nested: { keep: 2 } });
  });

  it("returns undefined when nothing is prunable", () => {
    expect(salvageExtraFields({ a: 1 }, [{ path: "a", code: "string_type" }])).toBeUndefined();
    expect(salvageExtraFields({ a: 1 }, [])).toBeUndefined();
    expect(
      salvageExtraFields({ a: 1 }, [{ path: "ghost", code: "extra_forbidden" }]),
    ).toBeUndefined();
  });

  it("does not mutate the input", () => {
    const input = { keep: 1, drop: 2 };
    salvageExtraFields(input, [{ path: "drop", code: "extra_forbidden" }]);
    expect(input).toEqual({ keep: 1, drop: 2 });
  });
});

describe("salvageJsonObject", () => {
  it("parses plain JSON unchanged", () => {
    expect(salvageJsonObject('{"a": 1}')).toEqual({ a: 1 });
  });

  it("extracts fenced JSON from prose", () => {
    expect(salvageJsonObject('Sure!\n```json\n{"a": 1}\n```\nHope that helps.')).toEqual({ a: 1 });
  });

  it("extracts the outermost object when prose wraps it", () => {
    expect(salvageJsonObject('Here is the answer: {"a": 1} — done')).toEqual({ a: 1 });
  });

  it("repairs trailing commas (the live scene-script failure)", () => {
    expect(salvageJsonObject('{"a": 1, "b": [1, 2, ], }')).toEqual({ a: 1, b: [1, 2] });
  });

  it("prefers the first fenced block when several appear", () => {
    expect(salvageJsonObject('```json\n{"first": true}\n```\nand\n```json\n{"second": true}\n```')).toEqual({
      first: true,
    });
  });

  it("returns undefined for garbage", () => {
    expect(salvageJsonObject("no json here")).toBeUndefined();
    expect(salvageJsonObject("")).toBeUndefined();
    expect(salvageJsonObject(undefined)).toBeUndefined();
    expect(salvageJsonObject("[1, 2]")).toBeUndefined(); // arrays are not the contract object
  });
});
