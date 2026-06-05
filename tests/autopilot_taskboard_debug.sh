#!/usr/bin/env bash
#
# Crazy Factory — task-board autopilot, HIGH-VERBOSITY / DEBUG variant.
#
# WHAT THIS IS
#   The debug-friendly sibling of autopilot_taskboard.sh. Same hands-off build,
#   but turned up to maximum observability so you can SEE every decision,
#   rejection, and failure — not just "an error occurred". Use it to evaluate,
#   analyse, and debug the loop.
#
# WHAT YOU GET
#   - Verbosity dial 0..10+ on every command. This script uses `-v 10`
#     (everything: phases, stages, decisions, rejection/error CHECKLISTS,
#     debug, trace). `--debug` (=7) is the lighter option.
#   - A full TIMESTAMPED trace written to a log file (CRAZY_FACTORY_LOGFILE),
#     regardless of console verbosity — the artifact to grep/share for analysis.
#   - The architecture contract (architecture.json) so the patch gate, the
#     whole-project coherence gate, and SELF_REJECTION detection are exercised
#     and their decisions are visible.
#
# HOW TO READ THE OUTPUT
#   [PHASE]      a run phase (contract / coder / application / validation)
#   [STAGE]      a stage outcome
#   [DECISION]   a decision point and why (e.g. contract.review -> repair)
#   [REJECT]     something was rejected, with the full reason checklist
#   [ERROR]      a failure, with the checklist of WHICH checks failed and why
#   [WARN]       a pause/park (e.g. remediation_exhausted, self_rejection)
#   Plain lines  the verbatim end-of-advance summary
#
# VERBOSITY CHEAT-SHEET
#   crazy-admin -q advance <id>            # 0  silent
#   crazy-admin advance <id>               # 4  default (decisions + rejections)
#   crazy-admin --debug advance <id>       # 7  + debug
#   crazy-admin -v 10 advance <id>         # 10 everything
#   CRAZY_FACTORY_VERBOSITY=10 crazy-admin advance <id>   # same, via env
#
# HOW TO USE
#   Run top to bottom. The local model is non-deterministic; a few blocks say
#   "re-run until ..." — just run that one line again. Each block is safe alone.

# ---------------------------------------------------------------------------
# 0. Go to the factory repo. Send a full, timestamped trace of EVERYTHING to a
#    log file (independent of console verbosity) for later analysis.
# ---------------------------------------------------------------------------
cd /mnt/ai/workspaces/crazy_factory
# 9D.7: fresh per-run log dir (not a single append-only file) + `latest` symlink,
# so grepping the trace never surfaces a previous run's stale failures.
RUN_TS="$(date +%Y%m%dT%H%M%S)"
LOG_DIR="logs/autopilot/task-board/$RUN_TS"
mkdir -p "$LOG_DIR"
ln -sfn "$RUN_TS" "logs/autopilot/task-board/latest"
export CRAZY_FACTORY_LOGFILE="$LOG_DIR/debug.log"
echo "full trace -> $CRAZY_FACTORY_LOGFILE  (latest -> logs/autopilot/task-board/latest)"

# Confirm the local model server is up — generation needs it.
curl -s -m 4 http://localhost:11434/api/tags >/dev/null && echo "ollama: UP" || echo "ollama: DOWN (start it; otherwise no real code is generated)"

# ---------------------------------------------------------------------------
# 1. Create the project at the external target location (re-scaffold cleanly).
# ---------------------------------------------------------------------------
bin/crazy-admin startproject task-board --apps-base /mnt/ai/workspaces/crazy_apps --force

# ---------------------------------------------------------------------------
# 2. Ingest the owner-provided project seed as context (drives the build).
# ---------------------------------------------------------------------------
bin/crazy-admin add-context task-board /mnt/ai/workspaces/crazy_apps/sample_contexts/task_board.md

# ---------------------------------------------------------------------------
# 3. Declare the ARCHITECTURE CONTRACT: the canonical tree + forbidden deps the
#    factory must obey. The checklist is derived from required_files (in this
#    order), and the patch + coherence gates enforce the rest. This is project
#    data (lives in the workbench), not engine logic.
# ---------------------------------------------------------------------------
cat > /mnt/ai/workspaces/crazy_apps/task-board/architecture.json <<'JSON'
{
  "src_dirs": ["src"],
  "test_dirs": ["tests"],
  "extra_allowed": ["README.md", "data"],
  "forbidden_dirs": ["app", "migrations", "models"],
  "forbidden_names": ["models.py", "database.py", "*.db", "*.sqlite", "*.sqlite3"],
  "forbidden_imports": ["sqlalchemy", "django", "flask", "fastapi", "sqlite3", "psycopg", "from .models", "import models"],
  "required_files": ["src/task_model.py", "tests/test_task_model.py", "src/storage.py", "tests/test_storage.py", "src/task_board.py"]
}
JSON

# ---------------------------------------------------------------------------
# 4. Enable the owner gates so the loop self-drives: apply approved code, run
#    validation, remediate failures, and pre-authorize the checklist-driven
#    tasks (autonomous). The deterministic safety floor still gates everything.
# ---------------------------------------------------------------------------
bin/crazy-admin enable-apply task-board
bin/crazy-admin enable-validation task-board
bin/crazy-admin enable-remediation task-board
bin/crazy-admin enable-autonomous task-board

# ---------------------------------------------------------------------------
# 5. Advance at MAX verbosity. Re-run this line to drive each beat; watch the
#    [PHASE]/[DECISION]/[REJECT]/[ERROR] stream. On a failure you see exactly
#    WHICH check failed and why (the error checklist), and on a rejection you
#    see every reason. Stops when the checklist is complete or it parks
#    (remediation_exhausted / self_rejection).
# ---------------------------------------------------------------------------
bin/crazy-admin -v 10 advance task-board

# Lighter alternative (verbosity 7) if level 10 is too noisy:
#   bin/crazy-admin --debug advance task-board

# ---------------------------------------------------------------------------
# 6. Drive several beats in a row at max verbosity until it converges or parks.
#    (Re-run this block as needed.)
# ---------------------------------------------------------------------------
bin/crazy-admin -v 10 advance task-board
bin/crazy-admin -v 10 advance task-board
bin/crazy-admin -v 10 advance task-board

# ---------------------------------------------------------------------------
# 7. Inspect progress and the full trace.
# ---------------------------------------------------------------------------
bin/crazy-admin status task-board
cat /mnt/ai/workspaces/crazy_apps/task-board/factory_tasks/MASTER_CHECKLIST.md
echo "=== last decisions / rejections / errors in the trace ==="
grep -E "\[DECISION\]|\[REJECT\]|\[ERROR\]|\[WARN\]" "$CRAZY_FACTORY_LOGFILE" | tail -30

# ---------------------------------------------------------------------------
# 8. Inspect what was built and prove it (run at the target).
# ---------------------------------------------------------------------------
ls -R /mnt/ai/workspaces/crazy_apps/task-board/src /mnt/ai/workspaces/crazy_apps/task-board/tests
cd /mnt/ai/workspaces/crazy_apps/task-board
python3 -m pytest tests
