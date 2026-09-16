# Roadmap

Plan of record: [CF2_ARCHITECTURE.md](CF2_ARCHITECTURE.md) and
[CF2_MIGRATION.md](CF2_MIGRATION.md). Historical Milestone 0–7 language
below is retained as ancestry; it is not the current execution plan.

## Priority (do not skip ahead)

| Pri | Outcome |
| --- | --- |
| **P0** (current) | Closed loop: `crazy-admin run` keeps executing until COMPLETE / HUMAN / BUDGET |
| **P1** | Runnable output: install/build/start on the tool executor; observe runtime |
| **P2** | Convergence: remaining product gaps become the next objective |
| **P3** | MCP wraps the working engine (`start` / `status` / `continue` / `stop`) |
| **P4** | Coding-agent adapter; specialized roles only where they improve completion |
| **P5** | Broader product intelligence, dynamic teams, self-improving capabilities |

Inspect/assess/MCP from Slice A shipped alongside P0 as inventory. They
must not become the development focus while P0/P1 remain unfinished.

## Ancestry (documentation bootstrap → local apprentice)

The original milestones (docs OS, local apprentice, Ollama, cron, MCP
evaluation, oversight, multi-model, multi-project) were partially
realized as the execution kernel. MCP is no longer "evaluate later":
a stdio server exists. Multi-project isolation already exists.
Oversight/Codex/Claude remain unbuilt as providers (P4).
