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

Automatic checkpoint commits must remain disabled unless explicitly enabled by
owner policy and reached through review and validation gates. They never imply
push, merge, force-push, or history rewrite authority.

## Implementation Actions

Creating code, tests, or other implementation artifacts requires a valid,
owner-approved planned task and must remain inside approved project workbench
paths. Capability switches still default off and must be enabled explicitly
before application, validation, remediation, or checkpoint commits occur.

## Interpretation

An action not listed here is not automatically allowed. Check [APPROVAL_RULES.md](APPROVAL_RULES.md) and [FORBIDDEN_ACTIONS.md](FORBIDDEN_ACTIONS.md).
