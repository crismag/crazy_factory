# 03 — Execution plan (subtasks, slices, tests, invariants)

Phase 9E. Each slice is gated (ruff + mypy + full suite under the clean-config
stash) and reversible. The deterministic floor and #37 budgets/no-progress
monitor stay in force throughout.

## Subtasks

| ST | What | Touches | Risk |
|---|---|---|---|
| **ST1** | **Skill library** — `Skill`/`SkillCall`, `SKILLS` registry, `render_catalog`, `validate_call`, `execute`; initial **repair** skills (`autofix_lint`, `strip_unused_imports`, `format_code`) + **scope** skills (`keep_only_files`, `defer_files`). Generalizes `recovery_router.ACTION_TYPES`. | new `scripts/skill_library.py` | med |
| **ST2** | **Keep-the-work** — persist generated patch content before adjudication; repair skills operate on the kept content. | `proposal_applier.py` (+ `persist_patch_content`) | low |
| **ST3** | **Deterministic fixable scan + auto-repair in the apply path** — before any reject, run `autofix_lint`/`keep_only_files` on kept content; only non-fixable issues continue. Closes the "unused import → empty app" failure **without any LLM**. | `proposal_applier.py` | med |
| **ST4** | **Adjudicator role** — `scripts/adjudicator.py`: disposition taxonomy, reviewer-model call, the decision ladder (floor → fixable scan → LLM → fallback), structured output, deterministic fallback. Consumes the `DiagnosisPacket` + seed grounding. | new `adjudicator.py` | high |
| **ST5** | **Wire adjudication into `run_application_stage`** — replace the binary gate with `adjudicate → execute allowed skills → apply/redirect/escalate`; `redirect` flows through `recovery_router` (reuse #37 classes/escalation). | `proposal_applier.py`, `factory_advance.py`, `recovery_router.py` | high |
| **ST6** | **Seed-derived project contract** — `derive_project_contract(seed, sub_contexts)`; supersede/generate `architecture.json`; feed `required_tree`/`required_behaviors`/`forbidden_tech` into acceptance + the floor + the adjudicator. Adds the missing `data/tasks.json`/`README`/UI. | new `project_contract.py`, `architecture.py`, `acceptance_check.py` | high |
| **ST7** | **redirect/context skills** — `revise_contract`, `update_focus`, `split_task`, `request_new_proposal`, `add_required_file`, `generate_subcontext`, `expand_focus_contract`. | `skill_library.py`, `recovery_router.py` | med |
| **ST8** | **Tests + autopilot re-run** — mocked-LLM per disposition; per-skill unit tests; floor-wins; LLM-down fallback; then a live task-board run measured by `crazy-admin metrics`/`acceptance`. | tests + scripts | — |

## Recommended order (each stop-safe)

- **Slice 1 = ST1 + ST2 + ST3.** *No LLM.* Skill library + keep-the-work +
  deterministic auto-repair in the apply path. **This alone fixes the current
  empty-app failure** (autofix the unused import, scope-down the extra modules,
  apply the real file) and is fully testable without a model. Highest value,
  lowest risk — do first.
- **Slice 2 = ST4 + ST5.** Add the LLM adjudicator above the deterministic
  scan; wire dispositions into apply + recovery. The LLM now *directs* the
  skills; `redirect` re-plans instead of discarding.
- **Slice 3 = ST6.** Seed-derived contract becomes the direction + acceptance
  basis; kill the hand-authored `architecture.json` drift.
- **Slice 4 = ST7 + ST8.** Redirect/context skills (the LLM authors sub-contexts
  and re-scopes), then the measured live re-run.

Rationale: Slice 1 delivers the concrete fix the user is blocked on *without*
betting on the local model; the LLM layers (2–4) add direction/intelligence on
top of a safe, deterministic base.

## Tests (per slice)

- **Skills:** each skill unit-tested deterministically; `validate_call` rejects
  unknown names, bad schema, out-of-workbench paths; `autofix_lint` removes a
  known unused import; `keep_only_files` drops out-of-focus files + records
  deferrals.
- **Keep-the-work:** a rejected/redirected patch's content is persisted and
  readable; repair transforms the saved content (not regenerated).
- **Adjudicator (mocked LLM):** one test per disposition (accept/fix/scope_down/
  redirect/escalate); **floor wins** (a forbidden import → `reject_unsafe` even
  if the LLM says accept); **LLM-down → deterministic fallback**, never fake
  accept; unknown skill call dropped.
- **Seed grounding:** `derive_project_contract` yields the full seed tree
  (incl. `data/tasks.json`, UI); a `flask`/`sqlite3` import → `reject_unsafe`
  from `forbidden_tech`; acceptance enforces `required_tree`.
- **Apply path:** the exact task-board failure (5-file patch + one unused
  import) now **applies the in-focus file** instead of producing an empty app.

## Safety invariants (must hold; tested)

- **Floor first & wins.** Only the deterministic floor emits `reject_unsafe`;
  the LLM cannot override or fabricate it.
- **LLM proposes, Python executes.** The LLM only returns skill calls;
  `validate_call` + the floor gate every execution; unknown/invalid calls are
  dropped, not run.
- **Bounded surface.** Destructive git / secrets / network are not skills, so
  not expressible. All path args are workbench-confined.
- **No discard.** Non-accept dispositions keep generated content.
- **Degrade safely.** LLM unavailable → deterministic fixables only, else
  escalate; never a fake accept.
- **Loop bounded.** #37 attempt budgets + no-progress monitor still terminate
  the loop; re-adjudication after a `fix` is counted.
- **Config untouched.** Owner's live `config/*.yaml` never committed; suite runs
  under the clean-config stash.

## Definition of done for 9E

- The task-board run **applies real files** (no empty app from a lint nit);
  fixables are fixed, over-reach is scoped down, and only direction divergence
  or safety stops a patch.
- Rejection decisions are **grounded in the seed-derived contract**, and the
  seed's full tree/behaviors/forbidden-tech are enforced.
- Every accept/fix/scope/redirect is an **auditable, skill-driven** action; the
  LLM directs, Python enforces.

## Out of scope (deferred)

Model-switching on escalation; a persistent cross-run skill-learning/knowledge
graph; multi-project skill sharing. The deterministic catalog + reviewer-model
adjudication cover the high-value path first.
