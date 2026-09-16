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

Live Ollama `run` on the benchmark is P1 (coding agent + install/
build/start tools). P0 proves the **arrows**, not a shipped app.

---

## Slice A — Product intelligence service (P2/P5 inventory)

### Objective

Inspect a project, compare intended vs observable product, persist
that intelligence, emit objectives, and expose it over CLI and MCP —
without rewriting the advance loop and without Ollama.

This remains useful. It is **not** the current development priority.

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
