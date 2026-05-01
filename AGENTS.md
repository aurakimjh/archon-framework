# Project AI Instructions

## Shared Workspace Asset Repository

This project belongs to the workspace governed by `../AGENTS.md`.

The shared reusable asset repository is:

`../projects-assets`

Use `projects-assets` for reusable prompts, diagnostic rules, sanitized log samples, report templates, schemas, chart guidelines, reusable sentences, and architecture analysis assets.

## Archon Project Boundary

This project is the public Archon framework project.

It is intentionally paired with `../archon-private`, which stores Archon-specific private operations, prompts, registry, review, benchmark, and work-management assets.

Keep `../archon-private` separate from `../projects-assets`.

Do not move, merge, or replace `../archon-private` with `../projects-assets`.

Only sanitized and generalized reusable assets from Archon work should be copied or referenced in `../projects-assets`.

## Rules

1. Project-specific implementation details should remain in this project.
2. Reusable diagnostic knowledge should be stored in or referenced from `../projects-assets`.
3. When adding reusable prompts, rules, parser mappings, report templates, reusable sentences, or diagnostic checklists, update `../projects-assets/ASSET_INDEX.md`.
4. Do not store secrets, credentials, private keys, tokens, or unsanitized production logs.
5. Before major AI-assisted changes, read:
   - `../AGENTS.md`
   - `./AGENTS.md`
   - `../projects-assets/AGENTS.md`, if reusable assets are involved.
