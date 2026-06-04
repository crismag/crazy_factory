# Phase 9C Roadmap

Phase 9C is "Truthful Zero-to-Green Autopilot." Its purpose is to make the
task-board autopilot either produce a working green app or stop at the first
unrecoverable failure with a clear nonzero result.

## Phase 9C.1: Make The Autopilot Fail Hard

- Add `set -euo pipefail`.
- Stop on failed context import.
- Stop on failed admin commands.
- Exit nonzero when final validation fails.
- Print final report path and validation report path.
- Run final `status`, `compileall`, `pytest`, and `ruff` as hard gates.
- Never exit `0` unless the generated project is fully green.

## Phase 9C.2: Add Clean Runtime Reset

- Add `crazy-admin resetproject <id> --clean-runtime`, or
  `startproject --force --clean-runtime`.
- Clean generated source, generated tests, context catalog/imports, state,
  reports, factory tasks, approvals, validation reports, checkpoint state, and
  caches.
- Preserve owner seed/context files unless the owner explicitly requests
  destructive removal.
- Make the autopilot prove it is starting from a clean workbench.

## Phase 9C.3: Repair Context Ingestion

- Make `add-context` idempotent.
- Allocate fresh import ids from catalog plus disk state, support safe replace,
  delete/recreate the selected import, or rebuild catalog from existing imports.
- Rebuild catalog from existing imports if needed.
- Promote owner seed into `PROJECT_GOAL.md` for project bootstrap, or prove
  imported context is loaded into prompts.
- Fail if context import fails.
- Fail if `context/catalog.yaml` is empty after import.

## Phase 9C.4: Reject Incomplete Patches Before Apply

- Add deterministic placeholder-code detection.
- Add unused-import detection before apply or require ruff on patch preview.
- Reject self-admitted incomplete patches.
- Validate patch files before writing to the workbench.
- Reject tests without implementation and implementation without validation.

## Phase 9C.5: Implement Real Remediation Loop

- If validation fails and remediation is enabled, automatically advance until:
  - validation passes, or
  - remediation budget is exhausted.
- Print attempt number, failed command, exact failure delta, files proposed for
  repair, and validation result after repair.
- Exit nonzero on exhaustion.

## Phase 9C.6: Enforce Seed-Level Acceptance

- Check required files from seed/architecture.
- Check behavior-specific tests:
  - task creation,
  - edit title,
  - toggle done,
  - delete task,
  - JSON save/load,
  - missing file,
  - corrupt JSON,
  - UI smoke import/launch.
- Do not call the app complete until seed acceptance passes.
- Treat `data/tasks.json` carefully: require it after first save, or explicitly
  accept and test lazy creation.

## Phase 9C.7: Fix Reporting Truthfulness

- Distinguish planning only, proposal created, patch previewed, files created,
  files modified, files skipped, validation passed, validation failed,
  checkpoint blocked, and checkpoint created.
- Include context catalog status, required-file coverage, validation commands,
  final blocker/success, and actual files written.
- Remove unconditional "No application code was modified" reporting.

## Later Phase: Improve Builder Autonomy

- Add explicit demo/autopilot mode that can auto-approve low-risk local patches.
- Continue through checklist items until a milestone is green.
- Keep push, merge, branch deletion, and destructive git operations forbidden.
