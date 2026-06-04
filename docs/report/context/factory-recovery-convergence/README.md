# Factory Recovery Convergence Context Package

Generated: 2026-06-04

This package defines the next proposed direction for Crazy Factory after the
task-board debug run: move recovery and convergence into Crazy Factory itself,
with deterministic recovery rules first and LLM-driven diagnosis/replanning as
an escalation layer.

The user preference is explicit: do not keep making shell scripts smarter until
they become the product. Scripts should be thin launch/proof harnesses. Crazy
Factory should own the reasoning loop.

## Load Order

1. `next_action_plan.md`
2. `target_architecture.md`
3. `recovery_state_model.md`
4. `flow_integration.md`
5. `acceptance_criteria.md`
6. `risks_and_guardrails.md`

## Core Idea

Recovery should be both:

- explicitly callable, for example `crazy-admin recover <project>`; and
- embedded inside normal flows, so `advance` or future `build --until accepted`
  can invoke recovery when a gate rejects work.

Python should handle obvious recovery cases deterministically. The LLM should
decide ambiguous or higher-level strategy after deterministic rules fail or
need escalation. Python still enforces boundaries, state transitions, retry
budgets, validation, and reporting truthfulness.

## Existing Modules To Reconcile

Do not build a greenfield recovery stack beside the current one. Phase 9D must
explicitly absorb or rename these existing pieces:

- `recovery_manager.py`: currently deterministic park-and-advise. Rename or
  narrow it to stall reporting, or fold its advice strings into structured
  recovery actions.
- `remediation.py`: currently validation-failure retry logic. Keep it as the
  `regenerate_patch` tactic under the recovery planner, or clearly place it
  below the new recovery router.
- `stall_detector.py`: currently treats blockers such as
  `application_rejected`, `validation_failed`, and `self_rejection` as
  persistent park conditions. Split blockers into recoverable vs persistent so
  recoverable failures route through recovery before parking.
