# Sequencing, module reconciliation, and safety invariants

## Work order (dependencies are real — respect them)

```
Slice 1  Prompt visibility ........... independent; do FIRST (cheapest win)
Slice 2  DiagnosisPacket ............. foundation; blocks 3,4,6,7
Slice 3  Wire packet -> patch-plan ... needs 2 (+ benefits from 1)
Slice 4  Wire packet -> coder ........ needs 2
Slice 5  Requirement expansion ....... needs seed-reaches-planning (landed); feeds 6,7
Slice 6  Completeness reviewer ....... needs 5 (criteria to review against) + 2
Slice 7  Acceptance retirement ....... missing_required half can land early; full form needs 5+6
Slice 8  Reporting + fresh logs ...... independent; report-truthfulness should precede any future report-feeding
```

Two things can land immediately and independently for quick correctness wins:
- **Slice 1** (prompt visibility) — no new code paths.
- **Slice 5's `missing_required` half** (Slice 7 step 1) — an item can't retire
  while required files are absent.

## Reconcile with existing modules (do NOT add a 4th overlapping system)

There are already three overlapping pieces; 9D must absorb, not duplicate:

| Module | Today | Under 9D |
|---|---|---|
| `recovery_manager.build_recovery_plan` | deterministic park + owner-advice strings; always `set_blocked=True`; invoked by `mission_loop` on stall | **demote to "stall reporter"**; strategic routing moves to `recovery_router` |
| `recovery_router.plan_recovery` | deterministic decisions (e.g. lint-quality rejection) | the deterministic table; consumes the **DiagnosisPacket**; LLM is the escalation layer above it |
| `remediation.py` | validation-failure → re-engage coder, bounded | one tactic (`regenerate_patch`) the router can choose; gated by `current_blocker == validation_failed` |
| `completeness_review` (Slice 6) | new | the pre-apply behavioral gate; feeds `revise_proposal` into the router |

The **DiagnosisPacket** is the shared input to `recovery_router`,
`completeness_review`, and the coder/patch-plan slices — one curated truth, many
consumers. (See the recovery-convergence package for the deterministic-first /
LLM-escalation ladder and the recoverable-vs-persistent blocker tier.)

State precedence already fixed: `application_rejected` outranks
`validation_failed` in `mission_state` (so recovery, not remediation, owns
rejection). Keep that invariant when wiring Slice 6's `revise_proposal`.

## Non-negotiable safety invariants (hold across ALL slices)

- **Deterministic floor wins.** The LLM (expander, reviewer, recovery planner)
  proposes; Python validates and applies. A floor hit (path/import/name
  violation, placeholder body, self-authorization, forbidden op) → reject,
  regardless of any model verdict.
- **No self-authorization.** The factory never authorizes/approves its own work
  except via explicit owner-enabled capabilities (default OFF). Autonomous mode
  removes typing, not the floor.
- **Write confinement.** All artifacts (packet, file contracts, evidence, logs)
  stay inside the project workbench / `factory_state/projects/<id>/` via
  `safe_write_*`. Never the engine root.
- **No destructive git.** No commit/push/merge/branch-deletion/reset by the
  factory; commit only when the owner asks.
- **Feed facts, not prose.** Models receive curated ground truth; never raw
  generated reports, never prior-session/stale data.
- **Degrade, never regress.** Every LLM step (expansion, completeness review,
  recovery) has a deterministic fallback; Ollama-down must not produce a fake
  `valid`/`pass` — it falls back to the floor or parks.
- **No fake completion.** An item/project is complete only on deterministic
  acceptance evidence (required files + criteria + tests + validation), never on
  a model's say-so.
- **Config untouched.** Never commit the owner's live `config/projects.yaml` /
  `factory.yaml` / `models.yaml` / `state/`; run the suite under the clean-config
  stash.

## Non-goals (from the direction doc)

Do not: solve quality by swapping models; dump larger raw context; feed raw
reports; relax safety; build UI first; allow destructive git; let the model
declare completion without deterministic acceptance evidence.

## Per-slice gate (every slice must pass before merge)

```bash
ruff format scripts/ tests/ && ruff check scripts/ tests/
/opt/devtools/python/3.11/bin/mypy scripts/
# under clean-config stash:
git stash push -- config/projects.yaml config/factory.yaml config/models.yaml
python3 -m unittest discover -s tests -q
git stash pop
```

Plus, after the generation-affecting slices (1–6), a manual task-board beat to
confirm qualitative improvement (less stub output, fewer placeholder-gate
rejections, richer acceptance criteria).
