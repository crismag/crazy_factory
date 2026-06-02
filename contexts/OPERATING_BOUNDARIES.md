# Operating Boundaries

## Factory And Workbench Separation

`factory/` and the supporting engine directories are the stable-ish operating
system. `apps/<name>/` is the application workbench. Workers may evolve an
approved app workbench but should rarely change the engine.

## Phase 2 Permissions

Allowed:

- read configuration, contexts, task files, reports, and repository metadata
- produce dry-run reports
- inspect git status and diff summaries
- call the local Architect model for planning-only task expansion
- call the local Planner model for one planning-only next action
- update `TASK_EXPANSION.md` and `NEXT_ACTION.md`
- update approved reports and JSON state snapshots

Not allowed:

- modify application code
- edit arbitrary files
- activate cron
- commit or push automatically
- read files outside the repository
- read likely secrets or credentials
- integrate MCP, LangGraph, n8n, Claude, or Codex
- call Coder, Test Builder, or Reviewer models

## Future Gated Capabilities

Continuous scheduling, automatic checkpoint commits, and automatic milestone
merges are future capabilities. They require explicit owner approval, safety
controls, review gates, and recovery validation before activation.

See `factory/governance/` for the durable authority model.
