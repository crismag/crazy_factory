# Crazy Factory Operating Package

Crazy Factory is a local-first autonomous software development apprentice. This
directory is its operating system: governance, role charters, workflows,
templates, project memory, and architecture notes for the Python runtime in the
repository root.

Implementation now lives outside this directory, mainly in `scripts/`, `bin/`,
`tests/`, `config/`, and `docs/`. Treat `factory/` as the durable operating
manual and policy layer. The 2.0 plan of record is
[CF2_ARCHITECTURE.md](CF2_ARCHITECTURE.md).

## Purpose

Crazy Factory is designed to run periodically, make incremental progress, and
preserve enough context that a future session can understand what happened, why
it happened, and what should happen next. It is organized as a team of
specialized workers:

| Worker | Primary responsibility |
| --- | --- |
| Director | Owner conversation: product + mission + next command (`crazy-admin brief`) |
| Architect | Expand goals into architecture and bounded work areas |
| Planner | Select and define the next smallest valuable task |
| Coder | Propose and apply owner-approved implementation changes within guarded paths |
| Test Builder | Define validation plans for owner-authorized tasks and proposals |
| Reviewer | Review quality, safety, and scope |
| Reporter | Record progress, memory, decisions, and next actions |
| Watcher | Observe activity, stalls, checkpoints, and recovery state |

## Reading Order

Start with:

1. [CF2_ARCHITECTURE.md](CF2_ARCHITECTURE.md) — current plan of record (P0 loop first)
2. [CF2_PHASE_TARGETS.md](CF2_PHASE_TARGETS.md) — phase-level target checklist
3. [CF2_TASK_CHECKLIST.md](CF2_TASK_CHECKLIST.md) — development TODO
4. [CF2_MIGRATION.md](CF2_MIGRATION.md) — slices and task cards
5. [../docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md](../docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md) — why prompt→output fails today
6. [FACTORY_CONTRACT.md](FACTORY_CONTRACT.md)
7. [MISSION.md](MISSION.md)
8. [PRINCIPLES.md](PRINCIPLES.md)
9. [FACTORY_LIFECYCLE.md](FACTORY_LIFECYCLE.md) — execution-kernel phases
10. [ARCHITECTURE.md](ARCHITECTURE.md) — historical kernel shape
11. [context/CURRENT_STATE.md](context/CURRENT_STATE.md)
12. [BACKLOG.md](BACKLOG.md)

Before autonomous work, load the applicable worker file in [roles/](roles/), the
shared rules in [instructions/](instructions/), and the relevant phase guide in
[workflows/](workflows/). For command usage and current runtime behavior, see
[../docs/USAGE.md](../docs/USAGE.md).

## Directory Guide

| Directory | Contents |
| --- | --- |
| `context/` | Durable factory memory and state snapshots |
| `instructions/` | Shared and worker-specific behavior rules |
| `roles/` | Worker charters and handoff contracts |
| `workflows/` | Operational procedures for lifecycle phases |
| `governance/` | Authority boundaries, approvals, and quality bars |
| `templates/` | Structured records for repeatable autonomous work |

## Current Status

The repository has moved beyond documentation bootstrap. It now includes a
Python CLI, a guarded one-beat advance pipeline, and a P0 closed-loop
mission runner (`crazy-admin run`). This operating package remains the
policy and memory layer; when it conflicts with the current CLI/runtime,
update the documentation or the runtime so the contract is explicit again.
