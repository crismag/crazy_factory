# Observed Failures

## Context Failures

- `add-context` refused to overwrite `context/imports/import_001/task_board.md`.
- The script continued after that failure.
- `context/catalog.yaml` ended empty.
- `factory_context/PROJECT_GOAL.md` remained scaffold placeholder text.
- The run claimed context-driven generation even though cataloged context was
  unavailable.
- `_next_import_id` derives the next id from the catalog, not from disk, so an
  empty catalog repeatedly selects `import_001`.
- `_copy_into_store` refuses to overwrite existing files.
- `save_catalog` runs only after copy succeeds, so an overwrite error leaves
  the catalog empty and the import wedged.

## Reset Failures

- `startproject --force` did not clean runtime artifacts.
- `startproject --force` overwrote `PROJECT_GOAL.md` with scaffold placeholder
  text.
- Historical reports and task artifacts remained in the workbench.
- Existing approvals and generated source influenced later runs.
- The run was not truly "from zero."

## Generation Failures

- `src/storage.py` contained only placeholder `pass` functions.
- `tests/test_storage.py` had an unused import and only one weak happy-path
  test.
- `src/task_board.py` was not generated.
- `data/tasks.json` was not generated.
- Task model omitted the seed's required `id` field.

## Validation Failures

Final validation failed:

- `python3 -m pytest tests` failed.
- `ruff check src tests` failed.
- Checkpoint was correctly blocked.

## Reporting Failures

- Reports claimed no application code was modified even when files were
  created.
- That phrase is emitted unconditionally by `report_writer.py`.
- Status showed zero context imports while advance output said context files
  were read.
- Patch notes admitted incomplete implementation, but the patch was still
  applied.

## Flow Failures

- Remediation was enabled but the script did not loop until pass or exhaustion.
- Final shell result did not represent final validation quality.

## Gate Failures

- `missing_required()` exists but is not used by runtime completion gates.
- Whole-project validation correctly blocked checkpointing, but the success
  definition still lacks seed-level acceptance.
- The current pre-apply gate checks syntax, paths, imports, line limits, and
  secrets, but not placeholder or self-admitted incomplete code.
