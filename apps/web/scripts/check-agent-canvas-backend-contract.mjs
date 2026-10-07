import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

import manifest from "./agent-canvas-contract-manifest.json" with { type: "json" };

function sorted(values) {
  return [...values].sort((left, right) => left.localeCompare(right));
}

function difference(left, right) {
  const rightValues = new Set(right);
  return sorted(left.filter((value) => !rightValues.has(value)));
}

function resolveReference(root, reference) {
  if (typeof reference !== "string" || !reference.startsWith("#/")) return null;
  return reference.slice(2).split("/").reduce((value, segment) => {
    if (!value || typeof value !== "object") return null;
    return value[segment.replaceAll("~1", "/").replaceAll("~0", "~")];
  }, root);
}

function enumValues(schema, root = schema, seen = new Set()) {
  if (!schema || typeof schema !== "object") return [];
  if (typeof schema.$ref === "string") {
    if (seen.has(schema.$ref)) return [];
    const resolved = resolveReference(root, schema.$ref);
    if (!resolved) return [];
    const nextSeen = new Set(seen);
    nextSeen.add(schema.$ref);
    return enumValues(resolved, root, nextSeen);
  }
  if (typeof schema.const === "string") return [schema.const];
  if (Array.isArray(schema.enum)) return schema.enum.filter((value) => typeof value === "string");
  if (Array.isArray(schema.anyOf)) return schema.anyOf.flatMap((member) => enumValues(member, root, seen));
  if (Array.isArray(schema.oneOf)) return schema.oneOf.flatMap((member) => enumValues(member, root, seen));
  if (Array.isArray(schema.allOf)) return schema.allOf.flatMap((member) => enumValues(member, root, seen));
  return [];
}

/**
 * Schemas the backend is expected to expose by name.
 *
 * The check below only ever compares what this manifest lists, so a schema missing
 * here is invisible to it -- which is how adding `SceneProp.keyframes` shipped with a
 * green gate. Every schema in this list is now also required to be present, so
 * deleting one cannot silently shrink the gate's own coverage.
 */
const REQUIRED_SCHEMA_NAMES = Object.keys(manifest.schemas);

export function agentCanvasContractMismatches(openApi, contractManifest = manifest) {
  const schemas = openApi?.components?.schemas ?? openApi?.$defs;
  if (!schemas || typeof schemas !== "object") {
    return ["OpenAPI components.schemas and JSON Schema $defs are unavailable"];
  }

  const mismatches = [];
  Object.entries(contractManifest.schemas).forEach(([schemaName, expected]) => {
    const actual = schemas[schemaName];
    if (!actual || typeof actual !== "object") {
      mismatches.push(`${schemaName} is missing from backend OpenAPI`);
      return;
    }

    // A bare `Dict[str, Any]` surfaces as an object with no `properties` at all,
    // and `Object.keys({})` is empty, so the property diff below would compare
    // nothing and pass. That is precisely how SceneScript went unchecked: 23
    // endpoints declare `scene_script: dict[str, Any]`, so OpenAPI knows no
    // fields exist to check and adding a field could never turn this gate red.
    // Fail loudly instead, so a typed contract is required to be listed here.
    if (!actual.properties || typeof actual.properties !== "object") {
      mismatches.push(
        `${schemaName} exposes no properties -- the backend is publishing it as an ` +
          "untyped dict/object, so this gate cannot verify it. Type it in the " +
          "backend (e.g. scene_script: SceneScriptRoot) or remove it from the manifest.",
      );
    }

    const actualProperties = Object.keys(actual.properties ?? {});
    const backendOnly = difference(actualProperties, expected.properties);
    const frontendOnly = difference(expected.properties, actualProperties);
    if (backendOnly.length || frontendOnly.length) {
      mismatches.push(
        `${schemaName} properties differ: backend-only [${backendOnly.join(", ")}]; frontend-only [${frontendOnly.join(", ")}]`,
      );
    }

    Object.entries(expected.enums ?? {}).forEach(([property, expectedValues]) => {
      const actualValues = enumValues(actual.properties?.[property], openApi);
      const backendEnumOnly = difference(actualValues, expectedValues);
      const frontendEnumOnly = difference(expectedValues, actualValues);
      if (backendEnumOnly.length || frontendEnumOnly.length) {
        mismatches.push(
          `${schemaName}.${property} enum differs: backend-only [${backendEnumOnly.join(", ")}]; frontend-only [${frontendEnumOnly.join(", ")}]`,
        );
      }
    });
  });
  return mismatches;
}

/**
 * Backend schemas the manifest does not track at all.
 *
 * Reported separately from the mismatch list because these are not contract
 * conflicts -- they are holes. A schema the frontend depends on can be added,
 * changed, or removed with this gate green, since the gate only ever iterates the
 * manifest. Surfacing untracked schemas is what turns "the gate passed" into a
 * statement about the gate's own coverage.
 */
export function untrackedBackendSchemas(openApi, contractManifest = manifest) {
  const schemas = openApi?.components?.schemas ?? openApi?.$defs;
  if (!schemas || typeof schemas !== "object") return [];
  const tracked = new Set(Object.keys(contractManifest.schemas));
  return Object.keys(schemas)
    .filter((name) => !tracked.has(name))
    .filter((name) => name.startsWith("Scene"))
    .sort((left, right) => left.localeCompare(right));
}

async function loadOpenApi(source) {
  if (/^https?:\/\//u.test(source)) {
    const response = await fetch(source);
    if (!response.ok) throw new Error(`OpenAPI request failed with HTTP ${response.status}`);
    return response.json();
  }
  return JSON.parse(await readFile(source, "utf8"));
}

async function main() {
  const source = process.argv[2] ?? process.env.ADWORKFLOW_OPENAPI;
  if (!source) {
    throw new Error(
      "Provide an OpenAPI JSON file or URL: npm run check:agent-canvas-contract -- <source>",
    );
  }
  const openApi = await loadOpenApi(source);
  const problems = [
    ...agentCanvasContractMismatches(openApi),
    // An empty result is the interesting case: the gate can only compare schemas
    // the manifest lists, so silence here means the gate was green without having
    // checked SceneScript at all. Say so rather than reporting a clean pass.
    ...(() => {
      const untracked = untrackedBackendSchemas(openApi);
      return untracked.length
        ? [
            `Untracked Scene* schemas in the backend that this gate does not compare: ` +
              `${untracked.join(", ")}. Add them to agent-canvas-contract-manifest.json ` +
              `with their property lists, or this gate is blind to them.`,
          ]
        : [];
    })(),
  ];
  if (problems.length) throw new Error(problems.join("\n"));
  process.stdout.write(
    `Agent Canvas frontend contract matches the tracked backend schemas ` +
      `(${REQUIRED_SCHEMA_NAMES.length} tracked).\n`,
  );
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
