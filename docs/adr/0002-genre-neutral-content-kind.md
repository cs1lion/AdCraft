# Genre-neutral content kind (de-specializing the ad workflow core)

## Context

We are fusing the dialogue-production ideas of the piagent-glm "video-agent" project (project B) into AdCraft, with the agreed goal of supporting genre-neutral short films (`short_film`) alongside ads. An audit of this codebase found advertising assumptions hard-coded at three levels.

Hard limits (schema / validation enforced):

| Location | Constraint | Effect on short films |
| --- | --- | --- |
| `apps/api/app/schemas/ad_workflow.py:31` | `duration_seconds: ge=15, le=60` | 1–3 minute shorts cannot be declared |
| `apps/api/app/services/v2_production_acceptance_validator.py:445` (also `v2_generation_pipeline.py:2723`, `v2_parallel_slot_scheduler.py:17`) | `product_main_image` is a required main slot in the acceptance chain | A film without a product fails acceptance |
| `apps/api/app/schemas/agent_canvas_draft_seeds.py:165` | BGM seeds hard-code `instrumental_only: True, no_vocals: True` | Vocal theme songs are impossible |
| `apps/api/app/services/workflow_node_catalog.py` | `product-generation` sits in the default node chain | Product-less workflows inherit a product node |

Soft limits (prompt / skill level; they bias generation rather than reject it):

- Specialist skills assume an advertising frame: script must "connect product value to audience motivation" (`video_agent_script_authoring/SKILL.md`), world settings carry "campaign relevance" (`video_agent_world_setting/SKILL.md`), props must fit "a short advertisement" (`video_agent_prop_design/SKILL.md`), characters serve "the advertising concept" (`video_agent_character_design/SKILL.md`).
- The Node agent's base policy self-identifies as "the sole production Agent identity for video advertising cognition" (`apps/api/agent/src/prompts/agents.ts:2`).
- `ad_workflow.py` defaults (`campaign_goal`, `desired_emotion`) are advertising semantics.

Already neutral (no change needed): the 15-second sequence window is a provider generation-window constraint, and the 3x3 grid, shot-cell prompt contracts, asset libraries, guided gates, and the `free_*` item family are content-agnostic.

## Decision

1. Introduce a top-level **`content_kind: ad | short_film`** declaration on the workflow. It is the single switch every advertising-specific rule must consult.
2. Parameterize the total duration cap: `ad` keeps 15–60s; `short_film` raises it (configurable setting, default 300s). The per-sequence 15s generation window is unchanged.
3. Make `product_main_image` optional when `content_kind = short_film`. The journey already models product exclusion (`product_excluded` exists in the `JourneyTransitionEvidenceV2` evidence kinds); the acceptance chain must honor it instead of failing. `short_film` gets a default node chain without `product-generation`.
4. Branch the specialist skill contracts on `content_kind`: the `short_film` branch drops product-narrative clauses and adopts the dialogue-authoring rules proven in project B (quantified line length ≈ 4 characters/second for Chinese; no stage directions in audience-facing dialogue; sanitized speech text).
5. Un-hardcode BGM `instrumental_only` / `no_vocals` (seed defaults remain for `ad`).

## What we deliberately did not take from B

B's creative upstream (a script stage; no character/scene asset system) is strictly weaker than AdCraft's identity-master + turnaround, scene board + multi-view, and world-setting machinery. Cross-pollinating it would be a regression. Only B's text-level dialogue constraints are adopted, into the branched skill contracts.

## Consequences

- Every new advertising-only rule must route through `content_kind`; adding one without a kind guard is a review-blocking defect.
- Production acceptance fixtures need a `short_film` variant.
- Work package P1 (speech track, ADR 0003) builds on this and authors its skill contracts dual-branch from day one.