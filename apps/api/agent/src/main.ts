import { readFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { createAgentRuntimeServer } from "./server.js";
import { PiModelAdapter } from "./pi-model-adapter.js";
import { PythonInternalClient } from "./python-internal-client.js";
import { SkillBundleError } from "./skills.js";
import { startVerifiedServer } from "./startup.js";

// Load apps/api/.env (single source of truth for keys + runtime config)
// without overriding variables the operator already exported.  Parsed by
// hand so the runtime does not need dotenv (or any new dependency) just
// to pick up the shared project configuration.
function loadSharedEnvFile(): void {
  const here = dirname(fileURLToPath(import.meta.url));
  const candidatePaths = [
    // dev: node_modules/tsx entry point resolves to src/main.ts alongside
    // package-local .env if the operator dropped one in apps/api/agent/.
    resolve(here, ".env"),
    // repo layout: apps/api/agent/src/main.ts -> apps/api/.env
    resolve(here, "..", "..", ".env"),
    resolve(process.cwd(), ".env"),
  ];
  for (const path of candidatePaths) {
    if (!existsSync(path)) continue;
    let content: string;
    try {
      content = readFileSync(path, "utf-8");
    } catch {
      continue;
    }
    for (const rawLine of content.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#")) continue;
      const match = /^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/.exec(line);
      if (!match) continue;
      const key = match[1];
      const rawValue = match[2];
      if (key === undefined || rawValue === undefined) continue;
      if (process.env[key] !== undefined) continue;
      let value = rawValue.trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      process.env[key] = value;
    }
    return;
  }
}
loadSharedEnvFile();

const token = process.env.AGENT_RUNTIME_INTERNAL_TOKEN?.trim();
if (!token) {
  throw new Error("AGENT_RUNTIME_INTERNAL_TOKEN is required.");
}
const mode = process.env.AGENT_RUNTIME_MODE === "fake" ? "fake" : "real";
if (mode === "fake" && process.env.NODE_ENV === "production") {
  throw new Error("Fake Agent runtime mode is forbidden in production.");
}

const host = process.env.AGENT_RUNTIME_HOST?.trim() || "127.0.0.1";
const port = Number.parseInt(process.env.AGENT_RUNTIME_PORT ?? "8765", 10);
const pythonBaseUrl = process.env.AGENT_RUNTIME_PYTHON_BASE_URL?.trim() || "http://127.0.0.1:8000";
const adapter =
  mode === "real"
    ? new PiModelAdapter(
        new PythonInternalClient({
          baseUrl: pythonBaseUrl,
          internalToken: token,
        }),
      )
    : undefined;
const server = createAgentRuntimeServer({
  internalToken: token,
  mode,
  ...(adapter ? { adapter } : {}),
});
await startVerifiedServer(server, port, host).catch((error: unknown) => {
  const code =
    error instanceof SkillBundleError
      ? error.code
      : "agent_runtime_startup_failed";
  console.error(`Agent runtime startup failed: ${code}.`);
  process.exit(1);
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => {
    server.close(() => process.exit(0));
  });
}
