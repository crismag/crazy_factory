# Acceptance Criteria

## Recovery Command

- [ ] `crazy-admin recover <project>` exists.
- [ ] It reads latest contract/proposal/application/validation/acceptance
  failure context.
- [ ] It runs deterministic recovery rules before any LLM call.
- [ ] It produces `recovery_decision.json` and `RECOVERY_DECISION.md`.
- [ ] It validates recovery decision schema.
- [ ] It rejects unknown action types.
- [ ] It refuses unsafe paths.
- [ ] It updates project state to `resume_from = recovery` or the selected
  target stage.

## Embedded Recovery

- [ ] `advance` invokes recovery after application rejection when recovery is
  enabled.
- [ ] `advance` invokes recovery after validation failure when remediation is
  insufficient or not applicable.
- [ ] `advance` invokes recovery after seed acceptance failure only after a
  structured acceptance gate exists.
- [ ] Previous validation success cannot mask current application rejection.
- [ ] Repeated rejection eventually parks with `recovery_exhausted`.

## Existing Module Reconciliation

- [ ] `recovery_manager.py` is renamed, narrowed, or folded into the new
  recovery reporting/action system.
- [ ] `remediation.py` is explicitly modeled as the validation-failure
  `regenerate_patch` tactic or a lower-level tactic invoked by recovery.
- [ ] `stall_detector.py` distinguishes recoverable and persistent blockers.

## LLM Escalation Behavior

- [ ] The recovery planner prompt includes rejection reasons, current artifacts,
  checklist focus, architecture contract, and seed/acceptance summary.
- [ ] The first-cut LLM decision set is limited to regenerate patch, revise
  proposal, replan task, and park.
- [ ] Deterministic code applies only allowed recovery actions.
- [ ] Mocked LLM tests cover each decision type.
- [ ] `split_task`, live `ask_owner`, and `revise_acceptance` are deferred.

## Task-Board Proof

- [ ] When a source-only patch is rejected, recovery requests a new proposal
  containing tests.
- [ ] When a syntactically invalid patch is rejected, recovery regenerates the
  patch or proposal instead of preserving stale artifacts.
- [ ] The checklist does not advance on rejected application.
- [ ] The project does not report ready-for-review while required files are
  missing.

## Reporting

- [ ] Session reports include a Recovery section.
- [ ] Recovery reports list trigger, decision, actions, retry count, and next
  stage.
- [ ] Activity blog records whether recovery changed runtime artifacts.
- [ ] Status output shows current blocker and recovery attempt count.
