import { describe, expect, it } from "vitest";
import {
  DIRECTOR_TAKES_CONTENT_KEY,
  MAX_DIRECTOR_TAKES,
  nextTakeLabel,
  parseDirectorTakes,
  serializeDirectorTakes,
  type DirectorTake,
} from "./directorTakes.ts";

function take(overrides: Partial<DirectorTake> = {}): DirectorTake {
  return {
    id: "take_1",
    label: "Take 1",
    scene_script: { shots: [] },
    operations: [],
    frame: 0,
    ...overrides,
  };
}

describe("parseDirectorTakes", () => {
  it("returns an empty list for absent or unusable input", () => {
    expect(parseDirectorTakes(undefined)).toEqual([]);
    expect(parseDirectorTakes("nope")).toEqual([]);
    expect(parseDirectorTakes({ take: "x" })).toEqual([]);
  });

  it("skips entries without a scene_script (restoring blank is worse)", () => {
    const raw = [
      take(),
      { id: "bad", label: "Broken", operations: [] },
    ];
    const parsed = parseDirectorTakes(raw);
    expect(parsed).toHaveLength(1);
    expect(parsed[0].id).toBe("take_1");
  });

  it("fills defaults for id, label, and non-finite frame", () => {
    const parsed = parseDirectorTakes([{ scene_script: { shots: [] }, frame: Number.NaN }]);
    expect(parsed[0].id).toBe("take_1");
    expect(parsed[0].label).toBe("Take 1");
    expect(parsed[0].frame).toBeNull();
  });

  it("keeps only object ops and drops array ops", () => {
    const parsed = parseDirectorTakes([
      take({
        id: "t",
        operations: [{ op: "add" }, ["list"], "scalar"] as unknown as DirectorTake["operations"],
      }),
    ]);
    expect(parsed[0].operations).toEqual([{ op: "add" }]);
  });
});

describe("serializeDirectorTakes", () => {
  it("caps at MAX_DIRECTOR_TAKES keeping the newest", () => {
    const many = Array.from({ length: MAX_DIRECTOR_TAKES + 2 }, (_, i) =>
      take({ id: `t${i}`, label: `Take ${i + 1}` }),
    );
    const serialized = serializeDirectorTakes(many);
    expect(serialized).toHaveLength(MAX_DIRECTOR_TAKES);
    expect(serialized[0].id).toBe("t2");
  });

  it("normalizes frame to null when absent", () => {
    const serialized = serializeDirectorTakes([take({ frame: undefined })]);
    expect(serialized[0].frame).toBeNull();
  });
});

describe("nextTakeLabel", () => {
  it("starts at Take 1 and skips used labels", () => {
    expect(nextTakeLabel([])).toBe("Take 1");
    expect(nextTakeLabel([take()])).toBe("Take 2");
    expect(
      nextTakeLabel([take(), take({ id: "t2", label: "Take 2" })]),
    ).toBe("Take 3");
  });
});

describe("content key", () => {
  it("is the stable structured_content key", () => {
    expect(DIRECTOR_TAKES_CONTENT_KEY).toBe("director_takes");
  });
});
