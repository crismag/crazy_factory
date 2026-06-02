# Allowed Actions

## Purpose

This document defines actions the factory may perform within an approved task and current operating mode.

## Documentation Actions

- read project files and approved context
- create and revise Markdown documentation
- update backlog, memory, risks, decisions, and reports
- create proposals and templates
- inspect repository state

## Git Actions

Allowed local git operations:

- status
- diff
- add
- commit
- log

Each operation must remain within task scope. A local commit must contain reviewed intended work only.

## Future Implementation Actions

Creating code, tests, or other implementation artifacts requires a future approved implementation phase and an approved planned task. These actions are not allowed during documentation bootstrap.

## Interpretation

An action not listed here is not automatically allowed. Check [APPROVAL_RULES.md](APPROVAL_RULES.md) and [FORBIDDEN_ACTIONS.md](FORBIDDEN_ACTIONS.md).

