# 05 — 9E.5 Context Expansion (revive the context factory → AI grounding)

The AI-facing twin of [04 Living Documentation](04_living_documentation.md).
Where 04 grows human-facing `docs/`, this grows **`factory_context/`** — the
grounding the planner/coder actually read — from the seed, every iteration.

Framing: this is the **unfinished wiring of the earlier 9A/9B context layer**
(`context_growth.py` exists but was never connected), delivered as a 9E
sub-phase because it shares 9E's skill library + seed-derived contract.

## The break (from analysis of `/mnt/ai/workspaces/crazy_apps/task-board/factory_context`)

`context_growth.py` is a real seed→context expansion engine (it can grow
`requirements`/`architecture`/etc.), but:

1. **It never runs in the build flow** — standalone `context-growth grow`
   command, not called by `advance`/`mission_loop`.
2. **It writes to the wrong sink** — *"only under `factory_state/projects/<id>/`"*,
   not `factory_context/` (which `build_prompt_package`/`load_context_bundle`
   read).
3. So the only expansion that ran is the narrow per-file `requirement_expander`
   (Layer 1 → `file_contracts/`). `factory_context/` is frozen at a
   **placeholder `PROJECT_GOAL.md` + one file contract** → the model builds
   under-grounded.

## Target: a growing, structured `factory_context/`

Defined structure (deterministic shape, LLM content — same pattern as 04),
expanded from the seed at beat 0 and sharpened each iteration:

```
factory_context/
  PROJECT_GOAL.md          # the REAL seed, expanded: purpose · core goal · scope · success
  architecture.md          # expected tree · module responsibilities · forbidden tech
  domain.md                # entities/states (Task = id/title/done)
  persistence.md           # data/tasks.json; missing/empty/corrupt handling
  ui.md                    # Tkinter actions: add/edit/delete/toggle/save/load
  constraints.md           # "Do not use …" guardrails + foundation/seeding notes
  acceptance_map.md        # requirement ↔ test mapping
  file_contracts/*.json    # per-file behavior/test specs (already works, 9D Layer 1)
```

Each file: stable anchors + IDs so growth is **surgical/idempotent** (no
clobber, history-safe), and each is **consumed by planning** (the dual-
consumption loop from 04 §"feedback").

## Triggers (wired into `advance`, shared with 04)

```
beat 0 (seed ingest)        -> expand PROJECT_GOAL.md from the real seed;
                               derive architecture.md/domain.md/constraints.md
on contract derive/revise   -> refresh architecture.md, acceptance_map.md
on focus change             -> expand file_contracts/<file> (Layer 1, already wired)
on item complete            -> sharpen the relevant context (e.g. persistence.md,
                               ui.md) from acceptance evidence
each beat                   -> feed factory_context/* back into planning grounding
```

## Subtasks (9E.5)

| ST | What | Touches | Risk |
|---|---|---|---|
| **CX1** | **Re-target the engine** — make `context_growth` write expanded artifacts to `factory_context/` (AI sink) instead of `factory_state/`; keep write-confinement | `context_growth.py`, `context_ledger.py` | med |
| **CX2** | **Seed → PROJECT_GOAL expansion** — at beat 0, expand the real seed into a structured `PROJECT_GOAL.md` (deterministic skeleton + LLM content); kill the placeholder; reconcile with the catalog import (one source of truth) | `context_growth.py`, `crazy_admin.py` | med |
| **CX3** | **Supporting context set** — generate `architecture.md`/`domain.md`/`persistence.md`/`ui.md`/`constraints.md`/`acceptance_map.md` from the **seed-derived ProjectContract** (9E ST6); deterministic structure, LLM fill | `context_growth.py`, `project_contract.py` | med |
| **CX4** | **Wire into `advance`** — a context-expansion step at the trigger points above; stop it being an orphan command; bounded (expand-once + sharpen, not regenerate-every-beat → preserves convergence) | `factory_advance.py` | med |
| **CX5** | **Expansion skills** — add to the 9E catalog so the LLM **directs** expansion: `expand_project_goal`, `generate_context(topic, body)`, `refresh_architecture_context`, `sharpen_context(file, note)` (reuses `generate_subcontext`/`expand_focus_contract`) | `skill_library.py` | low |
| **CX6** | **Feedback loop** — planning context (`load_context_bundle`/goal assembly) reads the expanded `factory_context/*` as grounding (structured context only; no raw run-prose, per 9D §6) | `context_loader.py`, `factory_advance.py` | med |
| **CX7** | **Tests + measured re-run** — structure tests (idempotent expansion, history-safe), mocked-LLM content, LLM-down → deterministic skeleton, context-feeds-planning; then a live run showing `factory_context/` grows over iterations | tests + scripts | — |

## Execution slices (gated, reversible)

- **Slice 1 = CX1 + CX2 (low-LLM):** re-target the engine + expand
  `PROJECT_GOAL.md` from the real seed. **Immediately replaces the worst
  document** with usable context, even with the model off (deterministic
  skeleton from the seed).
- **Slice 2 = CX3 + CX4:** generate the supporting context set from the
  seed-derived contract + wire expansion into `advance`.
- **Slice 3 = CX5 + CX6:** LLM-directed expansion skills + feed the grown
  context back into planning grounding.
- **Slice 4 = CX7:** tests + measured re-run.

Depends on 9E ST6 (seed-derived ProjectContract) for the supporting set, and
shares the per-beat trigger wiring with 9E.4 (Living Documentation) — implement
the two together (one engine, two sinks: `factory_context/` for AI, `docs/` for
humans).

## Invariants (tested)

- Writes confined to `factory_context/` (and `docs/` for 04); never
  `factory_state`/`.git`/config/outside the project.
- **Expand-once + sharpen** (not regenerate-every-beat) → convergence preserved,
  like the 9D frozen file contracts.
- Deterministic structure + LLM content; **LLM-down still writes the skeleton**
  from the seed (never leaves a placeholder).
- Only **structured** context is fed back to planning; raw narrative reports stay
  excluded (9D §6 truthfulness).
- Idempotent: re-running a beat doesn't duplicate or clobber context.

## Definition of done

- After a run, `factory_context/` holds an **expanded `PROJECT_GOAL.md`** (the
  real seed, structured) plus a **growing supporting context set**
  (architecture/domain/persistence/ui/constraints/acceptance), the planner/coder
  **read it as grounding**, and it **sharpened across iterations** — the
  "context factory" demonstrably runs and improves generation, instead of
  sitting frozen at a stub.

## Relationship to the other phases

- **9E.4 (Living Documentation):** same engine + triggers, human-facing `docs/`
  sink. Build together.
- **9E ST6 (seed-derived ProjectContract):** the single source the supporting
  context set + `docs/architecture` + the gates all derive from.
- **9D Layer 1 (`requirement_expander`):** already produces `file_contracts/`;
  this generalizes that narrow per-file expansion to the whole project context.
