# 04 — Living Documentation Growth (human + AI, integral to the flow)

The project's `docs/` is dead: `startproject` writes three stubs
(`seed.md` placeholder, `requirements.md` "_To be grown_", `decisions.md`
"_To be recorded_") and `advance` never touches them. A growth engine
(`context_growth.py`) exists but is orphaned (manual command, writes to
`factory_state/`, not the workbench `docs/`).

This phase makes documentation a **first-class, continuously-evolving output**
that the factory both **produces for humans** and **re-consumes as AI grounding**
— so each iteration's docs sharpen the next iteration's work.

## Principle: deterministic structure, LLM content, surgical evolution

The reason docs are "easy to evolve with LLM assistance" is **defined
structure**. Every living doc has a fixed schema with stable anchors, so growth
is a **surgical, idempotent update** (append an ADR, upsert a requirement row,
refresh the latest assessment) — never a freeform rewrite that drifts or
clobbers history.

```
Structure (deterministic) = templates, anchors, IDs, append/upsert rules   (Python)
Content   (LLM)           = the prose/values that fill each structured slot  (model)
Triggers  (events)        = when each doc grows                              (the loop)
Context   (evidence)      = what feeds each growth                           (seed + 9D/9E)
```

Same safety shape as the rest of 9D/9E: Python owns structure + write-confinement
+ truthfulness; the LLM (via skills) supplies content; LLM-down still writes the
deterministic skeleton.

## The living doc set (defined structure + context + trigger)

| Doc | Structure | Grows from (context) | Trigger |
|---|---|---|---|
| `docs/seed.md` | Goal · Constraints · Scope · Success · **Clarifications** (append log) | the **real** seed (import) + each iteration's sharpened understanding | seed ingest; whenever intent is clarified |
| `docs/requirements.md` | table: `R-id · statement · source(seed/discovered) · status · checklist-item · test` | seed-derived contract + discovered edge cases (DiagnosisPacket, completeness findings) | beat 0 (derive); each beat (upsert/strengthen) |
| `docs/decisions.md` | **append-only ADRs**: `ADR-id · date · context · decision · alternatives · status · supersedes` | adjudication dispositions, contract repairs, recovery/redirect choices | every significant decision |
| `docs/architecture.md` | tree · module responsibilities · interfaces · forbidden tech | the **seed-derived ProjectContract** (9E ST6) + `FocusRequirementSpec` | contract derived/revised; module lands |
| `docs/assessment.md` | latest snapshot + history: behaviors covered/missing vs seed · green state · next focus | acceptance evidence + `run_metrics` + required_behaviors | every beat (the seed's "assessment loop") |
| `docs/changelog.md` | append: `iteration · delivered · files · tests` | completed-item evidence | on item completion |
| `docs/modules/<file>.md` | purpose · interface · behaviors · tests | the file's `FocusRequirementSpec` | when a file completes |
| `docs/risks.md` / `open_questions.md` | append/resolve log | escalations, owner questions, unknowns | on escalate/ambiguity |
| `README.md` | app readme (seed **requires** it; currently absent) | seed + architecture | beat 0; refresh on milestone |

Stable structure → updates are testable and lossless (history preserved).

## The dual-consumption loop (why this is "integral for AI")

Docs are not just output — they **feed back in as grounding**. After each beat
writes/strengthens the structured docs, the planning context loader reads
`docs/requirements.md`, `docs/architecture.md`, and `docs/decisions.md` into the
next beat's prompt. So the AI **consumes its own evolving understanding**:

```
seed ─▶ derive requirements/architecture ─▶ build ─▶ adjudicate/decide
  ▲                                                          │
  └──── docs re-ingested as grounding (next beat) ◀── grow docs (req/ADR/assessment)
```

This is the growth you described: requirements **get stronger** (each beat adds
discovered behaviors + links them to tests), decisions **accumulate** (ADRs),
the seed **gets clearer** (clarifications), and the architecture tracks reality —
and all of it sharpens the next iteration.

> Safety note (vs the 9D "don't feed raw reports" rule): these are **structured,
> derived, truthful** docs (requirements/decisions/architecture), not freeform
> run-prose. They are valid grounding; narrative `*_REPORT.md` files stay
> excluded. Truthfulness gates (9D §6) apply — a doc may not assert what the
> evidence contradicts.

## Doc-growth skills (added to the 9E catalog)

The LLM **directs** doc growth through skills (it never writes files directly):

| Skill | Args | Structure rule (Python-enforced) |
|---|---|---|
| `clarify_seed` | `clarification` | append to `seed.md` Clarifications; never edit the original seed body |
| `update_requirements` | `rows[]` | upsert by `R-id`; status transitions validated; link to checklist item/test |
| `record_decision` | `title, context, decision, alternatives` | append next `ADR-id`; immutable once written (supersede, don't edit) |
| `write_assessment` | `covered[], missing[], next_focus` | overwrite "latest", append to history |
| `generate_module_doc` | `file` | render from `FocusRequirementSpec` into `docs/modules/<file>.md` |
| `append_changelog` | `delivered, files` | append iteration entry |
| `update_architecture` | — | re-render from the seed-derived ProjectContract |

All path-confined to the workbench `docs/`; all validated against their
structure rule before writing (reuse the 9E `validate_call` + executor).

## Triggers (wired into `advance`)

A **documentation-growth step** runs at defined points each beat:

```
on seed ingest        -> clarify_seed (real seed), update_requirements (v1),
                         update_architecture (v1), README v1
on contract derive/revise -> update_architecture, update_requirements links
on adjudication/recovery decision -> record_decision (ADR)
on item complete (acceptance evidence) -> append_changelog, generate_module_doc,
                         update_requirements (status), write_assessment
on every beat end     -> write_assessment (progress vs seed)
```

`context_growth.py` is **repurposed**: target the workbench `docs/` (not
`factory_state/`) and run inside the loop, not as an orphan command.

## Subtasks

| ST | What | Touches | Risk |
|---|---|---|---|
| **D1** | **Structured doc writer** — `doc_growth.py`: schemas + anchored renderers + append/upsert (ADR append, requirement upsert, assessment refresh), all deterministic + idempotent | new `doc_growth.py` | med |
| **D2** | **Seed reconciliation** — write the real seed into `docs/seed.md`; deterministic `requirements.md`/`architecture.md`/`README.md` rendered from the seed-derived contract (no LLM) | `crazy_admin.py`/`doc_growth.py` | low |
| **D3** | **Doc-growth skills** in the 9E catalog (`clarify_seed`, `update_requirements`, `record_decision`, `write_assessment`, `generate_module_doc`, `append_changelog`, `update_architecture`) | `skill_library.py` | med |
| **D4** | **Triggers + per-beat wiring** — call doc growth at the trigger points in `advance`; repurpose `context_growth` to the workbench `docs/` | `factory_advance.py`, `context_growth.py` | med |
| **D5** | **Dual-consumption loop** — planning context reads `docs/requirements.md` + `architecture.md` + `decisions.md` as grounding | `context_loader.py`/`factory_advance.py` | med |
| **D6** | **Tests + measured re-run** — structure tests (idempotent ADR append, requirement upsert, history-preserving assessment), mocked-LLM content, doc-feeds-context; then a live run showing docs grow over iterations | tests + scripts | — |

## Execution slices (gated, reversible)

- **Slice 1 = D1 + D2 (no LLM):** structured writer + seed reconciliation +
  deterministic requirements/architecture/README from the seed-derived
  contract. **Docs stop being dead immediately**, even with the model off.
- **Slice 2 = D3 + D4:** LLM-directed doc-growth skills + per-beat triggers
  (requirements strengthen, ADRs accrue, assessment refreshes).
- **Slice 3 = D5:** the feedback loop — the AI consumes its own docs as
  grounding.
- **Slice 4 = D6:** tests + a measured re-run.

Depends on 9E ST6 (seed-derived ProjectContract) for `requirements`/
`architecture`, and the 9E skill library for D3.

## Invariants (tested)

- Workbench-confined writes (`docs/` only); never factory runtime dirs.
- **Append-only history** for ADRs/changelog/assessment-history — growth never
  loses prior content.
- Deterministic structure + LLM content; **LLM-down still writes the skeleton**.
- Truthful docs (9D §6): no claim contradicting evidence; structured docs only
  are fed back as grounding (no raw run-prose).
- Idempotent updates: re-running a beat doesn't duplicate rows/ADRs.

## Definition of done

- After a run, `docs/` contains a **real, clarified seed**, a **requirements
  table that strengthened over iterations** (linked to tests), an **ADR decision
  log**, an **architecture doc tracking the code**, a **per-iteration
  assessment**, a **changelog**, **module docs**, and a **README** — and the
  factory **re-read its own requirements/architecture/decisions** as grounding
  each beat. Docs are useful to a human reader *and* measurably improved the
  next iteration's generation.
