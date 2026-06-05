#!/usr/bin/env bash
#
# Crazy Factory — hands-off "from zero to green" autopilot for tic-tac-toe.
# FULLY RUNNABLE, MAX-VERBOSITY / DEBUG variant.
#
# WHAT THIS IS
#   A thin OWNER-GATE driver you can run end-to-end: `bash tests/autopilot_tic_tac_toe.sh`.
#   Crazy Factory's own local Ollama models do ALL the thinking and coding (no
#   Claude, no external coding agent). This script only plays the owner — it
#   issues the authorize / approve / enable commands the engine requires, so a
#   tiny app self-drives from an empty folder to a green (tests-passing) build
#   without you hand-typing each gate or re-running each line.
#
#   The factory NEVER authorizes its own work. Autonomous mode is intentionally
#   left OFF here: the script (the owner) issues every gate, beat by beat, and
#   the deterministic safety floor still gates everything.
#
# WHAT IT EXERCISES (current flow)
#   - ARCHITECTURE CONTRACT (architecture.json): the frozen tree + forbidden
#     deps. The checklist is derived from required_files (in order); the patch
#     gate + whole-project coherence gate + SELF_REJECTION detection enforce it.
#   - The plan -> AI contract review (repairs safe gaps) -> coder -> apply ->
#     validate -> (bounded) remediation loop, driven to completion.
#   - MAX OBSERVABILITY: `-v 10` on every advance (phases, stages, decisions,
#     rejection/error CHECKLISTS, debug, trace) + a full timestamped trace to a
#     log file, so on any failure you see WHICH check failed and why.
#
# WHERE IT BUILDS
#   Directly at the owner's target location, OUTSIDE the factory repo:
#       /mnt/ai/workspaces/crazy_apps/tic-tac-toe
#   `--apps-base` sets (and persists) the apps base; the app builds at
#   <apps-base>/tic-tac-toe. Each project stays confined to its own folder;
#   writes outside it are rejected by the engine.
#
# HOW TO READ THE OUTPUT
#   [PHASE]    a run phase (contract / coder / application / validation)
#   [STEP]     a stage outcome
#   [DECISION] a decision point and why (e.g. contract.review -> repair)
#   [REJECT]   something was rejected, with the full reason checklist
#   [ERROR]    a failure, with the checklist of WHICH checks failed and why
#   [WARN]     a pause/park (e.g. remediation_exhausted, self_rejection)
#   Plain      the verbatim end-of-advance summary
#
# VERBOSITY CHEAT-SHEET
#   crazy-admin -q advance <id>          # 0  silent
#   crazy-admin advance <id>             # 4  default (decisions + rejections)
#   crazy-admin --debug advance <id>     # 7  + debug
#   crazy-admin -v 10 advance <id>       # 10 everything (this script)
#   CRAZY_FACTORY_VERBOSITY=10 crazy-admin advance <id>   # same, via env

set -u

# ---------------------------------------------------------------------------
# 0. Settings + a full, timestamped trace of EVERYTHING to a log file
#    (independent of console verbosity) for later analysis.
# ---------------------------------------------------------------------------
cd /mnt/ai/workspaces/crazy_factory

ID=tic-tac-toe
APPS_BASE=/mnt/ai/workspaces/crazy_apps
APP="$APPS_BASE/$ID"
ADMIN="bin/crazy-admin"
CHECKLIST="$APP/factory_tasks/MASTER_CHECKLIST.md"
MAX_BEATS=16   # generous: ~3 beats/item + remediation + local-model variance

# 9D.7: fresh per-run log dir (never append across unrelated runs) + a `latest`
# symlink, so a grep of the trace can never surface a previous run's failures.
RUN_TS="$(date +%Y%m%dT%H%M%S)"
LOG_DIR="logs/autopilot/$ID/$RUN_TS"
mkdir -p "$LOG_DIR"
ln -sfn "$RUN_TS" "logs/autopilot/$ID/latest"
export CRAZY_FACTORY_LOGFILE="$LOG_DIR/debug.log"
SUMMARY="$LOG_DIR/summary.md"
echo "full trace -> $CRAZY_FACTORY_LOGFILE  (latest -> logs/autopilot/$ID/latest)"

# Confirm the local model server is up — generation needs it.
curl -s -m 4 http://localhost:11434/api/tags >/dev/null \
  && echo "ollama: UP" \
  || echo "ollama: DOWN (start it; otherwise no real code is generated)"

# ---------------------------------------------------------------------------
# 1. Create the project at the external target location.
#    --apps-base persists the base to config/factory.yaml so the runtime
#    (advance) honors the same location. --force re-scaffolds cleanly if the id
#    already exists. There is no "activate" step — commands target by <id>.
# ---------------------------------------------------------------------------
$ADMIN startproject "$ID" --apps-base "$APPS_BASE" --force

# ---------------------------------------------------------------------------
# 2. Give the factory the goal — the brief the architect and planner read.
# ---------------------------------------------------------------------------
mkdir -p "$APP/factory_context"
cat > "$APP/factory_context/PROJECT_GOAL.md" <<'GOAL'
# Project Goal

Build a minimal, playable Python Tkinter Tic-Tac-Toe app.

What to build:
- src/tic_tac_toe.py: pure game-logic helpers (apply a move, detect win,
  detect draw, reset) plus a Tkinter 3x3 grid UI.
- tests/test_tic_tac_toe_logic.py: unit tests for win, draw, and invalid moves.

Constraints:
- Standard library + Tkinter only; no third-party dependencies.
- Two human players alternate X and O. No AI opponent, no networking.
- Keep the game logic importable and testable without a display.

How to verify:
- `python -m pytest tests` passes.
- `python src/tic_tac_toe.py` opens a playable window.
GOAL

# ---------------------------------------------------------------------------
# 3. Declare the ARCHITECTURE CONTRACT: the canonical tree + forbidden deps the
#    factory must obey. The checklist is derived from required_files (in this
#    order). This is project data (lives in the workbench), not engine logic.
# ---------------------------------------------------------------------------
cat > "$APP/architecture.json" <<'JSON'
{
  "src_dirs": ["src"],
  "test_dirs": ["tests"],
  "extra_allowed": ["README.md"],
  "forbidden_dirs": ["app", "ui", "gui"],
  "forbidden_names": ["*.db", "*.sqlite"],
  "forbidden_imports": ["numpy", "pygame", "requests", "PyQt5", "PySide6", "kivy"],
  "required_files": ["src/tic_tac_toe.py", "tests/test_tic_tac_toe_logic.py"]
}
JSON

# ---------------------------------------------------------------------------
# 4. OWNER GATES (set once) — let the loop apply approved code, run the tests,
#    and fix its own failing tests (bounded). enable-apply also turns on apply
#    mode, so no config edit is needed. NOTE: we do NOT enable-autonomous — the
#    factory still cannot authorize/approve its own work; the loop below issues
#    each authorize-task / approve-proposal as the owner.
# ---------------------------------------------------------------------------
$ADMIN enable-apply "$ID"
$ADMIN enable-validation "$ID"
$ADMIN enable-remediation "$ID"
$ADMIN enable-completeness "$ID"   # 9D Layer 2: reject incomplete patches pre-apply

# ---------------------------------------------------------------------------
# 5. Self-driving loop at MAX verbosity. Each beat advances exactly one stage:
#      plan+review contract  ->  (owner authorizes)  ->  coder proposes
#      ->  (owner approves)  ->  apply + validate  ->  remediate if red
#    so after each advance we (the owner) try to authorize the freshly-valid
#    contract and approve the freshly-valid proposal. Only the applicable gate
#    succeeds on a given beat; the others no-op. We stop when the build is green
#    AND every checklist item is done — or when the factory parks for review.
# ---------------------------------------------------------------------------
done_reason="reached the beat budget without converging"
for ((beat = 1; beat <= MAX_BEATS; beat++)); do
  echo
  echo "════════════════════ beat $beat/$MAX_BEATS ════════════════════"
  out="$($ADMIN -v 10 advance "$ID" 2>&1)"
  printf '%s\n' "$out"

  # Owner gates — best-effort; the one matching this beat's state succeeds.
  if $ADMIN authorize-task "$ID" >/dev/null 2>&1; then
    echo "  ↳ owner gate: authorized the contract"
  fi
  if $ADMIN approve-proposal "$ID" >/dev/null 2>&1; then
    echo "  ↳ owner gate: approved the proposal"
  fi

  # Parked for owner review? Stop and surface it.
  if grep -qE "remediation_exhausted|self_rejection|needs_owner_review" <<<"$out"; then
    done_reason="factory parked for owner review (see the trace)"
    break
  fi

  # Accepted? The deterministic acceptance checker is the single source of
  # truth: required files present + non-stub + checklist complete + validation
  # passed. Exit 0 means genuinely done.
  if $ADMIN acceptance "$ID" >/dev/null 2>&1; then
    done_reason="accepted: required files, no stubs, checklist complete, green"
    break
  fi
done
echo
echo "════════════════════ loop ended: $done_reason ════════════════════"

# 9D.7: shareable per-run summary (the honest outcome, not "app built").
{
  echo "# Autopilot run summary — $ID @ $RUN_TS"
  echo
  echo "- Outcome: $done_reason"
  echo "- Beats run: up to $MAX_BEATS"
  echo "- Trace: $CRAZY_FACTORY_LOGFILE"
  echo
  echo "## Checklist"
  [ -f "$CHECKLIST" ] && cat "$CHECKLIST" || echo "(no checklist yet)"
  echo
  echo "## Metrics"
  $ADMIN metrics "$ID" 2>/dev/null || echo "(metrics unavailable)"
} > "$SUMMARY"
echo "run summary -> $SUMMARY"

# ---------------------------------------------------------------------------
# 6. Inspect progress, the checklist, and the last decisions/errors.
# ---------------------------------------------------------------------------
$ADMIN status "$ID"
echo "=== MASTER_CHECKLIST ==="
[ -f "$CHECKLIST" ] && cat "$CHECKLIST" || echo "(no checklist yet)"
echo "=== last decisions / rejections / errors in the trace ==="
grep -E '\[DECISION\]|\[REJECT\]|\[ERROR\]|\[WARN\]' "$CRAZY_FACTORY_LOGFILE" | tail -30

# ---------------------------------------------------------------------------
# 7. Acceptance gate — the honest verdict. "Built" requires real evidence, not
#    a partial run. This sets the script's exit code.
# ---------------------------------------------------------------------------
echo "=== acceptance ==="
if $ADMIN acceptance "$ID"; then
  ACCEPT_RC=0
else
  ACCEPT_RC=1
fi

# ---------------------------------------------------------------------------
# 8. Prove it works, run exactly at the owner's target location.
# ---------------------------------------------------------------------------
echo "=== built tree ==="
ls -R "$APP/src" "$APP/tests" 2>/dev/null || echo "(src/tests not created yet)"
cd "$APP"
python3 -m pytest tests || true   # shown for visibility; acceptance is the gate
# Launch the window manually (needs a display):
# python3 src/tic_tac_toe.py

if [ "$ACCEPT_RC" -eq 0 ]; then
  echo "RESULT: app built and ACCEPTED ✓"
else
  echo "RESULT: PARTIAL build — not accepted (see gaps above). Exiting non-zero."
fi
exit "$ACCEPT_RC"
