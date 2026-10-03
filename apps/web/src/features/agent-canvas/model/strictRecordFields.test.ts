import { describe, expect, expectTypeOf, it } from "vitest";
import { V2ContractValidationError } from "../../../api/v2ContractValidationError.ts";
import { normalizeStrictRecord, type StrictRecordFieldsFor } from "./strictRecordFields.ts";

describe("normalizeStrictRecord", () => {
  it("infers each keyed return type and checks descriptor contract types", () => {
    const result = normalizeStrictRecord({}, "record", {
      name: () => "name",
      count: () => 1,
      absent: () => undefined,
    } satisfies StrictRecordFieldsFor<{ name: string; count: number; absent?: string }>);
    expectTypeOf(result).toEqualTypeOf<{ name: string; count: number; absent: undefined }>();
    expect(Object.keys(result)).toEqual(["name", "count", "absent"]);
    expect(Object.getOwnPropertyDescriptor(result, "absent")).toEqual({ value: undefined, enumerable: true, configurable: true, writable: true });
  });

  it("rejects unknown own enumerable keys before invoking validators in Object.keys order", () => {
    let calls = 0;
    const fields = { name: () => { calls++; return "name"; } };
    for (const [input, key] of [
      [{ z: 1, a: 2 }, "z"],
      [{ a: 1, z: 2 }, "a"],
      [{ "2": 1, "1": 2 }, "1"],
      [{ constructor: 1 }, "constructor"],
      [{ toString: 1 }, "toString"],
      [JSON.parse('{"__proto__": 1}'), "__proto__"],
    ] as const) {
      expect(() => normalizeStrictRecord(input, "root[2]", fields)).toThrow(new V2ContractValidationError(`root[2].${key}`, "unknown field"));
    }
    expect(calls).toBe(0);
  });

  it("validates declared field order with full paths, including missing values", () => {
    const calls: unknown[] = [];
    const fields = {
      first: (value: unknown, path: string) => { calls.push([value, path]); return value; },
      second: (value: unknown, path: string) => { calls.push([value, path]); return value; },
    };
    expect(normalizeStrictRecord({ second: null }, "payload[1]", fields)).toStrictEqual({ first: undefined, second: null });
    expect(calls).toEqual([[undefined, "payload[1].first"], [null, "payload[1].second"]]);
    const error = new V2ContractValidationError("payload.first", "expected string");
    expect(() => normalizeStrictRecord({}, "payload", { first: () => { throw error; }, second: () => { throw new Error("must not run"); } })).toThrow(error);
  });

  it("accepts inherited known values while ignoring hidden and symbol keys", () => {
    const input = Object.create({ name: "inherited", unknown: true });
    Object.defineProperty(input, "hidden", { value: true });
    input[Symbol("unknown")] = true;
    expect(normalizeStrictRecord(input, "root", { name: (value) => value })).toStrictEqual({ name: "inherited" });
  });

  it("writes reserved output keys as own enumerable data properties", () => {
    const result = normalizeStrictRecord({}, "root", { ["__proto__"]: () => "safe", constructor: () => undefined });
    expect(Object.getPrototypeOf(result)).toBe(Object.prototype);
    expect(Object.keys(result)).toEqual(["__proto__", "constructor"]);
    expect(Object.getOwnPropertyDescriptor(result, "__proto__")?.value).toBe("safe");
  });

  it("uses the existing contract error class for non-record inputs", () => {
    for (const value of [null, undefined, [], 1, "string", true]) {
      try { normalizeStrictRecord(value, "nested.record", {}); throw new Error("expected failure"); }
      catch (error) {
        expect(error).toBeInstanceOf(V2ContractValidationError);
        expect(error).toMatchObject({ name: "V2ContractValidationError", path: "nested.record", reason: "expected object", message: "Invalid nested.record: expected object" });
      }
    }
  });
});
