# Decision Log

## Purpose

This log is the canonical index of accepted project decisions. Use [templates/DECISION_RECORD_TEMPLATE.md](templates/DECISION_RECORD_TEMPLATE.md) for detailed records when a decision needs more space.

| ID | Date | Status | Decision | Rationale | Related records |
| --- | --- | --- | --- | --- | --- |
| D-001 | 2026-06-02 | accepted | Crazy Factory is local-first by default | Minimize data exposure and preserve owner control | [FACTORY_CONTRACT.md](FACTORY_CONTRACT.md) |
| D-002 | 2026-06-02 | accepted | The system is organized as specialized workers | Separation of responsibilities improves auditability and review quality | [roles/](roles/) |
| D-003 | 2026-06-02 | accepted | Work proceeds through a fixed lifecycle | Explicit phase gates make autonomous work observable and recoverable | [FACTORY_LIFECYCLE.md](FACTORY_LIFECYCLE.md) |
| D-004 | 2026-06-02 | accepted | Push, merge, and branch deletion are restricted; destructive git operations are forbidden | Protect repository history and owner authority | [governance/ALLOWED_ACTIONS.md](governance/ALLOWED_ACTIONS.md) |
| D-005 | 2026-06-02 | superseded | Current scope is documentation bootstrap only | Future implementation required an approved operating context first | [context/CURRENT_STATE.md](context/CURRENT_STATE.md) |
| D-006 | 2026-06-04 | accepted | The runtime may perform guarded local advances through explicit owner controls | The repository now has CLI/runtime support; documentation must describe current behavior and keep safety gates explicit | [USAGE.md](../docs/USAGE.md), [context/CURRENT_STATE.md](context/CURRENT_STATE.md) |
