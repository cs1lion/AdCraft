# Engineering Standards

Repository-wide engineering rules binding every context (`apps/api`, `apps/api/agent`, `apps/web`) and every agent working here. They build on the repo's existing tooling; rules marked **(B)** are adopted from the piagent-glm project's proven practice.

## 1. Self-verification ladder

Run the ladder for every context you touched, in order, before claiming completion. Paste the commands you ran and a result summary (e.g. `312 passed, 2 skipped`) into the commit/handoff note. Never write "verified" without proof of a run.

| Touched | Required ladder |
| --- | --- |
| `apps/api` (Python) | `uv run ruff check` → `uv run pytest` (select markers deliberately: `media`, `integration`, `e2e`) |
| `apps/api/agent` (Node) | `npm run typecheck` → `npm test` → after any schema/capability/skill change: `npm run generate:manifest && npm run verify:skills` |
| `apps/web` | `npm run check:quality` → plus `npm run check:agent-canvas-contract` when backend contracts changed → plus `npm run check` (includes bundle budget) when UI surface changed |

## 2. Contract sync

Generated artifacts are never hand-edited (`agent-runtime.schema.json`, generated TypeScript, skill manifests). Change the source, regenerate, re-verify. A Python schema change that reaches agent or web types must be followed by regeneration and `check:agent-canvas-contract`.

## 3. Test discipline

- pytest markers are strict (`--strict-markers`): classify every test (`media` / `integration` / `e2e` / `slow`). Unmarked tests are a defect.
- **(B) Mutation check**: when adding or changing a validator (prompt-contract quality, QA-registry checks), state in the test what it locks and mutate the input once to watch it go red.
- **(B) Round-trip**: any artifact consumed by a third-party parser (srt/ass subtitles, ffmpeg argument sequences) gets a parse → serialize → parse round-trip test.
- **(B) Real binary**: semantics mocks cannot lock (audio ducking timing, loudness targets) get `media`-marked tests against real ffmpeg.

## 4. Observable degradation

Every fallback path (e.g. speech failure → subtitle-only composition) must emit a queryable event or status marker. Silent degradation is forbidden.

## 5. Domain vocabulary

Use the glossary terms from the relevant `CONTEXT.md`. New domain words enter the glossary before (or together with) the code that introduces them. Do not drift into synonyms the glossary avoids.

## 6. Decisions

Cross-context decisions go to `docs/adr/`; per-context ones to `apps/<context>/docs/adr/`. If your change contradicts an ADR, surface it explicitly — do not silently override.

## 7. Security

- Credentials never enter the repository: no keys in docs, fixtures, logs, or tests. Providers are configured via the config center / environment only.
- If a secret is found exposed, the first action is **rotation**, not deleting the file. (Motivating incident: stepfun/agnes keys in project B's `.pi-studio/models.json`.)
- Provider identity is normalized by the provider layer; vendor names do not leak into domain code.

## 8. Performance budget

`apps/web` enforces a build budget (`perf:bundle`). UI changes that grow the bundle must justify the growth or shrink elsewhere.