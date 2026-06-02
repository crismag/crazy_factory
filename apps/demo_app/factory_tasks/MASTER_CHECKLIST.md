# Master Checklist

This checklist is the demo application's source of truth for milestone and
task completion state.

## `DEMO-M1` Mission-State Bootstrap Validation

- [x] Create the demo application construction-site structure.
- [x] Seed app-specific context, task, prompt, and report locations.
- [x] Create a safe dry-run factory tick.
- [x] Load persistent factory and project state during a dry-run tick.
- [x] Report mission recovery questions in each dry-run report.
- [x] Review Phase 1 mission-state behavior.

## `DEMO-M2` Future Tiny Build Planning

- [ ] Define one tiny approved future demo build task.
- [ ] Define acceptance criteria and validation checks.
- [ ] Keep application writes disabled until owner approval.

## `DEMO-PHASE3` Structured Planning Contracts

- [x] Emit a structured task contract from the planning loop.
- [x] Parse and validate the contract in the engine (opinionated rules).
- [x] Reject malformed, unbounded, or self-authorizing contracts.
- [x] Record `authorized: false`; reserve authorization for the owner.
- [ ] Owner reviews a valid contract and authorizes it (manual).
- [x] Add a Coder role gated on an authorized contract (Phase 4A).

## `DEMO-PHASE4` Authorized Coder Proposal Engine

- [x] Activate the Coder only for an authorized, valid contract.
- [x] Generate a structured proposal (`coder_proposal.json` + Markdown).
- [x] Validate proposals: allowed targets, no secrets/destructive ops, file
      limit, non-empty.
- [x] Reject malformed/unavailable proposals; never fake a valid one.
- [x] Record proposal state and report; never write or apply code.
- [x] Owner reviews proposal quality before any Phase 5 application engine.

## `DEMO-PHASE5` Proposal Application Preview Engine

- [x] Gate application on contract+proposal+explicit owner approval.
- [x] Generate a validated patch plan (`patch_plan.json` + `PATCH_PLAN.md`).
- [x] Validate paths/secrets/limits; reject unsafe plans.
- [x] Default to `preview_only`; apply only when explicitly enabled.
- [x] Write `APPLICATION_REPORT.md`; record application state.
- [ ] Owner enables apply mode for a reviewed plan (manual, deliberate).

## `DEMO-PHASE6` Test Builder and Validation Runner

- [x] Test Builder generates a structured test plan (`test_plan.json` + md).
- [x] Reject plans whose checks are not allowlisted.
- [x] Validation Runner executes only allowlisted, shell-free commands.
- [x] Execution gated by `validation.allow_run` (default off → skipped).
- [x] Blocked/failed checks block checkpoint promotion; recorded in state.
- [ ] Owner enables `validation.allow_run` to execute real checks.

## `DEMO-PHASE7` Checkpoint Commit Engine

- [x] Commit only when contract+proposal+application+validation all pass.
- [x] Auto-commit gated by `git.allow_auto_commit` (default off).
- [x] Stage only allowed commit paths; never engine/config/VCS files.
- [x] Commit message derived from the contract; checkpoint log + report.
- [x] Only safe git subcommands, shell-free; no push/merge/reset/rebase.
- [ ] Owner enables `git.allow_auto_commit` after reviewing checkpoints.
