# Task Board Autopilot Context Package

Generated: 2026-06-04T15:23:15Z

This package captures the Phase 9C target for the task-board autopilot:
turn Crazy Factory from a promising governed prototype into a truthful,
repeatable, zero-to-green application builder.

The immediate goal is factory integrity, not more task-board features. The
factory must not continue from broken context, must not reuse stale state during
a supposed clean run, must not apply fake or incomplete code, and must not
report success when validation is red.

## Load Order

1. `target_state.md`
2. `observed_failures.md`
3. `quality_gates.md`
4. `roadmap.md`
5. `acceptance_checklist.md`

## Related Report

Read the full analysis:

`docs/report/task-board-autopilot-analysis-2026-06-04.md`

## Current Diagnosis

The current task-board workbench is not green and not complete. It demonstrates
useful governance scaffolding, but it fails on context integrity, clean reset,
placeholder-code rejection, remediation looping, final validation, and
seed-level acceptance.

The deeper root cause is context starvation. The seed file exists under
`context/imports/import_001/task_board.md`, but `context/catalog.yaml` is empty,
so imported context is not loaded by the catalog-driven prompt path.
`PROJECT_GOAL.md` is still scaffold placeholder text. The generated code was
therefore shaped more by required filenames and generic instructions than by the
real product brief.

## Phase Name

Phase 9C - Truthful Zero-to-Green Autopilot
