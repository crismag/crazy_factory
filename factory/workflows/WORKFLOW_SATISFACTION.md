# Workflow: Satisfaction

## Purpose

Declare that a project is complete enough for owner review without silently
stopping.

## Preconditions

- required milestones are complete
- critical blockers are resolved
- required checks pass
- reports and architecture are current
- backlog is exhausted or intentionally deferred
- residual risk is recorded

## Procedure

1. Review goals, milestones, checkpoints, checks, risks, and backlog.
2. Record `satisfied` or `not_satisfied`.
3. Write `SATISFACTION_REPORT.md`.
4. Include goals achieved, remaining risks, future enhancements, known
   limitations, and recommended human review.
5. Preserve an explicit wait state for owner review.

## Safety Boundary

Satisfaction is a documented conclusion, not permission to merge, push, or
delete branches.
