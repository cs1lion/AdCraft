/**
 * Unit tests for the frontend prop / environment type fallback table.
 *
 * Locks the mirror contract with the backend's
 * ``app/services/scene3d/prop_type_fallback.py``: an unknown type degrades
 * to the nearest known primitive, and the table's values must be valid
 * schema enums.
 */

import { describe, expect, it } from "vitest";

import {
  ENVIRONMENT_TYPES,
  PROP_TYPES,
} from "../../../types/scene-script.generated";
import {
  buildFallbackReport,
  resolveEnvironmentFallback,
  resolvePropFallback,
} from "./propTypeFallback.ts";

describe("resolvePropFallback", () => {
  it("resolves 'locker' to 'box'", () => {
    expect(resolvePropFallback("locker")).toBe("box");
  });

  it("resolves 'vending_machine' to 'box'", () => {
    expect(resolvePropFallback("vending_machine")).toBe("box");
  });

  it("resolves 'coffee_table' to 'rect_table'", () => {
    expect(resolvePropFallback("coffee_table")).toBe("rect_table");
  });

  it("resolves 'torch' to 'lantern'", () => {
    expect(resolvePropFallback("torch")).toBe("lantern");
  });

  it("resolves 'sword' to 'weapon'", () => {
    expect(resolvePropFallback("sword")).toBe("weapon");
  });

  it("resolves 'notebook' to 'book'", () => {
    expect(resolvePropFallback("notebook")).toBe("book");
  });

  it("resolves 'bottle' to 'vase'", () => {
    expect(resolvePropFallback("bottle")).toBe("vase");
  });

  it("returns undefined for a known type", () => {
    expect(resolvePropFallback("box")).toBeUndefined();
    expect(resolvePropFallback("chair")).toBeUndefined();
  });

  it("returns undefined for a completely unknown type", () => {
    expect(resolvePropFallback("quantum_flux_capacitor")).toBeUndefined();
    expect(resolvePropFallback("")).toBeUndefined();
  });

  it("is case-insensitive", () => {
    expect(resolvePropFallback("Locker")).toBe("box");
    expect(resolvePropFallback("LOCKER")).toBe("box");
  });

  it("normalises hyphens to underscores", () => {
    expect(resolvePropFallback("vending-machine")).toBe("box");
  });

  it("resolves the spaced spelling the module docstring uses", () => {
    // The table is keyed vending_machine; the LLM writes "Vending Machine".
    expect(resolvePropFallback("vending machine")).toBe("box");
    expect(resolvePropFallback("Vending  Machine")).toBe("box");
    expect(resolvePropFallback("  vending machine  ")).toBe("box");
    expect(resolvePropFallback("vending/machine")).toBe("box");
  });

  it("does not merge distinct words by folding", () => {
    expect(resolvePropFallback("post")).toBeUndefined();
    expect(resolvePropFallback("pillar")).toBeUndefined();
    expect(resolveEnvironmentFallback("post")).toBe("pillar");
  });
});

describe("resolveEnvironmentFallback", () => {
  it("resolves 'column' to 'pillar'", () => {
    expect(resolveEnvironmentFallback("column")).toBe("pillar");
  });

  it("resolves 'canopy' to 'flat_roof'", () => {
    expect(resolveEnvironmentFallback("canopy")).toBe("flat_roof");
  });

  it("resolves 'gate' to 'door'", () => {
    expect(resolveEnvironmentFallback("gate")).toBe("door");
  });

  it("resolves 'ramp' to 'stairs'", () => {
    expect(resolveEnvironmentFallback("ramp")).toBe("stairs");
  });

  it("resolves 'hedge' to 'fence'", () => {
    expect(resolveEnvironmentFallback("hedge")).toBe("fence");
  });

  it("resolves 'terrain' to 'ground'", () => {
    expect(resolveEnvironmentFallback("terrain")).toBe("ground");
  });

  it("returns undefined for a known type", () => {
    expect(resolveEnvironmentFallback("wall")).toBeUndefined();
    expect(resolveEnvironmentFallback("tree")).toBeUndefined();
  });

  it("resolves the spaced spelling the module docstring uses", () => {
    expect(resolveEnvironmentFallback("guard rail")).toBe("fence");
    expect(resolveEnvironmentFallback("Guard-Rail")).toBe("fence");
    expect(resolveEnvironmentFallback("glass window")).toBe("window");
  });
});

describe("table completeness", () => {
  it("every fallback target is a valid PropTypeName", () => {
    // Verify via buildFallbackReport: every resolvedTo is a valid schema enum.
    const propAliases = [
      "locker",
      "vending_machine",
      "coffee_table",
      "torch",
      "sword",
      "notebook",
      "bottle",
    ];
    for (const alias of propAliases) {
      const report = buildFallbackReport("add_prop", alias);
      if (report.resolvedTo !== null) {
        expect(PROP_TYPES).toContain(report.resolvedTo as string);
      }
    }
    const envAliases = [
      "column",
      "canopy",
      "gate",
      "ramp",
      "hedge",
      "terrain",
    ];
    for (const alias of envAliases) {
      const report = buildFallbackReport("add_environment", alias);
      if (report.resolvedTo !== null) {
        expect(ENVIRONMENT_TYPES).toContain(report.resolvedTo as string);
      }
    }
  });
});

describe("buildFallbackReport", () => {
  it("reports a degradation for a known alias", () => {
    const report = buildFallbackReport("add_prop", "locker");
    expect(report.resolvedTo).toBe("box");
    expect(report.message).toContain("locker");
    expect(report.message).toContain("box");
  });

  it("reports an unresolvable type with resolvedTo = null", () => {
    const report = buildFallbackReport("add_prop", "quantum_flux_capacitor");
    expect(report.resolvedTo).toBeNull();
    expect(report.message).toContain("no known");
  });

  it("reports an environment degradation", () => {
    const report = buildFallbackReport("add_environment", "column");
    expect(report.resolvedTo).toBe("pillar");
    expect(report.message).toContain("pillar");
  });
});
