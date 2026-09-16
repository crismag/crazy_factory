# Baseline — Crazy Factory before Slice A

Recorded: 2026-09-16 on `main` at `d8b51d0`.

## Git

- Branch audited: `main`
- Latest commits: Issue #38 ST6 pairing, empty-workbench not-done,
  Issue #35 acceptance retirement, code-birth gate, 9E adjudicator
  wiring, seed-derived architecture (opt-in).

## Tests

```text
python3 -m unittest discover -s tests
Ran 519 tests in ~0.6s
FAILED (failures=2)
```

Pre-existing failures (ruff binary not on `PATH`; `python3 -m ruff`
works after `pip install ruff`, but `skill_library.autofix_lint`
invokes `["ruff", ...]`):

- `test_skill_library.AutofixLintTests.test_removes_unused_import`
- `test_proposal_applier.AutofixApplyTests.test_unused_import_is_autofixed_not_rejected`

These are characterization, not regressions of Slice A.

## CLI smoke (no Ollama required)

```text
bin/crazy-admin startproject --help
bin/crazy-admin status   # no target → guidance
```

Live `advance` against registered host apps (`tic-tac-toe`,
`task-board` at `/mnt/ai/workspaces/crazy_apps/...`) is not runnable
in this environment.

## Known live-run failures (historical, not re-executed here)

From `docs/report/task-board-autopilot-analysis-2026-06-04.md` and
GitHub issues #33, #37, #38:

- Context catalog empty while seed existed
- `PROJECT_GOAL.md` stayed scaffold
- Applied stubs (`save_data`/`load_data` = `pass`)
- pytest + ruff failed after apply
- Rejection loops with empty `app/`

## Invariants Slice A must not break

- Owner switches default OFF
- No auto-push / auto-merge
- Workbench write confinement
- `advance` still parks on `self_rejection` / `remediation_exhausted`
- Unit tests besides the two ruff-PATH failures stay green
