import { V2ContractValidationError } from "../../../api/v2ContractValidationError.ts";

type FieldValidator = (value: unknown, path: string) => unknown;
export type StrictRecordFields = Record<string, FieldValidator>;
export type StrictRecordFieldsFor<Result> = {
  [Key in keyof Result]-?: (value: unknown, path: string) => Result[Key];
};
export type StrictRecordResult<Fields extends StrictRecordFields> = {
  [Key in keyof Fields]: ReturnType<Fields[Key]>;
};

/** Descriptors use non-integer field names in declared validation/output order. */
export function normalizeStrictRecord<Fields extends StrictRecordFields>(
  value: unknown,
  path: string,
  fields: Fields,
): StrictRecordResult<Fields> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new V2ContractValidationError(path, "expected object");
  }
  for (const key of Object.keys(value)) {
    if (!Object.hasOwn(fields, key)) {
      throw new V2ContractValidationError(`${path}.${key}`, "unknown field");
    }
  }
  // fromEntries creates own enumerable data properties, including undefined and
  // __proto__. Each result is exactly the return type of its keyed validator.
  return Object.fromEntries(Object.keys(fields).map((key) => [
    key,
    fields[key](Reflect.get(value, key), `${path}.${key}`),
  ])) as StrictRecordResult<Fields>;
}
