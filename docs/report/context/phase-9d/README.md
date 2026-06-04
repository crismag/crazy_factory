# Phase 9D — Situational Context, Prompt Fidelity, Acceptance-Driven Convergence

Generated: 2026-06-04

This package expands [docs/direction_context_9D.md](../../../direction_context_9D.md)
into per-slice implementation plans, each anchored to the **actual current
code** (file:line) rather than greenfield prose. The direction doc says *what*;
these docs say *exactly where, how, in what order, and how to test it* — verified
against the tree as of this writing.

## One-line thesis

The factory's governance is sound; output is shallow because the LLM is **under-
briefed and un-reviewed**. 9D builds the missing **evidence layer** between the
model and the gates: feed curated ground truth (never factory prose), demand
completeness up front, and only retire work on acceptance evidence.

```
LLM = imagination and synthesis      Factory = evidence, enforcement, truth
```

## Load order

1. [00_prompt_visibility.md](00_prompt_visibility.md) — Slice 1 / 9D.0 (smallest high-impact; do first)
2. [01_diagnosis_packet.md](01_diagnosis_packet.md) — Slice 2 / 9D.1 (the keystone artifact)
3. [02_packet_wiring.md](02_packet_wiring.md) — Slices 3–4 / 9D.2
4. [03_requirement_expansion.md](03_requirement_expansion.md) — Slice 5 / 9D.3
5. [04_completeness_reviewer.md](04_completeness_reviewer.md) — Slice 6 / 9D.4
6. [05_acceptance_retirement.md](05_acceptance_retirement.md) — Slice 7 / 9D.5
7. [06_reporting_and_logs.md](06_reporting_and_logs.md) — Slice 8 / 9D.6 + 9D.7
8. [07_acceptance_target.md](07_acceptance_target.md) — 9D.8 (definition of done)
9. [08_sequencing_invariants.md](08_sequencing_invariants.md) — work order, module reconciliation, safety

## Current-code map (what each slice touches)

| Concern | Lives in | Current state |
|---|---|---|
| Shared prompt assembly | `scripts/prompt_builder.py` | constraints + goal + role rules; sound structure |
| Role rules | `factory/instructions/*_RULES.md` | abstract charters; `TEST_BUILDER_RULES` **stale** (forbids whole-project checks) |
| Coder proposal prompt | `scripts/coder_proposal.py:1016` (instruction), `:1032` (`contract_summary`) | gets objective/scope/acceptance_criteria; **no failure/rejection history** |
| Patch-plan (code) prompt | `scripts/proposal_applier.py` `request_patch_plan` | `proposal_summary` = file lists + steps; **no acceptance_criteria/objective** |
| Placeholder gate | `scripts/proposal_applier.py:408` `_is_placeholder_body` | exists (rejects `pass`-only); prompt never *asks* for completeness |
| Decomposition | `scripts/completion.py` `items_from_required_files` | deterministic, **generic per-file text** |
| Planning context assembly | `scripts/factory_advance.py:330-359` | `goal_text` + `planning_context` (focus = generic item) |
| Item tick (retirement) | `scripts/factory_advance.py:688` | ticks on whole-project coherence-green only |
| Required-files check | `scripts/architecture.py:198` `missing_required` | defined, **zero callers** |
| State / blockers | `scripts/mission_state.py` | `failure_count`, `remediation_attempt`, `last_*_status`; **no `attempt_history`** |
| Rejection reasons (source) | `planned_task.json` (validation block), `coder_proposal.json` (verdict), application result | structured JSON — read these, not the `.md` prose |
| Recovery / remediation | `scripts/recovery_router.py`, `scripts/remediation.py`, `scripts/recovery_manager.py` | overlapping; reconcile (see 08) |
| Report boilerplate | `scripts/report_writer.py:475` | hardcoded "No application code was modified" — a lie after apply |
| Per-project state root | `factory_state/projects/<id>/` | engine-managed; packet output candidate |

## Status

Already landed this effort (not part of 9D scope below): pytest-exit-5 fix,
coherence-command tightening, deterministic `recovery_router` for lint-quality
rejections, the `_is_placeholder_body` patch gate, the
`application_rejected`-outranks-`validation_failed` state precedence fix, and the
three mypy fixes. 9D builds on top of these.

## Guiding rule for every slice

**Feed facts, not factory prose.** Ground truth (exact pytest/ruff/compile
output, exact rejection reasons, real file contents) is fed generously. Generated
narrative reports are excluded until they are made truthful + structured
(09D.6). Stale prior-run data is freshness-filtered out. See
[08_sequencing_invariants.md](08_sequencing_invariants.md) for the non-negotiable
safety invariants that hold across all slices.
