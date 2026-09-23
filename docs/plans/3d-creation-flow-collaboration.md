# Collaboration Bulletin: Structured Derivation Across Nodes (3D 鍒涗綔娴?

Status: **open bulletin** (2026-09-15). This document is a local shared notice for two parties working on the 3D creation flow:

**Status ledger:**
- **[2026-09-15 P3a control-passes + fingerprint flip done — Party B]** Completed the remaining P3a scope: `scene3d/blender_converter.py` gains `include_control_passes` (compositor OutputFile nodes → `control_depth`/`control_normal`/`control_flow` sibling dirs; flow pass Cycles-gated, Eevee degrades with a printed marker); new `scene3d/control_passes.py` collects per-shot pass files (5-keyframe alignment) with a queryable `completeness` (full/partial/none) + `degradation_markers`; `v2_provider_executor._previs_control_level_from_payload` now requires the `previs_control_signal_support` fingerprint (ADR 0005 §4) to flip video→full — video runs without a stamped fingerprint stay `video_only` (conservative, queryable); `panel_previs_orchestration.orchestrate()` accepts `model_previs_signal_support` and degrades to `video_only` + warning when the fingerprint is absent. Ladder: ruff clean; `pytest` on the 9 previs/derivation modules = **240 passed** (new `tests/test_scene3d_control_passes.py` + updated `test_v2_previs_control_level.py` / `test_scene3d_pipeline.py` mutation checks; 2 of Party A's orchestration tests updated to pass the fingerprint for "full" — consistent with the new §4 rule). All P3a scope complete.
- **[2026-09-15 P5 frontend integration done — Party A]** Creation flow guidance frontend integration complete. Backend: 2 new API endpoints (`GET /workflows/{id}/creation-flow` for assessment, `GET /creation-flow/stages` for stage definitions). Frontend: `v2Api.getCreationFlowAssessment()` + `getCreationFlowStages()` client methods; 3 TypeScript types (`CreationFlowAssessmentResponse`, `CreationFlowStage`, `CreationFlowStageStatus`); `CreationFlowGuidance` component (6-stage progress bar, current stage, next action, blockers, warnings, expandable stage details) with CSS; integrated into AgentCanvasPageSurface toolbar with "🎬 Creation Flow" toggle button. TypeScript compiles clean.
- **[2026-09-15 P4 done 鈥?Party A]** World setting extension + guided creation-flow UX implemented. `WorldSettingCoreV2` extended with `owned_scene_ids: tuple[str, ...]` (max 32, per P0.5 audit 鈥?establishes world鈫抯cenes hierarchy). New `CreationFlowGuidanceService` (`app/services/creation_flow_guidance.py`): 6-stage flow (world_setting鈫抯cript鈫抯toryboard鈫抯cene_3d鈫抌inding鈫抮ender), `assess_flow(nodes)`鈫抈FlowAssessment` (current_stage, completed_stages, progress%, next_action, blockers, warnings), per-stage `StageStatus`, next-action generation (Create/Run/Move-to/Complete). 22 tests pass. **All P0-P4 phases complete.** Total: 135 tests pass across all structured-derivation modules.
- **[2026-09-15 P3a provider-layer marker done 鈥?Party B]** My assigned slice (ADR 0005 搂4/搂4a execution-path integration): `scene3d/prompt_builder.py` gains `PREVIS_CONTROL_LEVELS` + `previs_control_level(mode, control_signals_available)` (unknown modes fail closed to `text_only`); `scene3d/reference_assets.py` `VideoModelInput` exposes `previs_control_level` property + records `control_signals_available` in capabilities; `v2_provider_executor.py` `_execute_real_video` injects `previs_control_level` (+ reason) into the provider payload when a `scene3d_prompt_bundle` is present, and `_provider_asset_metadata` surfaces it into `V2ProviderResult.metadata` (queryable, never silent; unknown level 鈫?`text_only` + `previs_control_level_code="previs_control_level_unknown"`); `provider_model_catalog.py` gains `previs_control_signal_support {depth,normal,flow}` fingerprint on all three video manifests (seedance/agnes = all False; fake deterministic-video = all True so "full" level is testable in mock mode). Ladder: ruff clean on all touched files; `pytest` on `test_scene3d_prompt_builder + test_v2_previs_control_level + test_scene_script + test_panel_asset_binding + test_scenescript_derivation + test_storyboard_panel_derivation` = **179 passed** (new `tests/test_v2_previs_control_level.py` carries the mutation checks). **Overlap with Party A's P3 entry: both target the 搂4a marker 鈥?mine is the execution-path marker (persists into task metadata) + provider capability fingerprint; reconcile locally, prefer executor-level, drop duplicated local copies if any.** **Pre-existing failures, NOT from my change (reported per honesty rule): full unit suite = 353 passed / 11 failed 鈥?`test_v2_provider_result_commit_recovery.py` 脳5 (root cause `v2_final_composition_publication.py:245 os.fsync()` 鈫?`OSError [Errno 9] Bad file descriptor` on Windows test env), `test_v2_prompt_preparation_selfheal.py` 脳6 (same family), plus 2 stale collection-error test modules importing missing `app.api.v2.endpoints.workflows`. Flag to Party A/reviewer: platform-gate the fsync tests.** Remaining P3a scope (awaiting Party A 搂4 answer #3): `control_passes.py` (Blender depth/normal/flow) + executor consuming the fingerprint to flip `video_only` 鈫?`full`.
- **[2026-09-15 P3 done 鈥?Party A]** Panel-level 3D previs orchestration for video generation implemented. New `PanelPrevisOrchestrationService` (`app/services/panel_previs_orchestration.py`): StoryboardPanelV2[] 鈫?per-panel SceneScript (via P1b deriver) 鈫?per-panel VideoModelInput (via `build_video_model_input`) 鈫?FinalCompositionPlan. Reference mode determination per ADR 0005 搂4a: models supporting reference video 鈫?"video" mode; models supporting only images 鈫?"keyframes" (5 images/panel at 0/25/50/75/100%); prompt-only as last resort. `previs_control_level` degradation marker (full/video_only/images_only/text_only) queryable, never silent. FinalCompositionPlan: panel order, per-panel durations, transitions (cut/dissolve/fade), reference_modes, control_levels, total duration. Cross-panel binding consistency validation (P2). Warnings: mixed control levels, no-previs panels, non-sequential panel indices, >60s total duration. 27 tests pass (`tests/test_panel_previs_orchestration.py`). Per Objection 2: no new REST endpoint 鈥?this is a planning/orchestration layer consumed by existing storyboard-video-generation and final-composition nodes. Next: P4 (world_setting extension + guided creation-flow UX).
- **[2026-09-15 P2 done 鈥?Party A]** Panel asset binding + speech_bindings auto-fill implemented. `StoryboardPanelV2` extended with `character_speech_map: dict[str, str]` (character_id 鈫?speech_audio asset_id, per Objection 3). New `PanelAssetBindingService` (`app/services/panel_asset_binding.py`): `aggregate()` 鈫?`PanelAssetBundle` (character_ids/scene_id/prop_ids/speech_bindings/warnings, with `all_asset_ids` dedup property + `has_speech` + `bound_speech_count`); `generate_speech_bindings()` with bound/free mode override; `validate_binding_consistency()` cross-panel (speech_asset change detection + scene change detection). `SceneScriptDerivationService` integrated: speech_bindings auto-filled from `character_speech_map`, default bound mode (speech drives shot timing per ADR-0003), binding warnings propagated to derivation result. Per Objection 2: fields-first, no standalone endpoint yet (deferred until drag-asset UI ships). 68 tests pass (44 scenescript_derivation + 17 panel_asset_binding + 7 speech integration). Next: P3 (video generation consumes previs reference).
- **[2026-09-15 P1b done 鈥?Party A]** `SceneScriptDerivationService` implemented (`app/services/scenescript_derivation.py`): StoryboardPanelV2 鈫?SceneScriptRoot via deterministic rule-based mapping. Shot type 鈫?camera position + SceneCamera.shot_type (5 mappings); camera_move 鈫?camera keyframes (7 types: static/pan/tilt/dolly/zoom/crane/handheld); subject_action 鈫?character action + keyframes (5 actions: walk/talk/gesture/sit/stand, with walk generating 2-keyframe left鈫抮ight animation); character_ids/prop_ids/scene_id 鈫?asset-bound SceneCharacter/SceneProp/SceneEnvironmentObject (P0 asset-ref fields auto-filled); duration_seconds 鈫?SceneInfo.duration + total_frames. Warnings system (no characters/no scene/camera free-text not parsed in P1b baseline) + derived_fields audit trail. 44 tests pass (`tests/test_scenescript_derivation.py`). P1 complete (both derivation passes). Next: P2 (panel asset binding aggregation + speech_bindings auto-fill).
- **[2026-09-15 P1a done 鈥?Party A]** `StoryboardPanelDerivationService` implemented (`app/services/storyboard_panel_derivation.py`): script text + world_setting summary 鈫?`StoryboardPanelV2[]` via LLM (`llm_storyboard_model`). Structured output validation with markdown-code-block extraction, invalid-panel skipping with warnings, and 6 error codes (empty_script/llm_unavailable/llm_http_error/no_json_in_output/invalid_json/no_valid_panels). Per Party B Objection 1: script node is NEVER modified 鈥?derivation is a draft-layer intermediate for the storyboard node only. 18 tests pass (`tests/test_storyboard_panel_derivation.py`). Next: P1b (panel鈫扴ceneScript derivation).
- **[2026-09-15 P0.5 done 鈥?Party A]** `world_setting` audit complete. Existing `WorldSettingCoreV2` covers era (`era_and_place`), world rules (`world_rules`, 1-8 items), style baseline (`visual_continuity`, free-text list), core conflict (`premise`, free-text). `world_setting` is a `CanvasCreativeRoleV2` member (not a standalone `CanvasNodeTypeV2`); content lives in text nodes with creative_role=world_setting; consumed via `world_setting_inputs` at runtime. **Primary gap: multi-scene ownership** 鈥?no `owned_scene_ids` or world鈫抯cenes hierarchy. **P4 decision: extend existing `world_setting`** (add `owned_scene_ids` to `WorldSettingCoreV2`), NOT create a new node 鈥?glossary consistency + 55 existing consumers make extension cheaper and safer.
- **[2026-09-15 P0 done 鈥?Party A]** `StoryboardPanelV2` extended with 7 structured fields (`scene_id`, `character_ids`, `prop_ids`, `shot_type`, `camera_move`, `duration_seconds`, `scene_script_id`); `SceneScript` extended with 3 asset-ref fields (`SceneCharacter.character_asset_id`, `SceneProp.prop_asset_id`, `SceneEnvironmentObject.scene_asset_id`). ruff clean, 43 scene_script tests pass. P0.5 (world_setting audit) and P1 (derivation passes) next.

- **Party A (proposer)**: the author of the six-step gap analysis (script 鈫?storyboard 鈫?scene-3d 鈫?panel asset binding 鈫?video render, plus worldbuilding). Owns the **product judgment**: which capability lands when, what the UX should feel like.
- **Party B (feasibility annotator)**: the code-grounded reviewer. Owns **architecture conflict flags**: where the plan contradicts existing code, existing ADRs, or the repo's own construction conventions.

Decision rule (from `docs/agents/engineering-standards.md` + ADR-0002/0003 pattern): **product judgment belongs to Party A; architecture conflicts are annotated by Party B; the final ADR is merged by Party A, with Party B's annotations either adopted or honestly recorded as withdrawn candidates.**

---

## 1. Ground-truth audit (2026-09-15, verified against working tree)

Before discussing the plan, both parties should work from the same facts. What Party B verified directly in code:

| Claim in the six-step plan | Verified state |
| --- | --- |
| "scene-3d 鑺傜偣鎴戜滑宸插疄鐜? | **True.** `scene-3d` in `workflow_node_catalog.py` (category `visual_planning`, output `scene_script`), NL鈫扴ceneScript generation wired (`execute_canvas_scene_3d` op, 2026-09-15). See `docs/plans/3d-previs-construction.md` status ledger: P0/P1/P2/P6 done, P3 preview done, P4 (editing/timeline/lipsync) **not started**, P5 control-signal video-model integration **partial** (`prompt_builder` + `reference_assets` exist; `control_passes.py` / `reference_fallback.py` / provider `control_signals` + `previs_control_level` **not implemented**). |
| "ScriptSceneV2 / worldbuilding node don't exist" | **True.** `script` node output contract is prompt-text oriented (`dialogue`/`voice_style` in `workflow_v2.py`); no `ScriptSceneV2` schema. |
| "worldbuilding 鑺傜偣娌℃湁" | **Partially wrong 鈥?a `world_setting` system already exists.** `apps/api/app/schemas/agent_canvas_world_setting.py`: `WorldSettingCoreV2` carries `premise`, `era_and_place`, `world_rules` (tuple), `visual_continuity` (tuple); `WorldSettingContextEnvelopeV2` binds it to nodes with `target_audience` (per-creative-role audience, `agent_canvas_world_setting.py` `WORLD_SETTING_AUDIENCE_BY_CREATIVE_ROLE`). Frontend consumers exist under `agent-canvas/` (capability identity, chat panel). **The gap is narrower than the plan assumes**: what's missing is *multi-scene ownership* (a world setting owning several scene nodes) 鈥?the schema models **one** world-setting document per node, not a world鈫抯cenes hierarchy. |

**Implication:** Party A's P4 "new `worldbuilding` node" collides with the existing `world_setting` concept. Per the `CONTEXT.md` glossary discipline (one term per concept, synonyms avoided), the recommended move is: **extend `world_setting`** (add scene-ownership / multi-scene reference) rather than introduce a second, near-synonymous concept. Party A to confirm intent before P4 is scoped.

---

## 2. Party B's three objections (to be adopted or recorded as withdrawn in the final ADR)

### Objection 1 鈥?Do NOT extend the `script` node's output schema (plan step 2)

The plan proposes `ScriptSceneV2` (structured scenes[]/characters[]/dialogue[]/camera_suggestion) as part of the script node's canonical output. **Risk:** the script node's output contract is consumed by the script-specialist prompt contract AND the v2 acceptance chain (`v2_production_acceptance*`); changing it forces rework of both, and the advertising rules ADR-0002 pinned ("script must connect product value to audience motivation") live in that same contract.

**Recommended alternative (cheaper, same outcome):** keep the `script` node untouched. Put the derivation **on the storyboard side**: the storyboard node already declares `script` in its `optional_inputs` (node catalog). A storyboard-side LLM pass reads the script's text + the world_setting context and produces `StoryboardPanelV2[]` as a **draft-layer intermediate** of the storyboard node 鈥?it never enters the script node's canonical output. Derivation failure stays retryable and local to the storyboard node. Party A to confirm or rebut.

### Objection 2 鈥?Panel-level asset binding: fields first, endpoint later (plan step 5)

The plan proposes a new `PanelAssetBinding` model + `POST /workflows/{id}/storyboard/{panel_index}/bind-asset` endpoint. **Risk:** the repo already has a node-level binding mechanism (`agent_canvas_bindings.py`: `storyboard_visual_anchor` / `semantic_reference_role`). Running two binding sources (node-level + panel-level) in parallel makes reference dedup in `v2_reference_bundle_builder` (accepted / prompt_only / rejected buckets) materially harder.

**Recommended ordering:**
1. P0: add the fields to `StoryboardPanelV2` directly (`character_ids`, `scene_id`, `prop_ids`, `scene_script_id`) 鈥?they're just data, no new model needed yet.
2. Execution: the reference bundle builder aggregates panel-level references from those fields.
3. **Later:** only if/when the "drag asset onto a panel" UI actually ships, extract `PanelAssetBinding` + endpoint. The fields already carry the data; the model is a refactor, not a prerequisite.

### Objection 3 鈥?Panel-asset binding must wire into `speech_bindings` (plan step 5, missing piece)

The plan's P2 omits a coupling that ADR-0005 搂5 already mandates: `SceneScript.speech_bindings` (character 鈫?`speech_audio` asset, `bound` mode). Consequence of the gap: a character bound to a panel with recorded dialogue, when derived into a SceneScript, would drop its `speech_audio` reference, and ADR-0003's `duration_mode: bound` semantics break at the 3D layer (shot timing stops being driven by speech duration).

**Add to P2:** panel-bound character + its speech_audio 鈫?automatically fills `SceneScript.speech_bindings`; `bound` mode derives shot/character keyframe timing from speech duration; `free` mode 鈫?QA warning on mismatch (reuses ADR-0003's planned QA-registry check pattern).

---

## 3. Revised roadmap (Party A's P0鈥揚4, with Party B's corrections folded in)

| Phase | Content | Dependency | Notes |
| --- | --- | --- | --- |
| **P0** | `StoryboardPanelV2` structured fields (`scene_id` / `character_ids` / `prop_ids` / `shot_type` / `camera_move` / `duration_seconds` / `scene_script_id`); `SceneScript` asset-ref fields (`SceneCharacter.character_asset_id`, `SceneProp.prop_asset_id`, `SceneEnvironmentObject.scene_asset_id`) | none | Small-to-medium. Pure schema extension, mutation-check tests per `engineering-standards.md` 搂3. |
| **P0.5 (new)** | **Audit `world_setting` coverage** 鈥?confirm the existing schema covers "era / world rules / style baseline / core conflict"; scope P4 as an *extension* of `world_setting` (multi-scene ownership), not a new node | none | One-day audit; output is a 3-line decision that de-risks P4. |
| **P1** | storyboard-side derivation script鈫抪anels (per Objection 1: **script node untouched**); panel鈫扴ceneScript derivation (camera/subject_action 鈫?camera keyframes) | P0 | Large. Two derivation passes, each with user override + "re-derive or keep" semantics via existing `derived_from` relation type (`WorkflowRelationTypeV2`, `workflow_v2.py`). |
| **P2** | Panel asset binding via P0 fields + bundle-builder aggregation (per Objection 2: no standalone endpoint yet); **`speech_bindings` auto-fill** (per Objection 3) | P0, P0.5 | Medium. |
| **P3** | video-generation consumes previs reference + `prompt_builder` + `previs_control_level` degradation marker (ADR-0005 搂4/搂4a); per-panel video generation; final-composition assembles in panel order, preserving transitions | P1 | Large. Party B owns the provider-layer implementation (`v2_provider_executor.py`, `provider_model_catalog.py` capability fingerprinting, `reference_fallback.py` selection logic). |
| **P4** | `world_setting` extension (multi-scene ownership, per P0.5 outcome) + guided creation-flow UX (world 鈫?script 鈫?storyboard 鈫?3D 鈫?binding 鈫?render) | P0.5 + P1 | Medium-to-large. |

**Sequencing note:** P3 of the plan depends on P1, but **P3's provider-layer work can start immediately in parallel** 鈥?it only needs `SceneScript` + keyframes, both already exist (P0/P2 done). Party A to decide if P3 gets split into P3a (provider layer, start now) / P3b (per-panel generation, after P1).

---

## 4. Open questions for Party A — ANSWERED (2026-09-15)

1. **P4 world_setting:** ✅ **Extend existing `world_setting`** (Party B recommendation adopted). P0.5 audit confirmed `WorldSettingCoreV2` already covers era/rules/style/conflict; primary gap was multi-scene ownership. P4 added `owned_scene_ids: tuple[str, ...]` (max 32) to `WorldSettingCoreV2`. No new node — glossary consistency + 55 existing consumers make extension cheaper and safer.

2. **P1 override semantics:** ✅ **Per-panel toggle, surfaced as plan-vs-actual drift** (Party B sketch adopted). When user edits a derived panel, default is "keep manual" (don't silently re-derive). Per-panel `derivation_status` field (auto/manual/overridden) tracks drift; QA registry pattern from ADR-0003 appendix. **Deferred to P6** — current P1a/P1b derivation services are read-only (no write-back to panels yet), so override semantics can be added when derivation is wired into the storyboard node executor.

3. **P3a/P3b split:** ✅ **P3a approved and completed** (Party B delivered 2026-09-15: `previs_control_level()` in prompt_builder, `VideoModelInput.previs_control_level` property, executor injection, provider capability fingerprint — 179 tests pass). **P3b (control_passes.py depth/normal/flow + executor fingerprint consumption) approved to start now** — Party B may proceed. Party A's P3 orchestration service already exposes `previs_control_level` per panel; P3b will flip `video_only` → `full` when provider supports control signals.

4. **Panels count:** ✅ **Soft warning, not hard cap — but current implementation keeps fixed-9.** The existing `StoryboardGridContentV2.panels` is fixed 9 (min_length=9, max_length=9) per ADR-0002 provider generation-window constraint. P0 only extended `StoryboardPanelV2` fields, did NOT change the panels count. **Decision: keep fixed-9 for now** (matches existing grid UI and provider window); if a use case needs >9 panels, that's a separate ADR to relax the constraint with soft warning at 9+ (not 30). The 1..30 proposal from the initial plan is **withdrawn**.

5. **Lip-sync:** ✅ **Confirmed out of scope for this flow** — stays deferred until ADR-0003 P1 (voice-cast node + TTS executor) lands. Current `speech_orchestration.py` uses syllable-level lip sync (not phoneme-level); `speech_bindings` in P2 assumes `speech_audio` assets exist but doesn't generate them. Phoneme-level lip sync (Rhubarb/Oculus LipSync) remains in §5 deferred items.

## 5. Deferred items (recorded, not scheduled 鈥?per repo convention)

- **Audio-driven lip-sync without bound-mode speech driving (Wav2Lip / MuseTalk / 3D viseme tracks).** Discussed 2026-09-15; intentionally parked until the 3D flow is settled. Not imported from project B's pipeline (ADR-0003 搂1 rejection stands).
- **Free LLM-driven Three.js modeling.** Rejected: LLM boundary stops at the structured intent (SceneScript is the validated carrier, ADR-0005 搂1); Three.js is preview/verify only; layout determinism is the programmatic layout layer's job.

## 6. How to use this bulletin

- Party A: answer 搂4, mark each 搂2 objection **adopted / rebutted (with reason)**, then draft the ADR (new `docs/adr/000X-structured-derivation.md` or an amendment section to ADR 0005) with the product judgment in *Context* and *Decision*, objections adopted-or-withdrawn in the ADR's "withdrawn candidates" section.
- Party B: re-verifies every code reference in this bulletin before the ADR merge; P3a provider-layer implementation on request.
- Both: one-line status updates at the top of this file (like the status ledgers in `3d-previs-construction.md`), not comment threads.

---

## 7. Division of labor (鍒嗗伐鏄庣粏)

### Party A 鈥?Product & Implementation (浜у搧鍒ゆ柇涓庡疄鐜?

Owns the **product judgment**, **derivation services**, **data model extensions**, **frontend UX**, and **documentation**.

| Phase | Party A responsibilities |
| --- | --- |
| **P0** | Schema extension design & implementation (`StoryboardPanelV2` + `SceneScript` fields); mutation-check tests |
| **P0.5** | `world_setting` coverage audit; P4 extension decision (extend vs. new node) |
| **P1a** | `StoryboardPanelDerivationService` (script鈫抪anels); LLM prompt design; output validation; tests |
| **P1b** | `SceneScriptDerivationService` (panel鈫扴ceneScript); camera keyframe mapping rules; character action derivation; asset binding auto-fill; tests |
| **P2** | Panel asset binding aggregation in reference bundle builder; `speech_bindings` auto-fill from panel-bound characters + speech_audio |
| **P3b** | Per-panel video generation orchestration; final-composition assembly in panel order; UX for previs control level |
| **P4** | `world_setting` extension (`owned_scene_ids`); guided creation-flow UX (world 鈫?script 鈫?storyboard 鈫?3D 鈫?binding 鈫?render); ADR drafting |
| **Docs** | ADR 000X (structured derivation); user-facing docs; CHANGELOG updates |

### Party B 鈥?Architecture Review & Provider Layer (鏋舵瀯瀹℃牳涓?Provider 灞?

Owns **architecture conflict flags**, **provider-layer implementation**, **code review**, and **integration with existing systems**.

| Phase | Party B responsibilities |
| --- | --- |
| **All** | Code review of every Party A PR; verify code references in this bulletin; flag architecture conflicts before merge |
| **P0** | Verify schema extensions don't break existing consumers (`v2_reference_bundle_builder`, `agent_canvas_bindings.py`) |
| **P1** | Verify derivation services don't collide with existing `V2StoryboardDirector` / `V2StoryboardDetailMaterializer`; recommend integration points |
| **P2** | Verify panel-level binding aggregation doesn't break node-level binding dedup in `v2_reference_bundle_builder` |
| **P3a** | **Provider-layer implementation**: `v2_provider_executor.py` control-signals support; `provider_model_catalog.py` capability fingerprinting for previs reference; `reference_fallback.py` selection logic (video 鈫?5 keyframes 鈫?none); `previs_control_level` degradation marker |
| **P3** | Verify video-generation consumption of previs reference doesn't break existing provider contracts |
| **P4** | Verify `world_setting` extension doesn't break 55 existing consumers; review guided UX integration with existing guidance system |

### Parallel work streams

- **P3a (provider layer)** can start immediately in parallel with P1 鈥?it only needs `SceneScript` + keyframes, both already exist. Party B owns this.
- **P1a/P1b (derivation services)** are sequential (P1b needs P1a's panel output). Party A owns both.
- **P2 (binding + speech)** depends on P0 fields + P1 derivation. Party A owns, Party B reviews.
- **P4 (world_setting + UX)** depends on P0.5 audit + P1 derivation. Party A owns, Party B reviews integration.

### Decision rights

- **Product judgment** (what lands when, UX feel): Party A decides, Party B advises.
- **Architecture conflicts** (collisions with existing code/ADRs/conventions): Party B flags, Party A decides adopt or rebut (with reason recorded in ADR).
- **Final ADR**: Party A merges, with Party B's annotations either adopted or honestly recorded as withdrawn candidates.
- **Code merge**: Both parties review; Party B's architecture flags must be resolved (adopted or rebutted) before merge.

---

*Generated 2026-09-15 by Party B, working tree of `myAdcraft` @ main. All file references verified at that commit; re-verify before relying on them.*
