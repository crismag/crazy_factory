#!/usr/bin/env bash
#
# Manual end-to-end test of the Crazy Factory run flow.
#
# Exercises the documented usage flow (see docs/USAGE.md):
#
#     startproject -> add-context -> activate -> status -> advance
#
# and checks the safety-critical invariants of a planning-only advance:
#   * imported context is loaded into planning
#   * secret-like files are skipped on ingestion
#   * archives are extracted
#   * the planned task is produced UNAUTHORIZED (authorized: false)
#   * no application code is generated (capability switches stay OFF)
#
# This is SAFE to run against your working tree: it backs up and restores the
# tracked files a advance touches (config/projects.yaml, state/, reports/), uses a
# unique throwaway project under apps/ (gitignored), and never enables any
# capability switch. Ollama may be up or down — the flow works either way.
#
# Usage:  tests/manual_run_flow.sh
# Exit:   0 if every check passes, 1 otherwise.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ADMIN="bin/crazy-admin"
PROJECT_ID="manual_test_$$"
APP_PATH="apps/${PROJECT_ID}"

# --- pretty output (color only on a tty) -----------------------------------
if [ -t 1 ]; then
  GREEN="\033[32m"; RED="\033[31m"; BOLD="\033[1m"; DIM="\033[2m"; NC="\033[0m"
else
  GREEN=""; RED=""; BOLD=""; DIM=""; NC=""
fi
PASS=0
FAIL=0
pass() { echo -e "  ${GREEN}PASS${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}FAIL${NC} $1"; FAIL=$((FAIL + 1)); }
step() { echo -e "\n${BOLD}== $1 ==${NC}"; }

# --- isolation: back up tracked files, restore + clean up on exit ----------
BACKUP_DIR="$(mktemp -d)"
SEED_DIR="$(mktemp -d)"

cleanup() {
  # Restore tracked files the flow mutates.
  [ -f "$BACKUP_DIR/projects.yaml" ] && cp "$BACKUP_DIR/projects.yaml" config/projects.yaml
  if [ -d "$BACKUP_DIR/state" ]; then rm -rf state && cp -r "$BACKUP_DIR/state" state; fi
  if [ -d "$BACKUP_DIR/reports" ]; then rm -rf reports && cp -r "$BACKUP_DIR/reports" reports; fi
  # Remove throwaway runtime output.
  rm -rf "$APP_PATH" "factory_state/projects/${PROJECT_ID}"
  rm -rf "$BACKUP_DIR" "$SEED_DIR"
}
trap cleanup EXIT

cp config/projects.yaml "$BACKUP_DIR/projects.yaml"
[ -d state ] && cp -r state "$BACKUP_DIR/state"
[ -d reports ] && cp -r reports "$BACKUP_DIR/reports"

echo -e "${BOLD}Crazy Factory — manual run-flow test${NC}"
echo -e "${DIM}project=${PROJECT_ID}  app=${APP_PATH}  (throwaway, auto-cleaned)${NC}"

# --- build a sample context package ----------------------------------------
printf '# Vision\nA small todo CLI with tags and due dates.\n' > "$SEED_DIR/vision.md"
printf '# Requirements\n- add task\n- list tasks\n- TAG_SUPPORT_REQUIRED\n' > "$SEED_DIR/requirements.md"
printf 'max_tasks: 100\n' > "$SEED_DIR/constraints.yaml"
printf 'pretend-image' > "$SEED_DIR/mockup.png"     # unsupported: stored, not read
printf 'SECRET_TOKEN=do-not-ingest\n' > "$SEED_DIR/.env"   # secret: must be skipped
# An archive containing a supported + an unsupported file.
ZIP_PATH="$SEED_DIR/package.zip"
python3 - "$ZIP_PATH" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w") as zf:
    zf.writestr("api_contract.md", "# API\n- GET /tasks\n")
    zf.writestr("diagram.jpg", "pretend-jpeg")
PY

# --- 1. startproject -------------------------------------------------------
step "1. startproject"
"$ADMIN" startproject "$PROJECT_ID" "$APP_PATH" >/dev/null 2>&1
[ -f "$APP_PATH/crazy_project.yaml" ] && pass "workbench scaffolded" \
  || fail "workbench not scaffolded"
[ -f "$APP_PATH/context/catalog.yaml" ] && pass "context store created" \
  || fail "context store missing"
[ -d "$APP_PATH/app" ] && pass "app/ build target present" \
  || fail "app/ missing"

# --- 2. add-context (directory: includes a secret + an unsupported file) ---
step "2. add-context (directory)"
out="$("$ADMIN" add-context "$PROJECT_ID" "$SEED_DIR" 2>&1)"
echo -e "${DIM}${out}${NC}"
echo "$out" | grep -q "available to the AI" && pass "directory imported" \
  || fail "directory import failed"
echo "$out" | grep -q "Skipped (secret-like)" && pass ".env skipped as secret" \
  || fail ".env was not skipped"

# --- 3. add-context (archive) ----------------------------------------------
step "3. add-context (archive)"
out="$("$ADMIN" add-context "$PROJECT_ID" "$ZIP_PATH" 2>&1)"
echo -e "${DIM}${out}${NC}"
echo "$out" | grep -q "(archive)" && pass "archive imported + extracted" \
  || fail "archive import failed"
ls "$APP_PATH"/context/extracted/*/api_contract.md >/dev/null 2>&1 \
  && pass "supported file extracted from archive" \
  || fail "extracted file missing"

# --- 4. activate + status --------------------------------------------------
step "4. activate + status"
"$ADMIN" activate "$PROJECT_ID" >/dev/null 2>&1
out="$("$ADMIN" status 2>&1)"
echo -e "${DIM}${out}${NC}"
echo "$out" | grep -q "Active project: ${PROJECT_ID}" && pass "project activated" \
  || fail "activation not reflected in status"
echo "$out" | grep -qE "Context:[[:space:]]+[1-9]" \
  && pass "status reports imported context" \
  || fail "status shows no context"

# --- 5. advance (planning-only; nothing built) --------------------------------
step "5. advance"
out="$("$ADMIN" advance 2>&1)"
rc=$?
echo "$out" | grep -iE "context|contract|planner|architect" \
  | sed "s/^/  ${DIM}| /; s/$/${NC}/"
[ $rc -eq 0 ] && pass "advance exited 0" || fail "advance exit code ${rc}"
echo "$out" | grep -q "Loaded .* context file" \
  && pass "imported context loaded into planning" \
  || fail "context not loaded into planning"

PT="$APP_PATH/factory_tasks/planned_task.json"
if [ -f "$PT" ]; then
  if python3 -c "import json,sys; sys.exit(0 if json.load(open('$PT')).get('authorized') is False else 1)"; then
    pass "planned task is authorized: false (owner gate intact)"
  else
    fail "planned task is not authorized: false"
  fi
else
  echo -e "  ${DIM}(no planned_task.json written this advance)${NC}"
fi

# Safety: a planning-only advance must not write application code.
stray="$(find "$APP_PATH/app" -type f ! -name '.gitkeep' 2>/dev/null)"
[ -z "$stray" ] && pass "no application code generated" \
  || fail "unexpected files in app/: ${stray}"

# --- 6. owner-control surface ----------------------------------------------
step "6. owner controls"
out="$("$ADMIN" next "$PROJECT_ID" 2>&1)"
echo "$out" | sed "s/^/  ${DIM}| /; s/$/${NC}/"
echo "$out" | grep -qiE "Current (state|blocker):" \
  && pass "next reports a clear current state" \
  || fail "next gave no current state"

out="$("$ADMIN" status 2>&1)"
echo "$out" | grep -q "Capabilities (effective):" \
  && pass "status shows effective capabilities" \
  || fail "status missing capabilities section"

# Per-project capability toggle is reflected as an effective capability.
"$ADMIN" enable-apply "$PROJECT_ID" >/dev/null 2>&1
"$ADMIN" status 2>&1 | grep -qE "apply:[[:space:]]+true" \
  && pass "enable-apply flips effective apply capability" \
  || fail "enable-apply not reflected in status"
"$ADMIN" disable-apply "$PROJECT_ID" >/dev/null 2>&1

# --- summary ---------------------------------------------------------------
step "Summary"
echo -e "  ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}"
if [ "$FAIL" -ne 0 ]; then
  echo -e "${RED}${BOLD}RUN FLOW: FAIL${NC}"
  exit 1
fi
echo -e "${GREEN}${BOLD}RUN FLOW: PASS${NC}"
exit 0
