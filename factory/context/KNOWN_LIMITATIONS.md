# Known Limitations

## Current Limitations

- `crazy-admin run` closes the **process loop**. A raw `--prompt`
  now compiles into a specified seed on `stdlib-web`. The coding
  plugin still needs a live model (or the stdlib actuator for the
  task-board proof). npm/browser journeys are still out of scope.
- Default owner switches remain OFF. `run` enables an isolated
  workbench profile; other projects and the safety floor stay gated.
- `max_files_per_run: 5` and `max_lines_per_file` still bound a single
  beat (product limiter, not safety).
- There is no running-product inspection (CLI journey / browser).
- MCP is stdio only; no network auth story. Mission tools wrap the
  runner; they are not a second engine.
- `skill_library.autofix_lint` requires a `ruff` binary on `PATH`.
- Host registry entries may point at machines that are not this one.
- `factory/` documentation historically lagged the runtime; CF 2.0
  docs are now the plan of record.

## Planned Capability Limitations

Future versions should assume:

- local models may produce inconsistent output
- context windows are finite
- scheduled sessions may overlap or fail
- repository state may change between sessions (humans/other agents)
- external integrations may be unavailable
- not every task can be validated automatically
- owner input remains necessary for consequential choices and for
  anything that mutates factory source or trust policy

## Handling Rule

Limitations must be reported honestly. The factory must not claim
completion when evidence is unavailable or replace missing context
with invention. Demo-readiness is evidence-based
(`acceptance_check` + mission trace), not task exhaustion or "files
were generated."
