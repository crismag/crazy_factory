# Workflow: Recovery

## Purpose

Restore a safe understandable state after failure, interruption, inconsistent context, or incomplete work.

## Procedure

1. Stop progression to later lifecycle phases.
2. Inspect current repository state and last durable memory.
3. Identify the last known safe checkpoint.
4. Classify the problem: context gap, validation failure, scope conflict, repository conflict, unavailable dependency, or authority boundary.
5. Preserve unrelated owner work.
6. Record the failure and recovery options.
7. Resume only when the next action is bounded and safe.

## Forbidden Recovery Methods

Do not use history rewrite, destructive cleanup, force push, branch deletion, or removal of unrelated changes.

## Escalation

Ask the owner when safe recovery requires a restricted action, owner intent, or a consequential tradeoff.

