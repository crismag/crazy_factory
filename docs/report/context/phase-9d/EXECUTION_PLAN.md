# Phase 9D — Implementation Execution Plan (Lead Architect Review)

Reviewer stance: verify the 9D design against the **current** codebase; do not
redesign. All findings are anchored to real `file:line`. Verified gate order in
`factory_advance.main`:

```
contract stage ─▶ contract floor+review (contract_review: valid|repair|needs_owner_review|reject_unsafe)
 ─▶ remediation-plan (plan_remediation; gates on current_blocker==validation_failed)
 ─▶ coder stage ─▶ coder/proposal verdict (valid|rejected)
 ─▶ application stage ─▶ validate_patch_plan gate (approval ▸ syntax compile ▸ _is_placeholder_body ▸ patch_contract_violations) ─▶ apply|reject
 ─▶ is_contract_conflict (self-rejection detection)
 ─▶ test_builder ─▶ validation (whole-project coherence: compileall+pytest+ruff)
 ─▶ checkpoint ─▶ update_success_state (blockers; precedence fix landed)
 ─▶ retirement (mark_first_open_done: applied && !preserved && validation==passed)
 ─▶ run_recovery_router (ONLY if current_blocker==application_rejected && allow_remediation)
```

---

# Deliverable 1 — 9D Readiness Assessment

| Slice | Status | Files affected | Risk | Effort | Hard deps | Potential regressions |
|---|---|---|---|---|---|---|
| **9D.0** Prompt visibility | **Missing** | `proposal_applier.py`, `coder_proposal.py`, `prompt_builder.py`, `TEST_BUILDER_RULES.md`, `PLANNER_RULES.md` | Low | S (½ day) | none | downstream flow scripts grep summary lines (not these); none expected |
| **9D.1** DiagnosisPacket | **Missing** | new `diagnosis_packet.py` + test | Low–Med | M (1–2 d) | none (reads existing artifacts) | none (no consumers yet); risk = sourcing `attempt_history` |
| **9D.2** Wire packet → coder/patch-plan | **Missing** | `coder_proposal.py`, `proposal_applier.py`, `factory_advance.py` | Med | M | 9D.1 (+9D.0) | prompt bloat / token budget; `None` packet must no-op |
| **9D.3** Requirement expansion | **Missing** | new `requirement_expander.py`, `factory_advance.py`, `completion.py`/`contract_stage.py`, new rules | **High** | L (2–3 d) | seed-reaches-planning (landed) | **convergence**: must not re-vary decomposition; freezing required |
| **9D.4** Completeness reviewer | **Missing** | new `completeness_review.py`, `proposal_applier.py`/`factory_advance.py`, `recovery_router.py` | **High** | L | 9D.1, 9D.3 | **infinite revise loops**; false rejection; Ollama-down fake-pass |
| **9D.5** Acceptance retirement | **Partial** (`missing_required` exists, **0 callers**; tick on coherence only @`factory_advance.py:688`) | `factory_advance.py`, `architecture.py`, `completion.py` | Med | M | `missing_required` half: none; full: 9D.3+9D.4 | **retirement deadlock** (never completes); over-strict gate |
| **9D.6** Reporting truthfulness | **Partial** (reports exist; `report_writer.py:475` lies) | `report_writer.py`, `factory_advance.py` | Low–Med | M | none (consumes existing results) | flow scripts grep specific summary tokens — preserve them |
| **9D.7** Fresh debug logs | **Missing** (single append-only `CRAZY_FACTORY_LOGFILE`) | `tests/autopilot_*.sh`, `factory_messaging.py` (sink) | Low | S | none | log-path consumers; symlink portability |
| **9D.8** Acceptance target/checker | **Partial** (`architecture.json.required_files` exist; no checker; autopilot exits 0 on partial) | new checker (harness or `crazy_admin.py`), `tests/autopilot_taskboard.sh` | Med | M | 9D.5 | false "success"; UI smoke hang |

Recovery note: **9D.2/9D.4 recovery integration is Partial** — `recovery_router`
already deterministically handles `application_rejected` (→`revise_proposal`) and
patch issues (→`regenerate_patch`), but emits only 3 decisions, reads
`project_state` not a packet, and has no LLM escalation.

---

# Deliverable 2 — Detailed Implementation Plan

### 9D.0 Prompt visibility
- **Objective:** stop blind codegen; show the success definition + a quality bar.
- **Current:** `request_patch_plan` `proposal_summary` omits acceptance criteria;
  no quality bar in either generation prompt; `TEST_BUILDER_RULES` forbids
  whole-project checks (contradicts the coherence gate).
- **Modify:** add `objective/scope/acceptance_criteria/validation_expectations`
  to `proposal_summary`; append shared `QUALITY_BAR` to coder + patch-plan
  instructions; rewrite the stale test-builder bullet; add acceptance-criteria
  format to `PLANNER_RULES`.
- **New files:** none. **State:** none. **Data flow:** contract already loaded;
  thread it into `request_patch_plan`. **Validation:** unchanged. **Tests:**
  assert criteria + quality bar present in rendered prompts; assert stale string
  gone. (See 00_prompt_visibility.md for exact edits.)

### 9D.1 DiagnosisPacket
- **Objective:** one bounded, deterministic, role-sliceable evidence object.
- **Current:** none; ground truth scattered across `planned_task.json`,
  `coder_proposal.json`, validation result, `architecture.json`, checklist, state.
- **New files:** `scripts/diagnosis_packet.py`, `tests/test_diagnosis_packet.py`.
- **State changes:** add `attempt_history: list` + `session_id` to `project_state`
  (additive; default `[]`/derived) — OR reconstruct latest attempt in v1.
- **Data flow:** builder reads structured artifacts only (never `*_REPORT.md`);
  output → `factory_state/projects/<id>/diagnosis/current_packet.json`.
- **Prompt/validation:** none (foundation only). **Tests:** see 01 doc.

### 9D.2 Wire packet → coder/patch-plan
- **Objective:** every retry sees exact prior failure/rejection.
- **Current:** coder gets contract summary + workbench source + (remediation-only)
  prior validation report; patch-plan gets file lists only.
- **Modify:** add `coder_slice()`/`patch_plan_slice()`; pass `packet` param into
  `run_coder_stage`/`request_patch_plan`; build packet once per beat in
  `factory_advance` (after stages that produce artifacts, before next gen).
- **State:** none new. **Data flow:** packet → role slice → prompt section.
- **Prompt:** add "What happened last time (ground truth)". **Tests:** 02 doc.

### 9D.3 Requirement expansion (Layer 1)
- **Objective:** generic checklist item → frozen per-file behavior/test contract.
- **Current:** `items_from_required_files` generic; `planning_context` =
  bundle+arch+generic focus.
- **New:** `scripts/requirement_expander.py` (+test+rules); `file_contracts/`
  persistence under `factory_context/`.
- **Modify:** `factory_advance.py:356-359` to load-or-expand-and-freeze, fold spec
  into focus + contract acceptance_criteria.
- **State:** frozen file-contract files (not project_state). **Data flow:** seed →
  spec → contract criteria → all downstream prompts. **Prompt:** new expander
  role. **Validation:** unchanged. Fallback: generic, `expansion_status=fallback`.

### 9D.4 Completeness reviewer (Layer 2)
- **Objective:** reject thin-but-valid before write.
- **Current:** pre-apply gates are deterministic (approval/syntax/placeholder/
  contract); coder verdict is structural, not behavioral.
- **New:** `scripts/completeness_review.py` (+test); reuse `contract_review`
  vocabulary (`valid|revise_proposal|reject`).
- **Modify:** call after patch-plan, before apply, in `run_application_stage`/
  `factory_advance`; route `revise_proposal` through `recovery_router` (add the
  decision wiring); `reject` → park/escalate.
- **State:** per-trigger budget (reuse remediation/recovery counters).
- **Data flow:** packet+file-contract+patch → verdict. **Prompt:** reviewer model.
  **Validation:** floor still runs first (authoritative).

### 9D.5 Acceptance retirement (Layer 3)
- **Objective:** retire on evidence, not coherence alone.
- **Current:** `mark_first_open_done` ticks on `applied && !preserved &&
  validation==passed` (`:688`); `missing_required` uncalled.
- **Modify:** add `item_acceptance()` (missing_required==[] + coherence +
  required-tests-present + reviewer!=blocking); gate the tick on it; write
  per-item evidence (`factory_tasks/checklist_evidence.json`).
- **State:** evidence record. **Data flow:** spec+validation+reviewer → tick.
- **Incremental:** land `missing_required` half first (no LLM).

### 9D.6 Reporting truthfulness
- **Objective:** reports = projection of facts.
- **Current:** `report_writer.py:475` hardcodes "No application code was
  modified."
- **Modify:** make write/context/success claims conditional on
  `application_result`/catalog/validation; add factual fields; forbidden-claim
  tests. Preserve flow-script-grepped summary tokens in `factory_advance`.

### 9D.7 Fresh debug logs
- **Objective:** per-run logs; kill stale-failure misreads.
- **Modify (script-side):** `logs/autopilot/<project>/<ts>/{debug.log,summary.md}`
  + `latest` symlink; shell computes `<ts>` (engine stays deterministic).

### 9D.8 Acceptance target/checker
- **Objective:** evidence-based success; exit 0 only when green.
- **New:** deterministic acceptance checker (5 criteria: files exist+non-stub,
  `missing_required==[]`, all items acceptance-complete, 3 validations pass,
  headless UI smoke). **Modify:** autopilot loops until accepted or budget,
  labels partial, exits nonzero otherwise.

---

# Deliverable 3 — Cross-Slice Dependency Audit

```
9D.0 ─(independent; FIRST)
9D.1 ─▶ 9D.2 ─▶ (better measurement of 9D.3/9D.4)
9D.1 ─▶ 9D.4 (packet input)
9D.1 ─▶ 9D.6 (packet_id field; soft)
9D.3 ─▶ 9D.4 (criteria to review against)   [HARD]
9D.3 ─▶ 9D.5(full) ─▶ 9D.8                   [HARD]
9D.5(missing_required half) ─(independent; early win)
9D.4 ─▶ 9D.5(full)                            [HARD]
9D.6 ─(independent; must precede any future report-feeding) [policy gate]
9D.7 ─(independent; script-side)
```

- **Hard:** 9D.1→9D.2/9D.4; 9D.3→9D.4/9D.5full/9D.8; 9D.4→9D.5full.
- **Soft:** 9D.0 improves measurability of all gen slices; 9D.1→9D.6 (packet id).
- **Circular risks:** none true. Watch the **9D.4↔recovery_router** seam: the
  reviewer emits `revise_proposal`, which the router must consume without
  re-triggering the reviewer in the same beat (one-shot per beat).
- **Sequencing hazards:**
  - Doing 9D.4 before 9D.3 = reviewing against thin criteria → noise. **Block.**
  - Doing 9D.5 full before 9D.4/9D.3 = retirement deadlock (no evidence source).
    Land only the `missing_required` half early.
  - Feeding reports to models (future) before 9D.6 = self-poisoning. **Block.**

---

# Deliverable 4 — State Architecture Review

**Existing state (`mission_state.py`):** `last_application_status`,
`last_validation_status`, `last_test_plan_status`, `last_patch_plan_id`,
`application_applied`, `current_blocker`, `resume_from`, `remediation_attempt`,
`failure_count`, `checks_run`, `_VALIDATION_PASS_PRESERVES_BLOCKERS` (+ fail-path
precedence, landed). `recovery_router` persists `recovery_decision.json` +
attempt counters via `_record_attempt`. No `attempt_history`, no `session_id`,
no per-item evidence, no packet reference.

**Must add:**
- `session_id` (per run) — for packet freshness filtering.
- `attempt_history: list[Attempt]` — capped (e.g. last 5), append in
  `update_success_state`. **Belongs in `project_state`** (authoritative,
  co-located with blockers/counters it summarizes). Full/older history → derive
  from artifacts; keep state small to avoid bloat/corruption.
- per-item acceptance evidence → **separate file**
  (`factory_tasks/checklist_evidence.json`), not `project_state` (keeps state
  lean, evidence is workbench-scoped).
- optional `last_packet_id` reference for report cross-linking.

**Should DiagnosisPacket be the canonical evidence object?** **Yes — as the
canonical read-model, not the write-model.** `project_state` remains the single
source of truth (blockers, counters, statuses); the packet is a *derived,
bounded, freshness-filtered projection* assembled from state + artifacts, and is
the only thing prompts/reviewers/router consume. This avoids two truth sources:
state writes facts; packet curates them for the model.

**Migration:** all additions are **additive with safe defaults** (`.get(...,
default)`), so existing `project_state.json` files load unchanged — no migration
script. `attempt_history` defaults `[]`; `session_id` derived if absent. Ship the
packet reading from artifacts first (v1), add `attempt_history` append in the
same slice if budget allows.

---

# Deliverable 5 — Recovery System Reconciliation

| System | Current ownership | Future ownership |
|---|---|---|
| `recovery_manager.build_recovery_plan` | stall → park + owner-advice strings; `set_blocked=True`; called by `mission_loop` | **Stall reporter only** (human-facing advice + park); no strategic routing |
| `recovery_router.plan_recovery` | deterministic decisions on `application_rejected`/patch issues; reads `project_state`; emits park/revise_proposal/regenerate_patch | **The strategic router**; consumes **DiagnosisPacket**; deterministic table first, LLM escalation later; gains decisions (`escalate_to_planner`, `needs_owner_decision`) |
| `remediation.py` | `validation_failed` → re-engage coder, bounded | **A tactic** (`regenerate_patch`/re-coder) the router selects; still gated on `validation_failed` of *applied* code |
| `completeness_review` (9D.4) | — | Pre-apply behavioral gate; feeds `revise_proposal` into the router |

**Overlaps/conflicts (resolved):**
- remediation vs router both drive the next coder action. Resolved by the landed
  blocker precedence: router owns `application_rejected`; remediation owns
  `validation_failed` *of applied code*. They are now mutually exclusive per beat.
- recovery_manager and recovery_router both say "recovery." Rename manager →
  stall reporter to end the naming collision.

**Final authority chain (highest wins):**
```
Deterministic floor (path/import/name/placeholder/syntax/self-auth/forbidden-op)
  ▶ recovery_router deterministic table (known signal→action)
    ▶ LLM recovery planner (escalation/ambiguity; never overrides floor)
      ▶ park / needs_owner_decision (owner)
```
Goal: **one** recovery architecture (router) with remediation as a tactic and
recovery_manager demoted to reporting.

---

# Deliverable 6 — Acceptance Gate Review

**Current gate order:**
```
contract floor (deterministic) ▶ contract_review (AI ladder)
 ▶ coder proposal verdict (structural)
 ▶ application gate: approval ▸ syntax-compile ▸ placeholder ▸ contract-paths
 ▶ is_contract_conflict (self-rejection)
 ▶ validation (whole-project coherence)
 ▶ checkpoint ▶ retirement (coherence-green only)
```

**Proposed gate order (additions in CAPS):**
```
REQUIREMENT EXPANSION (pre-contract, frozen)
 ▶ contract floor ▶ contract_review
 ▶ coder proposal verdict
 ▶ application gate (approval▸syntax▸placeholder▸contract-paths)
 ▶ COMPLETENESS REVIEW (behavioral, pre-write)        ← 9D.4
 ▶ apply ▶ is_contract_conflict
 ▶ validation (coherence)
 ▶ checkpoint
 ▶ ACCEPTANCE GATE (missing_required + required-tests + reviewer) ← 9D.5
 ▶ retirement
```

- **Missing gates:** behavioral completeness (pre-write), required-file coverage
  (pre-retire), seed-acceptance (pre-complete). All added by 9D.3–9D.5/9D.8.
- **Weak gates:** placeholder gate (catches `pass`, not minimal-but-real) —
  strengthened by the completeness reviewer above it.
- **Duplicate?** coder proposal verdict vs completeness reviewer are
  **complementary** (structural vs behavioral), not duplicates — keep both.
- **No gate may be added below the deterministic floor.** Floor stays first +
  authoritative.

---

# Deliverable 7 — Implementation Risk Register

| Risk | Impact | Likelihood | Detection | Mitigation | Rollback |
|---|---|---|---|---|---|
| **Prompt bloat** | slow/over-long; local model degrades | Med | token count per call; latency metric | packet already bounded; slices select not expand; per-file byte cap | feature-flag packet slices off → prompts revert |
| **Context explosion** | OOM / context-window overflow | Low–Med | assert packet size ≤ budget in builder | hard byte/line/attempt caps; truncate w/ flag | cap `attempt_window=1`; disable source_snapshot |
| **Packet staleness** | model acts on old failures | Med | `session_id` mismatch counter; test #3 | freshness filter excludes prior session/task | disable packet (consumers no-op on `None`) |
| **State corruption** | bad blockers/counters | Low | schema check on load; full-suite | additive defaults; never rewrite existing keys | ignore new fields (`.get` defaults) |
| **Infinite revise loops** | no convergence; burn budget | **High** | per-trigger attempt counter; repeated-decision detector | mandatory escalation ladder; budget; `repeated_failure_patterns` | router falls back to `park` at budget |
| **Retirement deadlock** | item never completes though correct | Med | item stuck N beats w/ validation passing | acceptance gate must be *satisfiable*; required-tests check tolerant of naming; owner override | revert tick to coherence-only |
| **False acceptance** | thin code marked done | Med (pre-9D.5) | acceptance evidence audit; success-checker | layered gate (missing_required+tests+reviewer) | n/a (strictly safer than today) |
| **False rejection** | good code blocked | Med | reviewer disagree-rate vs validation | floor authoritative; reviewer advisory→revise not hard-reject; Ollama-down→floor_only | disable reviewer → deterministic gates only |
| **Performance degradation** | extra LLM calls/beat (expander, reviewer) | Med | beat wall-clock; calls/beat | freeze expansion (1×/file); reviewer only pre-apply; reuse reviewer model | flags to disable expander/reviewer |
| **Reviewer fake-pass when Ollama down** | stub slips through | Med | `review_status=floor_only` flag | never auto-`valid` on error; fall to floor | inherent (floor still blocks) |
| **Flow-script breakage** (grepped summary tokens) | CI/flows fail | Low | run `tests/*_flow.sh` | preserve exact `factory_advance` summary lines | revert report-writer body |

---

# Deliverable 8 — Recommended Execution Order (stop-safe phases)

Each phase leaves the factory **fully functional**; stop after any phase.

### Phase A — Visibility & Truth (no new subsystems)
9D.0 (prompt visibility) + 9D.6 (report truthfulness) + 9D.7 (fresh logs) +
9D.5-half (`missing_required` in retirement).
- **Outcome:** code prompt sees acceptance criteria + quality bar; reports stop
  lying; logs fresh; items can't retire with files missing.
- **Verify:** prompts contain criteria; report tests; an item with missing files
  doesn't retire; full suite green.
- **Rollback:** revert edits (no schema/flow change).

### Phase B — Evidence Layer
9D.1 (DiagnosisPacket) + 9D.2 (wire into coder/patch-plan).
- **Outcome:** retries see exact prior failure/rejection; less repeat-stub.
- **Verify:** packet tests; manual beat shows rejection text in next prompt; no
  prior-session leakage.
- **Rollback:** consumers no-op on `None` packet → Phase A behavior.

### Phase C — Expansion
9D.3 (requirement expansion, frozen file contracts).
- **Outcome:** generic items become concrete per-file behavior/test contracts.
- **Verify:** contract `acceptance_criteria` populated from seed; second beat
  doesn't re-call model; Ollama-down → fallback flagged; convergence intact
  (checklist order/count unchanged).
- **Rollback:** disable expander → generic focus (today).

### Phase D — Curation & Acceptance
9D.4 (completeness reviewer) + 9D.5-full (acceptance retirement) + recovery
reconciliation (router consumes packet; remediation as tactic; manager→reporter).
- **Outcome:** thin code rejected pre-write; retirement on evidence; one recovery
  architecture.
- **Verify:** thin proposal → `revise_proposal` with missing behaviors; floor
  still wins; no infinite loop (budget+escalation); deadlock guard.
- **Rollback:** disable reviewer (gates→deterministic), revert tick to coherence.

### Phase E — Closed-loop demo
9D.8 (acceptance checker + autopilot loop-until-accepted).
- **Outcome:** task-board exits 0 only when fully green; partial → nonzero.
- **Verify:** partial run exits nonzero/labeled; full run exits 0; checker tested.
- **Rollback:** autopilot reverts to single-beat + honest "partial" label.

---

# Deliverable 9 — Success Metrics (with baselines to collect first)

Collect **baseline** on the current `main` over N≥5 task-board runs *before*
Phase A, then re-measure after each phase.

| Metric | Definition | Source | Target trend |
|---|---|---|---|
| **Stub rejection rate** | % proposals hitting `_is_placeholder_body` | application verdict logs | ↓ (prompt asks for completeness) |
| **Proposal retry rate** | avg coder attempts per checklist item | `attempt_history` | ↓ |
| **Acceptance coverage** | % required behaviors with a mapped passing test | file-contract spec vs tests | ↑ → 100% at completion |
| **Avg retries per item** | beats from focus→retire per item | checklist evidence timestamps | ↓ |
| **Retirement accuracy** | % retired items that pass an independent acceptance re-check | acceptance checker (9D.8) | ↑ → ~100% |
| **Validation pass rate** | % beats with coherence==passed | validation_result | ↑ |
| **Context utilization quality** | % retries where the next proposal addresses the prior rejection reason | packet rejection vs next diff | ↑ |
| **Recovery convergence rate** | % `application_rejected`/`validation_failed` that reach green within budget (not park) | router decisions + final state | ↑ |
| **Repeat-mistake rate** | % retries repeating an identical prior rejection | dedup of rejection strings | ↓ |
| **Beat latency / LLM calls per beat** | wall-clock + call count | run logs | watch (expander/reviewer add calls) |
| **Demo success** | task-board meets all 5 acceptance criteria & exits 0 | acceptance checker | reach green |

**Baseline harness:** run `tests/autopilot_taskboard.sh` (current) ×5, capture
per-beat: proposal verdict, placeholder hits, validation status, blocker, items
retired, final exit. Store under `docs/report/context/phase-9d/baseline/` so
each phase can be compared against it.

---

## Lead recommendation

Start with **Phase A** — it's pure win, no new subsystems, fully reversible, and
it makes Phases B–E measurable. Do **not** start 9D.4 before 9D.3 (reviewing
against thin criteria is noise) or 9D.5-full before its evidence sources exist.
The one architectural commitment to make up front: **DiagnosisPacket is the
canonical read-model; `project_state` stays the write-model** — everything else
composes around that seam.
