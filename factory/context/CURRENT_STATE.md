# Current State

## Snapshot

As of 2026-09-16, Crazy Factory is a governed **task-execution
kernel** plus a closed-loop mission runner that selects a **current
execute objective** from remaining product gaps and observed
failures. It keeps calling the kernel until acceptance evidence, a
genuine human blocker, or a beat budget — without the owner
cranking `advance`.

It is not yet a prompt → working-application engine: a live coding
agent is still required to *write* the app. The factory can observe
a workbench start command, refuse COMPLETE when that command is
declared but does not run, and turn runtime/validation failures
into the next EXECUTE objective.

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
- P2 execute-objective generator (`current_objective.json`; wired into
  `advance` and the mission loop)
- product kernel: inspect/assess (also feeds P2 objectives)
- MCP stdio server including `start_mission` / `continue_mission` /
  `stop_mission` as wrappers around the runner
- tests (unit; live Ollama product builds are not in CI)

## Not Yet Available

- npm / node / browser journey inspection (P1 deferred)
- nested module/product loops (P2-05 deferred)
- coding-agent executor adapter (P4)
- dynamic role/skill acquisition (P5)

## Next State Transition

P2 engine is landed. Next: P3 `start` accepts context + target
(seed) in one call. Live Ollama task-board still needs P4.
See [CF2_PHASE_TARGETS.md](../CF2_PHASE_TARGETS.md) and
[CF2_TASK_CHECKLIST.md](../CF2_TASK_CHECKLIST.md).
