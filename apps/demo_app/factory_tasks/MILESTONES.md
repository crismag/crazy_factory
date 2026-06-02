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

## `DEMO-PHASE4`: Authorized Coder Proposal Engine

- Status: `active`
- Purpose: prove a Coder can translate an authorized, valid contract into a
  safe, structured implementation *proposal* without modifying source code.
- Completion criteria:
  - the Coder activates only for an owner-authorized, valid contract
  - a structured proposal (`coder_proposal.json` + `CODER_PROPOSAL.md`) is
    generated and validated
  - unsafe proposals (out-of-bounds paths, secrets, destructive ops, empty,
    over the file limit) are rejected
  - failure paths (unauthorized/invalid/malformed/Ollama down) exit cleanly
  - no files are written, no code is applied, no commit/merge/push occurs
- Non-goals (deferred to Phase 5): file writing, patch application, test
  execution.

## `DEMO-M3`: Future Application Checkpoint Trial

- Status: `deferred`
- Purpose: exercise a later approved implementation checkpoint with validation
  and explicit review.
