# Roadmap

Plan of record: [CF2_ARCHITECTURE.md](CF2_ARCHITECTURE.md) and
[CF2_MIGRATION.md](CF2_MIGRATION.md). Historical Milestone 0–7 language
below is retained as ancestry; it is not the current execution plan.

## Priority (do not skip ahead)

| Pri | Outcome | Status |
| --- | --- | --- |
| **P0** | Closed loop: `crazy-admin run` keeps executing until COMPLETE / HUMAN / BUDGET | `done` |
| **P1** | Runnable output: install/build/start on the tool executor; observe runtime | `done` |
| **P2** | Convergence: remaining product gaps become the next objective | `done` (engine + module loop) |
| **P3** | MCP wraps the working engine (`start` / `status` / `continue` / `stop`) | `done` (engine) |
| **P4** | Coding-agent adapter; factory-owned assignment; specialized roles later | `done` (P4a–P4f); agentic control; Cursor/Codex deferred |
| **P5** | Broader product intelligence, dynamic teams, self-improving capabilities | `done` (P5-01 Director + P5b module loop); P5-02/P5-03 deferred |
| **L0** | Prompt compiler + default `stdlib-web` stack + preview | `done` (compiler, stack, HTTP preview, deltas); vite-react later |

Living checklists:

- [CF2_PHASE_TARGETS.md](CF2_PHASE_TARGETS.md) — phase acceptance
- [CF2_TASK_CHECKLIST.md](CF2_TASK_CHECKLIST.md) — task TODO

Inspect/assess/MCP from Slice A shipped alongside P0 as inventory.
P2 wires remaining-gap objectives into EXECUTE. P3 wraps that engine:
`start_mission` takes context + target in one call. P4a is the capable
implementation actuator: `context → Crazy Factory → runnable accepted
application` on `task_board_web`. P4c is the starting coding
plugins (Claude/OpenAI; skip when no API key). P4d compiles a
purpose-built execution assignment from evidence; executor `ok` is
not acceptance. P4e observes runtime every beat and feeds
`executor_result.json` into the next objective. Ollama is opt-in,
not the default. P5a is the Director: `crazy-admin brief` / MCP
`director_brief` names the next featured command. P5b is the nested
module loop: finish one module before opening the next. L0 compiles
a raw owner prompt into a specified seed on the default
`stdlib-web` stack ([CF2_WEB_STACK.md](CF2_WEB_STACK.md)).
Follow-up prompts on a specified product are conversational deltas.
Intelligence map: [CF2_INTELLIGENCE.md](CF2_INTELLIGENCE.md). MCP
surface: [CF2_MCP_SURFACE.md](CF2_MCP_SURFACE.md).

## Ancestry (documentation bootstrap → local apprentice)

The original milestones (docs OS, local apprentice, Ollama, cron, MCP
evaluation, oversight, multi-model, multi-project) were partially
realized as the execution kernel. MCP is no longer "evaluate later":
a stdio server exists. Multi-project isolation already exists.
Oversight/Codex/Cursor remain unbuilt as IDE adapters (P4-09).
