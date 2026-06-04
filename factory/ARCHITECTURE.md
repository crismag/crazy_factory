# Architecture

## Status

This document defines the conceptual architecture for Crazy Factory planning and
guarded execution. Runtime details live in `scripts/`, `bin/`, `config/`, and
`docs/USAGE.md`; this file describes the intended system shape and boundaries.

## System Shape

Crazy Factory is a local-first autonomous development system organized around bounded sessions, specialized workers, durable memory, explicit governance, and observable lifecycle transitions.

## Conceptual Components

| Component | Responsibility |
| --- | --- |
| Session Coordinator | Start a bounded work session, identify mode, and advance lifecycle phases |
| Context Loader | Gather approved project context and relevant memory |
| Worker Layer | Apply Architect, Planner, Coder, Test Builder, Reviewer, and Reporter responsibilities |
| Task Registry | Track backlog items, planned tasks, active work, completion, and blockers |
| Memory Store | Preserve project, decision, architectural, task, failure, and success memory |
| Governance Gate | Check allowed actions, approvals, restricted operations, and stop conditions |
| Repository Adapter | Provide controlled local repository inspection and approved git operations |
| Reporting Layer | Produce session reports, next actions, and audit-friendly summaries |
| Model Adapter | Future boundary for Ollama and local model access |
| Oversight Adapter | Future boundary for optional MCP, Codex, Claude, and multi-model review |
| Scheduler Adapter | Future boundary for cron or equivalent periodic operation |
| State Store | Preserve current project, milestone, checkpoint, task, failures, and recovery instructions across interruption |
| Watcher | Observe progress, failures, stalls, reports, and resume state without modifying application code |

## Core Boundaries

- Project data remains local by default.
- External access is optional, explicit, and approval-gated.
- Worker roles operate through shared governance rather than direct unrestricted tool access.
- Memory files distinguish durable facts from proposals and transient observations.
- Repository operations are classified as allowed, restricted, or forbidden.
- Multi-project support must isolate context, memory, permissions, and reporting.
- Persistent missions must survive reboot, crash, pause, and manual stop through
  file-based state rather than transient model context.

## Mission State Architecture

Project runtime state lives inside each workbench, typically under
`<app_path>/state/`. Legacy root-level state may still exist for migration, but
new project-specific state should remain project-local:

| File | Purpose |
| --- | --- |
| `<app_path>/state/factory_state.json` | Mode, targeted project identity, capability-derived status, failure counters, and recovery guidance |
| `<app_path>/state/active_run.json` | Current phase, task, checkpoint, blocker, and immediate resume point |
| `<app_path>/state/project_state.json` | Project milestone, satisfaction status, checkpoint history pointer, and project recovery instructions |

Each application also maintains a `MASTER_CHECKLIST.md`, milestones, checkpoint
history, and satisfaction report. The checklist is the application-level source
of truth for incomplete work.

## Memory Architecture

The memory system preserves:

| Memory type | Purpose | Canonical location |
| --- | --- | --- |
| Project memory | Narrative state and active direction | [context/PROJECT_MEMORY.md](context/PROJECT_MEMORY.md) |
| Decision memory | Accepted decisions and rationale | [DECISION_LOG.md](DECISION_LOG.md), [context/DECISIONS.md](context/DECISIONS.md) |
| Architectural memory | Boundaries and proposals | This document and architecture decision records |
| Task memory | Backlog and planned work | [BACKLOG.md](BACKLOG.md), task records |
| Failure memory | Failed approaches and recovery notes | [context/PROJECT_MEMORY.md](context/PROJECT_MEMORY.md) |
| Success memory | Validated patterns worth repeating | [context/PROJECT_MEMORY.md](context/PROJECT_MEMORY.md) |

## Future Capability Boundaries

Ollama/local model access, cron-style mission invocation, project registries,
and multi-project targeting now have initial runtime support. MCP integration,
Codex/Claude oversight, richer multi-model collaboration, and production-grade
unattended operation remain roadmap items whose contracts must be planned and
approved before implementation.
