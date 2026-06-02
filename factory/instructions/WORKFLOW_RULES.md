# Workflow Rules

## Required Sequence

Use the lifecycle in [../FACTORY_LIFECYCLE.md](../FACTORY_LIFECYCLE.md):

`ARCHITECT_EXPAND -> PLAN -> IMPLEMENT -> TEST -> REVIEW -> COMMIT -> REPORT -> UPDATE_MEMORY -> SELECT_NEXT_TASK`

## Operating Rules

- Enter a phase only when required inputs exist.
- Produce the required phase output before advancing.
- Record skipped phases and why they were not applicable.
- Return to the earlier responsible phase when evidence exposes a problem.
- Stop for escalation when recovery exceeds authority.
- Keep one active bounded task unless the owner explicitly approves otherwise.

## Session End

Every session must end with a report, memory update, and next-action recommendation, including sessions that stop early or fail.

