# Required Quality Gates

## Preflight Gates

- Engine Python files compile.
- `bin/crazy-admin --help` succeeds.
- Ollama is reachable.
- Target apps base exists and is approved.
- Target workbench is clean or explicitly reset.
- The script runs with `set -euo pipefail`.
- Any failed admin command stops the autopilot.

## Context Gates

- `add-context` succeeds.
- `context/catalog.yaml` has at least one supported file.
- `PROJECT_GOAL.md` is not scaffold placeholder text, or imported context is
  confirmed loaded.
- Context import failures are fatal for autopilot.
- `add-context` is idempotent when stale import directories exist.
- Import ids must be allocated from catalog plus disk state, or imports must be
  safely replaceable.

## Reset Gates

- Clean-runtime reset removes stale generated source, generated tests, context
  imports/catalog, task artifacts, approvals, validation reports, factory
  reports, checkpoint state, and caches.
- Clean-runtime reset preserves owner-authored seed/context files unless the
  owner explicitly requests their removal.
- Autopilot prints or verifies the reset result before generation starts.

## Proposal Gates

Reject a proposal when:

- it does not modify or create files required by the task,
- it proposes tests but no implementation,
- it proposes implementation but no validation,
- it references missing modules or forbidden paths,
- it uses architecture-forbidden imports.

## Patch Gates

Reject a patch before apply when generated code contains:

- `pass` as a placeholder body,
- TODO-only implementation,
- "Implement logic here" comments,
- empty test bodies,
- unused imports,
- syntax errors,
- notes admitting the implementation remains incomplete.

Unused-import detection should use `ruff` on staged or temporary patch content
where practical. Avoid maintaining a custom Python import analyzer unless there
is no acceptable tool-based option.

## Architecture Gates

Enforce `architecture.json`:

- `required_files` must exist before milestone completion.
- `forbidden_dirs` must not appear.
- `forbidden_names` must not appear.
- `forbidden_imports` must not appear.

Required-file coverage and seed-level behavior acceptance are separate gates:
the file tree can be complete while behavior is still wrong.

## Validation Gates

Every applied patch must pass:

```bash
python3 -m compileall -q src tests
python3 -m pytest tests
ruff check src tests
```

Task-specific checks may be added, but whole-project coherence checks should
remain mandatory before checkpoint or script success.

For Tkinter UI validation, use a headless-safe smoke check or `xvfb-run` when
available. A blocking manual `python src/task_board.py` launch is not an
acceptable automated gate.

## Seed Acceptance Gates

Task-board success requires behavior checks for:

- task id/title/done creation,
- title editing,
- done toggling,
- deletion,
- JSON-compatible serialization,
- save/load through `data/tasks.json`,
- missing JSON returning an empty list,
- corrupt JSON failing safely,
- UI smoke construction without hanging.

## Reporting Gates

Reports must state:

- files created,
- files modified,
- files skipped,
- validation commands run,
- validation status,
- context catalog status,
- required-file coverage,
- final blocker or success state.

Reports must distinguish planning-only, proposal-created, patch-previewed,
files-created, files-modified, validation-passed, validation-failed,
checkpoint-blocked, and checkpoint-created states.
