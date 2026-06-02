# Workflow: Mission Recovery

## Purpose

Resume work after a reboot, crash, pause, manual stop, or ordinary wait without
reconstructing project position from transient model context.

## Required Inputs

- `state/factory_state.json`
- `state/active_run.json`
- `state/project_state.json`
- active application `factory_context/PROJECT_MEMORY.md`
- active application `factory_tasks/MASTER_CHECKLIST.md`
- active application `factory_tasks/MILESTONES.md`
- active application `factory_tasks/CURRENT_TASK.md`
- active application `factory_tasks/NEXT_ACTION.md`
- checkpoint history and stall report

## Procedure

1. Read factory mode and capability flags.
2. Confirm the configured project matches persistent state.
3. Read the last completed milestone and checkpoint.
4. Read the current task, blocker, checklist, and next action.
5. Inspect recent failure and stall evidence.
6. Answer the six mission recovery questions.
7. Resume only from the recorded bounded next action.
8. Escalate if state conflicts or required files are missing.

## Success Criteria

A later run can identify what happened, what remains, and where to resume
without guessing or enabling broader authority.

## Safety Boundary

Recovery must not use destructive cleanup, history rewrite, automatic merge,
or unapproved application edits.
