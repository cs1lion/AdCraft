# Director Command Bar: Intent-Level Motion for 3D Previs

## Status

Accepted (MVP shipped, 2026-09-28)

## Context

ADR 0005 introduced the 3D low-fidelity previs pipeline: SceneScript as the
canonical intermediate format, Three.js for the instant preview, and Blender
headless for the final render. The scene-3d workbench already ships a rich
authoring surface (drag, keyframe capture, gesture-drawn camera paths,
motion-preset inspectors), but every camera and character move the director
can express is **menu-shaped**: pick a target, pick a preset, pick a duration,
click apply. There is no continuous, language-shaped channel where the
director stands next to the monitor and the picture reacts to a sentence.

The user's request is that exact gap: a "director voice" — natural language
in, instant picture change out — covering scene building, camera language
(push-in, orbit, dolly zoom, handheld feel), and character motion (walk to,
turn to, approach). The request is explicitly low-fidelity: the goal is a
repeatable, previewable take, not a cinematic asset.

## Decision

Ship the MVP as a **deterministic intent layer** on top of the existing
ops gate, not as a free-form LLM script channel.

### 1. The director command is a small, typed intent

A command is `{ intent, target, preset, start_frame, duration_frames,
target_position? }` — one of the eight camera presets or four character
presets already shipped in `cameraMotionPresets.ts` /
`characterMotionPresets.ts`, addressed at one object at the playhead. The
intent is the unit the director names; the preset vocabulary is the unit the
gate understands.

### 2. The preset expands to ops in exactly one place on each side

- **Backend** `director_motion.py` owns the pure expansion (preset +
  anchor + duration → sampled `add_keyframe` ops). It is the server of
  record: the LLM and the web UI never hand-roll keyframe lists for a
  common move.
- **Frontend** `directorMotion.ts` reuses the same preset math
  (`cameraMotionPresets` / `characterMotionPresets`) for the optimistic
  preview, and emits the `request` body the backend endpoint accepts.
- The preset list is the **single source of truth** on each side; the
  expansion is deterministic and replayable. A command is a seed, not a
  free-form prompt: same command + same seed = same ops, which is what
  makes "rerun / A-B take / roll back" meaningful.

### 3. The backend owns the gate; the UI owns the preview

`POST /scene-3d/director-motion` validates the intent, expands it, then
runs the resulting ops through the existing all-or-nothing
`SceneScriptToolService` gate (the same gate `apply-operations` and the
white-model generator already use). A rejected command is a 400 with the
per-op violation — the UI keeps its optimistic preview and shows the
reason; a passed command returns the gate's post-apply script, which the
UI adopts as the new authoritative state. The preview and the persisted
state never drift: the gate is the single source of truth for "what is
legal", and the UI is the single source of truth for "what is happening
right now".

### 4. The command bar is the first visible surface

`DirectorCommandBar` (in the 3D editor) picks a target + a preset + a
duration, applies the expanded result optimistically through the editor's
existing `onChange` channel, then round-trips the gate. No new state
machine: the bar rides the editor's save/revert pipeline, and the editor's
inspector / gesture / drag surfaces keep working unchanged.

## Consequences

- **Predictable, replayable commands.** Every take the director cuts is a
  small ops diff that can be undone, re-run, or A/B'd against another
  preset. The "roll back to before he walked" is a one-click revert of a
  known batch.
- **Free-form language is a parser, not a new channel.** The intent shape
  is the seam a later NL layer plugs into: map a sentence to
  `{intent, target, preset, ...}` and the rest of the pipeline (expansion,
  gate, preview) is unchanged. The MVP is therefore a strict subset of the
  eventual feature, not a throwaway.
- **The gate is the contract.** Anything the director does — menu, bar,
  gesture, or (later) natural language — lands through
  `SceneScriptToolService`. The white-model generator, the 3D
  workbench, and the bar all share that one choke point; a new op kind or
  enum change is a one-line edit in the service and every channel
  inherits it.
- **Cost of the MVP.** One new backend module, one endpoint, one client,
  one bar, and the preset-list sync. No new asset pipeline, no Blender
  work, no LLM in the hot path. The deferred layers (NL parser, when/then
  triggers, LOD/asset tier, dialogue-as-performance) each land on the
  same seam and add no new channel.

## Non-Goals

- No free-form natural-language parsing in the MVP (curated preset
  vocabulary only; the `request` shape is the seam).
- No new asset / geometry pipeline (primitives + the existing enum
  vocabulary; "make the vending machine look real" is out of scope).
- No skeletal animation (character motion stays at the preset level:
  walk / turn / approach / talk, sampled keyframes, no rig).
- No multi-object scheduling in one command (a command is one object +
  one preset; "two people walk to the table at once" is two commands).
