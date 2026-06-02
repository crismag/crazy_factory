# Factory Lifecycle

## Overview

Each project is a persistent mission. Runs advance that mission through small recoverable checkpoints. A run may stop after any phase when approval, safety, or context requires owner intervention, but it must record where to resume.

Before task selection, every boot or recovery reads durable state, memory,
checklists, and milestones:

`BOOT -> READ_MEMORY -> READ_STATE -> READ_CHECKLISTS -> READ_MILESTONES`

| Phase | Objective | Primary worker | Required output |
| --- | --- | --- | --- |
| `ARCHITECT_EXPAND` | Translate goals into bounded system work | Architect | Architecture proposal or task expansion |
| `PLAN` | Define the next smallest valuable task | Planner | Planned task |
| `IMPLEMENT` | Perform approved scoped work | Coder | Change set |
| `TEST` | Validate behavior and guard regressions | Test Builder | Validation evidence |
| `REVIEW` | Check correctness, quality, and scope | Reviewer | Review record |
| `COMMIT` | Record an approved local repository checkpoint | Authorized operator | Local commit record |
| `REPORT` | Summarize work and evidence | Reporter | Session report |
| `UPDATE_MEMORY` | Preserve durable knowledge | Reporter | Updated context files |
| `SELECT_NEXT_TASK` | Choose the next candidate or stop | Planner | Next action |
| `WAIT` | Preserve a clear resume point until the next run | Reporter | Durable idle or blocked state |

## Phase Contracts

### `ARCHITECT_EXPAND`

- Objective: clarify goals, boundaries, dependencies, risks, and missing pieces.
- Inputs: project goal, current state, decisions, risks, backlog.
- Outputs: architecture proposal, expanded backlog items, decision questions.
- Success: large goals become understandable, bounded candidates.
- Failure: architecture remains ambiguous, conflicts with governance, or requires owner choice.
- Escalation: stop when a consequential architectural choice lacks approval.

### `PLAN`

- Objective: select one valuable task and make completion unambiguous.
- Inputs: approved candidates, roadmap, current state, risk register.
- Outputs: planned task with scope, exclusions, criteria, validation, and approval state.
- Success: task is small enough for one controlled work unit.
- Failure: hidden dependencies, unclear criteria, or excessive scope.
- Escalation: return to Architect or ask the owner to prioritize.

### `IMPLEMENT`

- Objective: perform only the approved task.
- Inputs: approved planned task, coding rules, relevant architecture.
- Outputs: bounded change set and implementation notes.
- Success: acceptance criteria are addressed without unrelated changes.
- Failure: scope expands, unsafe action becomes necessary, or repository state conflicts with the plan.
- Escalation: stop and request replanning or approval.

### `TEST`

- Objective: gather evidence that the task works and does not regress protected behavior.
- Inputs: planned task, change set, testing rules.
- Outputs: validation results, failures, gaps, and residual risk.
- Success: required checks pass or documentation-only validation is complete.
- Failure: checks fail, required evidence is missing, or validation is unavailable.
- Escalation: return to implementation, record limitation, or stop for owner input.

### `REVIEW`

- Objective: independently evaluate correctness, quality, safety, and scope.
- Inputs: task, diff, validation evidence, relevant decisions.
- Outputs: approval, requested changes, or escalation.
- Success: no unresolved blocking finding remains.
- Failure: defects, scope violations, insufficient evidence, or governance breach.
- Escalation: return to the responsible phase or notify the owner.

### `COMMIT`

- Objective: create a local traceable checkpoint after review.
- Inputs: reviewed change set, task ID, review result.
- Outputs: local commit reference or documented reason for no commit.
- Success: commit contains the intended reviewed scope and a meaningful message.
- Failure: unrelated changes are included, restricted git action is needed, or review is incomplete.
- Escalation: stop and repair scope; request approval for restricted operations.

### `REPORT`

- Objective: make activity legible to the owner and future sessions.
- Inputs: task, changes, validation, review, commit status.
- Outputs: session report and next action recommendation.
- Success: report distinguishes facts, evidence, assumptions, and open questions.
- Failure: report cannot account for changes or validation.
- Escalation: reconstruct evidence before proceeding.

### `UPDATE_MEMORY`

- Objective: preserve durable learning.
- Inputs: report, decisions, failures, successes, changed architecture, backlog updates.
- Outputs: updated context records and decision log.
- Success: next session can resume without guessing.
- Failure: important knowledge remains only in transient conversation.
- Escalation: stop and update records.

### `SELECT_NEXT_TASK`

- Objective: choose the next candidate or intentionally stop.
- Inputs: backlog, current state, roadmap, risks, previous report.
- Outputs: next action record.
- Success: next step is bounded, justified, and approval-aware.
- Failure: no safe candidate exists or repeated work is stalled.
- Escalation: use stall detection and notify the owner.

### `WAIT`

- Objective: stop safely without losing mission position.
- Inputs: next action, current milestone, checkpoint history, blocker state.
- Outputs: durable resume instructions and an explicit idle, blocked, paused, or satisfied state.
- Success: a later run can resume without reconstructing context.
- Failure: the next run would need to guess where work stopped.
- Escalation: update state and memory before ending the run.

## Satisfaction

The factory must not stop silently. When work appears complete, produce a
`SATISFACTION_REPORT.md` recording goals achieved, remaining risks, future
enhancements, known limitations, and recommended human review. Satisfaction
requires completed milestones, resolved critical blockers, passing required
checks, current reports, documented architecture, and an exhausted or
intentionally deferred backlog.
