---
name: add-portal
description: >
  Scaffolds and tests a new job portal search CLI skill under .agents/skills/
  with deterministic query handling and schema normalization. Triggers on /add-portal.
---

# /add-portal - Add Job Portal Skill

Guides the creation and integration of a new job board search CLI under `.agents/skills/<portal-name>-search/`.

---

## Workflow

1. Research target job portal API or public search interface.
2. Scaffold portal skill directory:
   - `SKILL.md` with portal metadata
   - `cli/src/cli.ts` implementing `search` and `detail` subcommands
   - `package.json` with dependencies
3. Test search and detail commands using `bun run`.
4. Register portal in search query workflows.
