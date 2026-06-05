# 08 — 9E.8 Patch-plan generation & artifact uplift

Transform `PATCH_PLAN.md` from a tombstone ("rejected; 5 files; line counts") into
a **rich, expanded, actionable plan** — and improve **what generates it** so the
LLM produces more useful content from a proper prompt + context. Subsumes the
earlier backlog item 9E.ST12 (artifact rendering) and pairs it with the
generation side.

## Current state (the gap)

Generation — `proposal_applier.request_patch_plan` (`:781`):
- Output schema is thin: `{plan_id, task_id, proposal_id, files:[{path, action,
  content}], notes}`. No per-file *intent*, no mapping to acceptance criteria,
  no self-declared risk/stubs, no rationale.
- Context is **constraint-heavy, success-light**: lots of "don't touch X / max N
  files," only recently (9E.0.1) the acceptance criteria, and it does **not**
  receive the **file contract** (`FocusRequirementSpec` behaviors/tests), the
  **situational packet** (prior rejection reasons), or a focus constraint — so it
  over-scopes and stubs.
- Plain `client.chat` (not the robust `structured_call`) → can refuse/garble.

Render — `render_patch_plan_md` (`:658`) + `patch_plan_to_dict` (`:616`):
- Shows **line counts only** (no content/diff); `patch_plan_to_dict` **drops
  content** entirely.
- Reasons are a **flat list** (a fatal error and an auto-fixable lint nit look
  identical); verdict is a bare `rejected`; no disposition, no next action, no
  stub flag, no acceptance coverage.

## Target

### Richer patch-plan schema

```yaml
plan_id, task_id, proposal_id
summary: string                 # what this patch delivers, in one line
rationale: string               # why these files/changes, tied to the contract
files:
  - path: string
    action: create|modify|delete
    content: string
    intent: string              # what this file does + why
    satisfies: [criterion_id]   # which acceptance criteria / behaviors it covers
    is_test: bool
    est_risk: low|medium|high
acceptance_coverage:            # criterion -> file/test that covers it
  - criterion: string
    covered_by: [path]
    status: covered | partial | missing
self_review:                    # the author's honest declaration
  stubs: [path]                 # files knowingly left minimal
  uncovered: [criterion]        # criteria not yet satisfied
notes: string
```

### Generation prompt + context (the "proper prompt and context")

Route through `structured_call` (9E.7) — priming + JSON + classify + reframe —
and **supply the right context**:

- **Task contract** (objective/scope/acceptance_criteria/validation_plan) — done
  (9E.0.1).
- **File contract** (`FocusRequirementSpec`: required_behaviors / required_tests
  / interfaces) — so the code targets the spec (links 9E.ST9).
- **Situational packet slice** (prior rejection reasons + current source) — so a
  retry fixes the named gap instead of repeating it.
- **Focus constraint** — implement ONLY the in-focus deliverable (the coherent
  item from 9E.ST6), not all files → kills over-scope/stubs.
- **Quality bar** (no placeholder/`pass`) — done (9E.0.2).
- **Self-review instruction** — "for each file, state its `intent` and which
  acceptance criteria it `satisfies`; if you must stub a file or leave a
  criterion uncovered, declare it in `self_review` rather than hiding it." Honest
  gaps beat hidden stubs (and feed the adjudicator's `scope_down`/`redirect`).

### Rich, actionable render

`PATCH_PLAN.md` should show:
- **Summary + rationale** (what/why).
- Per file: **the content (or a diff)**, `intent`, `satisfies`, `is_test`,
  `est_risk`; **stub flag** when a file is in `self_review.stubs` or is trivially
  small.
- **Acceptance coverage table** (criterion → covered/partial/missing).
- **Reasons classified by severity/disposition** (auto-fixable LINT vs INCOMPLETE
  vs fatal, from the #37 taxonomy) — not a flat list.
- **Disposition + next action** ("fix → will apply" / "revise: add tests for X"),
  not a bare "rejected."

## Subtasks (9E.8)

| ST | What | Touches | Risk |
|---|---|---|---|
| **PP1** | **Richer schema + parse** — extend `PatchFile`/`PatchPlan` (intent, satisfies, is_test, est_risk; plan summary/rationale/acceptance_coverage/self_review); parse tolerantly (old shape still works) | proposal_applier.py | med |
| **PP2** | **Generation via `structured_call`** + the success-context bundle (file contract + packet slice + focus + self-review instruction) | proposal_applier.py, requirement_expander/diagnosis_packet | med |
| **PP3** | **Keep-the-work** — persist `content` (stop dropping it in `patch_plan_to_dict`) so the render + a repair task can use it (this is ST2) | proposal_applier.py | low |
| **PP4** | **Rich render** — content/diff, intent, satisfies, acceptance-coverage table, severity-classified reasons, disposition + next action, stub flags | proposal_applier.py | med |
| **PP5** | **Severity classification of reasons** — reuse the `recovery_router` failure taxonomy to tag each reason (LINT/auto-fixable vs INCOMPLETE vs fatal) | proposal_applier.py, recovery_router.py | low |
| **PP6** | Tests — schema round-trips (old+new); generation supplies file-contract/packet context; render shows content + coverage + classified reasons; refusal handled (structured_call) | tests | — |

## Execution slices (gated, reversible)

- **Slice 1 = PP3 + PP4 + PP5 (render uplift, low-LLM):** persist content +
  render content/diff + classify reasons by severity + disposition. **The doc
  stops being a tombstone immediately**, even before the schema/generation change.
- **Slice 2 = PP1 + PP2:** richer schema + better generation prompt/context (file
  contract + packet + focus + self-review) via `structured_call`.
- **Slice 3 = PP6:** tests + a measured re-run.

Depends on: 9E.7 `structured_call` (done), keep-the-work/ST2, the file contract
(9D), the situational packet (9D), and the #37 taxonomy (done). Composes with the
adjudicator (9E.S2), which consumes `self_review` + acceptance_coverage to choose
`fix`/`scope_down`/`redirect`.

## Invariants (tested)

- **Back-compatible parse**: a minimal `{files:[{path,action,content}]}` still
  parses (new fields optional).
- **Content persisted** (no discard); render shows it.
- **No refusal/garbage**: generation uses `structured_call` → schema-validated or
  deterministic reject (never a stored refusal).
- **Truthful render**: reasons carry severity; a `rejected` verdict always shows
  the disposition + next action; stubs are flagged, not hidden.
- Workbench-confined; deterministic floor unchanged.

## Definition of done

`PATCH_PLAN.md` reads as a real plan: *here's what I'm building and why, the code
(or diff), how each file maps to acceptance criteria, what I knowingly stubbed,
and — if not applied — exactly what's auto-fixable vs what needs revision and the
next action.* The generator produced it from the contract + file-contract +
situational packet + focus, robustly (no refusal), and the content is kept for
repair/inspection.
