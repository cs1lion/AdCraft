# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT-MAP.md`** at the repo root: it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`** for cross-cutting decisions.
- Per-context ADRs: `apps/<context>/docs/adr/`.

If any of these files don't exist, proceed silently. Don't flag their absence or suggest creating them upfront. The `/domain-modeling` skill creates them lazily when terms or decisions are resolved.

## File structure

This is a multi-context repo:

```text
/
├── CONTEXT-MAP.md
├── docs/adr/                     # system-wide decisions
├── apps/
│   ├── api/                      # backend context
│   │   ├── CONTEXT.md
│   │   └── docs/adr/             # backend decisions
│   └── web/                      # frontend context
│       ├── CONTEXT.md
│       └── docs/adr/             # frontend decisions
└── compose.yaml
```

## Use the glossary's vocabulary

When your output names a domain concept, use the term as defined in the relevant `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, note it for `/domain-modeling`.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding it.
