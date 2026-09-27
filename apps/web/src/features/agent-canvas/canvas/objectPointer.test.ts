/**
 * objectPointer tests (V0.2 §8.2: 空间指向会减少语言歧义).
 *
 * The whole point of pointing is that the language layer can NAME what was
 * pointed at, so these lock the two properties the label exists for: it names
 * the object in the author's language, and it is the SAME phrase that gets
 * written into the prompt (one phrase, never two renderings that drift).
 */

import { describe, expect, it } from "vitest";

import { describeObjectPointer, objectPointerToken } from "./objectPointer.ts";
import type { SceneObjectRef } from "./sceneScriptEditModel.ts";

const character: SceneObjectRef = { kind: "character", id: "char_a" };

describe("describeObjectPointer", () => {
  it("names the object in the author's language", () => {
    expect(describeObjectPointer(character)).toBe("角色 char_a");
    expect(describeObjectPointer({ kind: "prop", id: "crate1" })).toBe("道具 crate1");
    expect(describeObjectPointer({ kind: "environment", id: "wall1" })).toBe("环境 wall1");
    expect(describeObjectPointer({ kind: "camera", id: "cam1" })).toBe("相机 cam1");
  });

  it("says nothing when nothing is pointed at (no phantom object)", () => {
    expect(describeObjectPointer(null)).toBeNull();
    expect(describeObjectPointer(undefined)).toBeNull();
    expect(describeObjectPointer({ kind: "character", id: "" })).toBeNull();
  });
});

describe("objectPointerToken", () => {
  it("wraps the SAME phrase the chip shows", () => {
    // One phrase, not two renderings: the label and the token must agree or
    // the prompt would say one thing while the chip says another.
    expect(objectPointerToken(character)).toBe(`【指向：${describeObjectPointer(character)}】`);
  });

  it("is absent when nothing is pointed at", () => {
    expect(objectPointerToken(null)).toBeNull();
  });
});
