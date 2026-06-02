# Milestones

## `DEMO-M1`: Mission-State Bootstrap Validation

- Status: `complete`
- Purpose: prove that Crazy Factory can preserve and read enough file-based
  state to resume after interruption.
- Completion criteria:
  - dry-run tick reads factory state, active-run state, project state,
    checklist, milestones, current task, and next action
  - report answers the six mission recovery questions
  - watcher summarizes resume state and possible stalls
  - no application code generation or automatic git action occurs

## `DEMO-M2`: Future Tiny Build Planning

- Status: `active`
- Purpose: define the first intentionally small application task after the
  mission-state bootstrap is reviewed.

## `DEMO-PHASE3`: Structured Planning Contracts

- Status: `active`
- Purpose: turn Planner output into a machine-validated task contract
  (`planned_task.json` + `PLANNED_TASK.md`) before any implementation role
  exists.
- Completion criteria:
  - the tick emits a structured contract parsed and validated by the engine
  - malformed or overly broad contracts are rejected, not trusted
  - the contract records `authorized: false`; only the owner may flip it
  - a downstream Coder may act only on an authorized, valid contract
  - no Coder execution, no weakened write boundaries, no auto-authorization

## `DEMO-M3`: Future Application Checkpoint Trial

- Status: `deferred`
- Purpose: exercise a later approved implementation checkpoint with validation
  and explicit review.
