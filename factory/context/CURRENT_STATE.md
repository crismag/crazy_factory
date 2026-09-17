# Current State

## Snapshot

As of 2026-09-16, Crazy Factory is a governed **task-execution
kernel** plus a closed-loop mission runner that selects a **current
execute objective** from remaining product gaps and observed
failures, a **P4 AgentExecutor** that writes workbench files via
Claude / OpenAI coding plugins (or the stdlib task-board proof
actuator), and a **P5a Director** that is the owner-facing
combination of product intelligence, mission outcome, and one
recommended next command.

It keeps calling the kernel until acceptance evidence, a genuine
human blocker, or a beat budget — without the owner cranking
`advance`. P4a proved `examples/seeds/task_board_web.md` from a
clean workbench reaches COMPLETE with runtime evidence. P4c makes
Claude and OpenAI the starting coding plugins. P4d compiles a
purpose-built execution assignment from evidence so the plugin is
not asked to “implement this task.” P4e observes runtime every
evaluation beat (not only after file acceptance) and annotates the
next execute objective with what the coding plugin actually wrote.
P4f makes continuation, objective, stance, and quality **model
decisions** with attempt-log persistence; rails still veto stop,
budget, unsafe start, and fake COMPLETE.
P5a names the next MCP/CLI verb instead of dumping inspect JSON.
L0 compiles a raw owner prompt into a specified seed on the default
`stdlib-web` stack so a one-liner can enter the same loop.

The execution audit is
[docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md](../../docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md).
The plan of record is [CF2_ARCHITECTURE.md](../CF2_ARCHITECTURE.md).
The intelligence map is [CF2_INTELLIGENCE.md](../CF2_INTELLIGENCE.md).
The MCP surface map is [CF2_MCP_SURFACE.md](../CF2_MCP_SURFACE.md).
The default web stack is [CF2_WEB_STACK.md](../CF2_WEB_STACK.md).

## Available Assets

- factory contract, governance, roles, templates (operating context)
- Python CLI/runtime (`bin/crazy-admin`, `scripts/factory_advance.py`)
- project registry and per-workbench runtime
- context ingestion, task contracts, coder proposals, patch apply,
  validation, checkpoint, recovery/adjudication
- P0 mission runner (`crazy-admin run` / `stop`, workbench profile,
  `MISSION_TRACE.md`)
- P1 runtime observer (workbench-scoped start probe + `runtime_result.json`
  on every evaluation beat)
- P2 execute-objective generator (`current_objective.json`; wired into
  `advance` and the mission loop)
- product kernel: inspect/assess (inventory; also feeds P2 objectives)
- P3 MCP `start_mission` accepts prompt/seed/context + target in one
  call; `get_status` / `inspect` include mission outcome, artifact,
  and trace
- P4 `AgentExecutor` plus `execution_assignment` (purpose-built
  assignment from evidence; Claude/OpenAI plugins; stdlib actuator;
  next objective reads `executor_result.json`)
- P5a Director (`crazy-admin brief`, MCP `director_brief` /
  `list_projects`; featured vs inventory MCP)
- P5b nested module loop (`focus_module`, `current_module.json`)
- L0 prompt compiler (`crazy-admin run --prompt`, MCP `start_mission.prompt`)
  on the default `stdlib-web` stack
- L0-05 conversational deltas (`factory_tasks/deltas.jsonl`,
  `docs/deltas.md`; follow-up `--prompt` / `continue_mission.prompt`)
- tests (unit; live Ollama product builds are not in CI)
- post-L0 live prompt-build assessment
  ([POST_L0_CAPABILITY_ASSESSMENT.md](../../docs/report/context/crazy-factory-2.0/POST_L0_CAPABILITY_ASSESSMENT.md))

## Not Yet Available

- npm / node / browser journey inspection (P1 deferred)
- nested product-of-products (P2-05 remainder)
- Cursor / Codex IDE adapters (P4-09)
- KAE-Memory / vector “AI memory”
- LangChain / LangGraph / n8n / Cline
- live Ollama as the coding model (P1-09; not the starting path)
- Vite preview stack (L0-07)
- dynamic role/skill acquisition (P5-02)
- factory self-improvement that writes `scripts/` (P5-03)
- network MCP / auth (P3-04)

## Next State Transition

L0-01…L0-11 are landed. A no-key `--prompt "build a habit
tracker"` still compiles and serves a generic CRUD preview, but
that is **`RUNNABLE_PREVIEW`**, not product COMPLETE. A follow-up
prompt stays a delta, invalidates prior acceptance, and re-opens
the mission until the delta is VERIFIED against compiled claims.
AgentExecutor missions no longer false-stop on an inner Ollama
`planning_contract_rejected` leftover; the inner Coder chain still
requires an owner-authorized valid `planned_task.json`.
Orchestration Slice 4C is landed: an **opt-in** `isolated-task`
path runs one selected TaskNode through isolated workspace →
Codex/AgentExecutor (still read-only file map) → independent
collect → Factory apply → canonical validation → product evidence.
Default `factory_advance` / `crazy-admin run` still write the
canonical workbench. Next is assess the live isolated Codex beat,
then the pattern library. Do not start LangChain, UI, network MCP,
KAE-Memory, or parallel coding agents from this reading.
Evidence: [POST_L0_CAPABILITY_ASSESSMENT.md](../../docs/report/context/crazy-factory-2.0/POST_L0_CAPABILITY_ASSESSMENT.md).
See [CF2_PHASE_TARGETS.md](../CF2_PHASE_TARGETS.md) and
[CF2_TASK_CHECKLIST.md](../CF2_TASK_CHECKLIST.md).
