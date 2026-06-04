#!/usr/bin/env bash
#
# Crazy Factory — hands-off "from zero to green" autopilot for tic-tac-toe.
#
# WHAT THIS IS
#   A thin OWNER-GATE driver. Crazy Factory's own local Ollama models do all the
#   thinking and coding (no Claude, no external coding agent). This script only
#   plays the owner — it issues the authorize / approve / enable commands the
#   engine requires, so you can watch one tiny app self-drive from an empty
#   folder to a green (tests-passing) build without hand-typing each gate.
#
# WHAT IS DIFFERENT NOW (no hacks)
#   Earlier versions had to hack around engine gaps. None of that is needed:
#     - NO `sed` of the project config — `enable-apply` flips apply mode itself.
#     - NO hand-seeded planned_task.json — the factory plans the task; the
#       AI contract reviewer repairs safe gaps so the plan lands valid.
#     - NO `activate` — there is no global "active project". Every command
#       targets the project by id (here, `tic-tac-toe`); you could equally use
#       `--path <dir>` or just run from inside the workbench.
#     - If the first build fails its tests, the owner-enabled REMEDIATION loop
#       re-engages the coder to fix it, bounded by a retry budget.
#
# WHERE IT BUILDS
#   Directly at the owner's target location, OUTSIDE the factory repo:
#       /mnt/ai/workspaces/crazy_apps/tic-tac-toe
#   `--apps-base` sets (and persists) the apps base; the app builds at
#   <apps-base>/tic-tac-toe. Each project stays confined to its own folder;
#   writes outside it are rejected by the engine.
#
# HOW TO USE
#   Run the blocks top to bottom. Commands are plain and explicit (no shell
#   variables). The local model is non-deterministic, so a few blocks say
#   "re-run until ..." — just run that one line again if the status isn't there
#   yet. Each block is safe to run on its own.

# ---------------------------------------------------------------------------
# 0. Go to the factory repo (the engine lives here; the app builds elsewhere).
# ---------------------------------------------------------------------------
cd /mnt/ai/workspaces/crazy_factory

# Confirm the local model server is up — generation needs it.
curl -s -m 4 http://localhost:11434/api/tags >/dev/null && echo "ollama: UP" || echo "ollama: DOWN (start it; otherwise no real code is generated)"

# ---------------------------------------------------------------------------
# 1. Create the project at the external target location.
#    --apps-base persists the base to config/factory.yaml so the runtime
#    (advance) honors the same location. The app path becomes
#    /mnt/ai/workspaces/crazy_apps/tic-tac-toe. --force re-scaffolds cleanly if
#    the id already exists. There is no "activate" step.
# ---------------------------------------------------------------------------
bin/crazy-admin startproject tic-tac-toe --apps-base /mnt/ai/workspaces/crazy_apps --force

# ---------------------------------------------------------------------------
# 2. Give the factory the goal. This is the project brief the architect and
#    planner read (the only project context they treat as the task to build).
# ---------------------------------------------------------------------------
cat > /mnt/ai/workspaces/crazy_apps/tic-tac-toe/factory_context/PROJECT_GOAL.md <<'GOAL'
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
# 3. Advance: the factory PLANS the next task (architect -> planner -> contract
#    -> AI contract review). Re-run this one line until the contract decision is
#    "valid" or "repair" (both mean the plan is authorizable). If it shows
#    "needs_owner_review", read factory_tasks/CONTRACT_REVIEW.md and advance
#    again. The factory never authorizes its own work.
# ---------------------------------------------------------------------------
bin/crazy-admin advance tic-tac-toe

# Optional: inspect what it decided to build first.
bin/crazy-admin status tic-tac-toe

# ---------------------------------------------------------------------------
# 4. OWNER GATE 1 — authorize the task. This only succeeds for a valid contract;
#    the factory cannot authorize its own work.
# ---------------------------------------------------------------------------
bin/crazy-admin authorize-task tic-tac-toe

# ---------------------------------------------------------------------------
# 5. Advance: the Coder model now PROPOSES the implementation (it does not write
#    code yet; it can see the current workbench source to target real files).
#    Re-run this one line until the output shows
#    "Coder proposal verdict: valid" (local-model variance may need 1-3 tries).
# ---------------------------------------------------------------------------
bin/crazy-admin advance tic-tac-toe

# ---------------------------------------------------------------------------
# 6. OWNER GATES 2-4 — approve the proposal, enable applying it, enable
#    validation (running the tests), and enable remediation (let the factory fix
#    its own failing tests, bounded). enable-apply also turns on apply mode, so
#    no config edit is needed.
# ---------------------------------------------------------------------------
bin/crazy-admin approve-proposal tic-tac-toe
bin/crazy-admin enable-apply tic-tac-toe
bin/crazy-admin enable-validation tic-tac-toe
bin/crazy-admin enable-remediation tic-tac-toe

# ---------------------------------------------------------------------------
# 7. Advance: the factory WRITES the generated files to the target location and
#    RUNS the tests. Re-run this one line until validation reaches
#    "Validation: passed". If a write applies broken code, the next advance is a
#    REMEDIATION attempt ("Remediation attempt N/3 ...") that regenerates a fix,
#    auto-approves it (owner-enabled), re-applies, and re-validates. Once green,
#    the applied code is preserved (not regenerated) on later advances.
# ---------------------------------------------------------------------------
bin/crazy-admin advance tic-tac-toe

# ---------------------------------------------------------------------------
# 8. Inspect what the factory built and prove it works, run exactly at the
#    owner's target location.
# ---------------------------------------------------------------------------
bin/crazy-admin status tic-tac-toe
ls -R /mnt/ai/workspaces/crazy_apps/tic-tac-toe/src /mnt/ai/workspaces/crazy_apps/tic-tac-toe/tests
cd /mnt/ai/workspaces/crazy_apps/tic-tac-toe
python3 -m pytest tests
# Launch the window manually (needs a display):
# python3 src/tic_tac_toe.py
