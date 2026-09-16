# Roadmap

Plan of record: [CF2_ARCHITECTURE.md](CF2_ARCHITECTURE.md) and
[CF2_MIGRATION.md](CF2_MIGRATION.md). Historical Milestone 0–7 language
below is retained as ancestry; it is not the current execution plan.

## Priority (do not skip ahead)

| Pri | Outcome | Status |
| --- | --- | --- |
| **P0** | Closed loop: `crazy-admin run` keeps executing until COMPLETE / HUMAN / BUDGET | `done` |
| **P1** | Runnable output: install/build/start on the tool executor; observe runtime | `done` (observer; live seed needs P4) |
| **P2** | Convergence: remaining product gaps become the next objective | `done` (engine) |
| **P3** | MCP wraps the working engine (`start` / `status` / `continue` / `stop`) | `done` (engine) |
| **P4** (current) | Coding-agent adapter; specialized roles only where they improve completion | `active` |
| **P5** | Broader product intelligence, dynamic teams, self-improving capabilities | `deferred` |

Living checklists:

- [CF2_PHASE_TARGETS.md](CF2_PHASE_TARGETS.md) — phase acceptance
- [CF2_TASK_CHECKLIST.md](CF2_TASK_CHECKLIST.md) — task TODO

Inspect/assess/MCP from Slice A shipped alongside P0 as inventory.
P2 wires remaining-gap objectives into EXECUTE. P3 wraps that engine:
`start_mission` takes context + target in one call. Next is a
coding-agent adapter (P4) for live builds.

## Ancestry (documentation bootstrap → local apprentice)

The original milestones (docs OS, local apprentice, Ollama, cron, MCP
evaluation, oversight, multi-model, multi-project) were partially
realized as the execution kernel. MCP is no longer "evaluate later":
a stdio server exists. Multi-project isolation already exists.
Oversight/Codex/Claude remain unbuilt as providers (P4).
