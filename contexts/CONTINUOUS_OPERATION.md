# Continuous Operation Vision

Crazy Factory is intended to become a persistent local-first software
development worker. It should work toward missions, checkpoints, milestones,
and satisfaction criteria over days, weeks, or months without losing its
place.

## Fundamental Questions

Every run must be able to answer:

1. What am I working on?
2. Why am I working on it?
3. What did I finish?
4. What failed?
5. What remains?
6. Where do I resume?

## Persistence Boundary

Important state must exist in files rather than only in an LLM context window.
The initial durable snapshots live in `state/`. Each application maintains its
own memory, checklist, milestones, backlog, reports, and next action.

## Current Constraint

Continuous unattended execution is a future capability. Phase 2 records
mission state and recovery information and validates a planning-only local
Architect and Planner loop. It does not activate scheduling, automatic
application edits, automatic commits, or automatic merges.
