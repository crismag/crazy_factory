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

## P3 — MCP wraps the working engine

### Objective

External callers start a genuine mission with context + target in
one call. Status and inspect report the mission outcome, artifact,
and trace — not just pipeline capabilities or product-kernel gaps.

### Changed

`scripts/mcp_server.py` (`start_mission` seed/context/target;
`inspect_project` / `get_status` include `mission`),
`scripts/crazy_admin.py` (`ensure_project`, `ingest_start_context`;
CLI inspect/status show mission), `scripts/mission_runner.py`
(`load_mission_snapshot`).

### Acceptance

- Unregistered `project_id` is created; seed file or inline context
  lands in `docs/seed.md` and is ingested before the loop starts.
- Missing seed is an MCP error (mission does not run).
- After a run, `get_status` and `inspect_project` (and CLI
  `status` / `inspect --json`) include outcome, artifact, and trace.
- Transport stays stdio JSON-RPC; no network auth.

---

## P4a — Minimal AgentExecutor + first autonomous application build

### Objective

Prove `context → Crazy Factory → runnable accepted application` on
`examples/seeds/task_board_web.md`. P0–P3 already provide mission,
continuation, runtime observation, remaining-gap objectives, and
MCP start. P4a is the missing implementation actuator:

`objective → AgentExecutor → coding-agent backend → workbench files
→ existing validation/runtime observation → existing evaluation
→ repair/next objective → repeat`

Do **not** build roles/skills/subagent organization. Do not start
P5, UI, or extra MCP.

### New

`scripts/agent_executor.py` (`AgentExecutor`, `LlmFileExecutor`,
`StdlibWebExecutor`, `ChainedExecutor`),
`examples/actuators/stdlib_task_board/`,
`tests/test_agent_executor.py`.

### Changed

`scripts/factory_advance.py` (apply executor after in-process apply,
reload architecture contract, validate, mark checklist complete),
`scripts/completion.py` (`mark_all_open_done`).

### Acceptance

- Provider-neutral executor contract (request in, files out).
- Path confinement: no engine `scripts/` / `factory/` writes.
- Task-board seed from a clean workbench → COMPLETE + HTTP runtime
  without ordinary owner intervention.
- Failures remain MORE_WORK / repair objectives, not silent success.
- Unnecessary HUMAN_REQUIRED is an automation defect.

---

## P5a — Director + featured MCP

### Objective

The owner talks to the Director. Product intelligence (inspect/assess)
plus the mission snapshot become one brief with a recommended next
command. MCP is split into featured vs inventory so clients do not
treat the Slice A dump as the product.

Do **not** build dynamic teams, factory self-mutation, or UI.

### New

`scripts/director.py`, `factory/CF2_MCP_SURFACE.md`,
`tests/test_director.py`.

### Changed

`scripts/mcp_server.py` (`director_brief`, `list_projects`, featured
first), `scripts/crazy_admin.py` (`brief`).

### Acceptance

- Placeholder seed → `provide_context` / `start_mission` with a real seed.
- Real seed, no mission → `start`.
- `BUDGET_EXHAUSTED` / remaining work → `continue_mission`.
- `HUMAN_REQUIRED` → `human` (does not recommend start/continue).
- `COMPLETE` → `done` (remaining product gaps are caveats).
- Empty registry → `import_project`; several projects → `pick_project`.

---

## P5b — Nested module loop

### Objective

Product intelligence already lists every module. EXECUTE used to jump
to the first *blocking* gap anywhere, so a stub in module B could
pre-empt finishing module A. The inner loop is now: stay on the first
open module until it is VERIFIED, then open the next. Repair still
outranks. Product-level gaps (placeholder, code birth, architecture,
validation) still outrank.

Do **not** build dynamic teams, factory self-mutation, or UI.

### Changed

`scripts/product_kernel.py` (`select_focus_module`),
`scripts/objective_generator.py` (`current_module.json`, execute
`module=`), `scripts/director.py` (`focus_module` in the brief),
`scripts/mission_runner.py` (snapshot).

### Acceptance

- Two-module workbench: first open module is `todo` even when `storage`
  is a blocking stub.
- After `todo` is VERIFIED, EXECUTE moves to `storage`.
- Director brief names `focus_module`.
- Inspect still lists every module's objectives (inventory stays complete).

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
