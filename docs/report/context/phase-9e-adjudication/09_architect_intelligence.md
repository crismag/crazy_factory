# 09 — 9E.9 Architect Intelligence (build the architect skill before the work)

The architect currently free-form-chats and produced **finished code instead of
an architecture** (TASK_EXPANSION.md), contributing zero architectural thinking
and poisoning the planner. 9E.7-L3 fixes the *shape*; this phase fixes the
*level*: **condition the LLM into a competent architect — give it the method and
the quality bar — before it does the architecture work**, so the expansion rises
to a real, project-level design that everything downstream derives from.

Principle (your framing): *build the AI's architect skill first, then have it
architect.* A persona alone is weak; the lift comes from priming the **method**
(a reasoning scaffold), the **deliverable shape**, a **self-check rubric**, and a
**worked example** — then a self-critique pass to harden it.

## The gap (from TASK_EXPANSION.md)

- **Wrong level + wrong job:** it wrote one file's code, not a project
  architecture (no boundaries, dependencies, data flow, risks, trade-offs, or
  decomposition). No architectural reasoning occurred.
- **No skill conditioning:** plain chat, vague "create one expansion"
  instruction. `ARCHITECT_RULES.md` is an abstract charter, not an operational
  method.
- **Single-file tunnel vision:** the architect should own the **whole-project**
  design (the seed: model + storage + UI + persistence + tests + tree), the
  layer that drives the seed-derived contract + decomposition. It operated below
  that level.

## The architect skill primer (pre-prompt that builds competence)

A reusable primer injected before the task (via `structured_call`, 9E.7),
composed of four parts:

1. **Persona + remit:** "You are a senior software architect. You design the
   project's structure and sequence — you do NOT write implementation code."
2. **Method (the reasoning scaffold — the actual intelligence):**
   ```text
   1. Restate the goal + the seed's required behaviors/constraints.
   2. Identify domain entities & state.
   3. Define modules: responsibility, public interface, and what each owns.
   4. Map dependencies + data flow; ensure layering is acyclic.
   5. Surface risks, trade-offs, and decisions that need owner input.
   6. Decompose into COHERENT, sequenced deliverables (a module + its tests,
      or a vertical behavior slice) — foundation first — covering every seed
      behavior.
   7. State NFRs/constraints derived from the seed ("Do not use …").
   ```
3. **Quality bar:** boundaries explicit; dependencies acyclic; every seed
   behavior mapped to a deliverable; no code; no hand-waving; declare unknowns.
4. **Worked few-shot:** one small seed → a good expansion, so the model has a
   concrete target.

## Structured architecture output (schema)

```yaml
summary: string
entities: [{name, fields, notes}]
modules:
  - name: string
    responsibility: string
    interfaces: [string]
    depends_on: [module]
data_flow: [string]
risks: [{risk, impact, mitigation}]
decisions_needed: [string]          # owner-review candidates (feeds S0b)
task_candidates:                    # the decomposition seed for ST6/ST11
  - deliverable: string             # coherent unit (module+tests / vertical slice)
    covers: [seed_behavior]
    depends_on: [deliverable]
    sequence: int
nfrs: [string]                      # derived from the seed's constraints
open_questions: [string]
```

Role-fit validation rejects "code-as-architecture" (no large code blocks; must
contain modules + task_candidates).

## Grounding + iteration (intelligence compounds)

- **Grounded** in the seed + seed-derived ProjectContract (ST6) + sub-contexts.
- **Evolves**: reads the prior `docs/architecture.md` / `factory_context/
  architecture.md` and **sharpens it each iteration** (living docs 9E.4) — the
  architecture gets clearer as the build reveals reality.
- **Self-critique pass** (the hardening): after the first expansion, a second
  pass checks it against the rubric (boundaries clear? deps acyclic? all seed
  behaviors covered? deliverables coherent?) and revises — a few iterations
  raise quality, per the 9E.7 iterate-to-harden pattern.

## Downstream wiring (why the level matters)

```
seed ─▶ ARCHITECT (skill-primed, project-level) ─▶ architecture
            ├─▶ seed-derived ProjectContract (ST6)   (structure/forbidden-tech)
            ├─▶ decomposition → coherent deliverables (ST6/ST11)
            ├─▶ planner: next action chosen FROM the architecture (not code)
            └─▶ docs/architecture.md (9E.4)           (human + AI grounding)
```

This is the fix for the cascade: a real architecture (not code) gives the
planner a proper "expansion," and gives decomposition coherent, sequenced
deliverables covering the full seed.

## Subtasks (9E.9) — add to backlog

| ID | Task | Touches | Risk |
|---|---|---|---|
| **ARC1** | **Architect skill primer** — persona + method scaffold + quality bar + worked few-shot; rewrite `ARCHITECT_RULES.md` from charter → operational method | new primer / `factory/instructions/ARCHITECT_RULES.md` | med |
| **ARC2** | **Structured architecture output + role-fit** via `structured_call` (subsumes 9E.7-L3) — the schema above; reject code-as-architecture | planning_roles.py, llm_interaction.py | med |
| **ARC3** | **Project-level scope + downstream wiring** — architect reasons over the whole seed; its `task_candidates` feed the seed-derived contract (ST6) + decomposition (ST6/ST11); planner consumes the architecture, not code | planning_roles.py, completion/architecture, contract_stage | high |
| **ARC4** | **Iterative architecture** — read + sharpen prior `architecture.md` each iteration; persist to docs (9E.4) / factory_context (9E.5) | planning_roles.py, doc/context growth | med |
| **ARC5** | **Self-critique pass** — second pass scores the expansion against the rubric and revises (iterate-to-harden) | planning_roles.py | med |
| **ARC6** | Tests + measured check — role-fit (code rejected), schema validation, behavior-coverage (every seed behavior in a task_candidate), grounding/iteration, planner consumes architecture | tests | — |

## Execution slices

- **Slice 1 = ARC1 + ARC2:** skill primer + structured architecture output (no
  more code-as-expansion; the planner stops being poisoned). Subsumes 9E.7-L3.
- **Slice 2 = ARC3:** project-level architecture drives the contract +
  decomposition (coherent deliverables covering the full seed).
- **Slice 3 = ARC4 + ARC5:** iterative sharpening + self-critique (the
  higher-level "intelligence").
- **Slice 4 = ARC6:** tests + measured re-run.

Depends on 9E.7 (`structured_call`) and composes with ST6 (seed-derived
contract), ST11 (seed-complete checklist), and 9E.4/9E.5 (architecture doc).

## Invariants (tested)

- **No code** in the architecture output (role-fit); it produces design, not
  implementation.
- Robust call: schema-validated or deterministic fallback; never a stored
  refusal/code-dump.
- Grounded in the seed; **every seed behavior maps to a task_candidate**
  (coverage check).
- Iteration sharpens, never clobbers, prior architecture (history-safe).
- Deterministic floor + owner authority unchanged.

## Definition of done

The architect, **primed into the role**, produces a real project-level
architecture (entities · modules · dependencies · risks · decisions · sequenced
coherent deliverables · NFRs) grounded in the seed and **sharpened each
iteration** — feeding the contract, decomposition, planner, and `architecture.md`.
It no longer writes code, no longer poisons the planner, and the design visibly
rises in quality over iterations.
