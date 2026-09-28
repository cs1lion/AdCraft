# V2 Fallback + Trigger Seams

## Status

Accepted (2026-09-28)

## Context

ADR 0012 shipped the director command bar MVP: a curated preset
vocabulary expands locally for the optimistic preview and round-trips
through the backend's all-or-nothing ops gate. Two capabilities
discussed in that ADR's "Consequences" section were intentionally
deferred: (1) unknown object types emitted by the LLM or the director
bar reject the whole batch with `object_type_unsupported`, and
(2) when/then event triggers ("wait for him to sit, then cut to the
close-up") had no expressible form in the ops vocabulary.

## Decision

### 1. Nearest-primitive fallback table is the single source of truth

`app/services/scene3d/prop_type_fallback.py` owns a small,
conservative `dict[unknown_word, known_primitive]` table for props and
environments. The gate (`SceneScriptToolService._validate_operation`)
consults the table *before* rejecting an unknown type: when the
fallback resolves, the op is rewritten in place and a
`note_degradation` warning is recorded in the batch result; when it
does not, the rejection stands and the batch is all-or-nothing as
before. The frontend mirror
(`sceneScriptEditModel.ts` imports `propTypeFallback.ts`) applies the
same table to the optimistic add-prop / add-environment path so the
browser preview degrades identically to the gate.

A new entry in the table is a one-line dict update; no gate, schema,
or endpoint change. The table is code, not a prompt rule — the
white-model generator never needs to know it exists.

### 2. Trigger events are pure expansion into existing ops

`app/services/scene3d/trigger_events.py` owns a `CHARACTER_TRIGGERS`
vocabulary (sit / stand / arrive / face / line_spoken) and a
`THEN_OP_KINDS` allowlist (add_keyframe, set_camera, rotate_object,
scale_object, move_object — all already in the gate's `OP_KINDS`).
A trigger event expands into a deterministic ops batch that rides the
existing gate; no new op kind or schema field is introduced.

The endpoint `POST /scene-3d/trigger-event` validates the trigger,
expands it, runs the then-ops through the gate, and returns the
post-apply script. The frontend client `applyTriggerEvent` and the
`DirectorCommandBar` trigger row complete the loop.

### 3. The LLM still never emits free-form scripts

Both the fallback table and the trigger expansion are *deterministic
bridges*: the LLM emits `{trigger, trigger_target, then_ops, ...}`
or `{op: "add_prop", type: "vending_machine"}` and the pipeline
expands it. The same "seed → deterministic ops → gate" invariant from
ADR 0012 is preserved; replayability and A/B comparison still hold.

## Consequences

- Unknown object types no longer kill a batch; they degrade to the
  nearest primitive with a visible warning. The white-model fidelity
  contract ("there" beats "like") is now enforced in code.
- When/then triggers are expressible in the ops vocabulary and
  replayable through the gate. A new trigger word is one table
  entry; the gate and schema are unchanged.
- The frontend mirror (`propTypeFallback.ts`) and the backend table
  (`prop_type_fallback.py`) must be kept in sync; a new entry added
  on one side without the other is a silent divergence. The
  `propTypeFallback.test.ts` suite locks the table contents.

## Non-Goals

- No LLM-side awareness of the fallback table (it is a gate-level
  hard fallback, not a prompt-level soft rule).
- No new op kinds: trigger then-ops are a subset of the existing
  `OP_KINDS`.
- No LOD / asset-tier system (deferred to a future ADR).
