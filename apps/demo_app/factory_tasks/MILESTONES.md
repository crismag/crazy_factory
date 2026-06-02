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

## `DEMO-PHASE5`: Proposal Application Preview Engine

- Status: `active`
- Purpose: turn an owner-approved, valid coder proposal into a concrete patch
  plan (exact file contents); apply it only when explicitly enabled.
- Completion criteria:
  - activates only under the full gate (contract authorized+valid, proposal
    valid, and explicit owner approval matching the proposal id)
  - generates a validated patch plan + `PATCH_PLAN.md` + `APPLICATION_REPORT.md`
  - rejects unsafe paths (protected dirs, root README, out-of-bounds,
    traversal), secrets, missing content, over file/line limits
  - default `preview_only` / `allow_apply: false` writes nothing; apply mode
    works only when explicitly enabled and the plan validates
  - failure paths exit cleanly; no commit/merge/push
- Non-goals (deferred): auto-commit (Phase 7), validation runner (Phase 6).

## `DEMO-PHASE6`: Test Builder and Validation Runner

- Status: `active`
- Purpose: prove that work is checked before any checkpoint — a Test Builder
  proposes a structured test plan, and a Validation Runner executes only
  allowlisted, shell-free commands.
- Completion criteria:
  - Test Builder produces a structured `test_plan.json` + `TEST_PLAN.md`
  - every `required_check` is an allowlisted command; non-allowlisted plans
    are rejected
  - Validation Runner executes only allowlisted commands, only with
    `validation.allow_run` enabled; otherwise checks are recorded `skipped`
  - blocked/failed checks become a recoverable failure (block future
    checkpoint promotion); results recorded in state and report
  - no auto-commit yet

## `DEMO-M3`: Future Application Checkpoint Trial

- Status: `deferred`
- Purpose: exercise a later approved implementation checkpoint with validation
  and explicit review.
