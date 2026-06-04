# Risks And Guardrails

## Risk: LLM Recovery Becomes Too Powerful

Recovery should not execute arbitrary instructions. LLM escalation must return
structured decisions that Python validates.

Guardrails:

- schema validation,
- fixed action enum,
- path confinement,
- owner controls,
- retry budgets,
- report every action.
- deterministic recovery rules before LLM escalation.

## Risk: Endless Recovery Loops

LLM-driven recovery can loop if it keeps choosing the same bad action.

Guardrails:

- per-trigger retry counters,
- repeated-decision detection,
- recovery history in prompt,
- mandatory escalation ladder,
- park with `recovery_exhausted`,
- owner-visible next action.

## Risk: Acceptance Becomes Too Vague

If acceptance remains purely textual, the factory may claim success too early.

Guardrails:

- LLM drafts acceptance,
- Python stores structured acceptance,
- deterministic checks enforce required files and commands,
- domain-specific checks run where possible.

## Risk: Scripts Become The Product Again

Debug/autopilot scripts should not own convergence logic.

Guardrails:

- keep scripts as launch/proof wrappers,
- implement recovery in `scripts/` runtime modules,
- expose CLI primitives,
- test recovery with unit tests, not shell-only behavior.

## Risk: Stale Artifacts Keep Reappearing

Task-board showed repeated application rejection with stale contract/proposal
shape.

Guardrails:

- recovery can retire stale task artifacts,
- approvals are cleared when their proposal is invalid for application,
- preserved artifacts must be invalidated when downstream gates reject them,
- state must record which artifact caused the blocker.

## Risk: Competing Recovery Systems

The repo already has `recovery_manager.py`, `remediation.py`, and
`stall_detector.py`. Adding a new planner without reconciling them would create
overlapping state machines.

Guardrails:

- explicitly rename or absorb `recovery_manager.py`,
- make `remediation.py` a tactic under recovery,
- split `stall_detector.py` blockers into recoverable and persistent,
- document ownership of retry budgets and blockers in one place.
