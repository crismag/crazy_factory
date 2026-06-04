# Recovery State Model

## Blockers

Use named blockers or stage statuses that distinguish current failure types:

- `application_rejected`
- `validation_failed`
- `acceptance_failed`
- `contract_rejected`
- `proposal_rejected`
- `self_rejection`
- `recovery_exhausted`
- `needs_owner_decision`

The current task-board run exposed a gap: application was rejected, but project
state still said validation passed because old code was coherent. These states
must be represented separately.

## Recoverable Vs Persistent

Split blockers into two tiers.

Recoverable first:

- `application_rejected`
- `validation_failed`
- `contract_rejected`
- `proposal_rejected`
- `self_rejection`

Persistent/park:

- `recovery_exhausted`
- `needs_owner_decision`

Some blockers may start recoverable but become persistent after retry budget is
spent or repeated identical decisions are detected.

## Recovery Record

Persist a recovery record in the project task/runtime area, for example:

```text
factory_tasks/recovery_decision.json
factory_tasks/RECOVERY_DECISION.md
```

Suggested fields:

```json
{
  "recovery_id": "REC-001",
  "trigger": "application_rejected",
  "trigger_stage": "application",
  "trigger_reasons": [],
  "decision": "revise_proposal",
  "target_stage": "coder",
  "actions": [],
  "attempt": 1,
  "max_attempts": 3,
  "source": "ollama",
  "validation": {
    "status": "valid",
    "reasons": []
  }
}
```

## Retry Accounting

Track retry budgets per task and per trigger type:

- application rejection attempts,
- validation remediation attempts,
- acceptance repair attempts,
- contract repair attempts,
- owner-question count.

Avoid one global failure counter that hides the kind of failure. The recovery
planner needs to know whether the system is stuck on proposal quality,
validation behavior, acceptance mismatch, or architecture constraints.

## State Transition Rule

When the current stage fails, the project must not report a generic
"validation passed; ready for owner review" state unless the current intended
work also passed its applicable gates.

Example:

- Application rejected, previous validation passed:
  - `last_application_status = rejected`
  - `last_validation_status = passed`
  - `current_blocker = application_rejected`
  - `resume_from = recovery`

This correctness fix should be implemented before the full recovery planner.
It is small, model-independent, and prevents misleading status/report output.

## Artifact Handling

Recovery should be able to retire stale artifacts safely:

- `approved_proposal.json`
- `coder_proposal.json`
- `patch_plan.json`
- `planned_task.json`
- rendered Markdown mirrors

Retirement should move artifacts to a recovery archive or delete only
factory-owned task artifacts. It must not delete generated application code
unless an explicit safe cleanup action is validated.

## Oscillation Guard

Repeated identical decisions must escalate deterministically:

```text
regenerate_patch -> revise_proposal -> replan_task -> needs_owner_decision -> recovery_exhausted
```

The LLM can recommend a decision, but the runtime should enforce escalation
when the same trigger/action repeats without progress.
