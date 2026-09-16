# Crazy Factory 2.0 — Task and development checklist

Living TODO. Check items off only with evidence (test, artifact, or
trace). Phase gates live in [CF2_PHASE_TARGETS.md](CF2_PHASE_TARGETS.md).

**Current focus:** L0 prompt compiler + default `stdlib-web` stack landed
**Last updated:** 2026-09-16

Status: `DONE` · `ACTIVE` · `PLANNED` · `DEFERRED`

---

## P0 — Closed loop

| ID | Status | Task | Evidence |
| --- | --- | --- | --- |
| CF2-P0-01 | DONE | Isolated workbench autonomous profile | `enable_workbench_profile` |
| CF2-P0-02 | DONE | Mission runner loop + evaluator | `scripts/mission_runner.py` |
| CF2-P0-03 | DONE | `crazy-admin run` / `stop` | `scripts/crazy_admin.py` |
| CF2-P0-04 | DONE | Engine tests (complete / human / budget / trace) | `tests/test_mission_runner.py` |
| CF2-P0-05 | DONE | Task-board benchmark seed | `examples/seeds/task_board_web.md` |
| CF2-P0-06 | DONE | MCP wrappers for start/continue/stop | `scripts/mcp_server.py` |
| CF2-P0-07 | DONE | Acceptance paths resolve against factory root | `scripts/acceptance_check.py` |
| CF2-P0-08 | DONE | Safety floor documented (keep vs scaffolding) | `P0_AUTONOMOUS_LOOP.md` §4 |

---

## P1 — Runnable output

| ID | Status | Task | Notes |
| --- | --- | --- | --- |
| CF2-P1-01 | DONE | Runtime observer: discover, confine, start, probe, kill | `scripts/runtime_observer.py` |
| CF2-P1-02 | DONE | Persist `runtime_result.json` + trace line | mission runner + observer |
| CF2-P1-03 | DONE | Failing start → MORE_WORK (not COMPLETE when start is declared) | `evaluate_mission` |
| CF2-P1-04 | DONE | Allowlist `python3 -m pip install -r requirements.txt` only | `validation_runner.py` |
| CF2-P1-05 | DONE | Architecture contract optional `start_command` / `listen_port` | `architecture.json` |
| CF2-P1-06 | DONE | Default compileall + pytest remain the validation floor | already allowlisted |
| CF2-P1-07 | DEFERRED | npm / node / webpack / vitest allowlist | after stdlib benchmark |
| CF2-P1-08 | DEFERRED | Browser / visual journey inspection | P1+ / Playwright later |
| CF2-P1-09 | DEFERRED | Live Ollama `run` on `task_board_web` | not the starting coding model; Claude/OpenAI are P4-03 |

---

## P2 — Convergence (engine)

| ID | Status | Task | Evidence |
| --- | --- | --- | --- |
| CF2-P2-01 | DONE | Objective generator: current gap → next EXECUTE goal | `scripts/objective_generator.py` |
| CF2-P2-02 | DONE | Wire product-kernel objectives into `advance` / mission | `factory_advance` + `mission_runner._select_objective` |
| CF2-P2-03 | DONE | Repair objective from validation/runtime failure | runtime/validation outrank product gaps |
| CF2-P2-04 | DONE | Replace silent `NO_PROGRESS` park with recover-or-human | first trip retry + `HUMAN_REQUIRED` |
| CF2-P2-05 | DONE | Nested module loop (one module to VERIFIED, then the next) | `select_focus_module`, `current_module.json` |

---

## P3 — MCP around the working engine

| ID | Status | Task | Evidence |
| --- | --- | --- | --- |
| CF2-P3-01 | DONE | Thin `start_mission` / `continue_mission` / `stop_mission` | `scripts/mcp_server.py` |
| CF2-P3-02 | DONE | `start` accepts context + target (seed) in one call | `start_mission` seed/context/target |
| CF2-P3-03 | DONE | `status` / `inspect` return mission outcome, artifact, trace | `load_mission_snapshot` |
| CF2-P3-04 | DEFERRED | Network MCP / auth | |

---

## P4 — Agent executor (P4a–P4f)

| ID | Status | Task | Evidence |
| --- | --- | --- | --- |
| CF2-P4-01 | DONE | `AgentExecutor` interface (objective + failures → workbench files) | `scripts/agent_executor.py` |
| CF2-P4-02 | DONE | One capable backend (stdlib task-board actuator; Ollama file-map opt-in) | `StdlibWebExecutor` + `LlmFileExecutor` |
| CF2-P4-03 | DONE | Claude / OpenAI coding plugins (Lovable-like intelligence, skip if no key) | `CloudCodingExecutor`, `scripts/coding_llm.py` |
| CF2-P4-04 | DEFERRED | Specialized roles only with measured gain | not this slice |
| CF2-P4-05 | DONE | `examples/seeds/task_board_web.md` → runnable accepted app | `tests/test_agent_executor.py` |
| CF2-P4-06 | DONE | Default chain (no cloud key → stdlib actuator) without env flag | `DefaultExecutorTests` |
| CF2-P4-07 | DONE | Failed workbench repaired on the next beat (no HUMAN_REQUIRED) | repair test |
| CF2-P4-08 | DONE | `crazy-admin run --seed` and MCP `start_mission` reach COMPLETE | owner-path tests |
| CF2-P4-09 | DEFERRED | Cursor / Codex IDE adapters | later providers; not MCP verbs |
| CF2-P4-10 | DONE | Purpose-built execution assignment from evidence (not “implement this”) | `execution_assignment.py`, `executor_slice` |
| CF2-P4-11 | DONE | Observe runtime every beat; next objective reads `executor_result.json` | `evaluate_mission` + `_annotate_with_executor` |
| CF2-P4-12 | DONE | Agentic control: attempt log, working memory, model-decided beats | `control_intelligence.py` |

---

## P5 — Product intelligence

| ID | Status | Task | Evidence |
| --- | --- | --- | --- |
| CF2-P5-01 | DONE | Director as the thing the owner talks to | `scripts/director.py`, `crazy-admin brief`, MCP `director_brief` |
| CF2-P5-02 | DEFERRED | Dynamic teams / skill registry | |
| CF2-P5-03 | DEFERRED | Factory self-improvement that writes `scripts/` | |
| CF2-P5-04 | DONE | `inspect` / `assess` inventory; featured MCP mapped | [CF2_MCP_SURFACE.md](CF2_MCP_SURFACE.md) |
| CF2-P5-05 | DONE | Featured MCP: `director_brief`, `list_projects`; inventory stays | `scripts/mcp_server.py` |
| CF2-P5-06 | DONE | Nested module loop in Director + EXECUTE | `focus_module` in brief; execute stays on one module |

---

## L0 — Prompt compiler + default web stack

| ID | Status | Task | Evidence |
| --- | --- | --- | --- |
| CF2-L0-01 | DONE | Raw owner prompt → specified seed + architecture | `scripts/prompt_compiler.py`, `tests/test_prompt_compiler.py` |
| CF2-L0-02 | DONE | Default executable stack `stdlib-web`; `vite-react` recorded successor | `scripts/web_stack.py`, [CF2_WEB_STACK.md](CF2_WEB_STACK.md) |
| CF2-L0-03 | DONE | CLI `--prompt` and MCP `start_mission.prompt` | `crazy_admin.py`, `mcp_server.py` |
| CF2-L0-04 | PLANNED | Preview-first loop (serve + observe the compiled stack every beat) | observer already probes; product preview UX later |
| CF2-L0-05 | DEFERRED | Conversational deltas on a running preview | after L0-04 |
| CF2-L0-06 | DEFERRED | Drop-in MCP “any prompt” productization | after compiler + stack proof |
| CF2-L0-07 | DEFERRED | `vite-react` executable (npm confine + probe) | P1-07 |

---

## Safety floor (never uncheck to “make it work”)

- [x] No auto-push / auto-merge / force-push / history rewrite
- [x] Path confinement to the assigned workbench
- [x] Secret / credential path blocks
- [x] No `sudo`, `rm -rf`, shell metacharacters in validation
- [x] Deletes default OFF
- [x] Factory must not write engine source

---

## How to update this file

1. Move `Current focus` to the next `PLANNED` item in the active phase.
2. Set the finished item to `DONE` and cite evidence.
3. Mirror the phase status in `CF2_PHASE_TARGETS.md`.
4. Do not mark a phase `done` because files were generated.
