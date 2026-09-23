# Construction Plan: Dialogue Track Fusion (P0–P4)

Status: approved plan (grilled 2026-09-10). Decisions live in ADR 0002 (content kind) and ADR 0003 (speech track); engineering rules in `docs/agents/engineering-standards.md`. This document is the file-level construction guide.

## Status ledger (audited 2026-09-15 against the working tree)

| Phase | Status | Evidence / note |
| --- | --- | --- |
| P0 ad-assumption decoupling | ✅ done | `content_kind` in `ad_workflow.py` + `workflow_v2.py`; `short_film` default chain in the node catalog; acceptance honors `product_excluded` |
| P3 provider pool patterns | ❌ not started | No per-key pools / min-interval rate limiting / unified poll template in the provider layer |
| P4 trusted catalog registration | 🟡 partial (2026-09-13/15) | Registered: `stepfun:step-tts-mini`, `stepfun:stepaudio-2.5-tts`, `fish_audio:fish-speech` (audio), `volcengine_ark:step-image-edit-2` (image), `volcengine_ark:agnes-video-2.5-flash` (video). TTS engines: `scene3d/stepfun_tts.py` + `scene3d/fish_audio_tts.py` + `tts_engine_factory.py` (orphaned — no workflow consumer yet). ⚠️ P4.3 voice catalog (≈20 zh voices) still missing. |
| P1 speech track (core) | ❌ not started | No `voice-cast` node, no `speech_audio` asset, no `duration_mode`, no `dialogue/` module, no `v2_qa_registry.py`, no ducking/loudness/soft-subtitle. **Note:** `scene3d/speech_orchestration.py` (timeline/lip-keyframe utilities + `SimpleTTSEngine` placeholder) exists but is a 3D-previs-local module with no production callers — it is NOT the P1 speech track. |

**Next step:** P1.a schema (`voice-cast` node + `speech_audio` asset + `duration_mode`), then P1.b TTS executor reusing the stepfun/fish engines + P3 pools.

---

Source projects: A = this repo (base), B = `piagent-glm` (dialogue pipeline ideas, provider pool patterns, model endpoints).

```
P0 ad-assumption decoupling ──► P1 speech track (with QA registry)
P3 provider pool patterns ────► P1's TTS calls
P4 trusted model catalog registration (independent, small)
P5 stateful storyboard ─────── recorded only, unscheduled
```

Working rules: one work package per branch, ladder per touched context (see engineering standards), contract sync after every schema touch, no real keys anywhere.

## P0 — Ad-assumption decoupling (prerequisite for P1)

| # | Task | Files | Notes |
| --- | --- | --- | --- |
| 0.1 | Add `content_kind: ad \| short_film` to the workflow schema + DB migration | `apps/api/app/schemas/ad_workflow.py`, `apps/api/app/schemas/workflow_v2.py`, new alembic revision under `apps/api/alembic/versions/` | Default `ad` keeps every existing behavior |
| 0.2 | Parameterize duration cap | `ad_workflow.py:31` (ge=15, le=60), `apps/api/app/core/config.py` | Setting e.g. `SHORT_FILM_MAX_DURATION_SECONDS` (default 300); sequence window `le=15` untouched |
| 0.3 | Honor product exclusion in acceptance | `apps/api/app/services/v2_production_acceptance_validator.py:445`, `v2_generation_pipeline.py:2723`, `v2_parallel_slot_scheduler.py:17` | `JourneyTransitionEvidenceV2` already has `product_excluded`; the validators must respect it + `content_kind` |
| 0.4 | Short-film default node chain (no `product-generation`) | `apps/api/app/services/workflow_node_catalog.py`, `workflow_plan.py` (edge list incl. `:425`), `workflow_node_executor.py` | New default chain: script → character → scene → storyboard → video → bgm → final-composition |
| 0.5 | Branch specialist skill contracts | `apps/api/agent/skills/video_agent_script_authoring/SKILL.md`, `video_agent_world_setting`, `video_agent_prop_design`, `video_agent_character_design`, `video_agent_storyboard_design`; prompt sources in `apps/api/agent/src/prompts/` | short_film branch drops product-narrative clauses; adopts B's dialogue rules (≈4 chars/sec, no stage directions in audience-facing dialogue, sanitized speech text). Then: `npm run generate:manifest && npm run verify:skills` |
| 0.6 | Un-hardcode BGM vocals | `apps/api/app/schemas/agent_canvas_draft_seeds.py:165`, `apps/web/src/features/agent-canvas/model/nodeDefaults.ts:47` | Seeds stay instrumental for `ad`; flag becomes content |
| 0.7 | De-advertise agent self-identity | `apps/api/agent/src/prompts/agents.ts:2` | "video advertising cognition" → content-kind-neutral phrasing |
| 0.8 | Acceptance fixtures | `apps/api/tests/test_v2_*` (acceptance/parity tests) | Add a `short_film` acceptance variant; regression: `ad` behavior byte-identical |

**Acceptance**: with `content_kind=short_film`, a 180s workflow without any product node passes preflight/acceptance; with `ad`, all existing tests pass unchanged. Front-end: content-kind surfaced in project creation (minimal UI in `apps/web` project flow).

## P3 — Provider pool patterns (small, before P1's TTS)

| # | Task | Files | Source pattern (B) |
| --- | --- | --- | --- |
| 3.1 | Multi-key pools with per-key concurrency + min-interval rate limiting | provider layer around `apps/api/app/services/v2_provider_executor.py` and provider config (`app/core/config.py`) | B `models.json`: per-entry `concurrency`, `minIntervalMs`, several keys of same model as separate pool members |
| 3.2 | Unified async-job poll template | same area; align with existing poll_media_tasks machinery | B `poll` block: `taskIdPath` / `statusUrl` template / `statusPath` / `doneValues` / `failedValues` / `resultPath` / `intervalMs` / `maxPolls` |
| 3.3 | Global concurrency cap + attempt bound | scheduler config | B `defaults`: `globalConcurrency: 6`, `maxAttempts: 4` |

**Acceptance**: two keys of one provider run concurrently within per-key limits; a 429/backoff path is covered by an `integration`-marked test with a stubbed HTTP layer.

## P4 — Trusted model catalog registration (independent, small)

| # | Task | Files |
| --- | --- | --- |
| 4.1 | Register stepfun as image-capable provider: `step-image-edit-2` (openai-compatible) | `apps/api/app/services/provider_model_catalog.py` (follow `TrustedModelManifest` shape used for `volcengine_ark`) |
| 4.2 | Register agnes as video-capable provider: `agnes-video-2.5-flash`, including its async-poll contract (consumed by 3.2's template) | same file |
| 4.3 | Register stepfun TTS `stepaudio-2.5-tts` + voice catalog (≈20 zh voices) as the speech track's first-choice provider | same file + P1 voice-cast config |

**Acceptance**: catalog entries validate; provider identity stays inside the provider layer (no vendor names in domain code); keys only via config center/env. ⚠️ Security note: B's `models.json` keys were exposed during analysis — rotate stepfun/agnes keys before first use.

## P1 — Speech track (core work package)

### P1.a Schema & domain

| # | Task | Files |
| --- | --- | --- |
| 1.1 | `voice-cast` node type in the node catalog (category `audio_generation`), with dialogue-line inputs | `apps/api/app/services/workflow_node_catalog.py`, `workflow_node_executor.py` |
| 1.2 | `speech_audio` asset/slot type carrying text, voice id, measured duration, loudness, `duration_mode` | `apps/api/app/schemas/workflow_v2.py` (+ prompt-contract models in `workflows_v2_prompt_contracts` family) |
| 1.3 | `duration_mode: bound \| free` on shot dialogue | same schema area |
| 1.4 | Node agent contract updates → regenerate | `apps/api/agent/contracts/`, `apps/api/agent/skills/` (new `video_agent_voice_cast` skill) → `npm run generate:manifest && npm run verify:skills` |
| 1.5 | Web types + canvas node UI (dialogue editor, voice picker, audio preview) | `apps/web/src/types-v2.ts` chain, `apps/web/src/features/agent-canvas/` → `check:agent-canvas-contract` |

### P1.b Speech processing (Python, ffmpeg foundation)

| # | Task | Files |
| --- | --- | --- |
| 1.6 | TTS provider executor path for `speech_audio` (stepfun TTS first, via P3 pools) | `apps/api/app/services/v2_provider_executor.py` |
| 1.7 | Ported pure functions from B, unit-tested: line-duration estimate (~4 chars/s), subtitle segmentation, speech-text sanitize allow-list | new `apps/api/app/services/dialogue/` module |
| 1.8 | Two-pass loudness normalization (measure with `ebur128`, then compensate) | new service module, runs via `FfmpegTool` |
| 1.9 | Filter-graph extension: speech track + sidechain ducking of BGM (`audio_mode` gains `speech` variants) | `apps/api/app/services/v2_final_composition_filters.py`, renderer `v2_final_composition_renderer.py` |
| 1.10 | Soft subtitle track asset (srt/ass) at preview; burn-in only at export (`drawtext`/`ass` filter, font from `final_composition_subtitle_font_path`) | renderer + `app/core/config.py` |
| 1.11 | Round-trip tests for srt/ass and ffmpeg argument sequences (engineering standard §3) | `apps/api/tests/` with `media` marker |

### P1.c QA registry (pre-commit checks)

| # | Task | Files |
| --- | --- | --- |
| 1.12 | Registry interface: ordered named checks, each returns pass/warn/fail + structured reason; failure blocks execution-result commit; warn emits event | new `apps/api/app/services/v2_qa_registry.py`; hook into the execution-result commit path in the v2 pipeline |
| 1.13 | Phase-1 checks (pure ffmpeg probes, no LLM): TTS duration sanity vs estimate; loudness within target; `bound` mode: speech duration vs shot duration comparison | implementations registered from `dialogue/` module |
| 1.14 | Mutation-check tests for every registry check (engineering standard §3) | tests |
| 1.15 | Observable degradation: speech failure → subtitle-only composition + queryable event/marker (engineering standard §4) | renderer + event store |

**Acceptance (P1)**: a `short_film` workflow with N dialogue shots produces cast voices, per-shot `speech_audio` assets with measured durations; `bound` shots adopt TTS timing; preview carries soft subtitles; export burns them and mixes speech over ducked BGM at target loudness; forced TTS failure yields subtitle-only output with a visible degradation marker; all QA checks demonstrably red under mutation.

## P5 (recorded only — do not schedule)

Stateful storyboard per ADR 0003 appendix: mutable-state layer per shot, shot-relation enums, plan-vs-actual verification as a QA-registry check, epistemic prompt clauses, downstream-impact marking UI. Re-evaluate after P0–P4 ship; first target `short_film`.

## Sequencing & risk

1. **P4 + P3** first (small, independent, unblock TTS).
2. **P0** next (its schema change touches the contract chain — do it before P1 piles on).
3. **P1.a → P1.c** in order; 1.9–1.10 depend on 1.8.
4. Risks: speech timing drift vs video segments (mitigate: QA bound-check + regeneration path); provider TTS voice drift between runs (pin voice ids in `speech_audio` metadata); alembic migration on live data (add + backfill `content_kind='ad'` default).