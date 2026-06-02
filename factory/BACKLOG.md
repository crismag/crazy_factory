# Backlog

## Purpose

The backlog is the canonical inventory of future work. It records outcomes to pursue, not a stream of vague ideas. Every implementation task must be expanded and planned before selection.

## Status Vocabulary

| Status | Meaning |
| --- | --- |
| `idea` | Captured but not yet evaluated |
| `candidate` | Worth expanding |
| `planned` | Scoped with acceptance criteria |
| `approved` | Authorized for selection |
| `active` | Currently being worked |
| `blocked` | Cannot proceed without recovery or escalation |
| `review` | Awaiting review outcome |
| `done` | Acceptance criteria met and evidence recorded |
| `deferred` | Intentionally postponed |

## Priority Vocabulary

| Priority | Meaning |
| --- | --- |
| `P0` | Safety, data integrity, or repository protection issue |
| `P1` | Blocks the next meaningful milestone |
| `P2` | Important milestone progress |
| `P3` | Useful improvement |
| `P4` | Optional exploration |

## Selection Rules

Select work by safety, dependency order, owner priority, value, scope size, and verifiability. Prefer one bounded task over several partially defined tasks. See [workflows/WORKFLOW_TASK_SELECTION.md](workflows/WORKFLOW_TASK_SELECTION.md).

## Bootstrap Backlog

| ID | Priority | Status | Outcome | Depends On |
| --- | --- | --- | --- | --- |
| CF-001 | P1 | candidate | Review and approve the documentation operating system | Documentation bootstrap |
| CF-002 | P1 | idea | Define the first implementation milestone and explicit non-goals | CF-001 |
| CF-003 | P2 | idea | Select the initial local model operating strategy | CF-002 |
| CF-004 | P2 | idea | Define session state storage requirements | CF-002 |
| CF-005 | P2 | idea | Define repository inspection and task selection requirements | CF-002 |
| CF-006 | P2 | idea | Define reporting and memory update requirements for the first prototype | CF-002 |
| CF-007 | P3 | idea | Evaluate periodic scheduling requirements | First prototype |
| CF-008 | P3 | idea | Evaluate oversight integration requirements | First prototype |
| CF-009 | P4 | idea | Explore multi-model collaboration policy | Stable single-model workflow |
| CF-010 | P4 | idea | Explore multi-project operation policy | Stable single-project workflow |

## Backlog Entry Contract

Expanded items should use [templates/TASK_EXPANSION_TEMPLATE.md](templates/TASK_EXPANSION_TEMPLATE.md). Selected work should use [templates/PLANNED_TASK_TEMPLATE.md](templates/PLANNED_TASK_TEMPLATE.md).

