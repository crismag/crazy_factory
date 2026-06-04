#!/usr/bin/env bash
#
# Crazy Factory — hands-off "from zero to green" autopilot for a task-board app.
#
# WHAT THIS IS
#   A thin OWNER-GATE driver. Crazy Factory's own local Ollama models do all the
#   thinking and coding (no Claude, no external coding agent). This script only
#   plays the owner — it issues the authorize / approve / enable commands the
#   engine requires, so you can watch one small app self-drive from an empty
#   folder to a green (tests-passing) build without hand-typing each gate.
#
#   It is the sibling of autopilot_tic_tac_toe.sh, and additionally demonstrates
#   CONTEXT INGESTION: the owner-provided project seed
#   (sample_contexts/task_board.md) is imported with `add-context` and folded
#   into the project context the planner/coder read.
#
# WHAT IS DIFFERENT FROM OLD VERSIONS (no hacks)
#     - NO `sed` of the project config — `enable-apply` flips apply mode itself.
#     - NO hand-seeded planned_task.json — the factory plans the task; the AI
#       contract reviewer repairs safe gaps so the plan lands valid.
#     - NO `activate` — there is no global "active project". Every command
#       targets the project by id (here, `task-board`); `--path <dir>` or running
#       from inside the workbench work too.
#     - PLAN BEFORE AUTHORIZE: you advance once to produce a contract, THEN
#       authorize it. The factory never authorizes its own work.
#     - If the first build fails its tests, the owner-enabled REMEDIATION loop
#       re-engages the coder to fix it, bounded by a retry budget.
#
# WHERE IT BUILDS
#   Directly at the owner's target location, OUTSIDE the factory repo:
#       /mnt/ai/workspaces/crazy_apps/task-board
#   Each project stays confined to its own folder; writes outside it are rejected.
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
#    --apps-base persists the base to config/factory.yaml so the runtime honors
#    the same location. The app path becomes
#    /mnt/ai/workspaces/crazy_apps/task-board. --force re-scaffolds cleanly if
#    the id already exists. There is no "activate" step.
# ---------------------------------------------------------------------------
bin/crazy-admin startproject task-board --apps-base /mnt/ai/workspaces/crazy_apps --force

# ---------------------------------------------------------------------------
# 2. INGEST THE PROVIDED PROJECT SEED as project context. The owner already
#    wrote the brief at sample_contexts/task_board.md (purpose, scope, expected
#    tree, functional + testing requirements). `add-context` imports it, screens
#    it for secrets, and folds the supported docs into the context the planner
#    and coder read — so the build is driven by the ingested seed, not a
#    hand-placed goal. (This is the headline thing task-board exercises:
#    the iterative, context-driven build loop.)
# ---------------------------------------------------------------------------
bin/crazy-admin add-context task-board /mnt/ai/workspaces/crazy_apps/sample_contexts/task_board.md

# If a later `advance` reports "no project goal", the seed can also be placed as
# the explicit brief the planner treats as the task to build:
#   cp /mnt/ai/workspaces/crazy_apps/sample_contexts/task_board.md \
#      /mnt/ai/workspaces/crazy_apps/task-board/factory_context/PROJECT_GOAL.md

# ---------------------------------------------------------------------------
# 3. Advance: the factory PLANS the next task (architect -> planner -> contract
#    -> AI contract review). Re-run this one line until the contract decision is
#    "valid" or "repair" (both authorizable). If it shows "needs_owner_review",
#    read factory_tasks/CONTRACT_REVIEW.md and advance again.
# ---------------------------------------------------------------------------
bin/crazy-admin advance task-board

# Optional: inspect what it decided to build first.
bin/crazy-admin status task-board

# ---------------------------------------------------------------------------
# 4. OWNER GATE 1 — authorize the task. Only succeeds for a valid contract.
# ---------------------------------------------------------------------------
bin/crazy-admin authorize-task task-board

# ---------------------------------------------------------------------------
# 5. Advance: the Coder model PROPOSES the implementation (no code written yet;
#    it can see the current workbench source to target real files). Re-run until
#    the output shows "Coder proposal verdict: valid" (1-3 tries is normal).
# ---------------------------------------------------------------------------
bin/crazy-admin advance task-board

# ---------------------------------------------------------------------------
# 6. OWNER GATES 2-4 — approve the proposal, enable applying it (also turns on
#    apply mode), enable validation (running the tests), and enable remediation
#    (let the factory fix its own failing tests, bounded).
# ---------------------------------------------------------------------------
bin/crazy-admin approve-proposal task-board
bin/crazy-admin enable-apply task-board
bin/crazy-admin enable-validation task-board
bin/crazy-admin enable-remediation task-board

# ---------------------------------------------------------------------------
# 7. Advance: the factory WRITES the files and RUNS the tests. Re-run this one
#    line until validation reaches "Validation: passed". If a write applies
#    broken code, the next advance is a REMEDIATION attempt
#    ("Remediation attempt N/3 ...") that regenerates a fix, auto-approves it
#    (owner-enabled), re-applies, and re-validates. Once green, the applied code
#    is preserved (not regenerated) on later advances.
# ---------------------------------------------------------------------------
bin/crazy-admin advance task-board

# ---------------------------------------------------------------------------
# 8. Inspect what the factory built and prove it works, run at the target.
# ---------------------------------------------------------------------------
bin/crazy-admin status task-board
ls -R /mnt/ai/workspaces/crazy_apps/task-board/src /mnt/ai/workspaces/crazy_apps/task-board/tests
cd /mnt/ai/workspaces/crazy_apps/task-board
python3 -m pytest tests
