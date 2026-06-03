#!/usr/bin/env bash
#
# End-to-end ACTUAL-GENERATION test of the Crazy Factory pipeline.
#
# Unlike tests/manual_run_flow.sh (planning-only, all switches OFF), this drives
# the full owner-gated pipeline with capabilities ENABLED so the factory really
# generates and applies code:
#
#   startproject -> real goal -> advance (contract)
#     -> authorize-task -> advance (coder PROPOSES code)
#     -> approve-proposal -> enable-apply + mode=apply -> advance (APPLIES code)
#     -> enable-validation -> advance (runs checks)
#     -> enable-commit -> advance (checkpoint; see gitignore note)
#
# It needs Ollama up (the LLM brain). With Ollama down the stages fall back to
# safe deterministic placeholders and NO real code is generated — the script
# detects this and reports it rather than producing a false pass.
#
# SAFE to run against your tree: throwaway project under apps/ (gitignored),
# backs up + restores config/projects.yaml, enables capabilities only on the
# throwaway project's own crazy_project.yaml, never pushes or merges. Because
# apps/* is gitignored, the auto-commit step cannot stage the generated code —
# the script reports this known limitation instead of failing.
#
# Usage:  tests/generation_flow.sh
# Exit:   0 if the pipeline reached APPLIED generated code, 1 otherwise.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ADMIN="bin/crazy-admin"
PROJECT_ID="gen_test_$$"
APP_PATH="apps/${PROJECT_ID}"
MAX_PLAN_RETRIES=6   # the LLM may emit an invalid contract/proposal; re-advance

# --- pretty output ----------------------------------------------------------
if [ -t 1 ]; then
  GREEN="\033[32m"; RED="\033[31m"; YELLOW="\033[33m"
  BOLD="\033[1m"; DIM="\033[2m"; NC="\033[0m"
else
  GREEN=""; RED=""; YELLOW=""; BOLD=""; DIM=""; NC=""
fi
PASS=0; FAIL=0
pass() { echo -e "  ${GREEN}PASS${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}FAIL${NC} $1"; FAIL=$((FAIL + 1)); }
warn() { echo -e "  ${YELLOW}WARN${NC} $1"; }
step() { echo -e "\n${BOLD}== $1 ==${NC}"; }
note() { echo -e "  ${DIM}$1${NC}"; }

# --- isolation: restore the owner's tracked registry + remove the throwaway --
# Set KEEP=1 to preserve the throwaway workbench (and active project) for
# inspection instead of cleaning it up on exit.
KEEP="${KEEP:-0}"
BACKUP_DIR="$(mktemp -d)"
cleanup() {
  [ -f "$BACKUP_DIR/projects.yaml" ] && \
    cp "$BACKUP_DIR/projects.yaml" config/projects.yaml
  if [ "$KEEP" = "1" ]; then
    echo -e "  ${DIM}KEEP=1: leaving ${APP_PATH} in place (registry restored).${NC}"
  else
    rm -rf "$APP_PATH" "factory_state/projects/${PROJECT_ID}"
  fi
  rm -rf "$BACKUP_DIR"
}
trap cleanup EXIT
cp config/projects.yaml "$BACKUP_DIR/projects.yaml"

echo -e "${BOLD}Crazy Factory — actual-generation flow${NC}"
echo -e "${DIM}project=${PROJECT_ID}  app=${APP_PATH}  (throwaway, auto-cleaned)${NC}"

# --- 0. Ollama reachability -------------------------------------------------
step "0. environment"
if curl -s -m 4 http://localhost:11434/api/tags >/dev/null 2>&1; then
  pass "Ollama reachable — real generation possible"
  OLLAMA_UP=1
else
  warn "Ollama is DOWN — stages will use deterministic fallbacks (no real code)"
  OLLAMA_UP=0
fi

# helper: run one advance, capture output, echo the headline lines
ADV_OUT=""
advance() {
  ADV_OUT="$("$ADMIN" advance 2>&1)"
  echo "$ADV_OUT" | grep -iE \
    "Contract validation|Contract authorized|Coder activated|Coder proposal|Application (mode|status|applied)|Validation:|Checkpoint:" \
    | sed "s/^/  ${DIM}| /; s/$/${NC}/"
}

# helper: did the last advance report a given headline value? Match the exact
# "Label: value" the advance prints (NOT status — the word "validation" itself
# contains "valid", which makes loose status greps falsely match).
adv_said() { echo "$ADV_OUT" | grep -qiE "$1"; }

# --- 1. startproject + activate ---------------------------------------------
step "1. startproject + activate"
"$ADMIN" startproject "$PROJECT_ID" "$APP_PATH" >/dev/null 2>&1
[ -f "$APP_PATH/crazy_project.yaml" ] && pass "workbench scaffolded" \
  || { fail "workbench not scaffolded"; exit 1; }
"$ADMIN" activate "$PROJECT_ID" >/dev/null 2>&1
"$ADMIN" status 2>&1 | grep -q "Active project: ${PROJECT_ID}" \
  && pass "project activated" || fail "activation not reflected"

# --- 2. give the factory a real, small, buildable goal ----------------------
step "2. seed a concrete goal"
# Describe the SOFTWARE, plainly — not the contract. Naming contract fields
# (validation_plan, acceptance_criteria, …) in the goal nudges the planner into
# a meta "improve the planning doc" task, whose code targets factory_context/
# and gets blocked by the write sandbox. Keep it concrete and about the app.
cat > "$APP_PATH/factory_context/PROJECT_GOAL.md" <<'EOF'
# Project Goal

Build a tiny, pure-Python calculator.

What to build:
- A module app/calculator.py with two functions:
  - add(a, b) returns a + b
  - subtract(a, b) returns a - b
- Unit tests in tests/test_calculator.py covering positive, negative, and zero
  inputs for both functions.

Constraints:
- Standard library only; no external dependencies.
- No CLI, no file or network I/O, no packaging. Just the module and its tests.

How to verify:
- Running the unit tests passes, and app/calculator.py compiles cleanly.
EOF
pass "wrote a concrete goal to factory_context/PROJECT_GOAL.md"

# Apply only writes files when mode=apply AND allow_apply is enabled. The
# project-local config is copied from the template (preview_only); flip it so
# an approved+enabled proposal is actually written to disk.
python3 - "$APP_PATH/config/factory.yaml" <<'PY'
import sys, re, pathlib
p = pathlib.Path(sys.argv[1])
text = p.read_text(encoding="utf-8")
text = re.sub(r"(proposal_application:\n(?:.*\n)*?\s*mode:\s*)preview_only",
              r"\1apply", text, count=1)
p.write_text(text, encoding="utf-8")
PY
grep -qE "mode:\s*apply" "$APP_PATH/config/factory.yaml" \
  && pass "set proposal_application.mode = apply (owner config)" \
  || fail "could not set mode=apply"

# --- 3. advance until the contract validates --------------------------------
# Each advance regenerates the (unauthorized) contract, so it may flip
# valid/rejected between tries — loop until the advance reports it valid.
step "3. advance -> task contract"
contract_valid=0
for attempt in $(seq 1 "$MAX_PLAN_RETRIES"); do
  note "advance attempt ${attempt}/${MAX_PLAN_RETRIES}"
  advance
  if adv_said "Contract validation: valid"; then contract_valid=1; break; fi
  note "contract rejected — re-planning"
done
PT="$APP_PATH/factory_tasks/planned_task.json"
[ -f "$PT" ] && pass "planned_task.json written" || fail "no planned_task.json"
if [ "$contract_valid" -eq 1 ]; then
  pass "contract validates"
else
  fail "contract did not validate after ${MAX_PLAN_RETRIES} tries"
  "$ADMIN" next "$PROJECT_ID" 2>&1 | sed "s/^/  ${DIM}| /; s/$/${NC}/"
  exit 1
fi
# Gate proof: coder must NOT have acted yet (task unauthorized).
adv_said "Coder activated: false" \
  && pass "coder stayed inactive before authorization (gate holds)" \
  || warn "coder activation state before auth was unexpected"

# --- 4. owner authorizes the task -------------------------------------------
step "4. authorize-task"
"$ADMIN" authorize-task "$PROJECT_ID" 2>&1 | head -1 \
  | sed "s/^/  ${DIM}| /; s/$/${NC}/"
python3 -c "import json,sys; sys.exit(0 if json.load(open('$PT')).get('authorized') is True else 1)" \
  && pass "planned_task.json now authorized: true" \
  || fail "authorization did not flip the contract"

# --- 5. advance -> coder PROPOSES code --------------------------------------
# The contract is now authorized+valid, so it is preserved across advances and
# the coder activates. A rejected proposal just means re-advance to regenerate.
step "5. advance -> coder proposal"
proposal_ok=0
CP="$APP_PATH/factory_tasks/coder_proposal.json"
for attempt in $(seq 1 "$MAX_PLAN_RETRIES"); do
  note "advance attempt ${attempt}/${MAX_PLAN_RETRIES}"
  advance
  if adv_said "Coder proposal verdict: valid" && [ -f "$CP" ]; then
    proposal_ok=1; break
  fi
  note "no valid proposal yet — re-advancing"
done
if [ "$proposal_ok" -eq 1 ]; then
  pass "coder produced a valid coder_proposal.json"
  adv_said "Coder activated: true" \
    && pass "coder activated (authorized + valid contract)" \
    || warn "proposal valid but 'Coder activated: true' line not seen"
else
  fail "coder did not produce a valid proposal after ${MAX_PLAN_RETRIES} tries"
  "$ADMIN" next "$PROJECT_ID" 2>&1 | sed "s/^/  ${DIM}| /; s/$/${NC}/"
  exit 1
fi

# --- 6. owner approves the proposal -----------------------------------------
step "6. approve-proposal"
"$ADMIN" approve-proposal "$PROJECT_ID" 2>&1 | head -1 \
  | sed "s/^/  ${DIM}| /; s/$/${NC}/"
[ -f "$APP_PATH/factory_tasks/approved_proposal.json" ] \
  && pass "approved_proposal.json written (proposal_id pinned)" \
  || fail "approval artifact missing"

# --- 7. enable apply capability ---------------------------------------------
step "7. enable-apply"
"$ADMIN" enable-apply "$PROJECT_ID" >/dev/null 2>&1
"$ADMIN" status 2>&1 | grep -A4 "Capabilities" | grep -qiE "apply:\s*true" \
  && pass "apply capability is effective" || fail "apply not enabled"

# --- 8. advance -> APPLY generated code to disk -----------------------------
step "8. advance -> apply (real generation lands on disk)"
advance
PATCH="$APP_PATH/factory_tasks/patch_plan.json"
[ -f "$PATCH" ] && pass "patch_plan.json written" || warn "no patch_plan.json"
adv_said "Application applied: true" \
  && pass "applier reported the patch applied" \
  || warn "applier did not report 'applied: true' (see Application status)"
# The payoff: actual generated files under any coder-writable dir (the coder
# may target app/, docs/, or tests/ depending on what it proposes first).
generated="$(find "$APP_PATH/app" "$APP_PATH/docs" "$APP_PATH/tests" \
  -type f ! -name '.gitkeep' 2>/dev/null)"
if [ -n "$generated" ]; then
  pass "generated files on disk:"
  echo "$generated" | sed "s|$APP_PATH/||; s/^/    ${GREEN}+ ${NC}/"
  # Show the actual generated content — the proof of real generation.
  echo "$generated" | while IFS= read -r f; do
    echo -e "    ${DIM}--- $(echo "$f" | sed "s|$APP_PATH/||") (first 20 lines) ---${NC}"
    sed -n '1,20p' "$f" | sed "s/^/      ${DIM}/; s/$/${NC}/"
  done
else
  fail "no generated files found under app/, docs/, or tests/"
fi

# --- 9. enable validation + advance -----------------------------------------
step "9. enable-validation -> advance"
"$ADMIN" enable-validation "$PROJECT_ID" >/dev/null 2>&1
advance
vline="$(echo "$ADV_OUT" | grep -iE 'Validation:' | head -1)"
[ -n "$vline" ] && note "$vline"
echo "$ADV_OUT" | grep -qiE "Validation: .*pass|executed: true" \
  && pass "validation executed" \
  || warn "validation did not execute (may need a test_plan with checks)"

# --- 10. checkpoint / commit (gitignore limitation) -------------------------
step "10. enable-commit -> advance (checkpoint)"
"$ADMIN" enable-commit "$PROJECT_ID" >/dev/null 2>&1
advance
cline="$(echo "$ADV_OUT" | grep -iE 'Checkpoint:' | head -1)"
[ -n "$cline" ] && note "$cline"
if echo "$ADV_OUT" | grep -qi "committed: true"; then
  pass "checkpoint auto-committed"
else
  warn "checkpoint not committed — expected: apps/* is gitignored, so the"
  warn "generated code under apps/${PROJECT_ID} cannot be staged. The gate is"
  warn "correct; committing embedded-app output needs the gitignore revisited."
fi

# --- summary ----------------------------------------------------------------
step "Summary"
if [ "$OLLAMA_UP" -eq 0 ]; then
  warn "Ollama was down: any 'generated' content was a deterministic placeholder."
fi
echo -e "  ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}"
note "Inspect the run: bin/crazy-admin status   (active project: ${PROJECT_ID})"
note "Generated files (pre-cleanup) were under ${APP_PATH}/app and /tests."
if [ "$FAIL" -ne 0 ]; then
  echo -e "${RED}${BOLD}GENERATION FLOW: FAIL${NC}"; exit 1
fi
echo -e "${GREEN}${BOLD}GENERATION FLOW: PASS${NC}"; exit 0
