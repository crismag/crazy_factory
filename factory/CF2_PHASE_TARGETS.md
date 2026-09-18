# Crazy Factory 2.0 — Phase-level targets

Living monitoring document. Update status here when a phase's
acceptance evidence changes. Do not skip ahead: P0 must stay `done`
before P5 work is selected.

Companion: [CF2_TASK_CHECKLIST.md](CF2_TASK_CHECKLIST.md) (task-level).
Plan: [CF2_ARCHITECTURE.md](CF2_ARCHITECTURE.md).
Audit: [../docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md](../docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md).

**Current phase:** ORCH-08 — packet consumes advisory patterns (`active`)
**Last updated:** 2026-09-18

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

- [ ] Live Ollama `run` on the benchmark (P1-09, not the starting coding model)
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
- [x] Runtime is probed every evaluation beat, not only after file acceptance
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
| Status | **done** (engine + module loop). Nested *product-of-products* remains out of scope. |
| Target | After success or failure, the Factory knows what remains and selects the next meaningful objective. |
| Success | Incomplete output does not look finished. Next work is a product gap, not merely “next file.” |
| Evidence | `scripts/objective_generator.py`, `tests/test_objective_generator.py`, mission `current_objective.json` |

Acceptance:

- [x] Evaluator states: COMPLETE / MORE_WORK / RECOVERABLE / HUMAN_REQUIRED / BUDGET
- [x] Product-kernel gaps can become the next EXECUTE objective
- [x] Checklist-as-filename is not the only progress signal (`current_objective.json` + planner block)
- [x] Repair objectives are created from observed failures (build/test/runtime)
- [x] `NO_PROGRESS` park produces a new objective or a justified HUMAN_REQUIRED, not a silent no-op
- [x] Nested module loop: EXECUTE stays on the first open module until VERIFIED

Not in this P2 slice:

- [ ] Nested product-of-products (multiple workbenches as one product)

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
| Status | **done** (P4a–P4f). Cursor/Codex IDE adapters and specialized roles remain deferred. |
| Target | Put strong coding systems in a position to succeed; independently judge the result. |
| Success | Crazy Factory owns mission/context/assignment/evaluate; the adapter owns implementation. |

Acceptance:

- [x] Agent executor interface (objective in, workbench files out)
- [x] One capable backend for the task-board proof (`StdlibWebExecutor`); Ollama file-map is opt-in
- [x] Claude (Anthropic) and OpenAI are the starting coding plugins; skip when no API key
- [x] Independent evaluator still decides PASS / MORE_WORK / BLOCKED
- [x] `examples/seeds/task_board_web.md` from a clean workbench → COMPLETE + runtime
- [x] Purpose-built execution assignment from evidence (not “implement this”)
- [x] Runtime is observed every evaluation beat; next objective reads executor files
- [x] Control intelligence persists attempts and decides outcome/kind/stance (rails veto)
- [ ] Specialized roles only where they measurably improve completion
- [ ] Cursor / Codex IDE adapters (P4-09)

P3 completion baseline: [CF2_P3_COMPLETION.md](CF2_P3_COMPLETION.md).
P4a completion baseline: [CF2_P4A_COMPLETION.md](CF2_P4A_COMPLETION.md).
P4c completion baseline: [CF2_P4C_COMPLETION.md](CF2_P4C_COMPLETION.md).
Intelligence map: [CF2_INTELLIGENCE.md](CF2_INTELLIGENCE.md).
P5a completion baseline: [CF2_P5_COMPLETION.md](CF2_P5_COMPLETION.md).

---

## P5 — Broader product intelligence

| | |
| --- | --- |
| Status | **done (P5-01 / P5b)**. Dynamic teams and factory self-improve stay deferred. |
| Target | Product-level convergence. The Director is what the owner talks to. |
| Rule | P0/P1 are finished; this slice does **not** include P5-02/P5-03, UI, or network MCP. |

Acceptance (P5a):

- [x] Director brief combines live inspect + mission snapshot + one next command
- [x] CLI `crazy-admin brief`
- [x] MCP `director_brief` / `list_projects` are featured; inspect/assess stay inventory
- [x] Featured vs inventory documented in [CF2_MCP_SURFACE.md](CF2_MCP_SURFACE.md)
- [x] `HUMAN_REQUIRED` does not recommend continue/start
- [x] `COMPLETE` is `done` (remaining product gaps are caveats)
- [x] Nested module loop: Director names `focus_module`; EXECUTE finishes it before the next
- [ ] Dynamic teams / skill registry (P5-02)
- [ ] Factory self-improvement that writes `scripts/` (P5-03)

---

## L0 — Prompt compiler + default web stack

| | |
| --- | --- |
| Status | **done** through L0-11. No-key generic CRUD is `RUNNABLE_PREVIEW`, not COMPLETE. Habit-class claims require behavioral evidence. AgentExecutor missions skip the Ollama planning-contract blocker. Vite-react remains later. |
| Target | A raw owner sentence becomes a specified factory seed on one executable web stack. |
| Success | `crazy-admin run id --prompt "…"` and MCP `start_mission.prompt` write Goal/Success + `architecture.json` instead of parking on `specify_intent`. Follow-up prompts on a specified product are deltas. |
| Evidence | `scripts/prompt_compiler.py`, live pack [prompt_build_2026-09-16](../docs/report/context/crazy-factory-2.0/prompt_build_2026-09-16/), [POST_L0_CAPABILITY_ASSESSMENT.md](../docs/report/context/crazy-factory-2.0/POST_L0_CAPABILITY_ASSESSMENT.md) |

Acceptance:

- [x] Unspecified prompt compiles to a non-placeholder seed
- [x] Structured Goal+Success seeds are left verbatim
- [x] `startproject` scaffold is not compiled until the owner supplies a prompt
- [x] Default stack is `stdlib-web` (`python3 -m src.app`, port 8765)
- [x] `vite-react` is recorded and not executable (npm still forbidden)
- [x] Claude/OpenAI fill screens when a key is present; pytest uses fallback
- [x] Hand-authored `architecture.json` is not overwritten
- [x] Preview-first: compiled `stdlib-web` workbenches get a reachable HTTP UI and `preview.json`
- [x] Conversational deltas on a running preview (L0-05)
- [x] Re-open mission on a new owner delta (L0-08)
- [x] Product-intent acceptance vs generic preview (L0-09)
- [x] Habit-class claims use runtime/persistence/visible evidence (L0-10)
- [x] AgentExecutor missions do not require an Ollama planning contract (L0-11)
- [ ] npm / Vite executable stack (P1-07 / L0-07)

---

## ORCH — Orchestration readiness

| | |
| --- | --- |
| Status | **active** (Slice 6). Patterns are advisory only. |
| Target | Bounded packet reads ranked catalog hits without outranking owner intent, architecture, or COMPLETE. |
| Success | `compile_assignment` attaches `pattern_ids` / `pattern_notes`; stale packets omit hits; scheduler/evidence/graph stay uncoupled. |
| Evidence | [CF2_ORCHESTRATION.md](CF2_ORCHESTRATION.md), `scripts/execution_assignment.py`, `tests/test_pattern_consume.py` |

Acceptance:

- [x] Current objective → assignment → executor → evidence path audited
- [x] Context authority documented (intent/evidence outrank planning prose)
- [x] Task graph persists beside `current_objective.json` without changing `next_execute_objective` priority
- [x] Nodes carry dependencies, claim ids, evidence targets, and context refs
- [x] No parallel coding, no specialist swarm, no pattern lock-in
- [x] Context packet (Slice 3)
- [x] Isolated task workspace (Slice 4)
- [x] Safe task-result integration (Slice 4B)
- [x] Opt-in isolated Codex task pipeline (Slice 4C)
- [x] Pattern library seed (Slice 5)
- [x] Task expansion consumes advisory pattern hits (Slice 6)
