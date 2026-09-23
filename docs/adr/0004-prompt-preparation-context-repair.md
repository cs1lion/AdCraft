# Prompt-preparation context repair: rebuild missing immutable snapshots from workflow state

## Context

Node writers that enqueue a prompt-preparation dispatch without a frozen
`StageAuthoringContextV1` snapshot (direct/legacy writers, reconcile
successors of a snapshot-less row) leave a row the bounded recovery worker
refuses to process: `prompt_preparation_context_missing` is not
retryable, so the row terminalizes on its first attempt and the managed
Node's assertion evidence can never be rebuilt.  A user mistake that
clears a managed Node's evidence therefore dead-ends the whole workflow
instead of recovering.

## Decisions

1. **Rebuild on demand, persist exactly once.** The production worker
   gains a `context_repairer` hook: when a claimed row has no snapshot,
   the repairer reconstructs one `StageAuthoringContextV1` from current
   workflow state (guidance session + requirement ledger + working
   document + style anchor, one canonical `internal_skill_ref` per role
   variant) and `repair_context_in_lease` freezes it onto the row under
   the owning lease.  Rows that already own a snapshot are never
   rewritten — the "frozen snapshot" invariant is preserved, not relaxed.

2. **Repaired rows keep their original dispatch identity.** The
   `logical_key`/`dispatch_id` pair is the deterministic identity of one
   preparation operation and was derived *without* a context digest; it
   stays untouched.  Only `context_json`/`context_digest` gain the
   rebuilt snapshot.  The dispatch schema's identity validator therefore
   accepts a non-None digest that is absent from the stored key
   (a repaired row) and still cross-checks every other identity field.

3. **Node writers now pass the context when they can.**
   `AgentCanvasNodeService.create`/`patch` (and the repository
   `add_node`/`add_node_with_bindings`/`update_node` seams) accept an
   optional authoring-context provider; when the workflow has a usable
   guidance session the dispatch row is born with its snapshot, so the
   repair path stays a repair path rather than the common path.

4. **Fail closed when no session exists.** A workflow without guidance
   state cannot be rebuilt without inventing authority, so the legacy
   `prompt_preparation_context_missing` terminal behavior is kept for
   that case.

## Consequences

- A managed Node whose evidence was cleared by a user mistake recovers
  through the ordinary worker loop: reconcile enqueues a successor →
  repairer freezes a snapshot → `prepare()` rebuilds the assertion
  evidence with the compiler.  No operator intervention is required.
- The repair emits one queryable event
  (`node_prompt_preparation_context_repaired`), satisfying the
  observable-degradation rule in the engineering standards.
- `internal_skill_ref` in a rebuilt context is deterministic per Node
  role (shared table with the materialization path), so a later
  materialization that names the context for the same stage still sees
  a byte-identical value for the same inputs.
