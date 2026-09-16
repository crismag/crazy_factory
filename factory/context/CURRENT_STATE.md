# Current State

## Snapshot

As of 2026-09-16, Crazy Factory is a governed **task-execution
kernel** plus a closed-loop mission runner that selects a **current
execute objective** from remaining product gaps and observed
failures, a **P4a AgentExecutor** that can write workbench files
for the stdlib task-board proof seed, and a **P5a Director** that
is the owner-facing combination of product intelligence, mission
outcome, and one recommended next command.

It keeps calling the kernel until acceptance evidence, a genuine
human blocker, or a beat budget — without the owner cranking
`advance`. P4a proved `examples/seeds/task_board_web.md` from a
clean workbench reaches COMPLETE with runtime evidence. P5a names
the next MCP/CLI verb instead of dumping inspect JSON.

The execution audit is
[docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md](../../docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md).
The plan of record is [CF2_ARCHITECTURE.md](../CF2_ARCHITECTURE.md).
The MCP surface map is [CF2_MCP_SURFACE.md](../CF2_MCP_SURFACE.md).

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
- product kernel: inspect/assess (inventory; also feeds P2 objectives)
- P3 MCP `start_mission` accepts seed/context + target in one call;
  `get_status` / `inspect` include mission outcome, artifact, and trace
- P4a `AgentExecutor` (stdlib task-board actuator + optional Ollama
  file-map) writes workbench files under path confinement
- P5a Director (`crazy-admin brief`, MCP `director_brief` /
  `list_projects`; featured vs inventory MCP)
- P5b nested module loop (`focus_module`, `current_module.json`)
- tests (unit; live Ollama product builds are not in CI)

## Not Yet Available

- npm / node / browser journey inspection (P1 deferred)
- nested product-of-products (P2-05 remainder)
- Cursor / Codex / Claude executor adapters (P4-03)
- dynamic role/skill acquisition (P5-02)
- factory self-improvement that writes `scripts/` (P5-03)
- network MCP / auth (P3-04)

## Next State Transition

P5b is landed: the nested **module** loop finishes one module
(`focus_module` / `current_module.json`) before opening the next.
Remaining P5 is dynamic teams and self-improve — do not start those,
UI, or network MCP from this slice.
See [CF2_PHASE_TARGETS.md](../CF2_PHASE_TARGETS.md) and
[CF2_TASK_CHECKLIST.md](../CF2_TASK_CHECKLIST.md).
