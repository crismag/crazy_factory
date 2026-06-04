# Target State

## Purpose

The task-board autopilot should demonstrate a clean, governed, repeatable path
from owner seed to a working application.

The immediate target is not a larger task-board feature set. The immediate
target is a factory that cannot continue from broken context, cannot apply fake
or incomplete code, cannot reuse stale state during a supposed clean run, and
cannot report success when validation is red.

## Phase

Phase 9C - Truthful Zero-to-Green Autopilot

## Target User Experience

Running:

```bash
bash tests/autopilot_taskboard.sh
```

should either:

- produce a working task-board app with passing validation and exit `0`, or
- stop at the first unrecoverable failure with a clear diagnostic and nonzero
  exit.

## Target Generated Application

The app should be a minimal Python Tkinter task board with:

- add task
- edit selected task
- delete selected task
- toggle done status
- save tasks to JSON
- load tasks from JSON on startup

## Required Generated Files

- `README.md`
- `src/task_model.py`
- `src/storage.py`
- `src/task_board.py`
- `data/tasks.json`, either present after generation or created on first save
  with lazy creation explicitly tested
- `tests/test_task_model.py`
- `tests/test_storage.py`

## Required Validation

From `/mnt/ai/workspaces/crazy_apps/task-board`:

```bash
python3 -m compileall -q src tests
python3 -m pytest tests
ruff check src tests
```

For UI launch validation, use a non-blocking/headless-safe smoke check rather
than a manual blocking `python src/task_board.py` call.

## Required Factory Behavior

- `tests/autopilot_taskboard.sh` uses fail-hard shell behavior.
- The project starts from a clean runtime state.
- Context import succeeds or the run stops.
- Empty context catalog after import is fatal.
- `PROJECT_GOAL.md` is meaningful, or imported context is proven loaded into
  planner/coder prompts.
- Incomplete generated patches are rejected before application.
- Remediation loops until validation passes or budget is exhausted.
- Reports truthfully distinguish planning, proposal, preview, write,
  validation, checkpoint, blocker, and success states.

## Success Definition

The autopilot is successful only when:

- context import succeeds,
- generated code has no placeholder implementations,
- required files exist,
- whole-project tests pass,
- lint passes,
- seed acceptance passes,
- reports truthfully describe writes and validation,
- the script exits `0` only on green.

If any unrecoverable gate fails, the autopilot should stop with a clear
diagnostic and nonzero exit.
