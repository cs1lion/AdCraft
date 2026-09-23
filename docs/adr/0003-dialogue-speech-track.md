# Dialogue / speech track (native fusion of project B's dialogue pipeline)

## Context

Fusion goal (grilled 2026-09-10): give AdCraft a dialogue-driven capability — voice casting, speech audio, subtitle handling — shared by `ad` and `short_film` content kinds (ADR 0002). Project B (piagent-glm video-agent) has a proven dialogue pipeline (voice cast → TTS → lip-sync clips → dubOver → subtitle burn → two-pass loudness) but ships it as a standalone Node seven-stage pipeline. We rejected importing that pipeline: AdCraft's Workflow v2 stays canonical and B's logic is translated into it natively.

Feasibility was verified against the codebase: AdCraft already has a complete local ffmpeg foundation — `app/tools/ffmpeg.py`, capability fingerprinting (`ready/degraded/unsupported`), encoder allow-lists, filter-graph compilation (`v2_final_composition_filters.py`), and the final composition renderer (normalize → concat → mix). Missing pieces are speech mixing and subtitle burn-in only.

## Decisions

1. **Native fusion.** New node type `voice-cast`, new asset type `speech_audio`, new slots — no second pipeline, no new service.
2. **Dual duration coupling.** Shot dialogue carries `duration_mode: bound | free`. `bound`: the TTS-measured duration drives the shot's timing. `free`: the speech track is arranged independently. The schema ships both from day one.
3. **Subtitle dual mode.** Preview/candidate stages use a soft subtitle track (srt/ass asset, player-rendered). Burn-in (drawtext/ass filter) happens only at final export. `final_composition_subtitle_font_path` already exists as the font hook.
4. **Full local processing.** Speech enters the filter graph as its own track with sidechain ducking of BGM; two-pass loudness normalization (measure with ebur128, then compensate — port of B's export semantics); line-duration estimation (~4 chars/second) and subtitle segmentation rules are ported as pure functions.
5. **QA registry, not ad-hoc checks.** A registry of automated pre-commit checks runs before an execution result commits back to selected asset versions. Phase-1 entries are pure ffmpeg probes (no LLM): TTS duration sanity, loudness targets, `bound`-mode speech-vs-shot duration comparison. The interface reserves a slot for B's plan-vs-actual shot-state verification (unscheduled; see appendix).
6. **Observable degradation.** Speech failure falls back to a subtitle-only composition and must emit a queryable event/marker. Silent fallbacks are forbidden. A's existing `fallback_class` / `recovery_mode` machinery is untouched; this is a speech-track-local backup path.

## Withdrawn candidates (recorded honestly)

- **Quota ledger (reserve/settle/release).** AdCraft has no metered billing surface; its existing "budgets" (`thinking_budget_tokens`, provider-conformance budgets) are agent compute budgets, not media spend. Deferred until multi-user quotas or cost dashboards become real requirements.
- **Confirmation gates.** Already covered: the `guidance_awaiting` kinds (`clarification`, `concept_selection`, `media_review`, `manual_node_run`, `milestone_idle`) plus `required_deferred_final_review` are a superset of B's two gates.
- B's LLM visual QA loop and the dual-gate follow-read check (envelope + ASR) stay phase 2 — a different magnitude of engineering than the speech track.

## Provider layer support

The speech track's TTS provider (first choice: stepfun `stepaudio-2.5-tts`, openai-compatible) is registered in the trusted model catalog, and the provider layer adopts B's pool patterns: multi-key pools, per-key concurrency, min-interval rate limiting, a unified poll-protocol template, global concurrency cap, and attempt-bounded retries. Credentials live only in the config center / environment.

## Appendix (recorded, unscheduled): stateful storyboard (P5)

Project B's storyboard design treats a storyboard as "a shot sequence with state records". Worth re-evaluating after phase 1, specifically for `short_film`:

- Three-layer separation: fixed setup (asset references) / **mutable state** (position, holder, door open/closed, hand occupancy, mood) / cinematography. AdCraft has the fixed layer (asset references + must-use bindings) and cinematography fields, but no mutable-state layer.
- Explicit shot-relation enums: temporal (continue / overlap / elide / flashback), spatial (same-location re-angle / follow migration / location switch), action, and sound relations.
- Plan-vs-actual dual track: the scripted end-state is a claim to verify against generated keyframes; conflicts are regenerated before the error propagates. This is the storyboard-shaped instance of the QA-registry entry reserved in decision 5.
- Epistemic clauses (occlusion ≠ disappearance; screen position ≠ world position) as prompt-contract lines.
- UI: editing an upstream shot marks affected downstream shots for user-confirmed propagation.