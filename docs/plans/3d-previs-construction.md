# Construction Plan: 3D Low-fidelity Previs (P0–P6)

Status: **P0 done · P1 partial · P2 done (encoder/keyframes hardening 2026-09-15) · P3 partial · P4 not started · P5 not started · P6 backend done (7/7 templates) / frontend not started** (audited 2026-09-15 against the working tree). Decisions live in ADR 0005 (3D previs); speech-track coupling in ADR 0003; free authoring + observability in ADR 0006; engineering rules in `docs/agents/engineering-standards.md`. This document is the file-level construction guide.

## Status ledger (2026-09-15 audit — replaces the old "P0–P6 completed" claim)

| Phase | Done | Partial / missing |
| --- | --- | --- |
| P0 schema + validators + tests | ✅ `scene_script.py`, `test_scene_script.py` (43), 6 cross-field validators | TS types are a hand-maintained mirror (`apps/web/src/types/scene-script.ts`), not the contract-sync pipeline P0.4 promised |
| P1 skill + node + NL parse | ✅ `video_agent_3d_storyboard` skill **registered** (manifest + generated manifest, 2026-09-15); `parser.py` + tests (23); `scene-3d` in `CanvasNodeTypeV2`, node dispatcher and v1 catalog; `scene_script` asset type; **NL→SceneScript generation wired** (`execute_scene_3d` now calls LLM via new `execute_canvas_scene_3d` op + `AgentCanvasScene3DOutput` contract + `parse_llm_output`, then persists `structured_content["scene_script"]` so the web preview activates on reload) | |
| P2 Blender + encoder + keyframes + API | ✅ converter/renderer/encoder/keyframes + real-Blender integration test (5, skip-gated on `BLENDER_EXECUTABLE`); 12 REST endpoints; async job manager; encoder/keyframes now glob-safe for >999 frames (2026-09-15) | ❌ P2.3 low-poly `assets/` subpackage not created (geometry inlined in the converter); sync `/render` was event-loop-blocking (fixed 2026-09-15 via `asyncio.to_thread`); `RenderJobManager.cancel` cannot kill a running Blender subprocess and temp dirs leak (known limitation, documented in the module docstring) |
| P3 web preview | ✅ `SceneScriptPanel` / `SceneScript3DPreview` / `SceneScriptPlaybackContext` + `three`/R3F deps; panel wired into `AgentCanvasNode` when `structured_content["scene_script"]` exists; web `CanvasNodeTypeV2` + node icon/labels/roles include `scene-3d` (2026-09-15) | ❌ no producer of `scene_script` content yet, so the preview is inert until P1.5 lands |
| P4 editing + timeline + lip-sync UI | — | ❌ none of `scene3d/editor|timeline|lipsync` exists |
| P5 control signals + video-model integration | ✅ `prompt_builder` / `reference_assets` (video→keyframes→none fallback) + tests (31) | ❌ no `control_passes.py` / `reference_fallback.py` / `v2_qa_registry.py`; provider layer has no `control_signals` / `previs_control_level` (ADR 0005 §4/§4a not implemented) |
| P6 templates + multi-aspect | ✅ 7/7 template generators (4 added 2026-09-15); aspect adaptation pure functions + endpoint; tests (46) | ❌ `render_settings` (resolution/FOV) not consumed by the Blender converter (hardcoded 960×540); no frontend picker/aspect toggle |

## 2026-09-15 code fixes (this audit)

1. `execute_scene_3d` called `encode_png_sequence(frame_dir=..., frame_rate=...)` — the real signature is `(input_dir, output_path, fps)`; first call would have raised `TypeError`. Fixed.
2. `AgentCanvasNodeRow` SQL CHECK excluded `scene-3d` while `CanvasNodeTypeV2` included it → any persisted scene-3d node would violate the constraint. New migration `alembic/versions/20260915_01_add_scene3d_node_type.py` + `models.py` updated + local DB migrated.
3. Web `CanvasNodeTypeV2` (`types-v2.ts`) now includes `"scene-3d"` to match the backend literal; fixed the 3 resulting `Record<CanvasNodeTypeV2,…>` type errors in `AgentCanvasNodeIcon` / `nodeDefaults` / `useAgentCanvasProviderModels`. `tsc --noEmit` clean.
4. ruff errors in `test_scene3d_api.py` / `start_backend.py` cleaned up.
5. **ADR 0006 P0 landed in the same tree** (audit 2026-09-15): `authoring_origin` / `intent_hint` now **persisted** on `agent_canvas_nodes` (migration `20260915_02` + `_node_values` / `_node_from_row` + `agent_canvas_nodes.py` create path) — previously they were schema-only fields that silently reset on reload, which would have broken the `/progress` next_action wording. `GET /workflows/{id}/progress` endpoint + frontend graph progress + `NodeRunBlockedError` structured run guards + `retryAllFailed` are in the tree (see ADR 0006).

## P1.4/P1.5 landed (audit 2026-09-15)

- **P1.4 (skill registration)** — DONE: `video_agent_3d_storyboard` added to `skills/manifest.json` + `generate:manifest` + `verify:skills` all pass.
- **P1.5 (NL→SceneScript wired)** — DONE:
  - New operation `execute_canvas_scene_3d` in `video_agent_operation_registry.py` + `agent/src/registry.ts` + `contracts/agent-capabilities.json` (regenerated `agent-capabilities.ts`).
  - New result contract `AgentCanvasScene3DOutput` in `app/schemas/agent_runtime.py` (carries `raw_output`, the full LLM text).
  - `NodeExecutionContext` now carries `durable_runner: DurablePiRunService | None` (shared by all executors).
  - `execute_scene_3d` now **generates** the SceneScript from `generation_prompt` via the LLM (one retry pass via `parse_llm_output`'s `retry_feedback`) if `structured_content["scene_script"]` is missing, then falls through to the existing Blender/encode/mux path. The outcome already returns the dict, so `publish_node_output` persists it — the web `SceneScriptPanel` activates on reload.
  - In `fake` mode or when no agent runtime is configured, generation is skipped and the node still requires an explicit `structured_content["scene_script"]` (clear `scene_script_missing` error, no silent stub).

## Next steps (smallest value first)

1. ~~P1.4: register the 3D skill~~ ✅ done 2026-09-15
2. ~~P1.5: wire NL→SceneScript into the executor~~ ✅ done 2026-09-15
3. P5.1/5.3: control passes + provider `control_signals` (the controllability value prop).
4. P6: make the Blender converter consume `render_settings` (resolution/FOV) from `adapt-aspect`.
5. P4: interactive editing / timeline / lip-sync UI (the `scene3d/editor|timeline|lipsync` modules).

---

```
P0 SceneScript schema + validators
   │
   ▼
P1 Agent skill + scene-3d node + natural-language parse
   │
   ▼
P2 Blender renderer + low-poly asset library + render API
   │
   ▼
P3 Frontend Scene3DNode + Three.js live preview
   │
   ├──────────────┐
   ▼              ▼
P4 Interactive    P6 Shot templates + multi-aspect
editing + timeline (can run parallel after P3)
+ speech linkage
   │
   ▼
P5 Geometric control signals + video-model integration
```

Working rules: one work package per branch, ladder per touched context (see engineering standards), contract sync after every schema touch, no real keys anywhere, ADR conflicts surfaced explicitly.

---

## P0 — SceneScript domain model & validators (prerequisite)

Goal: the canonical intermediate format exists as validated Pydantic models with round-trip tests. No UI, no LLM, no rendering.

| # | Task | Files | Notes |
| --- | --- | --- | --- |
| 0.1 | SceneScript Pydantic models: `SceneScriptRoot`, `SceneCharacter`, `SceneProp`, `SceneEnvironmentObject`, `SceneCamera`, `SceneShot`, `CharacterKeyframe`, `CameraKeyframe`, `SpeechBinding` | new `apps/api/app/schemas/scene_script.py` | Enums: `shot_type` (wide/medium/closeup/over_shoulder/pov), `action` (stand/talk/walk/sit/gesture). Coordinates: list[float] length 3, meters. `rotation_y` degrees (LLM-friendly), normalized internally. |
| 0.2 | Validators: no overlapping shot frame ranges; camera keyframe frames within referencing shot bounds; character keyframe frames within total duration; `speech_bindings` reference existing character ids; `bound` mode requires speech_asset ref | same file, `@model_validator` / `@field_validator` | Mutation-check tests per validator (engineering standard §3): state what it locks, mutate input once, watch it go red. |
| 0.3 | Unit tests: schema parse/serialize round-trip, validator mutation checks, enum completeness | `apps/api/tests/test_scene_script.py` | `pytest` unit marker (no media/integration needed). Round-trip: JSON → model → JSON → model equality. |
| 0.4 | TypeScript type generation: SceneScript types exported to web | `apps/api/app/schemas/scene_script.py` (source) → regenerate via existing contract-sync pipeline → `apps/web/src/types-v2.ts` or new `apps/web/src/types/scene-script.ts` | Follow existing `check:agent-canvas-contract` pattern. Hand-editing generated types forbidden. |
| 0.5 | Glossary entry: add `SceneScript`, `previs`, `low-fidelity`, `blocking` to the relevant `CONTEXT.md` glossary | `apps/api/CONTEXT.md`, `apps/web/CONTEXT.md` (if glossary exists there) | Engineering standard §5: new domain words enter glossary before or with the code. |

**Acceptance:** `uv run ruff check` + `uv run pytest` pass on `apps/api`; SceneScript round-trips through JSON; every validator has a mutation test; web types regenerate and `check:agent-canvas-contract` passes. No behavior change to existing workflows.

---

## P1 — Agent skill + scene-3d node + natural-language parse

Goal: a user can input a natural-language scene description and receive a validated SceneScript. No rendering yet (that is P2).

| # | Task | Files | Notes |
| --- | --- | --- | --- |
| 1.1 | New agent skill `video_agent_3d_storyboard`: SKILL.md defining input (natural language + optional upstream script/character/scene assets) → output (SceneScript JSON) | new `apps/api/agent/skills/video_agent_3d_storyboard/SKILL.md` | Follow existing skill structure (e.g. `video_agent_storyboard_design`). Prompt contract must require valid SceneScript, forbid free-text output. Include few-shot examples. |
| 1.2 | `scene-3d` node type in node catalog (category `visual_planning`), input slot: natural-language description or upstream asset refs; output slot: `scene_script` asset | `apps/api/app/services/workflow_node_catalog.py`, `workflow_node_executor.py` | Does not replace `storyboard` node. Default `short_film` chain may insert `scene-3d` after `storyboard` (optional, not forced). |
| 1.3 | `scene_script` asset/slot type in workflow schema | `apps/api/app/schemas/workflow_v2.py` (+ prompt-contract models if applicable) | Asset carries: `scene_script_json` (str), `generated_by` (skill id), `validation_status` (valid/invalid), `duration_seconds`. |
| 1.4 | Agent contract updates → regenerate manifest → verify skills | `apps/api/agent/contracts/`, `apps/api/agent/skills/video_agent_3d_storyboard/` → `npm run generate:manifest && npm run verify:skills` (in `apps/api/agent`) | Engineering standard §1: agent context ladder. |
| 1.5 | LLM call path: node executor invokes `video_agent_3d_storyboard` skill, parses LLM output into SceneScript, runs validators, stores as asset | `apps/api/app/services/workflow_node_executor.py` (scene-3d branch), new `apps/api/app/services/scene3d/parser.py` | Parser must handle LLM output wrapping (markdown code fences, etc.). Invalid SceneScript → execution result marked failed with structured reason, no silent fallback. |
| 1.6 | Web: node type registration + minimal node UI (input textarea, output SceneScript JSON viewer) | `apps/web/src/features/agent-canvas/` (node registry, node UI), `apps/web/src/types-v2.ts` | Minimal UI for P1: text input + JSON output display. 3D preview comes in P3. `check:agent-canvas-contract` must pass. |

**Acceptance:** a `scene-3d` node can be added to a workflow; given a natural-language description, it produces a validated SceneScript asset; invalid LLM output fails loudly with structured reason; `ruff` + `pytest` + agent `typecheck`/`test`/`verify:skills` + web `check:quality` + `check:agent-canvas-contract` all pass.

---

## P2 — Blender renderer + low-poly asset library + render API

Goal: backend can take a SceneScript and produce a low-fidelity animated MP4 + keyframe images. Blender runs headless in the backend worker.

| # | Task | Files | Notes |
| --- | --- | --- | --- |
| 2.1 | `BlenderRenderer` service: subprocess invocation of `blender --background --python <script>`, timeout, stdout/stderr capture, artifact collection, cleanup | new `apps/api/app/services/scene3d/blender_renderer.py` | Blender path from config (`BLENDER_EXECUTABLE`, default `blender` on PATH). Capability fingerprint: `ready/degraded/unsupported` matching existing ffmpeg capability pattern. Timeout per shot, configurable. |
| 2.2 | SceneScript → Blender Python script generator: emits a self-contained .py that builds the scene (characters, props, environment, cameras, keyframes) and renders PNG sequence | new `apps/api/app/services/scene3d/blender_converter.py` | Generated script is deterministic from SceneScript. Uses bpy API. Frame rate 30 fps. Eevee for preview-quality, Cycles for final (config flag). |
| 2.3 | Low-poly asset library: named primitive compositions (`lowpoly_human`, `round_table`, `pillar`, `gable_roof`, `wall`, `lantern`, `floor`) parameterized by color and scale | new `apps/api/app/services/scene3d/assets/` (`__init__.py`, `characters.py`, `props.py`, `environment.py`) | Each asset is a function that takes bpy context + params and returns created object names. Shared by converter; frontend has parallel implementations (P3). |
| 2.4 | PNG sequence → MP4 encoding: reuse existing ffmpeg foundation (`app/tools/ffmpeg.py`, filter-graph compiler) | new `apps/api/app/services/scene3d/encoder.py` or extend existing composition renderer | H.264, yuv420p, crf 23. Round-trip test: encode → probe duration/frame count (engineering standard §3 round-trip + real binary). |
| 2.5 | Render API endpoints: `POST /scene3d/render` (accepts SceneScript, returns job id), `GET /scene3d/render/{job_id}` (status + artifacts: mp4 url, keyframe image urls) | new `apps/api/app/api/routes/scene3d.py` (or existing router pattern) | Async job: render is long-running; use existing async-job machinery (align with `poll_media_tasks` pattern). Artifacts stored via existing asset storage. |
| 2.6 | Keyframe extractor: per shot, extract exactly 5 frames at 0%, 25%, 50%, 75%, 100% of the shot duration as numbered images (`keyframe_00` through `keyframe_04`) | new `apps/api/app/services/scene3d/keyframes.py` | Used by P5 for video-model guidance. 5 frames is the fallback for providers that don't accept reference video (ADR 0005 §4a). Output as `keyframe_images` asset with per-shot frame lists. |
| 2.7 | Integration tests: `media`-marked test renders a small fixed SceneScript (2 shots, 30 frames each) with real Blender, asserts MP4 exists, duration ≈ expected, keyframe count correct | `apps/api/tests/test_scene3d_render.py` (`media` marker) | Real binary test (engineering standard §3). Skip gracefully if Blender unavailable (`unsupported` capability) but mark as skipped, not silently passing. |

**Acceptance:** `POST /scene3d/render` with a valid SceneScript produces an MP4 + keyframe images; render job status is queryable; Blender absence degrades to `unsupported` with a queryable marker; `media`-marked integration test passes where Blender is available; `ruff` + `pytest` pass.

---

## P3 — Frontend Scene3DNode + Three.js live preview

Goal: the `scene-3d` canvas node shows a live 3D preview of the SceneScript, with orbit controls and animation playback. No editing yet (that is P4).

| # | Task | Files | Notes |
| --- | --- | --- | --- |
| 3.1 | Scene3DNode canvas node component: node shell (header, ports, status) + 3D viewport area + playback controls (play/pause/seek/frame counter) | new `apps/web/src/features/agent-canvas/canvas/nodes/Scene3DNode/` (`Scene3DNode.tsx`, `Scene3DNode.css`, `index.ts`) | Follow existing `AgentCanvasNode` structure and node registry pattern. Node registers in the node picker. |
| 3.2 | Three.js renderer: `@react-three/fiber` + `@react-three/drei` Canvas; SceneScript → R3F scene graph (characters, props, environment, cameras) | new `apps/web/src/features/scene3d/renderer/` (`Scene3DCanvas.tsx`, `SceneScriptScene.tsx`, `useSceneScriptAnimation.ts`) | Install `three`, `@react-three/fiber`, `@react-three/drei` as web deps. Justify bundle growth (engineering standard §8 perf budget) or shrink elsewhere. |
| 3.3 | Frontend low-poly asset components: parallel implementations of P2's asset library (`LowPolyHuman`, `RoundTable`, `Pillar`, `GableRoof`, `Wall`, `Lantern`, `Floor`) as R3F components | new `apps/web/src/features/scene3d/assets/` | Must match backend asset geometry/scale so preview ≡ render. Shared param types from generated SceneScript TS types. |
| 3.4 | Animation playback: character keyframe interpolation (position, rotation_y, action), camera keyframe interpolation (position, look_at), shot-based camera switching | `useSceneScriptAnimation.ts` (frame clock + interpolators) | Linear interpolation for position/rotation; action enum drives optional micro-animation (e.g. `talk` → head bob, initially simple). Frame rate 30 fps. Playback scrubber. |
| 3.5 | OrbitControls + camera preview: user can orbit/zoom the 3D view independently of the SceneScript cameras; a toggle shows the active SceneScript camera's view | `Scene3DCanvas.tsx` | Drei `OrbitControls`. Active-camera-view toggle is a preview aid, not an edit (editing comes in P4). |
| 3.6 | Node data flow: node reads SceneScript from asset (via existing canvas data flow), passes to renderer; render-status indicator (backend render job state) | `Scene3DNode.tsx`, existing canvas runtime/hooks | "Render" button calls P2's render API; shows progress; on completion, offers MP4 playback + keyframe thumbnails. |
| 3.7 | Contract + quality checks: `check:agent-canvas-contract`, `check:quality`, bundle budget (`perf:bundle`) | `apps/web` | Engineering standard §1 web ladder. Bundle growth must be justified in the PR. |

**Acceptance:** a `scene-3d` node with a valid SceneScript shows a live 3D preview; playback animates characters and cameras, switching per shot; orbit controls work; "Render" triggers backend render and shows MP4/keyframes on completion; all web checks pass including bundle budget.

---

## P4 — Interactive editing + timeline + speech linkage

Goal: user can edit the 3D scene interactively (drag characters/cameras, edit properties), edit on a multi-track timeline, and link to the speech track (ADR 0003) for `bound`-mode timing.

| # | Task | Files | Notes |
| --- | --- | --- | --- |
| 4.1 | 3D transform editing: TransformControls for characters and cameras (drag to move, rotate); selected object highlight; gizmo mode toggle (translate/rotate) | `apps/web/src/features/scene3d/editor/` (`useTransformControls.ts`, `SelectionContext.tsx`) | Drei `TransformControls`. Editing writes back to SceneScript state (immutable update). |
| 4.2 | Property panel: selected object's properties (position x/y/z, rotation_y, action for characters; shot_type, position, look_at for cameras) editable via number inputs/selects | new `apps/web/src/features/scene3d/editor/PropertyPanel.tsx` | Two-way binding with SceneScript. Action enum from generated types. |
| 4.3 | Multi-track timeline: reuse `@xzdarcy/react-timeline-editor`; tracks: character action/position keyframes, camera keyframes, shot boundaries, speech clips (read-only linkage initially) | new `apps/web/src/features/scene3d/timeline/` (`Scene3DTimeline.tsx`, `trackBuilders.ts`) | Timeline is the editing surface for keyframe timing. Dragging a keyframe updates SceneScript. Playhead syncs with 3D viewport playback. |
| 4.4 | Speech-track linkage: when upstream `voice-cast` / `speech_audio` assets exist, show speech clips on the timeline; `bound` mode locks shot/character timing to speech durations (ADR 0003 `duration_mode`) | `Scene3DTimeline.tsx`, node data flow | `bound` mode: shot boundaries and character keyframe placement are derived from speech timing (editing speech updates 3D timeline, with user confirmation for downstream propagation — see ADR 0003 Appendix UI note). `free` mode: independent, with QA warning on mismatch. |
| 4.5 | Lip-sync (initial): audio-amplitude-driven head micro-motion for `talk` action; driven by the final mixed audio waveform (from speech track) | new `apps/web/src/features/scene3d/lipsync/` (`useAudioAmplitude.ts`, `HeadBob.tsx`) | Simple version: amplitude → head rotation_x micro-bob. Viseme-driven shape keys deferred (noted as future). Backend Blender render also applies the same amplitude-driven motion for consistency. |
| 4.6 | SceneScript → edit → SceneScript round-trip: all edits produce a new valid SceneScript; validators run on edit; invalid state shown inline (red highlight + message) | `apps/web/src/features/scene3d/` (validation hook) | Frontend validation mirrors P0 backend validators (shared logic or re-implemented in TS; must stay in sync — covered by contract test). |
| 4.7 | Undo/redo for edits: scene-level undo stack | new `apps/web/src/features/scene3d/editor/useSceneHistory.ts` | Snapshots of SceneScript state. Standard undo/redo keyboard shortcuts. |

**Acceptance:** user can drag characters/cameras in the 3D viewport and see SceneScript update; property panel edits reflect in 3D; timeline keyframes are draggable and sync with playback; speech clips appear when upstream voice-cast exists; `bound` mode locks timing; lip-sync head motion plays during `talk`; invalid edits are flagged; undo/redo works; all web checks pass.

---

## P5 — Geometric control signals + video-model integration

Goal: the 3D previs produces depth/normal/motion control passes and uses them (plus keyframes + prompts) to guide high-fidelity video generation. This is the final controllability闭环.

| # | Task | Files | Notes |
| --- | --- | --- | --- |
| 5.1 | Blender geometric render passes: depth (Z pass), normal (normal pass), optical flow / motion vectors (vector pass) rendered per keyframe | `apps/api/app/services/scene3d/blender_converter.py` (extend), new `apps/api/app/services/scene3d/control_passes.py` | Blender compositor or view-layer passes. Output as PNG/EXR per pass per keyframe. Eevee may not support all passes → Cycles for control-pass rendering (config flag, documented). |
| 5.2 | `control_signals` asset type: carries depth/normal/flow image refs per shot per keyframe | `apps/api/app/schemas/workflow_v2.py` | Asset refs are storage URLs. Optional — a render job may produce only color keyframes if passes are disabled. |
| 5.3 | Video-model provider layer extension: video-generation calls accept optional `control_signals` (array of {type: depth|normal|flow, image_ref, weight}) and `reference_input` ({mode: video|images|text, video_url?, image_urls[]?}) | `apps/api/app/services/v2_provider_executor.py`, `provider_model_catalog.py` | Provider-agnostic. Each provider declares which signal types and reference modes it accepts (capability fingerprint). Unsupported signals/modes are omitted with a queryable degradation marker (engineering standard §4). |
| 5.4 | Video prompt generator: SceneScript + shot description + character/prop descriptions → structured video-model prompt (shot framing, camera move, action, style). When reference mode is `images`, prompt explicitly notes "these 5 frames are keyframes of a continuous camera move; interpolate smoothly between them" | new `apps/api/app/services/scene3d/prompt_generator.py` | Pure function, unit-tested. Prompt includes camera movement in natural language (derived from camera keyframe delta). Style inherited from upstream style skill if present. |
| 5.5 | Video generation node integration: `video` node (or new `video-from-previs` node) consumes `scene_script` + `keyframe_images` + `control_signals` + generated prompt → calls video provider. **Reference fallback selector**: chooses input mode per provider — `video` (MP4 + control signals) → `video_only` (MP4) → `images` (5 keyframe images) → `text` (prompt only) | `apps/api/app/services/workflow_node_executor.py` (video branch), `workflow_node_catalog.py`, new `apps/api/app/services/scene3d/reference_fallback.py` | Reuse existing video-generation machinery; add previs-derived inputs. Fallback is deterministic based on provider capability fingerprint. Execution result carries `previs_control_level` marker (`full`/`video_only`/`images_only`/`text_only`) — queryable degradation, never silent (ADR 0005 §4a). |
| 5.6 | Provider capability fingerprinting: per-provider `control_signal_support: {depth: bool, normal: bool, flow: bool}` and `reference_support: {video: bool, images: bool, text: bool}` | `provider_model_catalog.py` | `ready/degraded/unsupported` pattern. A provider that accepts only color keyframes gets `degraded` for previs guidance. A provider that accepts nothing gets `text_only`. |
| 5.7 | QA registry checks: control-pass completeness (expected passes present for requested shots), prompt-generation sanity (non-empty, contains camera-move language), previs-vs-video duration alignment | `apps/api/app/services/v2_qa_registry.py` (new entries registered from `scene3d/` module) | Mutation-check tests per new registry entry (engineering standard §3). |
| 5.8 | Frontend: previs → video comparison view (side-by-side lowfi previs and generated video), per-shot | `apps/web/src/features/scene3d/` (`PrevisVideoCompare.tsx`) | User can verify the high-fidelity video matches the previs framing/camera move. Mismatch → regenerate with adjusted prompt (manual loop initially; automated plan-vs-actual verification deferred per ADR 0003 Appendix). |

**Acceptance:** a full workflow `scene-3d` → `video` produces a high-fidelity video guided by previs keyframes + control signals + generated prompt; providers that don't support control signals degrade gracefully with a queryable marker; QA registry checks run and block on failures; side-by-side comparison is available; all ladders pass.

---

## P6 — Shot template library + multi-aspect adaptation (ecosystem)

Goal: reduce the skill barrier — users can apply cinematic shot templates and auto-adapt to multiple aspect ratios. Can run in parallel after P3.

| # | Task | Files | Notes |
| --- | --- | --- | --- |
| 6.1 | Shot template definitions: named templates (dialogue-shot-reverse-shot, tracking-follow, emotional-push-in, revealing-pull-back, over-shoulder-conversation) as SceneScript partial transforms | new `apps/api/app/services/scene3d/templates/` (`__init__.py`, `definitions.py`, `transformer.py`) | A template takes a SceneScript + character ids + location and produces camera/shot additions or replacements. Pure functions, unit-tested. |
| 6.2 | Template application API: `POST /scene3d/templates/apply` (SceneScript + template id + params → new SceneScript) | `apps/api/app/api/routes/scene3d.py` (extend) | Validates output. Idempotent-ish: applying a template returns a new SceneScript, does not mutate input. |
| 6.3 | Multi-aspect auto-composition: given a SceneScript (default 16:9), produce 9:16 (vertical) and 1:1 (square) variants by adjusting camera FOV/position/framing | new `apps/api/app/services/scene3d/aspect_adapter.py` | Pure function. Strategy: vertical → narrower FOV + camera reposition to keep subjects centered; square → crop-safe framing. Unit tests with fixed SceneScripts. |
| 6.4 | Frontend template picker + aspect toggle: in Scene3DNode, a "Apply shot template" dropdown and an aspect-ratio toggle (16:9 / 9:16 / 1:1) that re-renders preview | `Scene3DNode.tsx`, new `TemplatePicker.tsx`, `AspectToggle.tsx` | Aspect toggle updates preview camera framing; render API accepts aspect param. |

**Acceptance:** at least 5 shot templates are defined and applicable; applying a template produces a valid SceneScript with expected camera/shot changes; aspect adapter produces 3 variants from one SceneScript; frontend template picker and aspect toggle work; all checks pass.

---

## Cross-cutting concerns (apply to every phase)

- **Contract sync:** any SceneScript schema change → regenerate TS types → `check:agent-canvas-contract`. Never hand-edit generated artifacts (engineering standard §2).
- **Test markers:** every test classified (`unit` / `media` / `integration` / `e2e` / `slow`). Unmarked tests are a defect (engineering standard §3).
- **Real binary:** render/encode tests use real Blender/ffmpeg, marked `media` (engineering standard §3).
- **Observable degradation:** Blender absence, control-signal unsupported, speech-track missing — all emit queryable events/markers, never silent (engineering standard §4).
- **Domain vocabulary:** use `SceneScript`, `previs`, `low-fidelity`, `blocking`, `shot`, `keyframe` consistently. New terms enter the glossary (engineering standard §5).
- **Security:** no provider keys in code/tests/fixtures. Blender needs no keys. Video-model provider keys via config center/env only (engineering standard §7).
- **Performance budget:** Three.js + drei is a significant frontend dependency addition. Justify bundle growth in the P3 PR or shrink elsewhere (engineering standard §8).
- **ADR conflicts:** if any phase's implementation contradicts ADR 0003 (speech track) or ADR 0005 (this ADR), surface it explicitly — do not silently override (engineering standard §6, domain.md).
