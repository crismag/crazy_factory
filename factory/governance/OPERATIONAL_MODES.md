# Operational Modes

## Purpose

Modes define the authority available during a session. The active mode must be recorded in reports.

## `DOCUMENTATION_BOOTSTRAP`

Allowed: documentation, context, templates, plans, governance, and repository inspection.

Forbidden: implementation code, scripts, tests, and executable artifacts.

## `PLANNING_ONLY`

Allowed: architecture expansion, backlog management, task planning, documentation updates, and reporting.

Forbidden: implementation changes.

## `IMPLEMENTATION_BOUNDED`

Future mode. Allowed only after owner approval for one planned task. Includes scoped implementation and validation within governance.

## `REVIEW_ONLY`

Allowed: inspect work, validation evidence, and repository state; write review and reporting documents.

Forbidden: implementation changes unless a new task is planned.

## `RECOVERY`

Allowed: inspect state, document failures, narrow next actions, and restore understanding.

Forbidden: destructive cleanup and unapproved repository actions.

## `PAUSED`

Allowed: reporting and owner-directed documentation only. No autonomous progress.

