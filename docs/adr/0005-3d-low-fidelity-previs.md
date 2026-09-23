# 3D Low-fidelity Previs for Controllable Video Production

## Context

AdCraft's current storyboard-to-video path relies on text-driven image/video generation. Shot composition, camera movement, character blocking, and spatial consistency are expressed through natural-language prompts and are therefore non-deterministic: regenerating a shot can change the camera angle, character positions drift between shots, and complex camera moves (push-in, tracking, orbit) are unreliable.

Marketing and short-film production (ADR 0002 `content_kind: short_film`) increasingly requires cinematographic control — precise shot framing, repeatable camera moves, and spatial continuity across cuts. The film/games industry solves this with **previsualization (previs)**: low-fidelity 3D scenes that lock down blocking, camera, and timing before expensive high-fidelity rendering.

This ADR introduces a 3D low-fidelity previs capability into AdCraft: a user describes a scene in natural language, the system produces a structured 3D scene description, renders a low-fidelity animated reference, and uses that reference (keyframes + geometric control signals + prompts) to guide high-fidelity video generation.

**Relationship to existing work:**
- ADR 0003 (dialogue/speech track) already defines `duration_mode: bound | free` and a `speech_audio` asset. The previs timeline consumes the speech track's timing in `bound` mode and aligns character action/lip-sync to it.
- ADR 0003 Appendix (P5 stateful storyboard) records a three-layer separation (fixed setup / mutable state / cinematography) and plan-vs-actual verification. This ADR's SceneScript is the concrete carrier for that mutable-state + cinematography layer; P5's storyboard-state ideas are re-evaluated here rather than imported wholesale.
- Existing `storyboard` node produces 2D shot descriptions. The 3D previs is a **new node type**, not a replacement; a workflow may use either or both.

## Decisions

### 1. SceneScript as the canonical intermediate format

A structured JSON description — `SceneScript` — is the single source of truth between the LLM parser, the frontend 3D preview, the backend Blender renderer, and the video-prompt generator. It is not a prompt; it is a validated domain object.

Top-level sections:
- `scene`: name, environment kind, lighting preset, total duration
- `characters`: id, type (low-poly human initially), appearance, keyframes (position, rotation_y, action enum)
- `props`: id, type, position, scale
- `environment_objects`: walls, pillars, floors, roofs
- `cameras`: id, shot_type enum, keyframes (position, look_at target)
- `shots`: id, camera ref, start_frame, end_frame, description
- `speech_bindings` (optional): character id → speech_audio asset ref, for `bound`-mode timing alignment

SceneScript is defined as Pydantic models in `apps/api/app/schemas/scene_script.py` and regenerated into TypeScript for the web via the existing contract-sync pipeline. Hand-editing generated types is forbidden (engineering standard §2).

**Rationale:** a shared validated format lets each layer evolve independently — the LLM parser can improve without touching the renderer, and the frontend preview can add interactivity without changing the backend.

### 2. Dual-engine rendering: Three.js preview + Blender headless final

Two renderers consume SceneScript, each with a distinct job:

| Engine | Role | Quality | Latency | Deploy |
| --- | --- | --- | --- | --- |
| Three.js (@react-three/fiber) in the web canvas node | Real-time interactive preview, editing, playback | Low-fidelity (intentional) | Immediate | Browser |
| Blender 5.x headless (`--background --python`) | Final low-fidelity render: PNG sequences, MP4, geometric control passes (depth/normal/optical-flow) | Higher (Eevee for preview, Cycles for final) | Seconds–minutes per shot | Backend worker, Blender in container |

The frontend never calls Blender directly. It renders SceneScript in Three.js for live feedback. When the user confirms or requests a render, the backend renders with Blender and returns the asset.

**Rationale:** Three.js gives the interactivity a canvas node needs; Blender gives the render-pass flexibility (depth, normal, motion vectors) that pure browser rendering cannot easily produce. Both consume the same SceneScript, so preview and final are consistent by construction.

### 3. New node type `scene-3d`, not a modification of `storyboard`

A new workflow node type `scene-3d` (category `visual_planning`) is added to the node catalog. It carries:
- Input slot: natural-language scene description (or upstream script/character/scene assets)
- Output slot: `scene_script` asset (the validated JSON), plus rendered `lowfi_animation` asset (MP4) and `keyframe_images` asset

The existing `storyboard` node remains untouched. A `short_film` workflow may chain `storyboard` → `scene-3d` → `video`, or use `scene-3d` standalone.

**Rationale:** separating the node avoids coupling 2D storyboard semantics to 3D previs and keeps each node's contract small. Users who don't need 3D control are unaffected.

### 4. Geometric control signals for video-model guidance

The Blender renderer produces, per shot, not only the color keyframe but also optional geometric passes:
- **Depth map** — per-pixel camera-space distance
- **Normal map** — per-pixel surface orientation
- **Optical flow / motion vectors** — per-pixel 2D displacement between frames

These are delivered alongside the color keyframe and the generated prompt to the video model as control references (analogous to ControlNet conditioning). The video-model provider layer abstracts which signals a given provider accepts; unsupported passes are omitted with a queryable degradation marker (engineering standard §4).

**Rationale:** this is the core controllability advantage of 3D previs over text-to-video. A color reference alone leaves spatial structure to the model's imagination; depth/normal/motion signals lock it down.

### 4a. Video-model reference fallback: 5 keyframe images when reference video is unsupported

Not all video models accept a reference video or motion-vector input. When a provider cannot consume the low-fidelity animation MP4 or geometric control passes, the system falls back to **5 keyframe images per shot** as visual reference.

Fallback hierarchy (per provider, determined by capability fingerprinting):

| Provider capability | Reference input | Quality of control |
| --- | --- | --- |
| Reference video + control signals | MP4 + depth/normal/flow + prompt | Highest — full motion + geometry |
| Reference video only | MP4 + prompt | High — motion preserved, geometry approximate |
| Reference images only (first frame / multi-frame) | 5 keyframe images + prompt | Medium — composition preserved, motion interpolated by model |
| Text only | Prompt only | Lowest — no spatial guarantee |

The 5 keyframe images are extracted per shot at: frame 0 (start), 25%, 50% (mid), 75%, and last frame. They are delivered as a numbered image sequence with the shot description as context. The prompt generator explicitly notes "these 5 frames are keyframes of a continuous camera move; interpolate smoothly between them" to guide the model's motion synthesis.

This fallback is a **queryable degradation** (engineering standard §4): when a provider falls to image-only or text-only, the execution result carries a `previs_control_level` marker (`full` / `video_only` / `images_only` / `text_only`) so the user knows how much control was actually applied. No silent degradation.

**Rationale:** 3D previs's value is controllability. Even when a model can't consume the full animation, 5 well-chosen keyframes preserve composition, character positions, and camera trajectory far better than text alone. The fallback ensures the feature works with every video provider, not only those with reference-video support.

### 5. Speech-track alignment via `duration_mode`

When a `scene-3d` node is downstream of a `voice-cast` node (ADR 0003):
- `bound` mode: the speech track's measured durations drive shot timing and character keyframe placement. The SceneScript `shots` and character `keyframes` are generated to fit the speech timeline; lip-sync (head micro-motion initially, viseme-driven shape keys later) is driven by the final mixed audio.
- `free` mode: the 3D timeline is independent; speech is overlaid in final composition, and the QA registry warns on speech-vs-shot duration mismatches.

This reuses ADR 0003's `duration_mode` semantics without introducing a second timing system.

### 6. Low-poly asset library, procedurally composed

Initial characters and props are composed from primitive geometry (cubes, spheres, cylinders, cones) — the same approach validated in the Blender prototype. A `scene3d_assets` module provides named presets (`lowpoly_human`, `round_table`, `pillar`, `gable_roof`, `lantern`) parameterized by color and scale. Assets are referenced by id in SceneScript, not inlined.

**Rationale:** primitives keep the asset surface small, deterministic, and fast to render in both Three.js and Blender. Higher-fidelity assets can be added later without changing the SceneScript schema (asset id is an indirection).

### 7. Plan-vs-actual verification in the QA registry

The QA registry (introduced in ADR 0003 §5) gains 3D-previs checks:
- SceneScript validity (schema validation, no overlapping shot ranges, camera keyframes within shot bounds)
- Render completeness (every shot has at least one keyframe; expected frame count matches)
- `bound`-mode speech-vs-shot duration alignment (reuses ADR 0003's check pattern)
- Geometric-pass availability (warn, not fail, when a provider cannot consume a produced pass)

Failures block execution-result commit; warnings emit queryable events. This is the concrete realization of ADR 0003 Appendix's "plan-vs-actual dual track."

## Withdrawn candidates (recorded honestly)

- **Text-only shot descriptions with enhanced prompting.** Rejected: cannot guarantee spatial consistency or repeatable camera moves; the core problem is determinism, not prompt quality.
- **Frontend-only 3D (Three.js preview, no Blender).** Rejected: cannot produce depth/normal/motion control passes or render-quality MP4; the video-model guidance would be limited to color keyframes.
- **Importing an external previs tool (e.g. Blender Studio, Unreal) as a service.** Rejected: violates the native-fusion principle (ADR 0003 §1); adds a heavy dependency and a second UI paradigm. Blender is used only as a headless renderer, invisible to the user.
- **Replacing the `storyboard` node with 3D previs.** Rejected: 2D storyboard remains the right tool for many ad workflows; 3D previs is an additional capability, not a migration target.
- **NeRF / 3D Gaussian Splatting for scene reconstruction.** Deferred: promising for lowering scene-creation cost, but requires a separate research track and is not needed for the initial controllability goal. Recorded as a possible P6+ extension.

## Provider layer support

- **Blender runtime:** pinned version (5.x LTS) in the backend worker container; render calls go through a `BlenderRenderer` service (`apps/api/app/services/scene3d/blender_renderer.py`) that manages subprocess invocation, timeout, and artifact collection. No vendor keys required.
- **Video model providers:** the existing provider layer (`v2_provider_executor.py`, `provider_model_catalog.py`) is extended to accept optional `control_signals` (depth/normal/flow image refs) on video-generation calls. Providers that do not support control signals ignore them; the capability is fingerprinted per provider (`ready/degraded/unsupported`, matching the existing ffmpeg capability pattern).
- **TTS / speech:** reused from ADR 0003; no new provider.
- **LLM for SceneScript generation:** reused from the existing agent runtime; the `video_agent_3d_storyboard` skill defines the prompt contract. No new model provider.

Credentials never enter the repository (engineering standard §7).

## Appendix: SceneScript schema sketch (reference, not the source of truth)

The authoritative schema lives in `apps/api/app/schemas/scene_script.py`. This sketch is for readability only:

```json
{
  "scene": { "name": "teahouse-dialogue", "environment": "indoor", "lighting": "warm", "duration": 10.0 },
  "characters": [
    {
      "id": "char1", "type": "lowpoly_human", "appearance": { "color": "#8B4513" },
      "keyframes": [
        { "frame": 0, "position": [0.9, -0.9, 0], "rotation_y": 150, "action": "stand" },
        { "frame": 120, "position": [0.9, -0.9, 0], "rotation_y": -30, "action": "talk" }
      ]
    }
  ],
  "props": [{ "id": "table1", "type": "round_table", "position": [0, -1.6, 0], "scale": 1.0 }],
  "environment": [
    { "id": "wall1", "type": "wall", "position": [0, -7, 2.5] },
    { "id": "pillar1", "type": "pillar", "position": [-3.5, -6.7, 2.1] }
  ],
  "cameras": [
    {
      "id": "cam1", "shot_type": "wide",
      "keyframes": [
        { "frame": 0, "position": [12, -14, 8], "look_at": [0, -1.5, 1.3] },
        { "frame": 60, "position": [8.5, -10, 6], "look_at": [0, -1.5, 1.3] }
      ]
    }
  ],
  "shots": [
    { "id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 60, "description": "wide establishing" }
  ],
  "speech_bindings": [{ "character": "char1", "speech_asset": "speech_audio:abc123", "mode": "bound" }]
}
```

Coordinate convention: Blender right-handed Z-up, meters. Frame rate default 30 fps. `rotation_y` is in degrees for LLM friendliness, normalized to radians internally.
