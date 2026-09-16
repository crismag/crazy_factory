# Crazy Factory 2.0 — Target Architecture

Plan of record for the restart. Historical phase packages under
`docs/report/context/` remain evidence, not the plan. The execution
audit is
[`docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md`](../docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md).
The broader repository assessment is
[`docs/report/context/crazy-factory-2.0/ASSESSMENT.md`](../docs/report/context/crazy-factory-2.0/ASSESSMENT.md).

## Immediate product

Crazy Factory must take a bounded application context and **keep
working until there is a runnable, validated application** — or a
clearly justified blocker that genuinely requires a human.

UI, dashboards, large agent organizations, and product-intelligence
theater are not the first milestone. The first failure is simpler:

> The factory does not yet reliably take an input prompt/context and
> autonomously continue doing the work required until it produces a
> working output.

Reference systems such as Lovable for the **automation behind
prompt → working application**, not for UI.

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
| **P1** | Runnable output (install/build/start tools + inspect) | next |
| **P2** | Convergence: remaining gaps become the next objective | product kernel inspect helps; not yet wired into EXECUTE |
| **P3** | External invocation: MCP wraps the working engine | thin `start_mission` / `status` / `continue` / `stop` |
| **P4** | Better agents: coding-agent adapter, then specialized roles | later |
| **P5** | Broader product intelligence, dynamic teams, self-improve | postpone |

Do not begin P5 while P0 is unsolved.

## P0 shape (what this slice owns)

```text
crazy-admin run <id> [--seed FILE]
  apply WORKBENCH_AUTONOMOUS profile   # apply+validate+remediate+autonomy
                                       # safety floor intact (no push/merge/
                                       # delete, no engine writes, path confine)
  loop until COMPLETE | HUMAN_REQUIRED | BUDGET:
      EVALUATE (acceptance, growth, blocker)
      if not terminal:
          EXECUTE = one factory_advance beat (existing kernel)
          OBSERVE = validation_result + workbench_metrics + blocker
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

Today the in-process Coder remains the default executor so `run` can
use Ollama. P4 adds an agent executor interface; do not grow the
internal patch engine first.

## Nested loops (later, not first)

| Loop | Cycle | When |
| --- | --- | --- |
| Task | implement → test → review → repair | existing `factory_advance` under EXECUTE |
| Module | discover → specify → … → verify | P2 |
| Product | understand → assess → objectives → inspect | P2/P5 |
| Factory | capability gap → acquire → validate | postponed; owner-gated |

Maturity remains **derived from evidence**, not a workflow you step.

## Public interface

P0 CLI: `crazy-admin run|stop` (plus existing `advance` for one beat).

P3 MCP, wrapping the engine, never replacing it:

`crazy_factory.start(context, target)` → `start_mission`

`crazy_factory.status(project)` → `get_status` / `inspect_project`

`crazy_factory.continue(project)` → `continue_mission`

`crazy_factory.inspect(project)` → `inspect_project`

`crazy_factory.stop(project)` → `stop_mission`

MCP without the execution engine would only expose the incomplete
workflow remotely. Slice A's inspect/assess tools remain available;
they are not the product.

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
