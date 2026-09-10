# CONTEXT-MAP

This repository has more than one bounded context. Each context owns its own `CONTEXT.md` and `docs/adr/`.

- `apps/api/` — backend (Python / FastAPI / multi-agent runtime). See `apps/api/CONTEXT.md`.
- `apps/web/` — frontend (React / Vite / Agent Canvas). See `apps/web/CONTEXT.md`.

`docs/adr/` at the repo root holds decisions that cross both contexts (deployment, monorepo conventions, shared contracts).
