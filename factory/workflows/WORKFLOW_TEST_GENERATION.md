# Workflow: Test Generation

## Status

This workflow governs future implementation validation. Documentation bootstrap creates no test artifacts.

## Purpose

Create evidence that acceptance criteria are met and likely regressions are controlled.

## Procedure

1. Map each acceptance criterion to a validation check.
2. Identify changed behavior and regression risk.
3. Create the smallest meaningful future checks consistent with repository conventions.
4. Run or inspect applicable validation.
5. Record passed, failed, skipped, and unavailable checks separately.
6. Return reproducible failures to implementation.

## Outputs

- validation plan
- evidence record
- disclosed gaps
- residual risk

## Escalation

Stop completion claims when required evidence cannot be gathered.

