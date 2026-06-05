# Execution Backlog — stored planned tasks (9D leftovers · #37 · 9E)

A durable, dependency-ordered queue of planned tasks for later execution.
Status: `DONE` (implemented) · `QUEUED` (planned, not started). Each task links
to its detailed plan doc. Run every implemented slice through the gate: `ruff` +
`mypy` + full suite under the clean-config stash.

> **Governing principle (see README):** scripts are *utility + bounded
> controls*, not a brain — deterministic safety rails + skill validation/
> execution + observability only. **Decisions are skill-governed adjudication
> (LLM picks bounded skills).** Do NOT grow Python heuristics — especially in
> recovery. New failure handling = a new **skill** or adjudicator reasoning, not
> a new `if`-branch. Implement every item below this way.

## Already implemented (for reference)

| Item | Status | Where |
|---|---|---|
| 9D A–E (visibility, DiagnosisPacket, requirement expansion, completeness reviewer, acceptance checker) | DONE (committed) | 9D package |
| Issue #37 — failure taxonomy + escalation + no-progress monitor | DONE (committed `b68d627`) — **but per the governing principle, this deterministic router is now the "heuristic pile" to STOP growing**: keep it thin (fast-path + observability + no-progress rail) and migrate decisions to the adjudicator + skill catalog (see 9E.S1b). | ISSUE_37_recovery_throughput.md |
| Fence-unfence in `parse_patch_plan` (the "invalid syntax line 1") | DONE | proposal_applier.py |
| Skip validation after a rejected apply (no phantom E902/no-tests) | DONE | factory_advance.py |
| 9E.7 Slice 1 — planner robustness (`llm_interaction.py` + planner wiring) | DONE (`dbe959a`) | 07_robust_llm_calls.md |
| **9E.S0** — severity policy module (`severity.py`) | DONE (`6dc3a20`) | severity.py |
| **9E.S1** — skill library + apply-path lint autofix (**empty-app unblocker**) | DONE (`d5fc4d2`) | skill_library.py / proposal_applier.py |
| **9E EVID-1** — carry rejection reasons via state (packet) | DONE (`a9f5bec`) | mission_state.py / diagnosis_packet.py |
| **9E.S1b** — recovery-executes-fixes | SUPERSEDED by 9E.S1 (lint auto-fixed pre-apply, no longer reaches recovery); residual deferred to the adjudicator (9E.S2) per the no-heuristics principle | — |

## QUEUED — execution order

Tiered by dependency. **Tier 0 items are ready now (no new deps).**

### Tier 0 — ready now (mostly deterministic / no-LLM)

| ID | Task | Plan | Risk | Notes |
|---|---|---|---|---|
| **9E.S0** | **Severity & governance policy (foundational)** — central `severity_of(finding) -> BLOCK\|FIX\|WARN\|INFO` consulted by every gate. **Lint/style/format/guideline findings are FIX or WARN, never BLOCK** — flow proceeds (auto-fixed or recorded), so non-critical issues can't cripple generation. Only the **safety floor** (secrets, destructive git, path-escape, self-authorization, forbidden tech) and **direction divergence** are BLOCK. **Split governance into HARD rules (block) vs GUIDELINES (advisory/warn)** — e.g. "prefer src/ layout" is a guideline (warn), "no writes outside workbench" is a hard rule (block). Wire into `validate_patch_plan` (demote `unused import`/format to WARN/FIX — **flips `test_rejects_unused_imports_before_apply`**), the #37 failure taxonomy (tag each class with a severity), and the adjudication dispositions (severity → accept/fix/warn/redirect/reject_unsafe). | 00, 01 + (reviews) | med | underpins S1/S1b/adjudication; "lint is not critical" |
| **9E.S0b** | **Overridable blocks & owner-review checkpoints** — no block is a silent dead-end. Every gate stop emits an **owner-review decision point** (reason · rule/decision violated · case-for-override · actions: approve/override/revise-constraint/revise-seed), recorded as an ADR in `decisions.md`. Split blocks into **absolute safety floor** (owner-override only, explicit+logged, AI NEVER auto-bypasses) vs **policy/decision blocks** (re-openable; AI may *recommend* reopening when evidence shows the constraint contradicts a required behavior). Add an **owner-enabled `allow_auto_bypass` capability (default OFF)** that may auto-relax **policy/decision blocks only** (never the floor), bounded + logged + reversible. Add **decision re-evaluation** so a later iteration can reopen a wrong prior decision (seeder/earlier-block). Reuses `needs_owner_decision` / `CONTRACT_REVIEW` owner-checklist / capability bridge. | 00, 02 + (governance review) | high | preserves the safety-floor invariant: owner is the override authority |
| **9E.S0c** | **Externalize the reject/deny/allow policy to owner-visible config** — no hardcoded, non-overridable deny lists. Move the ~14 constants (`FORBIDDEN_APPLY_PREFIXES`/`FORBIDDEN_EXACT_PATHS`/`_PLACEHOLDER_PHRASES`/`_INCOMPLETE_NOTE_PATTERNS` in proposal_applier; `FORBIDDEN_PATH_PREFIXES`/`SECRET_MARKERS`/`WORKBENCH_FORBIDDEN_TOP`/`PLACEHOLDER_ENV_FILES` in coder_proposal; `FORBIDDEN_SCOPE_KEYWORDS`/`ALLOWED_APPROVAL_STATUSES` in task_contract; `ALLOWED_COMMANDS`/`FORBIDDEN_TOKENS` in validation_runner; `ALLOWED_GIT_SUBCOMMANDS`/git_guard ops; `REFUSAL_MARKERS`; `_CONFLICT_MARKERS`) into an owner-editable **`config/rejection_policy.yaml`** (+ per-project override). **Current values become defaults** (no behavior change). Add a **`crazy-admin policy`** command + generated **`POLICY.md` checklist** so the owner sees every active rejectable pattern + its severity. Tier each by **severity (S0)**; mark floor entries **HARD/owner-override-only + logged (S0b)**; **AI never edits the policy** (owner-only). | S0, S0b + (policy inventory) | med | "no hidden hardcoded rejects; user-aware + overridable" |
| **9E.S1** | **Skill library + keep-the-work + deterministic auto-repair in the apply path** (ST1+ST2+ST3) — autofix lint, scope-down extras, persist patch content. **Unblocks the empty-app failure without the model.** | 01, 02, 03 | med | the keystone; highest value |
| **9E.S1b** | **Recovery executes fixes via SKILLS (not retire+re-ask, not more heuristics)** — give recovery the **executable repair skills** (`autofix_lint`/`strip_unused_imports`/`keep_only_files`) and let the **adjudicator select the fix skill** for a fixable defect, so recovery DOES the fix it diagnoses instead of `regenerate_patch`→`park`. Per the governing principle: this is **skill selection, not a new deterministic class→action branch** — keep the existing #37 `classify_failure` router **thin (fast-path/observability)** and migrate decisions to the adjudicator + catalog; do not grow the heuristic pile. (Defense-in-depth behind 9E.S1's apply-path autofix.) | 01, 00 + (recovery_decision review) | med | "make rejection do real work" + "no growing heuristics" |
| **EVID-1** | **Packet sources from state, not deleted artifacts** — recovery retires `patch_plan.json`, so the DiagnosisPacket loses the rejection it must carry forward. Read rejection reasons from `project_state` (`last_application_reasons`/`recovery_class_history`). | (remaining-files review) | low | NEW bug found in `current_packet.json` |
| **STATE-1** | **State coherence** — `status` must reflect blocked/parked (not "planning" while `recovery_exhausted`); sync/derive report mode from effective apply (not stale `factory_state.mode`); unify task-id scheme (`task_001` vs `task-board-001`). | (state review) | low | NEW |
| **RPT-S1** | **Truthful reporting Slice 1** (RPT1+RPT4) — kill "dry-run/no edit" after an apply attempt; workbench-scope the CHECKPOINT file lists (stop leaking `config/projects.yaml`). | 06 | low | |
| **DOC-S1** | **Living docs Slice 1** (D1+D2, no-LLM) — structured doc writer + real seed → `docs/seed.md` + deterministic `requirements`/`architecture`/`README` from the seed-derived contract. | 04 | med | |
| **CX-S1** | **Context expansion Slice 1** (CX1+CX2) — re-target `context_growth` to `factory_context/`; expand real seed → `PROJECT_GOAL.md` (kill placeholder). | 05 | med | |
| **9E.9** | **Architect Intelligence** (subsumes 9E.7-L3) — condition the LLM into a competent architect *before* the work: a **skill primer** (persona + method scaffold + quality bar + worked few-shot; rewrite `ARCHITECT_RULES.md` charter→method), a **structured project-level architecture output** (entities/modules/deps/data_flow/risks/decisions/sequenced coherent `task_candidates`/nfrs; role-fit rejects code-as-architecture), **downstream wiring** (its `task_candidates` feed the seed-derived contract ST6 + decomposition ST6/ST11; planner consumes the architecture, not code), **iterative sharpening** of `architecture.md`, and a **self-critique pass**. ARC1–ARC6 + slices in doc 09. | **09** | high | "architect must rise to a higher level; build the skill first" |
| **9E.7-L3** | **(SUBSUMED by 9E.9/ARC2)** Architect on `structured_call` + defined expansion shape** — the architect currently free-form-chats and produced **finished code instead of an architecture expansion** (role confusion), which is both wasted *and* poisons the planner (fed in as "Architect Expansion"). Route through `structured_call` with priming + a **schema for a real expansion** (`boundaries`, `dependencies`, `risks`, `task_candidates` — NOT code), and add **role-fit validation** that rejects code-as-expansion. Stops the architect doing the coder's job and stops the cascade into the planner. | 07 | med | |
| **MISC-1** | Reconcile `app/` vs `src/` convention (scaffold + base coder prompt say app/; seed/architecture say src/); clarify the validation skip-reason wording. | (reviews) | low | |

### Tier 1 — needs the seed-derived contract (9E ST6)

| ID | Task | Plan | Risk |
|---|---|---|---|
| **9E.ST6** | **Seed-derived ProjectContract** — derive structure/acceptance/forbidden-tech from the seed; supersede the hand-authored `architecture.json` (adds `data/tasks.json`, README, UI). **Also: decomposition must emit COHERENT, right-sized deliverables** (e.g. a module **+ its tests** as one item, or a vertical behavior slice), not per-file fragments — so each iteration accomplishes something observable (and the model+tests no longer split, removing the "no test in patch" rejection). Touches `completion.items_from_required_files`. | 02 | high |
| **9E.ST9** | **Enforce the contracts we already generate** — wire `FocusRequirementSpec` (`required_behaviors`/`required_tests`) into the completeness reviewer + `acceptance_check` (today they're advisory-only). | 02 + (contract review) | med |
| **9E.ST13** | **Contract artifact uplift** — make `planned_task.json`/`PLANNED_TASK.md` traceable + evolvable. Add: criterion **IDs** + structured **`target_files`** + criterion↔test↔file **traceability** (link the `file_contract`/`FocusRequirementSpec`); **provenance/versioning** (architect/planner source, iteration, timestamp, supersedes — so contracts visibly sharpen each iteration); **real stop-conditions** (the "Risks And Stop Conditions" section currently has none); a **reframed `validation_plan`** (how to *verify* acceptance, reconciled with `test_plan.json`, not a build plan); and a **`dependencies`** field. | 02 + (PLANNED_TASK review) | med |
| **9E.ST11** | **Seed-complete checklist** — derive `MASTER_CHECKLIST.md` from the **seed-derived ProjectContract's `required_tree` + `required_behaviors`**, not the narrow hand-authored `architecture.json.required_files`. Must include the items the seed requires but the checklist drops: `README.md`, `data/tasks.json`, the **Tkinter UI behaviors** (add/edit/delete/toggle as user actions), **persistence edge cases** (missing→empty, empty list, corrupt JSON), a **UI smoke/launch** validation item, and a final **whole-project acceptance** item. Touches `completion`/`architecture` + ST6. | 02 + (MASTER_CHECKLIST review) | med |
| **9E.ST10** | **Contract scope & coherence adjudication** — extend `contract_review` from completeness/safety to also score **scope/value/coherence**: does the task meaningfully advance the seed? is it right-sized? is it internally coherent? `redirect`/`revise_contract` when not. Fix the concrete bugs found: the contract **excludes the tests it also requires** (`Explicit Exclusions: "Writing unit tests in tests/test_task_model.py"` vs Validation Plan/acceptance requiring them), and acceptance criteria that **conflate single-file scope with whole-project gates**. | 00, 02 + (CONTRACT_REVIEW review) | med |
| **DOC-S2** | Living docs Slice 2 (D3+D4) — doc-growth skills + per-beat triggers. | 04 | med |
| **CX-S2** | Context expansion Slice 2 (CX3+CX4) — supporting context set from the contract + wire into `advance`. | 05 | med |
| **RPT-S2** | Truthful reporting Slice 2 (RPT2+RPT3+RPT5) — narrative ACTIVITY + aggregate DAILY from a shared `progress_snapshot()`. | 06 | med |
| **9E.7-L4** | Curate planner/architect context (focus + blocker, not the full `factory_tasks` dump). | 07 | med |

### Tier 2 — the LLM adjudication layer (needs S1 + ST6)

| ID | Task | Plan | Risk |
|---|---|---|---|
| **9E.S2** | **Adjudicator role + wiring** (ST4+ST5) — disposition taxonomy; replace the binary gate with adjudicate→skills→apply/redirect/escalate; `redirect` via recovery. | 00, 03 | high |
| **9E.8** | **Patch-plan generation & artifact uplift** (subsumes ST12) — improve BOTH what generates the patch plan (richer schema + proper prompt/context: file contract + situational packet + focus + self-review, via `structured_call`) AND the render (content/diff, intent, acceptance-coverage table, severity-classified reasons, disposition + next action, stub flags). Slice 1 (render uplift, low-LLM) makes the doc actionable immediately. | **08** | med |
| **9E.S3** | Redirect/context skills (ST7) — `revise_contract`, `split_task`, `update_focus`, `request_new_proposal`, `add_required_file`, `generate_subcontext`. | 01, 03 | med |
| **DOC-S3 / CX-S3** | Dual-consumption loop — AI re-ingests its own `docs/` + `factory_context/` as grounding. | 04, 05 | med |
| **9E.7-L5** | Generalize the robust-call wrapper to coder/contract/test/adjudicator. | 07 | med |

### Tier 3 — closing the loop

| ID | Task | Plan | Risk |
|---|---|---|---|
| **9E.S4** | Acceptance/loop-until-accepted hardened on the new gates; measured task-board re-run vs `crazy-admin metrics`/`acceptance`. | 03, 07_target | — |
| **DEFER** | Model-switching on escalation; cross-run skill/knowledge learning; `recovery_manager`→stall-reporter rename; per-attempt `attempt_history` log. | various | — |

## Recommended first execution session

`9E.S1` (skill library + keep-work + auto-repair) → it unblocks the empty-app
failure deterministically and underpins the adjudicator. Pair with the cheap
Tier-0 wins: `EVID-1`, `STATE-1`, `RPT-S1` (all low-risk, no-LLM).

## How to resume

1. Pick the next `QUEUED` task (Tier 0 first).
2. Open its plan doc (column "Plan") for the detailed subtasks/tests/invariants.
3. Implement → gate → mark `DONE` here (and note commit).
