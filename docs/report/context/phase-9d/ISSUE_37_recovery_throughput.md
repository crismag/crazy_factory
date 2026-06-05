# Issue #37 — Excessive Rejection Loops / Throughput — Subtasks & Execution Plan

GitHub: crismag/crazy_factory#37 ("Excessive Rejection Loops Are Crippling
Development Throughput"). Goal: turn recovery from *"reject → regenerate →
reject → park(budget)"* into *"diagnose → repair → advance, escalate on
repetition, park with a reason."*

## Already shipped this session (close part of #37)

- **#37 §3 — no validation after failed apply:** `factory_advance` now skips
  whole-project validation on any beat where the apply was rejected (kills the
  phantom `ruff E902 / pytest exit 5` against an unwritten project).
- **#37 §1 symptom — syntax loops:** `proposal_applier.parse_patch_plan`
  unfences per-file content (the "invalid syntax (line 1)" fence bug).
- **#37 §4/§5 infra (partial):** `DiagnosisPacket` already feeds prior rejection
  reasons + validation + workspace + acceptance into the next coder beat;
  `run_metrics` already reports files/tests/checklist/acceptance.

## Subtasks (remaining)

| ST | #37 § | What | Risk |
|---|---|---|---|
| **ST1** | §1 | **Failure taxonomy** — `classify_failure(reasons) → class` (`NO_CONTENT`, `PROPOSAL_DESYNC`, `SYNTAX`, `INCOMPLETE`, `LINT`, `CONTRACT`, `UNKNOWN`); class-driven recovery routing. Closes the previously-parked `NO_CONTENT` gap. | low |
| **ST2** | (bug) | **`PROPOSAL_DESYNC` fix** — `proposal_id '3' != approved '2'` after regenerate → re-propose cleanly (clear approval + retire proposal/patch), not park. | low |
| **ST3** | §2,§4 | **Escalation ladder** — persist `recovery_class_history`; when the same class repeats ≥ N, **escalate to park with a classified diagnosis + mitigation** instead of blind-regenerating. Replace bare "budget exhausted" with the classified reason. | med |
| **ST4** | §6 | **No-progress monitor** — track files-applied / checklist-done deltas; over M beats with no application and no checklist advance → `NO_PROGRESS` park with diagnosis. | med |
| **ST5** | §4 | **Metrics as a loop signal** — ST4 *is* the metric-as-control wiring (`run_metrics` counters drive the monitor). | low |

Deferred (documented, not in this pass): model-switching on escalation, a live
"why are we stuck?" LLM analysis step (the deterministic taxonomy + the packet's
reason feedback cover the high-value path first).

## Execution order (each gated + reversible)

- **F1 = ST1 + ST2 + ST3** — all in `recovery_router` (+ a small `project_state`
  field for history). Self-contained, testable without the live model.
- **F2 = ST4 + ST5** — `factory_advance` loop counters + a `NO_PROGRESS`
  recovery path; touches `mission_state` for the persisted counter.

## Design — F1 (recovery_router)

```
classify_failure(reasons) -> CLASS         # most-specific-first string match
plan_recovery:
  trigger/attempt/reasons (unchanged)
  cls = classify_failure(reasons)
  repeats = trailing count of cls in project_state["recovery_class_history"]
  if attempt > max_attempts OR repeats >= ESCALATE_AFTER:
      -> park, reason = classified diagnosis + _MITIGATION[cls]   # not "budget exhausted"
  else route by class:
      NO_CONTENT|SYNTAX|LINT      -> regenerate_patch (retire patch artifacts)
      INCOMPLETE|PROPOSAL_DESYNC  -> revise_proposal (clear approval + retire proposal/patch + request_new_proposal)
      CONTRACT|UNKNOWN            -> park (classified diagnosis)
apply_recovery: append cls to recovery_class_history (capped)
```

Invariants preserved: deterministic floor unchanged; existing decision values for
syntax/unused-import/missing-tests/completeness stay the same (now via the
taxonomy); park always carries an actionable, classified reason.

## Design — F2 (no-progress monitor)

```
each beat: progressed = application_result.applied OR checklist_item_completed
  if progressed: project_state["beats_without_progress"] = 0
  else: increment
  if beats_without_progress >= NO_PROGRESS_BEATS: blocker = NO_PROGRESS (park w/ diagnosis)
```

`NO_PROGRESS` is a persistent blocker (stall_detector) → the loop stops churning.

## Acceptance for #37

- A repeated single failure class escalates to a **classified** park
  ("Repeated SYNTAX failures (3×): …mitigation") rather than bare "budget
  exhausted." (tested)
- `NO_CONTENT` and `PROPOSAL_DESYNC` no longer park with "no rule matched";
  they regenerate / re-propose. (tested)
- No validation noise after a rejected apply (shipped).
- A run that applies nothing and completes nothing over M beats trips
  `NO_PROGRESS` instead of looping to budget. (tested)
