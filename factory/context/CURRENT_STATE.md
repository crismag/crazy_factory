# Current State

## Snapshot

As of 2026-09-16, Crazy Factory is a governed **task-execution
kernel** plus a P0 **closed-loop mission runner**. It can keep
calling the kernel until acceptance evidence, a genuine human
blocker, or a beat budget — without the owner cranking `advance`.

It is not yet a prompt → working-application engine: a live coding
agent is still required to *write* the app. The factory can now
observe a workbench start command and refuse COMPLETE when that
command is declared but does not run.

The execution audit is
[docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md](../../docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md).
The plan of record is [CF2_ARCHITECTURE.md](../CF2_ARCHITECTURE.md).

## Available Assets

- factory contract, governance, roles, templates (operating context)
- Python CLI/runtime (`bin/crazy-admin`, `scripts/factory_advance.py`)
- project registry and per-workbench runtime
- context ingestion, task contracts, coder proposals, patch apply,
  validation, checkpoint, recovery/adjudication
- P0 mission runner (`crazy-admin run` / `stop`, workbench profile,
  `MISSION_TRACE.md`)
- P1 runtime observer (workbench-scoped start probe + `runtime_result.json`)
- product kernel: inspect/assess (P2/P5 inventory, not the loop)
- MCP stdio server including `start_mission` / `continue_mission` /
  `stop_mission` as wrappers around the runner
- tests (unit; live Ollama product builds are not in CI)

## Not Yet Available

- npm / node / browser journey inspection (P1 deferred)
- remaining-gap objectives driving EXECUTE (P2)
- coding-agent executor adapter (P4)
- dynamic role/skill acquisition (P5)

## Next State Transition

P1 (active): runtime observer + workbench-scoped start/install.
See [CF2_PHASE_TARGETS.md](../CF2_PHASE_TARGETS.md) and
[CF2_TASK_CHECKLIST.md](../CF2_TASK_CHECKLIST.md).
