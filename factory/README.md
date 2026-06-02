# Crazy Factory Documentation Package

Crazy Factory is a local-first autonomous software development apprentice. This directory is its operating system: a documentation package for future implementation work, autonomous sessions, human oversight, and auditable project memory.

This package intentionally contains no implementation code, scripts, tests, or executable artifacts.

## Purpose

Crazy Factory is designed to run periodically, make incremental progress, and preserve enough context that a future session can understand what happened, why it happened, and what should happen next. It is organized as a team of specialized workers:

| Worker | Primary responsibility |
| --- | --- |
| Architect | Expand goals into architecture and bounded work areas |
| Planner | Select and define the next smallest valuable task |
| Coder | Implement approved tasks in a future build phase |
| Test Builder | Define and create validation in a future build phase |
| Reviewer | Review quality, safety, and scope |
| Reporter | Record progress, memory, decisions, and next actions |

## Reading Order

Start with:

1. [FACTORY_CONTRACT.md](FACTORY_CONTRACT.md)
2. [MISSION.md](MISSION.md)
3. [PRINCIPLES.md](PRINCIPLES.md)
4. [FACTORY_LIFECYCLE.md](FACTORY_LIFECYCLE.md)
5. [ARCHITECTURE.md](ARCHITECTURE.md)
6. [context/CURRENT_STATE.md](context/CURRENT_STATE.md)
7. [BACKLOG.md](BACKLOG.md)

Before autonomous work, load the applicable worker file in [roles/](roles/), the shared rules in [instructions/](instructions/), and the relevant phase guide in [workflows/](workflows/).

## Directory Guide

| Directory | Contents |
| --- | --- |
| `context/` | Durable project memory and state snapshots |
| `instructions/` | Shared and worker-specific behavior rules |
| `roles/` | Worker charters and handoff contracts |
| `workflows/` | Operational procedures for lifecycle phases |
| `governance/` | Authority boundaries, approvals, and quality bars |
| `templates/` | Structured records for repeatable autonomous work |

## Current Status

The repository is in documentation bootstrap. Future system capabilities are roadmap items only. The next phase is to review and approve this operating package before any implementation work begins.

