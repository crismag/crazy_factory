# Phase 4–8 Implementation Review

Status of the review-and-harden pass over the authorized Coder proposal engine
(Phase 4) through continuous operation and recovery (Phase 8). Each phase was
inspected against its contract; only the genuine gaps below were fixed. All
phases were already merged to `main`; this pass adds defense-in-depth and
closes test gaps without weakening any governance boundary.

## Method

One review branch, one commit per phase, gates (`ruff check`,
`ruff format --check`, `mypy`, `pytest`) green after each. No root README
edits, no weakened write boundaries, no new auto-authorization or
auto-push/merge.

## Phase 4 — Authorized Coder Proposal Engine

- **Findings:** the activation gate (`is_contract_actionable`), malformed-JSON
  handling, fallback-never-fake-valid, path whitelist (`app/docs/tests` only),
  forbidden-keyword scan, report verdict, and `last_coder_status` were all
  present and correct. No code gap.
- **Fixes:** closed two boundary test gaps — the root `README.md` and
  `files_to_delete` entries are both rejected when outside the allowed app
  paths.
- **Remaining risk:** secret/keyword substring matching can over-reject benign
  text (safe direction — it never under-rejects).

## Phase 5 — Proposal Application Engine

- **Findings:** preview/apply separation, the approval gate (separate
  `approved_proposal.json` with id match), path/line/file limits, and
  fail-closed parsing were correct. Two real gaps.
- **Fixes:**
  - **Deletes denied by default.** `validate_patch_plan` rejects delete actions
    and `apply_patch_plan` skips them unless
    `proposal_application.allow_delete` is explicitly enabled (default false).
  - **Partial-apply tracking.** `apply_patch_plan` returns
    `(applied_files, error)` instead of raising, so a mid-sequence failure is
    reported as a partial application. There is intentionally no transactional
    rollback; this is documented.
- **Remaining risk:** no rollback on partial apply — surfaced in the report so
  the owner can reconcile. Apply remains off by default.

## Phase 6 — Test Builder and Validation Runner

- **Findings:** strict command allowlist (shell-metachar + forbidden-token
  screen + argv-prefix match), shell-free execution, timeout, fail-closed
  aggregation, and the `allow_run` gate (default off) were correct.
- **Fix:** a failed check now records a bounded, single-lined snippet of the
  command output (stderr preferred) in its detail, so the validation report is
  diagnosable instead of showing only the exit code.
- **Remaining risk:** none material; allowlist is conservative.

## Phase 7 — Checkpoint Commit Engine

- **Findings:** the full gate (contract+proposal+application+validation),
  allowed-path staging, contract-derived message, off-by-default auto-commit,
  and the no-push/merge/reset boundary were correct.
- **Fix:** commit with an explicit pathspec (`git commit -m <msg> -- <paths>`)
  so only engine-staged allowed paths are committed even if the index already
  had other files staged — a pre-staged forbidden/engine file can never ride a
  checkpoint commit.
- **Remaining risk:** none material. A failed commit is reported with reasons.

## Phase 8 — Continuous Operation and Recovery

- **Findings:** stop/pause/blocked/satisfied flags (reconciled with JSON
  booleans), stall detection, recovery + block, satisfaction criteria, and
  persisted failure counters were correct. One real gap.
- **Fix:** a mission lock (`state/mission.lock`, pid + UTC timestamp) prevents
  overlapping cron runs — a fresh lock makes a second run exit `locked`, while
  a lock older than `mission.lock_stale_seconds` (default 3600) is taken over.
  Released in a `finally` block. Lock and runtime `*.flag` files are
  gitignored.
- **Remaining risk:** the lock is advisory (timestamp-based), adequate for the
  single-host cron use case; it is not a cross-host distributed lock.

## Tests Added

Boundary cases (root README, delete-out-of-bounds), delete-denied-by-default
and delete-only-when-enabled, validator delete rejection, captured failure
output, pre-staged-forbidden-file exclusion, and lock acquire/block/takeover/
release. Suite: 168 tests, ruff + mypy clean across 29 source files.

## Remaining Risks (consolidated)

- No transactional rollback on partial apply (reported, apply off by default).
- Substring keyword matching can over-reject (safe direction).
- Mission lock is single-host advisory, not distributed.
- Defaults remain SAFE/OFF: `dry_run`, no app writes, `allow_apply` off,
  `allow_delete` off, `allow_run` off, `git.allow_auto_commit` off.

## Recommended Next Action

The Phase 3–8 pipeline is implemented and hardened. The next step is owner-
driven exercise of the live pipeline one capability at a time (authorize a
contract → review proposal → approve application + enable apply → enable
validation run → enable auto-commit), each a deliberate switch the owner
controls. No further autonomous capability should be added until a full
end-to-end run has been reviewed.
