# 9D.8 — Acceptance target for the task-board demo

**Goal:** a single, checkable definition of "the autopilot succeeded," so success
is evidence-based, not vibes. The autopilot exits `0` **only** when all of this
is green; otherwise it exits nonzero with the gap named.

## Required files

```
README.md
src/task_model.py
src/storage.py
src/task_board.py
data/tasks.json
tests/test_task_model.py
tests/test_storage.py
```

These should equal `architecture.json.required_files` for the task-board (plus
`README.md`/`data/tasks.json` in `extra_allowed`), so `missing_required`
(Slice 5) enforces file coverage automatically.

## Required behaviors

```
create task with id, title, done status
edit task title
toggle done status
delete task
serialize tasks to JSON
save tasks to data/tasks.json
load tasks on startup
missing JSON returns empty list
corrupt JSON handled safely
Tkinter UI smoke check does not hang
```

Each maps to a `required_behavior` in a per-file contract (Slice 3) and to a
test (Slice 5 evidence). The UI smoke check must be **headless-safe / non-
blocking** — never a manual `python src/task_board.py` that hangs CI.

## Required validation (whole project)

```bash
python3 -m compileall -q src tests
python3 -m pytest tests
ruff check src tests
```

## How "success" is computed (not asserted)

A small deterministic acceptance checker (can live in the autopilot harness or as
`crazy-admin status --acceptance`) verifies:

1. every required file exists and is non-trivial (not a stub — reuse
   `_is_placeholder_body` on `src/*`),
2. `missing_required` is empty,
3. every checklist item is acceptance-complete (Slice 5 evidence),
4. the three validation commands pass on the whole project,
5. a headless UI import/smoke of `src/task_board.py` returns without hanging
   (subprocess with timeout; importable without a display).

Only when all five hold does the autopilot print success and exit `0`.

## Honesty rule (until the above is reliable)

Until the loop converges to this target, the autopilot must label a partial
result as **"N of M checklist items complete — partial build"** and exit
**nonzero**, never "app built." This is the `set -euo pipefail` + loop-until-
accepted discipline from the prior recovery package, now with a concrete target.

## Acceptance

- A run that produces only `task_model` + its test is reported as partial and
  exits nonzero.
- A run meeting all five criteria exits `0`.
- The checker is deterministic and unit-tested with a fixture workbench.
