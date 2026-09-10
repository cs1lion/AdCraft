# apps/web — Frontend Bounded Context

`apps/web` is the React / Vite frontend that drives AdCraft. It owns the user-facing Agent Canvas, the asset library browser, project management, and the visual surfaces for guided authoring. The backend boundary is the FastAPI service in `apps/api`; this context never reads its tables directly.

## Language

**Project**:
A user-facing container for one advertisement. In the UI, the project list (`/pages/projects`) shows active / archived / trashed projects; opening a project surfaces its workflow.
_Avoid_: "Campaign" (a project is one ad; campaigns are not modelled here).

**Workflow**:
The editable, backend-authored production plan for a project. In the UI it appears as the Agent Canvas — a graph of nodes, slots, and items — and is always loaded from the backend's v2 boundary.
_Avoid_: "Pipeline", "plan".

**Node**:
A production step on the canvas (e.g. `script`, `product-generation`, `character-generation`, `scene-generation`, `bgm`, `storyboard`, `final-composition`, `free-generation`). Each node carries a status (`not_ready` / `ready` / `running` / `waiting` / `completed` / `partial_failed` / `failed`) and a position on the canvas.
_Avoid_: "Step", "task".

**Slot**:
A typed placeholder inside a node (e.g. `product_main_image`, `shot_cell_2`, `final_video`). Slots are the units that hold generated assets and reference asset library entries. They have a lifecycle mirroring the node's status.
_Avoid_: "Channel", "output", "asset slot".

**Asset Version**:
A specific point in an asset's evolution. The asset browser shows asset versions; "selected version" is the version the workflow currently consumes.
_Avoid_: "Revision" (a revision is the backend term for a workflow snapshot, not for an asset).

**Asset Library**:
The cross-project, persistent collection of approved assets, organised by type (Character, Scene, Product, Image, Video, Audio). Surfaces as the Asset Browser and the canonical-asset viewers.
_Avoid_: "Gallery", "stock".

**Reference**:
A pointer from a workflow object to a library or uploaded asset. References carry a mode (`asset_library`, `mention`, `upload`).
_Avoid_: "Mention" alone (a mention is one reference mode).

**Agent Canvas**:
The interactive, node-and-edge graph that is the primary authoring surface (`features/agent-canvas`). It hosts the connected authoring flow, node pickers, context menus, and media previews.
_Avoid_: "Workflow editor" (the canvas is a specific surface; the workflow is the underlying object).

**Guided Authoring**:
The conversational flow that walks a user through producing each step of a workflow (e.g. confirming a script, picking a storyboard variation). Surfaces as in-canvas chat panels and post-ready checkpoints.
_Avoid_: "Chatbot", "AI assistant" (those are implementation terms; guided authoring is a domain concept).

**Production Journey**:
The state machine a project moves through from initial conversation → guided authoring → materialization → execution → final composition. The UI surfaces only the parts the user controls.
_Avoid_: "Workflow journey" (a journey is *about* a workflow, not the workflow itself).

**Acceptance Test**:
A v2 production acceptance fixture the backend runs; the UI may surface a preflight result but does not run the test itself.
_Avoid_: "E2E test" (acceptance is contractual; e2e is a test category that may not match).

**Workspace**:
The top-level React tree provider that exposes the current project, agent canvas, and asset library state (`app/WorkspaceProvider.tsx`).
_Avoid_: "App" (workspace is the runtime state; "app" is the user-facing term we keep for the shell).

**Contact Sheet**:
A thumbnail grid of asset variants shown when the user is choosing between candidates. Implemented in `features/assets/AssetContactSheet.tsx`.
_Avoid_: "Carousel" (a carousel is one way to render a contact sheet).

**Hologram Stage**:
The animated, layered preview surface for recommended character/scene assets (`features/assets/HologramStage.tsx`, `HologramParticlesCanvas.tsx`). It's a visual idiom, not a domain concept.
_Avoid_: Calling it a "viewer" — `CanonicalAssetViewer` is the static counterpart.

**Health**:
A lightweight backend-availability signal surfaced through `app/HealthContext.ts` and used to gate UI features when the API is down.
_Avoid_: "Status", "liveness".

**Route Provider**:
A component that scopes a feature to a route (`app/routeProviders.test.tsx`, `app/WorkspaceRoute.tsx`). It's a wiring concept, not a domain concept.
_Avoid_: "Page" (a page is a route, not a provider).

## Out of scope

- The backend domain (workflow authoring, event store, slot scheduler, provider integrations) lives in `apps/api`. The UI consumes its public HTTP boundary only.
- The Node-based `apps/api/agent` runtime. From the UI's perspective it is invisible — every interactive AI behaviour goes through the Python FastAPI service.
- Server-side storage and persistence. The UI holds transient state in `collections/`, `storage/`, and React context; it never owns the source of truth.
- Editor / IDE concerns (lint, typecheck, build) — these are dev-time, not domain.
