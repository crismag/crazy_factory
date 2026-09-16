# Crazy Factory 2.0 — Migration and slice tasks

## Strategy

Additive. The execution kernel keeps working as one beat. P0 adds an
in-process continuation controller around it. Product-intelligence
files under each workbench's `factory_state/` remain optional inspect
artifacts, not the thing that makes software.

## P0 — Closed autonomous execution loop

### Objective

Prove the factory can accept a bounded context and keep executing
until acceptance evidence is complete, a genuine human blocker is
set, or the beat budget is spent — without the owner calling
`advance` between normal steps.

### Reused

`factory_advance.main` (one beat), `owner_controls.set_capability`,
`acceptance_check.evaluate_acceptance`, `workbench_growth`,
`flags`, `mission_state.load_state`.

### Changed

`scripts/crazy_admin.py` (`run` / `stop`), `docs/USAGE.md`,
`factory/context/*`, `factory/CF2_ARCHITECTURE.md` (P0-first).

### New

`scripts/mission_runner.py`, `examples/seeds/task_board_web.md`,
`tests/test_mission_runner.py`, P0 audit document.

### Acceptance

- Already-accepted workbench → `run` exits 0, **zero** beats.
- Greenfield workbench → continues until budget (no Ollama required
  when `advance` is injected / kernel fallbacks do not ship code).
- Human blocker (`self_rejection`, `needs_owner_decision`,
  `recovery_exhausted`, `remediation_exhausted`) → stop, no further
  beats.
- Workbench profile enables apply/validation/remediation/autonomy
  and does **not** enable delete, push, or merge.
- `MISSION_TRACE.md` + `mission_result.json` written under reports.

### Risks

Live Ollama `run` on the benchmark is P1 (coding agent). P0 proves
the **arrows**, not a shipped app. P1 adds a workbench runtime
observer so file-only acceptance is not mistaken for a running app.

---

## P1 — Runnable output (active)

### Objective

Independently observe whether the workbench application can be
started, and allow a bounded `pip install -r requirements.txt` inside
the workbench. Failures return to the P0 loop as MORE_WORK.

### New

`scripts/runtime_observer.py`, `tests/test_runtime_observer.py`.

### Changed

`scripts/mission_runner.py` (runtime gate after acceptance),
`scripts/validation_runner.py` (pip -r allowlist),
`architecture.json` optional `start_command` / `listen_port`.

### Acceptance

- No start command → COMPLETE still allowed (P0 engine tests).
- Declared start targeting a missing module → MORE_WORK, not COMPLETE.
- `python3 -c` / `pip install pkg` / npm stay blocked.
- HTTP listen_port is probed on 127.0.0.1; process is killed after.

---

## P2 — Remaining-gap objectives drive EXECUTE

### Objective

Turn observed product gaps and failures into **one** next execute
objective. EXECUTE plans that gap, not merely the next checklist
filename. A silent `NO_PROGRESS` park is not a product decision:
retry once with a repair objective, then escalate to HUMAN_REQUIRED.

### Reused

`product_kernel.inspect_project`, `workbench_growth`,
`runtime_result.json`, `validation_result.json`, `progress_blocker`.

### Changed

`scripts/factory_advance.py` (inject objective into planner context;
`handle_no_progress` retry-then-park),
`scripts/mission_runner.py` (`_select_objective`; `no_progress` →
`HUMAN_REQUIRED`).

### New

`scripts/objective_generator.py`, `tests/test_objective_generator.py`.

### Acceptance

- Greenfield / placeholder seed → `code_birth` or `specify_intent`.
- Runtime or validation failure outranks product-kernel gaps.
- `current_objective.json` is persisted and appears in the mission trace.
- First `NO_PROGRESS` streak retries; second parks as HUMAN_REQUIRED.

---

## Slice A — Product intelligence service (P2/P5 inventory)

### Objective

Inspect a project, compare intended vs observable product, persist
that intelligence, emit objectives, and expose it over CLI and MCP —
without rewriting the advance loop and without Ollama.

This remains useful as inspect/assess inventory. EXECUTE now consumes
a generated objective (see P2 above); Slice A is not itself the loop.

### Reused

`project_contract.parse_seed`, `architecture.load_contract`,
`workbench_growth.workbench_metrics`, `acceptance_check.evaluate_acceptance`,
`completion.parse_checklist`, `crazy_admin` targeting, workbench paths.

### Changed

`scripts/crazy_admin.py` (inspect/assess/serve-mcp), `docs/USAGE.md`.

### New

`scripts/product_kernel.py`, `scripts/mcp_server.py`,
`bin/crazy-factory-mcp`, tests.

### Tests

`tests/test_product_kernel.py`, `tests/test_mcp_server.py`,
`tests/test_mission_runner.py`. Full unit suite must stay at the
recorded baseline plus the new P0/inspect tests.

### Rollback

Revert this branch.
