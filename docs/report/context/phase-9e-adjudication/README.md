# Phase 9E — Seed-Grounded Adjudication & the Skill Library

Generated: 2026-06-05

Turns "rejection" from a blunt, mechanical, work-discarding gate into an
**LLM-directed adjudication grounded in the project seed**, where the LLM
analyses and *plans* but executes nothing directly — it directs a vetted
catalog of deterministic **skills**, and Python enforces the safety floor and
runs only allowed skills.

## Guiding principle (governs EVERY task in this package)

> **Do not make the script smarter. Make it more obedient, observable, and
> skill-driven.** Scripts are utility + bounded controls; decisions are
> skill-governed adjudication.

- **Python is rails, not a brain.** Its only jobs: the deterministic **safety
  floor**, **skill validation + execution**, **state I/O**, and
  **observability/logging**. It is *not* a decision engine.
- **Decisions are skill-governed adjudication.** The LLM adjudicates and selects
  from the **bounded skill catalog**; Python validates and executes only allowed
  skills and never relaxes the floor.
- **Recovery especially:** it must become a **skill-governed adjudication with
  deterministic safety rails only** — *not* a growing pile of Python heuristics.
  The #37 `classify_failure` per-class branches are the **anti-pattern to stop
  growing**: keep them as a thin fast-path/observability layer and migrate the
  *decisions* to the adjudicator + skills. New failure handling = a new **skill**
  (or adjudicator reasoning), **not** a new Python `if`-branch.
- **Degrade to the rail, not to cleverness.** LLM-unavailable → a *minimal* safe
  rail (apply only known-safe bounded auto-fixes, else **park/escalate to
  owner**) — never an expanding deterministic decision tree.

Every backlog item below is implemented under this principle.

## Why (grounded in the task-board findings)

From analysing `/mnt/ai/workspaces/crazy_apps/task-board`:

1. **Rejection is inverted.** It fires on trivial *fixables* (a single
   `unused import 'Optional'` rejected a 5-file, ~105-line patch → empty app)
   and **never checks direction** against the seed. The one question rejection
   exists to answer — *"is this taking the project somewhere the seed didn't
   ask for?"* — is never asked.
2. **Rejected work is discarded.** `patch_plan.json` persists no `content`, so
   44 lines of working `task_model.py` were thrown away — a "fix task" is
   impossible because the artifact is gone.
3. **The seed is sidelined as the basis of decisions.** It's ingested and
   expanded at planning, but the structural gate is a hand-authored
   `architecture.json` that *diverges* from the seed tree (no `data/tasks.json`,
   no `README.md`, UI deferred/stubbed), and the gate logic ignores the seed
   entirely.
4. **The coder over-scopes** (proposed 5 files incl. deliberate stubs) against a
   single-file checklist item — "extra modules" that should be dropped, not
   rejected.

## The reframe

> Rejection's purpose is to stop work that drives the project in the **wrong
> direction** relative to the seed and its expansions — not to reject trivial
> matters that are simply **for fixing**.

So a review yields a **disposition**, not a binary verdict:

```text
accept · fix · scope_down · redirect · escalate · reject_unsafe(floor-only)
```

- **fixables** (lint, unused imports, formatting, extra/over-scoped modules) →
  **fixed or scoped-down**, never discarded.
- **directional divergence** from the seed/sub-contexts → **redirect** (revise
  plan/contract/context and re-plan).
- **safety** (forbidden ops, secrets, path/contract-floor) → the only thing that
  hard-rejects, and only the deterministic floor can produce it.

## The principle

```text
LLM   = analysis, adjudication, planning, direction   (proposes skill calls)
Skills = deterministic, schema'd, safety-bounded operations the LLM may invoke
Python = enforces the floor, validates each skill call, executes only allowed ones
```

The LLM is **fed the skill catalog** (names, when-to-use, params) so it can make
proper decisions and *direct the script* to deliver the right task — generating
new contexts/sub-tasks and repair/redirect actions — while never touching the
filesystem or git itself. This generalizes the existing
`recovery_router.RecoveryAction` + `ACTION_TYPES` allow-list (already a proto
skill registry) into a full, LLM-selected catalog.

## Load order

1. [00_adjudication_model.md](00_adjudication_model.md) — dispositions + the LLM adjudicator/director role + the floor
2. [01_skill_library.md](01_skill_library.md) — the catalog fed to the LLM, schema, allow-list, executor, safety
3. [02_seed_grounding_and_keep_work.md](02_seed_grounding_and_keep_work.md) — seed-derived contract, direction guard, no-discard repair
4. [03_execution_plan.md](03_execution_plan.md) — subtasks, gated slices, tests, invariants
5. [04_living_documentation.md](04_living_documentation.md) — 9E.4: human-facing `docs/` as a living, evolving output (defined structure + skills + triggers)
6. [05_context_expansion.md](05_context_expansion.md) — 9E.5: revive the context factory → grow AI-facing `factory_context/` from the seed (twin of 9E.4; shared engine)
7. [06_truthful_reporting.md](06_truthful_reporting.md) — 9E.6: truthful, progress-oriented ACTIVITY/DAILY/CHECKPOINT reports (finish 9D §6; consume run_metrics + #37 signals)
8. [07_robust_llm_calls.md](07_robust_llm_calls.md) — 9E.7: robust LLM role calls (prime · classify · iterate · never use a refusal) — Slice 1 implemented
9. [08_patch_plan_uplift.md](08_patch_plan_uplift.md) — 9E.8: patch-plan generation (prompt+context) & rich, actionable `PATCH_PLAN.md` (subsumes ST12)
10. [09_architect_intelligence.md](09_architect_intelligence.md) — 9E.9: build the architect *skill* (method + schema + self-critique) so the expansion rises to project-level architecture (subsumes 9E.7-L3)
11. [BACKLOG.md](BACKLOG.md) — **stored execution queue** (all QUEUED tasks, dependency-ordered, with status)

## Non-negotiable invariant (carries from 9D/#37)

Model proposes, Python validates and executes. Only the deterministic floor can
hard-reject. LLM-unavailable degrades to deterministic safe behavior (fix
trivial, else escalate) — never a fake accept. Attempt budgets + the no-progress
monitor still bound the loop.
