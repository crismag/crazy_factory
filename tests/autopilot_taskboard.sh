#!/usr/bin/env bash
#
# Crazy Factory - truthful zero-to-green autopilot for the task-board sample.
#
# This script is intentionally strict. It exits 0 only when the generated
# project is green by compile, pytest, ruff, and seed-level acceptance checks.

set -euo pipefail

PROJECT_ID="task-board"
REPO="/mnt/ai/workspaces/crazy_factory"
APPS_BASE="/mnt/ai/workspaces/crazy_apps"
APP="${APPS_BASE}/${PROJECT_ID}"
SEED="${APPS_BASE}/sample_contexts/task_board.md"
ADMIN="${REPO}/bin/crazy-admin"
MAX_PLAN_ATTEMPTS=5
MAX_PROPOSAL_ATTEMPTS=5
MAX_REMEDIATION_ATTEMPTS=6

cd "$REPO"

step() {
  printf '\n[STEP] %s\n' "$1"
}

fail() {
  printf '\n[ERROR] %s\n' "$1" >&2
  latest_reports
  exit 1
}

latest_reports() {
  if [ -d "$APP/factory_reports" ]; then
    local report
    report="$(ls -t "$APP"/factory_reports/session-*.md 2>/dev/null | head -n 1 || true)"
    [ -n "$report" ] && printf '[REPORT] latest session: %s\n' "$report" >&2
  fi
  [ -f "$APP/factory_tasks/VALIDATION_REPORT.md" ] \
    && printf '[REPORT] validation: %s\n' "$APP/factory_tasks/VALIDATION_REPORT.md" >&2
}

run_admin() {
  "$ADMIN" "$@"
}

require_ollama() {
  curl -fsS -m 4 http://localhost:11434/api/tags >/dev/null \
    || fail "Ollama is not reachable at http://localhost:11434."
  printf '[OK] ollama: up\n'
}

verify_context_loaded() {
  run_admin status "$PROJECT_ID" | tee "$APP/factory_reports/autopilot-status-context.txt"
  grep -Eq 'Context:[[:space:]]+[1-9][0-9]* supported file\(s\), [1-9][0-9]* import\(s\)' \
    "$APP/factory_reports/autopilot-status-context.txt" \
    || fail "Context import did not produce a supported catalog entry."
  [ -s "$APP/context/catalog.yaml" ] || fail "context/catalog.yaml is empty."
  grep -q 'f0001:' "$APP/context/catalog.yaml" \
    || fail "context/catalog.yaml contains no cataloged files."
}

advance_until_authorizable() {
  local attempt
  for attempt in $(seq 1 "$MAX_PLAN_ATTEMPTS"); do
    step "planning attempt ${attempt}/${MAX_PLAN_ATTEMPTS}"
    run_admin advance "$PROJECT_ID"
    if run_admin authorize-task "$PROJECT_ID"; then
      printf '[OK] contract authorized\n'
      return 0
    fi
  done
  fail "Could not produce an authorizable contract."
}

advance_until_proposal_approved() {
  local attempt
  for attempt in $(seq 1 "$MAX_PROPOSAL_ATTEMPTS"); do
    step "proposal attempt ${attempt}/${MAX_PROPOSAL_ATTEMPTS}"
    run_admin advance "$PROJECT_ID"
    if run_admin approve-proposal "$PROJECT_ID"; then
      printf '[OK] proposal approved\n'
      return 0
    fi
  done
  fail "Could not produce an approvable proposal."
}

hard_validation() {
  (
    cd "$APP"
    python3 -m compileall -q src tests
    python3 -m pytest tests
    ruff check src tests
    python3 - <<'PY'
from __future__ import annotations

import importlib
import json
from pathlib import Path

required = [
    "README.md",
    "src/task_model.py",
    "src/storage.py",
    "src/task_board.py",
    "tests/test_task_model.py",
    "tests/test_storage.py",
]
missing = [path for path in required if not Path(path).is_file()]
if missing:
    raise SystemExit(f"missing required file(s): {missing}")

storage = importlib.import_module("src.storage")

data_path = Path("data/tasks.json")
if data_path.exists():
    data_path.unlink()
if storage.load_data() != []:
    raise SystemExit("missing tasks JSON must load as an empty list")

payload = [{"id": 1, "title": "Write tests", "done": False}]
storage.save_data(payload)
if not data_path.is_file():
    raise SystemExit("save_data did not create data/tasks.json")
if storage.load_data() != payload:
    raise SystemExit("save/load round trip failed")

data_path.write_text("{not-json", encoding="utf-8")
try:
    corrupt_result = storage.load_data()
except Exception as exc:  # noqa: BLE001 - acceptance reports all failures
    raise SystemExit(f"corrupt JSON was not handled safely: {exc}") from exc
if corrupt_result != []:
    raise SystemExit("corrupt JSON should return an empty list")

model = importlib.import_module("src.task_model")
task = model.Task(1, "Seed task", False)
if getattr(task, "id", None) != 1:
    raise SystemExit("Task must expose id")
if getattr(task, "title", None) != "Seed task":
    raise SystemExit("Task must expose title")
if getattr(task, "done", None) is not False:
    raise SystemExit("Task must expose done status")

ui = importlib.import_module("src.task_board")
if not any(hasattr(ui, name) for name in ("TaskBoard", "TaskBoardApp", "main")):
    raise SystemExit("task_board module lacks a UI entry point")

json.dumps(storage.load_data())
PY
  )
}

advance_until_green() {
  local attempt
  for attempt in $(seq 1 "$MAX_REMEDIATION_ATTEMPTS"); do
    step "apply/validate/remediate attempt ${attempt}/${MAX_REMEDIATION_ATTEMPTS}"
    run_admin advance "$PROJECT_ID"
    if hard_validation; then
      printf '\n[SUCCESS] task-board is green.\n'
      latest_reports
      return 0
    fi
    printf '[WARN] validation still red; continuing while remediation budget remains.\n'
  done
  fail "Validation did not pass before remediation budget was exhausted."
}

step "preflight"
require_ollama
[ -f "$SEED" ] || fail "Missing task-board seed: $SEED"

step "clean project scaffold"
run_admin startproject "$PROJECT_ID" --apps-base "$APPS_BASE" --force --clean-runtime
[ -d "$APP" ] || fail "Project workbench was not created: $APP"

step "import owner seed"
run_admin add-context "$PROJECT_ID" "$SEED"
verify_context_loaded

step "plan and authorize"
advance_until_authorizable

step "generate and approve proposal"
advance_until_proposal_approved

step "enable owner-approved write, validation, and remediation controls"
run_admin enable-apply "$PROJECT_ID"
run_admin enable-validation "$PROJECT_ID"
run_admin enable-remediation "$PROJECT_ID"

step "drive to green"
advance_until_green
