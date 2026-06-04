# Crazy Factory Operating Package

Crazy Factory is a local-first autonomous software development apprentice. This
directory is its operating system: governance, role charters, workflows,
templates, project memory, and architecture notes for the Python runtime in the
repository root.

Implementation now lives outside this directory, mainly in `scripts/`, `bin/`,
`tests/`, `config/`, and `docs/`. Treat `factory/` as the durable operating
manual and policy layer that explains how autonomous advances are supposed to
behave.

## Purpose

Crazy Factory is designed to run periodically, make incremental progress, and
preserve enough context that a future session can understand what happened, why
it happened, and what should happen next. It is organized as a team of
specialized workers:

| Worker | Primary responsibility |
| --- | --- |
| Architect | Expand goals into architecture and bounded work areas |
| Planner | Select and define the next smallest valuable task |
| Coder | Propose and apply owner-approved implementation changes within guarded paths |
| Test Builder | Define validation plans for owner-authorized tasks and proposals |
| Reviewer | Review quality, safety, and scope |
| Reporter | Record progress, memory, decisions, and next actions |
| Watcher | Observe activity, stalls, checkpoints, and recovery state |

## Reading Order

Start with:

1. [FACTORY_CONTRACT.md](FACTORY_CONTRACT.md)
2. [MISSION.md](MISSION.md)
3. [PRINCIPLES.md](PRINCIPLES.md)
4. [FACTORY_LIFECYCLE.md](FACTORY_LIFECYCLE.md)
5. [ARCHITECTURE.md](ARCHITECTURE.md)
6. [context/CURRENT_STATE.md](context/CURRENT_STATE.md)
7. [BACKLOG.md](BACKLOG.md)

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
Python CLI and guarded advance pipeline, with owner-controlled stages for
planning, contracts, coder proposals, patch application, validation, and
checkpoint commits. This operating package remains the policy and memory layer;
when it conflicts with the current CLI/runtime, update the documentation or the
runtime so the contract is explicit again.
