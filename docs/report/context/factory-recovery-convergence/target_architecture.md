# Target Architecture

## Current Shape

Crazy Factory currently behaves like:

```text
architect -> planner -> contract -> coder -> application -> validation -> checkpoint
```

This is a good governance skeleton, but it is mostly linear. When a downstream
gate rejects work, the system records the rejection but does not reliably decide
whether to regenerate, replan, split, ask the owner, or park.

## Proposed Shape

Add recovery as a first-class router plus reusable service:

```text
architect
planner
contract reviewer
coder
application gate
validation gate
acceptance gate
recovery router
recovery planner escalation
reporter
```

Recovery is not a one-off remediation patch. It is a decision layer that can
route the next move. Obvious cases should not require an LLM.

## Existing Module Reconciliation

Phase 9D should not create competing retry systems.

- `recovery_manager.py` should be renamed/narrowed to stall reporting or folded
  into structured recovery decision rendering.
- `remediation.py` should become the validation-failure `regenerate_patch`
  tactic under the recovery router, or be explicitly documented as a lower-level
  tactic that recovery can invoke.
- `stall_detector.py` should distinguish recoverable blockers from persistent
  blockers. `application_rejected`, `validation_failed`, and `self_rejection`
  should route to recovery first and park only after recovery exhaustion.

## Deterministic Recovery Table

Start with deterministic rules for known patterns:

- `application_rejected` plus "does not include or declare validation tests":
  clear stale approval and request a new proposal containing source plus tests.
- `application_rejected` plus Python syntax error:
  retire patch plan and regenerate patch/proposal with syntax error in context.
- `validation_failed`:
  invoke the existing remediation tactic within budget.
- repeated identical recovery decision:
  escalate deterministically to the next tier rather than repeating forever.

## Recovery Router Responsibilities

The deterministic recovery router reads:

- current blocker,
- latest stage status,
- rejection reasons,
- retry counters,
- latest artifacts.

It applies known safe mappings before any model call.

## Recovery Planner Responsibilities

The LLM recovery planner reads:

- current checklist focus,
- project seed/context summary,
- architecture contract,
- current contract/proposal/patch plan,
- deterministic rejection reasons,
- validation output,
- acceptance gaps,
- retry counts,
- recent recovery decisions.

It decides ambiguous or escalated cases:

- regenerate the patch for the same proposal,
- revise the coder proposal,
- revise the planned task,
- clear stale approvals,
- retire stale artifacts,
- record an owner question and park,
- park with a named blocker.

## Deterministic Runtime Responsibilities

Python must still enforce:

- path confinement,
- owner controls,
- artifact clearing boundaries,
- retry budgets,
- schema validation,
- allowed action types,
- no destructive git operations,
- no writes outside workbench/runtime roots,
- truthful reporting.

## Important Distinction

LLM recovery may choose the strategy. It must not directly execute filesystem
or git changes. It proposes a structured recovery action plan; deterministic
code validates and applies only allowed state/artifact transitions.
