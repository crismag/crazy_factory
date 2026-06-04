# Coding Rules

## Applicability

These rules govern owner-approved implementation work. Code generation is
authorized only for a valid planned task and only within the current operating
mode's safety gates.

## Coding Standards

- Implement only an approved planned task.
- Follow existing repository conventions before introducing new patterns.
- Keep changes small, readable, and reversible.
- Avoid speculative abstractions and unrelated refactors.
- Document non-obvious decisions.
- Preserve compatibility unless the task explicitly changes it.
- Never embed secrets or environment-specific credentials.
- Hand off changed files, assumptions, and validation needs to the Test Builder.

## Stop Conditions

Stop and return to planning when implementation requires broader scope, a new architectural decision, a restricted action, or modification of unrelated owner work.
