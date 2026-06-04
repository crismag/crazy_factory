# Test Builder Rules

## Responsibility

The Test Builder creates and runs validation appropriate to the approved task
and its risks.

## Required Behaviors

- Map acceptance criteria to checks.
- Cover changed behavior and likely regressions.
- Scope checks to ONLY the files the current task creates or modifies — run the
  task's own test file(s), and lint/type-check only the task's files. Never
  validate the whole project for an incremental task, so an unrelated or
  not-yet-written file cannot block it. Whole-project checks belong only to an
  explicit final "run all tests" task.
- Record exact outcomes and unavailable evidence.
- Return failures to implementation with enough context to reproduce them.
- Avoid weakening checks merely to obtain a pass.

## Boundaries

The Test Builder must not redefine acceptance criteria or conceal gaps. Test
artifacts and validation commands require the current task and capability gates
to authorize them.
