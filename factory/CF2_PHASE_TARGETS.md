# Crazy Factory 2.0 — Phase-level targets

Living monitoring document. Update status here when a phase's
acceptance evidence changes. Do not skip ahead: P0 must stay `done`
before P5 work is selected.

Companion: [CF2_TASK_CHECKLIST.md](CF2_TASK_CHECKLIST.md) (task-level).
Plan: [CF2_ARCHITECTURE.md](CF2_ARCHITECTURE.md).
Audit: [../docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md](../docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md).

**Current phase:** P4b — owner path + repair (P4a `done`)
**Last updated:** 2026-09-16

Status vocabulary: `done` · `active` · `planned` · `deferred`

---

## P0 — Closed autonomous execution loop

| | |
| --- | --- |
| Status | **done** (engine). Product completion is P1. |
| Target | Given a bounded context, the Factory keeps working without the owner calling `advance` between normal steps. |
| Success | `context → work → observe → evaluate → continue` until COMPLETE, HUMAN_REQUIRED, or BUDGET. |
| Evidence | `scripts/mission_runner.py`, `crazy-admin run` / `stop`, `tests/test_mission_runner.py`, `MISSION_TRACE.md` |

Acceptance (all met):

- [x] Isolated workbench profile enables apply + validation + remediation + autonomy
- [x] Profile does **not** enable delete, push, or merge
- [x] Already-accepted workbench → `run` exits 0 with **zero** beats
- [x] Greenfield workbench continues until budget (no Ollama required)
- [x] Human blockers stop the loop (`self_rejection`, `needs_owner_decision`, recovery/remediation exhausted, stop/pause)
- [x] Beat budget is a hard stop
- [x] Mission writes `MISSION_TRACE.md` + `mission_result.json`
- [x] Acceptance evaluation is CWD-independent (paths resolve against factory root)
- [x] MCP `start_mission` / `continue_mission` / `stop_mission` wrap the same runner

Not in P0 (deliberately):

- [ ] Live Ollama/coding-agent produces a working app (P1/P4)
- [ ] Install / build / start tools (P1)
- [x] Remaining-gap objectives drive EXECUTE (P2)

---

## P1 — Runnable output

| | |
| --- | --- |
| Status | **done** (observer). npm remains out of scope. |
| Target | The Factory can produce and **independently validate** an actual application, not just source files. |
| Success | Observer records compile/test **and** start/runtime evidence. Failures feed the same P0 loop as MORE_WORK / RECOVERABLE. |
| Evidence | `scripts/runtime_observer.py`, pip `-r` allowlist, `tests/test_runtime_observer.py` |

Acceptance:

- [x] Workbench-scoped start command can be discovered and executed
- [x] Start commands outside the workbench, `python3 -c`, pip-except-requirements, npm, curl, sudo are refused
- [x] `python3 -m pip install -r requirements.txt` is allowlisted (requirements file must sit in the workbench); arbitrary `pip install pkg` stays blocked
- [x] Runtime result is persisted (`runtime_result.json`) and appears in the mission trace
- [x] Accepted files **plus** a failing start command → MORE_WORK (not COMPLETE)
- [x] Accepted files **without** a start command still COMPLETE (P0 engine tests)
- [x] Documented listen port is probed over HTTP on 127.0.0.1
- [x] Started process is always terminated after the probe
- [ ] npm / node / webpack remain **out of scope** until the stdlib benchmark passes
- [x] Task-board seed can be compiled, tested, and started when implementation exists

---

## P2 — Reliable convergence

| | |
| --- | --- |
| Status | **done** (engine). Nested module loops remain deferred. |
| Target | After success or failure, the Factory knows what remains and selects the next meaningful objective. |
| Success | Incomplete output does not look finished. Next work is a product gap, not merely “next file.” |
| Evidence | `scripts/objective_generator.py`, `tests/test_objective_generator.py`, mission `current_objective.json` |

Acceptance:

- [x] Evaluator states: COMPLETE / MORE_WORK / RECOVERABLE / HUMAN_REQUIRED / BUDGET
- [x] Product-kernel gaps can become the next EXECUTE objective
- [x] Checklist-as-filename is not the only progress signal (`current_objective.json` + planner block)
- [x] Repair objectives are created from observed failures (build/test/runtime)
- [x] `NO_PROGRESS` park produces a new objective or a justified HUMAN_REQUIRED, not a silent no-op

Not in this P2 slice:

- [ ] Nested module/product loops (P2-05, deferred)

---

## P3 — External invocation

| | |
| --- | --- |
| Status | **done** (engine). Network MCP/auth remains deferred. |
| Target | MCP exposes the **working** engine. |
| Success | `start()` initiates a genuine persistent mission. MCP is not a remote copy of the incomplete workflow. |

Acceptance:

- [x] `start_mission` / `continue_mission` / `stop_mission` / `get_status` exist
- [x] `start` can take context + target in one call (seed ingest)
- [x] `inspect` / `status` report mission outcome + artifact + trace
- [x] Stdio MCP remains the transport; no implied network auth story yet

---

## P4 — Better agents

| | |
| --- | --- |
| Status | **done** (P4a). Cursor/Codex/Claude adapters and specialized roles remain deferred. |
| Target | Delegate low-level coding to a capable agent behind an adapter. |
| Success | Crazy Factory owns mission/evaluate/tools; the adapter owns implementation. |

Acceptance:

- [x] Agent executor interface (objective in, workbench files out)
- [x] One capable backend for the task-board proof (`StdlibWebExecutor`); Ollama file-map skips when down
- [x] Independent evaluator still decides PASS / MORE_WORK / BLOCKED
- [x] `examples/seeds/task_board_web.md` from a clean workbench → COMPLETE + runtime
- [ ] Specialized roles only where they measurably improve completion

P3 completion baseline: [CF2_P3_COMPLETION.md](CF2_P3_COMPLETION.md).
P4a completion baseline: [CF2_P4A_COMPLETION.md](CF2_P4A_COMPLETION.md).
Do not start P5, UI, extra MCP, or a multi-agent org from this slice.

---

## P5 — Broader product intelligence

| | |
| --- | --- |
| Status | `deferred` |
| Target | Product-level convergence, dynamic teams, self-improving capabilities. |
| Rule | **Do not begin P5 while P0/P1 remain unfinished.** |

Inspect/assess/MCP inventory from Slice A may stay in the tree. It is not
the development focus.
