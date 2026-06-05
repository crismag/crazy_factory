# 06 — 9E.6 Truthful, progress-oriented reporting

The reports update but log **activity, not outcomes**, and **mislabel** what
happened after rejections. This phase makes the reports tell the truth and
report **progress** (and feeds the same progress data to the human `docs/`
assessment from 9E.4).

## The break (from analysis of `factory_reports/`)

- **ACTIVITY_BLOG.md** — uniform boilerplate per beat ("Dry-run advance / created
  session-X / Last role: reporter / no application edit attempted"). Says nothing
  about the rejection, failure class, recovery decision, or progress. **Untrue:**
  apply was on and an apply was attempted+rejected — not a "dry-run," and an
  edit *was* attempted.
- **DAILY_REPORT.md** — four pointer lines ("Dry-run advance completed. Detailed
  report: …"); no aggregate, same mislabel.
- **CHECKPOINT_REPORT.md** — has real content (eligible=false + reasons) but
  **leaks factory-repo files** (`config/projects.yaml`, a stray log) into
  "Excluded Files," is **last-only** (overwritten), and omits failure class.
- **session-*.md** — richest (Mission Recovery block), yet header says
  `Mode: dry_run` / `Outcome: dry-run complete` while its own Application section
  says `mode: apply` — **self-contradictory** — and the rejection *reasons* +
  recovery decision aren't surfaced in the summary.

Cross-cutting: **activity-not-progress** (same as #37), **half-done truthfulness**
(9D §6 fixed `write_facts` but not Mode/ACTIVITY/DAILY), **history loss + scope
leak** in CHECKPOINT. The run-level story (0/5 items, 0 files over 4 beats,
failure-class trail, `no_progress`) is nowhere — though `run_metrics` can already
produce it.

## Target report schemas

**ACTIVITY_BLOG.md** — per-beat *narrative of what happened*:
```text
## <ts> — beat N (mode: apply)
- Attempted: coder proposed 5 files (focus: src/task_model.py)
- Outcome: application REJECTED — LINT: unused import 'Optional'
- Recovery: regenerate_patch → park (budget exhausted)
- Applied: none · Item completed: none · Blocker: application_rejected
```

**DAILY_REPORT.md** — run/day *aggregate* (from `run_metrics` + #37 signals):
```text
## <date> — task-board
- Acceptance: NOT YET · Checklist 0/5 (0%) · Files applied: 0 · Tests passing: 0
- Beats: 4 · Blockers by class: LINT×4 → no_progress
- Net progress vs seed: 0 of 8 required behaviors
- Next: <focus> · Last beat: session-…md
```

**CHECKPOINT_REPORT.md** — keep eligibility + reasons; add:
- **workbench-scoped** staged/excluded (never factory-repo files),
- a short **attempt history**,
- **"what must be true to checkpoint"** (the gap: apply succeeds + validation
  passes).

**session-*.md** — **truthful mode** (`apply`, "attempted apply — rejected", not
"dry-run complete"); surface the rejection reasons + recovery decision inline.

## Subtasks (9E.6)

| ST | What | Touches | Risk |
|---|---|---|---|
| **RPT1** | **Truthful mode/outcome everywhere** — derive Mode from the effective apply state; replace "Dry-run advance / no application edit" with the real outcome (`applied` / `attempted apply — rejected: <reasons>`). Finishes 9D §6 for ACTIVITY/DAILY/session header. | `report_writer.py` | low |
| **RPT2** | **ACTIVITY = per-beat narrative** — render attempted/outcome/recovery/applied/blocker per beat from `application_result` + recovery decision + `item_completed`. | `report_writer.py`, `factory_advance.py` | low |
| **RPT3** | **DAILY = run aggregate** — render from `run_metrics.collect_metrics` + #37 failure-class trail + acceptance verdict; behaviors-covered vs seed. | `report_writer.py`, `run_metrics.py` | med |
| **RPT4** | **CHECKPOINT fix** — confine staged/excluded scanning to the **workbench**; add attempt history + the "gap to checkpoint." | `checkpoint_commit.py` (+ report) | med |
| **RPT5** | **Shared progress source** — one `progress_snapshot()` (files applied, items done, behaviors covered, blocker, failure-class) consumed by DAILY, `docs/assessment.md` (9E.4), and `crazy-admin metrics`, so all three agree. | `run_metrics.py` | med |
| **RPT6** | **Tests + re-run check** — assert no report claims "dry-run/no edit" after an apply attempt; ACTIVITY shows the rejection + class; DAILY shows 0/5 + blocker; CHECKPOINT excludes only workbench paths. | tests | — |

## Execution slices (gated, reversible)

- **Slice 1 = RPT1 + RPT4** — truthfulness + the CHECKPOINT scope leak. Pure
  correctness, low risk; stops the reports from lying.
- **Slice 2 = RPT2 + RPT3 + RPT5** — narrative ACTIVITY + aggregate DAILY from a
  shared progress snapshot (also feeds `docs/assessment.md`).
- **Slice 3 = RPT6** — tests + measured re-run.

Depends on `run_metrics` (exists), the #37 failure-class/`no_progress` signals
(exist), and pairs with 9E.4 (`assessment.md` shares `progress_snapshot`).

## Invariants (tested)

- **No untrue claims** (9D §6): a report may not say "dry-run"/"no edit" when an
  apply was attempted; mode reflects reality.
- **Workbench-scoped**: checkpoint/report file lists never include factory-repo
  or owner-config paths.
- **Progress over activity**: DAILY/ACTIVITY report outcomes (applied/done/
  blocked/class), not just "an advance ran."
- **History-safe**: ACTIVITY/DAILY append; CHECKPOINT keeps recent attempts.
- **Single source of truth**: DAILY, `assessment.md`, and `metrics` all read
  `progress_snapshot()` — they cannot disagree.

## Definition of done

- Reading `ACTIVITY_BLOG`/`DAILY_REPORT`/`CHECKPOINT_REPORT` after a run tells a
  human (and the AI) **what was attempted, what was rejected and why, what
  advanced, and how far from the seed** — truthfully — without opening the raw
  per-task artifacts. No report mislabels an apply attempt as a dry run.
