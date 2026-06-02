# Operating Boundaries

## Factory And Workbench Separation

`factory/` and the supporting engine directories are the stable-ish operating
system. `apps/<name>/` is the application workbench. Workers may evolve an
approved app workbench but should rarely change the engine.

## Phase 1 Permissions

Allowed:

- read configuration, contexts, task files, reports, and repository metadata
- produce dry-run reports
- inspect git status and diff summaries
- build prompts without calling models

Not allowed:

- modify application code
- edit arbitrary files
- activate cron
- commit or push automatically
- read files outside the repository
- read likely secrets or credentials
- integrate MCP, LangGraph, n8n, Claude, or Codex

See `factory/governance/` for the durable authority model.
