# Next Action Plan

## Proposed Phase

Phase 9D - Deterministic-First Recovery And LLM Convergence

## Objective

Upgrade Crazy Factory from a governed patch pipeline into a self-correcting
application builder.

The immediate implementation goal is not to make task-board pass by scripting
more steps. The goal is to teach Crazy Factory how to respond correctly when
its own gates reject a contract, proposal, patch plan, validation result, or
acceptance result.

First-cut recovery should be deterministic-first. The LLM should be an
escalation layer for ambiguous cases, not the only way recovery works.

## Why This Is Needed

The task-board debug run showed clear improvement:

- context import succeeded,
- the seed reached planning,
- one slice applied and validated,
- reports truthfully listed workbench writes,
- bad later patches were rejected before apply.

But Crazy Factory did not converge:

- application rejection did not trigger a meaningful recovery plan,
- validation of the previous tiny slice passed while current intended work was
  rejected,
- the same stale task/proposal shape kept being retried,
- checklist progress stayed at 1/5,
- seed-level acceptance was still absent from runtime state.

This is not mainly a shell-script problem. It is a missing factory-native
recovery/convergence capability.

## Primary Deliverable

Add a recovery router and planner flow that can produce a structured recovery
decision. In the first cut, deterministic rules produce decisions for known
failure patterns; the LLM planner is used only when no deterministic rule
matches or when repeated deterministic decisions fail.

```json
{
  "decision": "regenerate_patch | revise_proposal | replan_task | park",
  "reason": "...",
  "target_stage": "contract | coder | application | validation",
  "actions": [
    {
      "type": "retire_artifact | clear_approval | request_new_proposal | request_new_contract | update_focus | record_owner_question",
      "path": "...",
      "detail": "..."
    }
  ],
  "retry_budget": {
    "used": 1,
    "max": 3
  }
}
```

## Implementation Sequence

1. Fix the state-masking bug now: application rejection must not leave the
   project saying "validation passed; ready for owner review."
2. Split blockers into recoverable vs persistent. Recoverable blockers route to
   recovery first; parking happens only after exhaustion or owner decision.
3. Wire the acceptance gate before adding acceptance recovery. `missing_required`
   and seed checks must have runtime callers before `acceptance_failed` is a
   meaningful trigger.
4. Add deterministic recovery table, decision schema validation, and safe
   artifact clearing helpers.
5. Add explicit `crazy-admin recover <project>` using the deterministic table.
6. Embed recovery in `advance` after application rejection, validation failure,
   and self-rejection where owner controls allow it.
7. Add the LLM recovery planner as escalation above the deterministic table.
8. Add reporting sections and mocked-LLM tests.
9. Add `build --until accepted` last, as thin orchestration over existing
   factory-native primitives.

## Non-Goals

- Do not make shell scripts responsible for strategic recovery.
- Do not bypass deterministic safety gates.
- Do not auto-commit, push, merge, or delete git history.
- Do not let recovery edit files outside the approved workbench/runtime roots.
- Do not treat pytest success as product success when required files or seed
  acceptance are incomplete.
- Do not ship `split_task` or live `ask_owner` in the first cut. Park with a
  recorded owner question instead.
