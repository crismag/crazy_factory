# Crazy Factory 2.0 — Task and development checklist

Living TODO. Check items off only with evidence (test, artifact, or
trace). Phase gates live in [CF2_PHASE_TARGETS.md](CF2_PHASE_TARGETS.md).

**Current focus:** `CF2-P2-01` Objective generator (P1 observer landed; live seed build still needs a coding agent)
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

## P1 — Runnable output (active)

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
| CF2-P1-09 | DEFERRED | Live Ollama `run` on `task_board_web` yields a runnable app | needs P4 or a live model |

---

## P2 — Convergence

| ID | Status | Task |
| --- | --- | --- |
| CF2-P2-01 | PLANNED | Objective generator: current gap → next EXECUTE goal |
| CF2-P2-02 | PLANNED | Wire product-kernel objectives into `advance` / mission |
| CF2-P2-03 | PLANNED | Repair objective from validation/runtime failure |
| CF2-P2-04 | PLANNED | Replace silent `NO_PROGRESS` park with recover-or-human |
| CF2-P2-05 | DEFERRED | Nested module/product loops |

---

## P3 — MCP around the working engine

| ID | Status | Task |
| --- | --- | --- |
| CF2-P3-01 | DONE | Thin `start_mission` / `continue_mission` / `stop_mission` |
| CF2-P3-02 | PLANNED | `start` accepts context + target (seed) in one call |
| CF2-P3-03 | PLANNED | `status` / `inspect` return mission outcome, artifact, trace |
| CF2-P3-04 | DEFERRED | Network MCP / auth |

---

## P4 — Agent executor

| ID | Status | Task |
| --- | --- | --- |
| CF2-P4-01 | PLANNED | `AgentExecutor` interface (objective + contract → workbench result) |
| CF2-P4-02 | PLANNED | Default adapter = in-process Coder |
| CF2-P4-03 | DEFERRED | Cursor / Codex / Claude adapter |
| CF2-P4-04 | DEFERRED | Specialized roles only with measured gain |

---

## P5 — Product intelligence (do not start)

| ID | Status | Task |
| --- | --- | --- |
| CF2-P5-01 | DEFERRED | Director as the thing the owner talks to |
| CF2-P5-02 | DEFERRED | Dynamic teams / skill registry |
| CF2-P5-03 | DEFERRED | Factory self-improvement that writes `scripts/` |
| CF2-P5-04 | DONE (inventory) | `inspect` / `assess` / product kernel exist; not the priority |

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
