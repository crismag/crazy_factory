# 02 — Seed grounding (direction guard) + keep-the-work (no discard)

Two findings drive this doc: the seed is **not the basis of accept/reject**, and
rejected work is **discarded**. Both must change for adjudication to mean
anything.

## A. The seed-derived project contract (the basis of direction)

Today the structural gate is a hand-authored `architecture.json` that diverges
from the seed (`sample_contexts/task_board.md`): it dropped `README.md` and
`data/tasks.json`, and let the Tkinter UI be deferred/stubbed — none of which the
seed permits. Fix: **derive the contract from the seed**, don't hand-author it.

New skill / step `derive_project_contract(seed, sub_contexts) -> ProjectContract`
(LLM-proposed, deterministically validated), producing:

```yaml
required_tree:            # from the seed's "Expected Initial Tree"
  - README.md
  - src/task_board.py     # the Tkinter UI is a REQUIRED deliverable
  - src/task_model.py
  - src/storage.py
  - data/tasks.json
  - tests/test_task_model.py
  - tests/test_storage.py
required_behaviors:       # from "Functional/Testing Requirements"
  - add/edit/delete/toggle task
  - save/load JSON; missing file -> empty; corrupt JSON handled
forbidden_tech:           # from "Do not use"
  - database, web server, auth, cloud, AI features, packaging, complex styling
persistence_target: data/tasks.json
validation: [pytest tests, launch src/task_board.py]
```

- This **supersedes** the script's `architecture.json` (or is generated *into*
  it), so structure + acceptance + forbidden-tech all trace to the seed.
- It becomes the reference the adjudicator checks **direction** against:
  *does this proposal/patch advance `required_behaviors`, stay inside
  `required_tree`, and avoid `forbidden_tech`?*
- `forbidden_tech` is the real directional guard the floor can enforce
  deterministically too (e.g. a `flask`/`sqlite3` import → `reject_unsafe`),
  derived from the seed rather than manually transcribed.

Sub-contexts (the 9D per-file `FocusRequirementSpec`, and any
`generate_subcontext` outputs) are part of the grounding the adjudicator reasons
over — "the same with any sub and generated context."

## B. Direction guard examples (what `redirect`/`reject_unsafe` should catch)

Grounded in this run's actual misses:

| Situation | Today | Under 9E |
|---|---|---|
| Persistence put in `task_model.py` instead of `storage.py` (seed says storage) | unnoticed | `redirect` — `revise_contract`/`update_focus` to match the seed tree |
| `data/tasks.json` dropped from the contract | unnoticed | direction finding → `add_required_file("data/tasks.json")` |
| Tkinter UI deferred + stubbed though it's a core seed goal | unnoticed | direction finding → keep UI as a first-class required item |
| Proposal adds `flask`/`sqlite3` (seed forbids) | maybe caught by transcribed list | `reject_unsafe` from seed-derived `forbidden_tech` |
| `unused import 'Optional'` | rejects whole patch | `fix` (autofix_lint) — never a direction issue |
| Proposes 5 files for a 1-file focus item | rejects whole patch | `scope_down` (keep_only_files + defer) |

## C. Keep-the-work (no discard, ever)

Today `patch_plan.json` stores `path/action/line_count` — **no content** — so a
non-accepted patch is gone. Change:

1. **Persist generated content** as its own artifact, e.g.
   `factory_tasks/patch_content/<slug>.txt` (or a `content` field in a
   sidecar), written by the `persist_patch_content` skill the moment a patch
   plan is produced — *before* adjudication.
2. **Repair operates on the kept content**, not a from-scratch regenerate:
   `fix`/`scope_down` skills transform the saved content (strip the import, drop
   the extra file) and re-adjudicate. A `redirect` keeps it as the starting
   point for the revised proposal.
3. **`reject_unsafe`/`escalate` keep the content too** (quarantined under the
   task dir) so the owner can inspect what was generated.

Result: a trivially-fixable patch becomes a **fix task on real code**, not a
discard — exactly the "reject vs. a new task of fixing" distinction. The
44-line `task_model.py` from this run would have been kept, de-imported, and
applied.

## D. Reconciliation

- `architecture.json` becomes a **generated** artifact (from the seed) or is
  validated against the seed-derived contract; the autopilot scripts stop
  hand-authoring a diverging one.
- `missing_required` / acceptance checks read `required_tree` (so `README.md`,
  `data/tasks.json`, the UI are all enforced).
- `forbidden_tech` feeds both the deterministic floor (hard) and the adjudicator
  (direction).
