# apps/api — Backend Bounded Context

`apps/api` is the Python / FastAPI service that drives AdCraft. It exposes the agent-driven workflow runtime, the v2 authoring/event-store pipeline, asset libraries, and provider integrations for image / video / audio / BGM / final composition.

## Language

**Workflow**:
An end-to-end, editable production plan for one advertisement. Carries its own `workflow_schema_version`, items, slots, nodes, edges, and revisions.
_Avoid_: Pipeline, job, ad, project (a project is the user's surface around a workflow).

**Workflow v1 vs v2**:
`v1` is the legacy graph-based workflow runtime (nodes + parallel graph runner). `v2` is the current event-sourced authoring/runtime split (working version, revisions, execution service, slot scheduler). When a doc says "Workflow" without a prefix, it means the v2 shape.
_Avoid_: Mixing "workflow" with the file path `app/workflows/`; that module hosts shared v1/v2 helpers, not the canonical workflow.

**Project**:
The user-facing container around a single workflow. Owns its own `project_id`, status (active/archived/trashed), favourites, and cover asset. Many operations go through the project boundary even when the underlying object is the workflow.
_Avoid_: "Campaign" (a project is one ad's container, not a multi-ad campaign).

**Workflow Item**:
A typed product the workflow is producing (`product`, `character`, `scene`, `bgm`, `shot`, `free`, `final_composition`).
_Avoid_: "Asset" (assets are produced *from* items; items are the workflow's internal slots).

**Workflow Slot**:
A typed placeholder on a node that an item fills (e.g. `product_main_image`, `shot_cell_2`, `final_video`). A slot has a lifecycle (`empty` → `blocked` / `ready` → … → `completed` / `failed` / `skipped`).
_Avoid_: "Output", "channel", "asset slot".

**Workflow Node**:
A single production step in a workflow (`script`, `product-generation`, `character-generation`, `scene-generation`, `bgm`, `storyboard`, `final-composition`, `free-generation`). Has a node status and a node type; owns slots.
_Avoid_: "Step", "task" (a node is a unit of authoring; a task is a provider-side request).

**Asset**:
A concrete media artefact (image, video, audio, text) produced by or uploaded into a workflow. Identified by an `AssetVersion`; carries source (`upload` / `generated` / `imported` / `derived`), lineage, and references.
_Avoid_: "File" (assets are a domain concept, not a filesystem concept).

**Asset Version**:
A specific point in an asset's evolution; the canonical unit of "which generation of this asset is selected".
_Avoid_: "Revision" (a revision is for a workflow, an asset version is for an asset).

**Asset Library**:
The cross-project, persistent collection of approved assets. Organised by type (Character, Scene, Product, Image, Video, Audio). Each library entry is a reusable reference, not a workflow-local artefact.
_Avoid_: "Gallery", "stock".

**Reference**:
A pointer from one workflow object to an existing asset (library or local) that the runtime should reuse. References carry a mode (`asset_library`, `mention`, `upload`) and a resolution policy.
_Avoid_: "Mention" alone (a mention is one specific reference mode).

**Revision**:
A snapshot of a workflow at a point in time, identified by `revision_no` and `content_hash`, with a `change_source` (`create`, `migration`, `prompt_edit`, `structure_edit`, `reference_change`, `selected_version_change`, `script_confirm`, `timeline_edit`, `restore`, `execution_result`).
_Avoid_: "Version" (asset version ≠ workflow revision; different lifecycles).

**Working Version**:
The currently-edited state of a workflow. Working versions are mutated by authoring, then a new Revision is created when the change is accepted.
_Avoid_: "Draft" (a working version is canonical, not throwaway).

**Execution**:
The act of running a node's slots against providers. An execution produces events (in v2: into the event store) and ultimately an execution result that commits back to selected asset versions.
_Avoid_: "Job" (provider-side jobs are inside an execution, not the execution itself).

**Slot Scheduler**:
The v2 component that plans and dispatches slot executions in parallel, respecting dependencies and budgets.
_Avoid_: "Parallel runner" (v1's `parallel_graph_runner` is the legacy counterpart).

**Specialist Agent**:
A scoped agent role (e.g. `front_desk`, `script_writer`, `character_designer`, `storyboard_director`) with its own prompt contract and tool surface. V2 prompts are produced by the prompt contract adapter from a `SpecialistConfig`.
_Avoid_: "Agent" alone (every agent is a specialist; there is no generic "agent" surface).

**Capability**:
A named, contract-typed operation a specialist can perform (e.g. `script.generate`, `storyboard.detail`). Capabilities are published through a capability registry and dispatched via `capability_dispatch`.
_Avoid_: "Action", "command" (a command is a wrapper around one or more capabilities).

**Provider**:
An external model / media service (LLM, image, video, audio, BGM, composition). The provider layer normalises identity, credentials, capabilities, and result commits.
_Avoid_: "Vendor" (providers abstract over vendors).

**Front Desk**:
The agent service that first receives a user prompt, decides the production journey, and dispatches to specialists. Lives in `services/front_desk.py`.
_Avoid_: "Router" (a router is a lower-level primitive; the front desk is the user-facing entry).

**Production Journey**:
The state machine representing how a user request progresses from initial conversation → guided authoring → materialization → execution → final composition.
_Avoid_: "Workflow journey" (the journey is *about* a workflow, not the workflow itself).

**Guided Interaction**:
A conversational turn the user takes through a guided authoring step (e.g. confirming a script, accepting a generated character, picking a storyboard variation). Persisted as a guided interaction event.
_Avoid_: "Prompt" (a guided interaction has a fixed shape and a recorded outcome).

**Materialization**:
The act of turning a working version + references into concrete provider inputs and outputs. The materialization plan and materialization commit bookend the execution.
_Avoid_: "Rendering" (rendering is final composition, not materialization).

**Final Composition**:
The last node of a workflow. Assembles video, subtitles, BGM, and product assets into the finished ad.
_Avoid_: "Editing" (video editing is a sub-step; final composition is the published artefact).

**Acceptance Test**:
A v2 production acceptance fixture/validator pair that gates a release. Lives in `services/v2_production_acceptance_*`.
_Avoid_: "E2E" (acceptance is the contractual surface; e2e is a test category that may or may not match an acceptance test).

**Content Kind**:
The top-level declaration of what a workflow produces: `ad` or `short_film`. The single switch every advertising-specific rule must consult (ADR 0002). Decides the duration cap, whether `product_main_image` is required, the default node chain, and which branch of the specialist skill contracts applies.
_Avoid_: "Genre" (content kind is a production-mode switch, not a creative genre), "Template" (it is not a preset workflow).

**Voice Cast**:
The node type (planned, ADR 0003) that assigns voices to characters/dialogue lines and produces speech audio via a TTS provider. Its output is `speech_audio`.
_Avoid_: "TTS Node" (TTS is the provider action; voice cast is the authoring step that binds voices to lines).

**Speech Audio**:
An asset type (planned, ADR 0003) carrying one dialogue line's spoken audio plus its text, voice id, measured duration, loudness, and `duration_mode`. Produced by the voice-cast execution, consumed by final composition.
_Avoid_: "BGM" (music bed, separate track), "Narration Asset" (narration is a usage, not the type).

**Duration Mode**:
`bound` or `free` on shot dialogue (planned, ADR 0003). `bound`: the TTS-measured duration drives the shot's timing. `free`: the speech track is arranged independently of shot timing.
_Avoid_: "Timing Mode" (the settled term is duration mode).

**QA Registry**:
The ordered registry of automated pre-commit checks (planned, ADR 0003) that runs before an execution result commits back to selected asset versions. Phase-1 checks are pure ffmpeg probes. A check returns pass/warn/fail with a structured reason; fail blocks the commit.
_Avoid_: "Review" (media_review is the human gate; the QA registry is machine-side), "Validator" (prompt-contract validators run before dispatch, the QA registry runs on results).

**Stateful Storyboard**:
Recorded, unscheduled concept (ADR 0003 appendix, from project B): a storyboard whose shots carry a mutable-state layer (positions, holders, door states), explicit shot-relation enums, and plan-vs-actual verification of scripted end-states against generated frames.
_Avoid_: promoting it to a planned feature — it is explicitly not scheduled.

## Out of scope

- The frontend (Agent Canvas, asset browser, project list, designer shells) lives in `apps/web`.
- The standalone `apps/api/agent` (Node / TypeScript) is the v2 *client* of this Python service: it runs the pi-coding-agent runtime against the FastAPI HTTP boundary. From this context's perspective it is a downstream caller, not part of the bounded context.
- Provider-specific SDKs and credentials. The provider layer normalises them; do not import vendor names into domain code.
- File-system and storage backends. The persistence layer (`app/persistence/`) abstracts these; the context only sees asset versions and revisions.
