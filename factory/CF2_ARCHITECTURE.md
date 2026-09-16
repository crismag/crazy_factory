# Crazy Factory 2.0 — Target Architecture

Plan of record for the restart. Historical phase packages under
`docs/report/context/` remain evidence, not the plan. The execution
audit is
[`docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md`](../docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md).
The broader repository assessment is
[`docs/report/context/crazy-factory-2.0/ASSESSMENT.md`](../docs/report/context/crazy-factory-2.0/ASSESSMENT.md).

## Immediate product

Crazy Factory is an intelligence-driven software-creation system:
incomplete human intent becomes coherent, demonstrable working
software through understanding, investigation, planning, execution,
observation, judgment, and iterative improvement. It is **not** a
clone of Lovable or any other builder.

The factory owns mission, context construction, assignment quality,
observation, and judgment. Coding models (Claude, OpenAI, later
others) are replaceable workers. MCP is the external machinery.
Capability first, architecture second, technology third — see
[CF2_INTELLIGENCE.md](CF2_INTELLIGENCE.md).

Closed-loop continuation remains mandatory: keep working until a
runnable, validated application exists, or a justified human
blocker. UI, dashboards, and multi-agent theater are not the
milestone.

## Essential state machine

```text
Prompt / Context
    → Mission
    → Understand
    → Plan
    → Execute
    → Observe
    → Evaluate
    → Recover / Continue
    → Execute …
    until ACCEPTED OUTPUT
```

Operationally:

`ASSESS → OBJECTIVE → EXECUTE → VALIDATE → EVALUATE`

Then:

- `EVALUATE → COMPLETE`
- `EVALUATE → OBJECTIVE`
- `EVALUATE → RECOVER → OBJECTIVE`
- `EVALUATE → HUMAN_REQUIRED`
- `EVALUATE → BUDGET_EXHAUSTED`

Architect / Planner / Coder / Test / Reviewer live **under EXECUTE**.
They must not be the thing the owner cranks with `advance`.

## Priority order

| Pri | Meaning | Status on this branch |
| --- | --- | --- |
| **P0** | Closed loop: context → work → observe → repair → continue | `scripts/mission_runner.py`, `crazy-admin run` |
| **P1** | Runnable output (install/build/start tools + inspect) | `done` (observer) |
| **P2** | Convergence: remaining gaps become the next objective | `done` (engine; `objective_generator`) |
| **P3** | External invocation: MCP wraps the working engine | `done` (`start` + seed; inspect/status report mission) |
| **P4** | Better agents: coding-agent adapter, then specialized roles | **done (P4a–P4e)**; Cursor/Codex IDE adapters deferred |
| **P5** | Broader product intelligence, dynamic teams, self-improve | **done (P5-01 Director)**; P5-02/P5-03 deferred |

P5-01 is the Director (owner-facing brief + featured MCP). Do not
start dynamic teams, factory self-mutation, or UI from this slice.
Phase and task checklists: [CF2_PHASE_TARGETS.md](CF2_PHASE_TARGETS.md),
[CF2_TASK_CHECKLIST.md](CF2_TASK_CHECKLIST.md).
MCP surface: [CF2_MCP_SURFACE.md](CF2_MCP_SURFACE.md).

## P0 shape (what this slice owns)

```text
crazy-admin run <id> [--seed FILE]
  apply WORKBENCH_AUTONOMOUS profile   # apply+validate+remediate+autonomy
                                       # safety floor intact (no push/merge/
                                       # delete, no engine writes, path confine)
  loop until COMPLETE | HUMAN_REQUIRED | BUDGET:
      EVALUATE (acceptance, growth, blocker, runtime probe)
      if not terminal:
          EXECUTE = one factory_advance beat (existing kernel)
          OBSERVE = validation_result + workbench_metrics + runtime_observer
          TRACE   append MISSION_TRACE.md
  report artifact or justified blocker
```

The workbench autonomous profile is **development-scaffolding inverted
for one isolated project**. It is not a license to disable the safety
floor.

## What Crazy Factory must own vs delegate

| Own | Delegate (later coding-agent adapter) |
| --- | --- |
| Mission + continuation | Token-level code edits |
| Isolated workbench + safety floor | Multi-file implementation |
| Objective + acceptance contract | Framework/idiom knowledge |
| Tool execution (tests; later build/start) | Generating the patch |
| Independent evaluate | Self-talk about quality |
| Trace / report | — |
| Stop for genuine human authority | — |

Today the in-process Coder remains a kernel stage. P4 adds a
provider-neutral `AgentExecutor`. The factory compiles a
purpose-built `ExecutionAssignment` from existing evidence
(`scripts/execution_assignment.py`) before any coding plugin runs.
Claude and OpenAI remain workers, not the architecture. The stdlib
task-board actuator remains the deterministic proof backend. Ollama
is opt-in. Do not grow a multi-agent org in this slice.

## Nested loops (later, not first)

| Loop | Cycle | When |
| --- | --- | --- |
| Task | implement → test → review → repair | existing `factory_advance` under EXECUTE |
| Module | discover → specify → … → verify | P5b (`select_focus_module`) |
| Product | understand → assess → objectives → inspect | P2/P5 |
| Factory | capability gap → acquire → validate | postponed; owner-gated |

Maturity remains **derived from evidence**, not a workflow you step.

## Public interface

P0 CLI: `crazy-admin run|stop` (plus existing `advance` for one beat).
P5 CLI: `crazy-admin brief` (Director: product + mission + next command).

P3 MCP, wrapping the engine, never replacing it. P5a splits the
surface into **featured** vs **inventory**
([CF2_MCP_SURFACE.md](CF2_MCP_SURFACE.md)):

Featured (owner / Director conversation):

`director_brief` → intended product + mission + one next command

`list_projects` → registered workbenches + last mission outcome

`crazy_factory.start(context, target)` → `start_mission`
(seed path, inline context, and optional workbench path)

`crazy_factory.status(project)` → `get_status`
(includes mission outcome, artifact, trace)

`crazy_factory.continue(project)` → `continue_mission`

`crazy_factory.stop(project)` → `stop_mission`

Inventory (power-user): `inspect_project`, `assess_project`,
`advance_project`, `import_project`, `provide_context`, `get_findings`,
`get_objectives`, `reconcile_project`.

MCP without the execution engine would only expose the incomplete
workflow remotely. Slice A's inspect/assess tools remain inventory;
the Director is the conversation.

## What stays deterministic

Path confinement, git floor (no push/merge/delete/history rewrite),
secrets, schema, retry budgets, owner stop/pause, persistence, MCP
read vs write. Capability switches default OFF globally; `run`
enables the isolated profile **for that workbench only**.

## What stays (or becomes) AI

Architecture proposals, code, ambiguous recovery. Implementation may
later be delegated to an external coding agent behind a capability
contract.

## What is postponed

Dashboards, elaborate PM interfaces, dynamic role creation, factory
source mutation, Playwright platform, ten auditor personas, Factory
self-improvement that writes `scripts/`.

## Benchmark (first proof)

Seed: `examples/seeds/task_board_web.md`

Python stdlib-only task board so today's pytest/compileall allowlist
can eventually validate it without npm. Acceptance is behavioral, not
"files exist."

A passing P0 **engine** test (no Ollama): `crazy-admin run` keeps
invoking the kernel until COMPLETE / HUMAN / BUDGET and writes a
mission trace. A passing P1 **product** test (needs a coding agent):
the same command on that seed yields a runnable app.
