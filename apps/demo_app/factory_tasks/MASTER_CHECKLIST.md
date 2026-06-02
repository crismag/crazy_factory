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
- [ ] Owner reviews proposal quality before any Phase 5 application engine.
