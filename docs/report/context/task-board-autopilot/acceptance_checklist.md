# Acceptance Checklist

## Autopilot Script

- [ ] Fails fast on command errors.
- [ ] Uses `set -euo pipefail`.
- [ ] Starts from a clean workbench.
- [ ] Imports context successfully.
- [ ] Exits nonzero on validation failure.
- [ ] Loops remediation until pass or budget exhaustion.
- [ ] Prints final artifact/report locations.
- [ ] Runs final status, compile, pytest, and ruff as hard gates.
- [ ] Exits `0` only when the generated project is fully green.

## Clean Runtime Reset

- [ ] `resetproject <id> --clean-runtime` or
  `startproject <id> --force --clean-runtime` exists.
- [ ] Generated source is removed before a clean run.
- [ ] Generated tests are removed before a clean run.
- [ ] Stale context imports and catalog are removed or rebuilt coherently.
- [ ] Stale task artifacts, approvals, validation reports, checkpoint state,
  factory reports, and caches are removed.
- [ ] Owner-authored seed/context files are preserved unless explicitly removed.

## Context Integrity

- [ ] `context/catalog.yaml` contains the task-board seed.
- [ ] `PROJECT_GOAL.md` is meaningful or imported context is confirmed loaded.
- [ ] Status output matches catalog reality.
- [ ] `add-context` is idempotent when prior imports exist on disk.
- [ ] Empty catalog after import is fatal.

## Generated App Structure

- [ ] `src/task_model.py`
- [ ] `src/storage.py`
- [ ] `src/task_board.py`
- [ ] `data/tasks.json` exists after first save, or lazy creation is explicitly
  tested and accepted.
- [ ] `tests/test_task_model.py`
- [ ] `tests/test_storage.py`

## Generated Behavior

- [ ] Create task with id, title, done status.
- [ ] Edit task title.
- [ ] Toggle done status.
- [ ] Delete task from collection.
- [ ] Serialize tasks to JSON-compatible structures.
- [ ] Save tasks to `data/tasks.json`.
- [ ] Load tasks on startup.
- [ ] Missing JSON file returns empty task list.
- [ ] Corrupt JSON is handled safely.
- [ ] Tkinter UI smoke check is headless-safe and does not hang.

## Quality

- [ ] No placeholder `pass` implementations.
- [ ] No TODO-only generated bodies.
- [ ] No unused imports.
- [ ] No empty tests.
- [ ] No forbidden imports or files.
- [ ] Patch notes do not admit incomplete implementation.
- [ ] Source patches include relevant tests or documented existing coverage.

## Validation

- [ ] `python3 -m compileall -q src tests` passes.
- [ ] `python3 -m pytest tests` passes.
- [ ] `ruff check src tests` passes.
- [ ] UI smoke check passes without hanging.

## Reporting

- [ ] Reports list created and modified files accurately.
- [ ] Reports show context catalog status.
- [ ] Reports show required-file coverage.
- [ ] Reports do not claim "no application code was modified" after writes.
- [ ] Checkpoint remains blocked until validation passes.
- [ ] Shell exit status matches final validation quality.
