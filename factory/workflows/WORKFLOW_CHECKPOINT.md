# Workflow: Checkpoint

## Purpose

Record the smallest safe recoverable unit of completed work.

## Requirements

Every checkpoint records:

- checkpoint ID
- timestamp
- project and milestone
- files modified
- reason
- outcome
- checks executed
- remaining work
- suggested next action

## Procedure

1. Confirm the bounded task outcome and review evidence.
2. Record the checkpoint in application checkpoint history.
3. Update project memory, checklist, milestone status, and next action.
4. Update persistent state with the last completed checkpoint.
5. Create a local checkpoint commit only when commit capability is approved and
   enabled.
6. Return to task selection or wait with an explicit resume point.

## Safety Boundary

A checkpoint does not imply permission to push or merge. Automatic checkpoint
commits remain a future gated capability.
