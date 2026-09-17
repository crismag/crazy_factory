#!/usr/bin/env python3
"""Factory-owned integration of one isolated task workspace (Slice 4B).

The worker does not merge, push, or choose what becomes canonical.
Crazy Factory inspects the workspace, authorizes paths, checks
canonical overlap, applies an approved subset, validates, and rolls
back when validation fails.

Live AgentExecutor / Codex is not switched here. Product evidence is
not collected here. Claims are not verified by a successful apply.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from execution_assignment import ALLOWED_TOPS, BLOCKED_PARTS, path_in_scope
from product_intent import intent_revision
from repo_tools import BLOCKED_NAMES, BLOCKED_SUFFIXES
from task_workspace import (
    KIND_WORKTREE,
    STATUS_STALE,
    WorkspaceError,
    WorkspaceRecord,
    collect_workspace_result,
    load_workspace,
    persist_record,
    refresh_workspace_staleness,
    workbench_is_git_repo,
)
from validation_runner import run_validation

INTEGRATION_FILE = "integration.json"
BACKUP_DIR = "apply_backup"

APPLY_NOT_APPLIED = "not_applied"
APPLY_APPLIED = "applied"
APPLY_ROLLED_BACK = "rolled_back"
APPLY_REFUSED = "refused"

CONFLICT_NONE = "none"
CONFLICT_OVERLAP = "overlapping"
CONFLICT_INELIGIBLE = "ineligible"
CONFLICT_STALE = "stale"

SCOPE_STRONG = "strong"
SCOPE_WEAK = "weak"
SCOPE_POLICY = "factory_policy"

OP_ADD = "add"
OP_MODIFY = "modify"
OP_DELETE = "delete"

_UNSAFE_REASONS = frozenset(
    {
        "blocked_path",
        "out_of_root",
        "traversal",
        "symlink_escape",
        "secret",
        "engine_path",
    }
)
_RUNTIME_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".pyc"}
_WALK_SKIP = frozenset(
    {
        "__pycache__",
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        BACKUP_DIR,
    }
)
_GIT_TIMEOUT = 15
_VALIDATE_TIMEOUT = 30


class IntegrationError(RuntimeError):
    """Refused or failed Factory-owned integration."""


@dataclass
class ApplyPlan:
    """Deterministic apply plan. Every field has a consumer."""

    task_id: str
    workspace_id: str
    intent_revision: int
    source_base_revision: str
    changed_files: list[str]
    added_files: list[str]
    deleted_files: list[str]
    allowed_changes: list[str]
    rejected_changes: list[str]
    conflict_status: str
    apply_status: str
    validation_status: str
    scope_confidence: str = SCOPE_POLICY
    reasons: list[str] = field(default_factory=list)
    rejected_reasons: dict[str, str] = field(default_factory=dict)
    operations: dict[str, str] = field(default_factory=dict)


def _as_path(value: object, root: Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (root / path)


def _app_dir(project: dict[str, Any], root: Path) -> Path:
    return _as_path(project["app_path"], root).resolve()


def _workspace_home(record: WorkspaceRecord) -> Path:
    return Path(record.workspace_path).resolve().parent


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
        check=False,
    )


def _head_sha(app: Path) -> str:
    if not workbench_is_git_repo(app):
        return ""
    result = _git(["rev-parse", "HEAD"], app)
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _norm_rel(rel: str) -> str | None:
    text = str(rel or "").replace("\\", "/").strip()
    if not text or text.startswith(("/", "~")):
        return None
    path = Path(text)
    if path.is_absolute():
        return None
    parts = [part for part in path.parts if part not in (".", "")]
    if not parts or ".." in parts:
        return None
    return Path(*parts).as_posix()


def _scope_paths(assignment: Any | None, task: Any | None) -> tuple[str, ...]:
    raw: list[str] = []
    if assignment is not None:
        raw.extend(str(x) for x in (getattr(assignment, "repo_scope", ()) or ()))
    if task is not None:
        raw.extend(
            str(x) for x in (getattr(task, "affected_scope", ()) or ())
        )
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = item.replace("\\", "/").lstrip("./")
        text = text.removeprefix("file:").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return tuple(cleaned)


def _scope_confidence(scope: tuple[str, ...]) -> str:
    if not scope:
        return SCOPE_POLICY
    tops = set(ALLOWED_TOPS)
    for item in scope:
        parts = Path(item).parts
        if len(parts) >= 2:
            return SCOPE_STRONG
        if item not in tops:
            return SCOPE_STRONG
    return SCOPE_WEAK


def _is_secret(rel: str) -> bool:
    for part in Path(rel).parts:
        lowered = part.lower()
        if lowered in BLOCKED_NAMES or lowered.startswith(".env"):
            return True
        if any(lowered.endswith(suffix) for suffix in BLOCKED_SUFFIXES):
            return True
    return Path(rel).suffix.lower() in BLOCKED_SUFFIXES


def _is_runtime_artifact(rel: str) -> bool:
    path = Path(rel)
    if any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
        return True
    suffix = path.suffix.lower()
    if suffix in _RUNTIME_SUFFIXES:
        return True
    return bool(
        path.parts and path.parts[0] == "data" and suffix in {".json", ".jsonl"}
    )


def _unsafe_reason(rel: str) -> str | None:
    parts = Path(rel).parts
    if not parts:
        return "traversal"
    if any(part in BLOCKED_PARTS for part in parts):
        if ".git" in parts:
            return "engine_path"
        if any(part in {"scripts", "factory", "config", "bin"} for part in parts):
            return "engine_path"
        return "blocked_path"
    if parts[0] not in ALLOWED_TOPS:
        return "out_of_root"
    if _is_secret(rel):
        return "secret"
    return None


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        return False


def _confined(base: Path, rel: str) -> Path | None:
    """Join ``rel`` under ``base`` without following a symlink escape."""
    base = base.resolve()
    current = base
    for part in Path(rel).parts:
        nxt = current / part
        if _is_link(nxt):
            return None
        current = nxt
    resolved = current.resolve()
    if resolved != base and base not in resolved.parents:
        return None
    try:
        resolved.relative_to(base)
    except ValueError:
        return None
    return current


def _digest(path: Path) -> str | None:
    if _is_link(path) or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _walk_tree(tree: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    if not tree.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(tree, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in _WALK_SKIP]
        base = Path(dirpath)
        for name in filenames:
            path = base / name
            try:
                rel = path.relative_to(tree).as_posix()
            except ValueError:
                continue
            found.append((rel, path))
    return found


def _augment_delta(
    tree: Path,
    baseline: dict[str, str],
    changed: list[str],
    added: list[str],
    deleted: list[str],
    canonical: Path,
) -> tuple[list[str], list[str], list[str]]:
    """Include files collect_workspace_result skipped (secrets, extra tops).

    Files that isolation never hashed (``factory_tasks/``, etc.) are not
    worker changes when they still match the canonical tree.
    """
    seen = set(changed)
    current: dict[str, Path] = {}
    for rel, path in _walk_tree(tree):
        if any(part in _WALK_SKIP for part in Path(rel).parts):
            continue
        current[rel] = path
        if rel in baseline or rel in seen:
            continue
        tree_digest = _digest(path)
        dest = canonical / rel
        canon_digest = _digest(dest) if dest.exists() else None
        if (
            tree_digest is not None
            and canon_digest is not None
            and tree_digest == canon_digest
        ):
            continue
        added.append(rel)
        changed.append(rel)
        seen.add(rel)
    for rel in baseline:
        if rel not in current and rel not in seen:
            deleted.append(rel)
            changed.append(rel)
            seen.add(rel)
    return sorted(set(changed)), sorted(set(added)), sorted(set(deleted))


def _operation(rel: str, added: set[str], deleted: set[str]) -> str:
    if rel in deleted:
        return OP_DELETE
    if rel in added:
        return OP_ADD
    return OP_MODIFY


def _overlap_reason(
    rel: str,
    op: str,
    *,
    baseline: dict[str, str],
    canonical: Path,
    tree: Path,
) -> str | None:
    dest = _confined(canonical, rel)
    src = _confined(tree, rel)
    current = _digest(dest) if dest is not None else None
    if dest is not None and _is_link(dest):
        return "canonical path is a symlink"
    if op == OP_ADD:
        if current is None:
            return None
        workspace = _digest(src) if src is not None else None
        if workspace is not None and current == workspace:
            return None
        return "canonical already has a different file at this path"
    base = baseline.get(rel)
    if op == OP_DELETE:
        if current is None:
            return None
        if base is not None and current != base:
            return "canonical file changed since workspace creation"
        return None
    if current is None:
        return "canonical file deleted since workspace creation"
    if base is not None and current != base:
        workspace = _digest(src) if src is not None else None
        if workspace is not None and current == workspace:
            return None
        return "canonical file changed since workspace creation"
    return None


def _classify_path(
    rel: str,
    *,
    tree: Path,
    canonical: Path,
    op: str,
    scope: tuple[str, ...],
    confidence: str,
) -> str | None:
    """Return a rejection reason, or None when the path may be applied."""
    unsafe = _unsafe_reason(rel)
    if unsafe:
        return unsafe
    dest = _confined(canonical, rel)
    if dest is None:
        return "symlink_escape"
    try:
        dest.resolve().relative_to(canonical.resolve())
    except ValueError:
        return "out_of_root"
    if op != OP_DELETE:
        src = _confined(tree, rel)
        if src is None:
            return "symlink_escape"
        if _is_link(tree / rel):
            return "symlink_escape"
    if _is_runtime_artifact(rel):
        if confidence == SCOPE_STRONG and path_in_scope(rel, scope):
            return None
        return "runtime_artifact"
    if confidence == SCOPE_STRONG and scope and not path_in_scope(rel, scope):
        return "out_of_scope"
    return None


def _has_tests(app: Path) -> bool:
    tests = app / "tests"
    if not tests.is_dir():
        return False
    return any(tests.rglob("test_*.py")) or any(tests.rglob("*_test.py"))


def _validate_canonical(app: Path) -> str:
    commands: list[str] = []
    if (app / "src").is_dir():
        commands.append("python3 -m compileall -q src")
    if _has_tests(app):
        commands.append("python3 -m pytest tests -q")
    if not commands:
        return "skipped"
    result = run_validation(
        test_plan_id="task-integration",
        required_checks=commands,
        root=app,
        allow_run=True,
        timeout_seconds=_VALIDATE_TIMEOUT,
    )
    return result.status


def persist_plan(
    record: WorkspaceRecord, plan: ApplyPlan
) -> Path:
    home = _workspace_home(record)
    home.mkdir(parents=True, exist_ok=True)
    path = home / INTEGRATION_FILE
    path.write_text(json.dumps(asdict(plan), indent=2) + "\n", encoding="utf-8")
    return path


def load_plan(record: WorkspaceRecord) -> ApplyPlan | None:
    path = _workspace_home(record) / INTEGRATION_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    reasons = raw.get("rejected_reasons") or {}
    if not isinstance(reasons, dict):
        reasons = {}
    ops = raw.get("operations") or {}
    if not isinstance(ops, dict):
        ops = {}
    return ApplyPlan(
        task_id=str(raw.get("task_id") or ""),
        workspace_id=str(raw.get("workspace_id") or ""),
        intent_revision=int(raw.get("intent_revision") or 0),
        source_base_revision=str(raw.get("source_base_revision") or ""),
        changed_files=[str(x) for x in (raw.get("changed_files") or [])],
        added_files=[str(x) for x in (raw.get("added_files") or [])],
        deleted_files=[str(x) for x in (raw.get("deleted_files") or [])],
        allowed_changes=[str(x) for x in (raw.get("allowed_changes") or [])],
        rejected_changes=[str(x) for x in (raw.get("rejected_changes") or [])],
        conflict_status=str(raw.get("conflict_status") or CONFLICT_NONE),
        apply_status=str(raw.get("apply_status") or APPLY_NOT_APPLIED),
        validation_status=str(raw.get("validation_status") or "not_run"),
        scope_confidence=str(raw.get("scope_confidence") or SCOPE_POLICY),
        reasons=[str(x) for x in (raw.get("reasons") or [])],
        rejected_reasons={str(k): str(v) for k, v in reasons.items()},
        operations={str(k): str(v) for k, v in ops.items()},
    )


def plan_integration(
    project: dict[str, Any],
    root: Path,
    workspace_id: str,
    *,
    assignment: Any | None = None,
    task: Any | None = None,
) -> ApplyPlan:
    """Inspect workspace state and Factory policy. Does not write the app."""
    record = load_workspace(project, root, workspace_id)
    if record is None:
        raise IntegrationError(f"workspace not found: {workspace_id}")
    try:
        record = refresh_workspace_staleness(project, root, record)
        record = collect_workspace_result(project, root, record)
    except (WorkspaceError, ValueError, OSError) as exc:
        raise IntegrationError(f"cannot inspect workspace: {exc}") from exc
    current_rev = intent_revision(project, root)
    tree = Path(record.workspace_path)
    canonical = _app_dir(project, root)
    reasons: list[str] = []
    conflict = CONFLICT_NONE
    if int(record.intent_revision) != int(current_rev):
        conflict = CONFLICT_STALE
        reasons.append(
            f"stale intent revision {record.intent_revision} != {current_rev}"
        )
    if record.status == STATUS_STALE:
        conflict = CONFLICT_STALE
        reasons.append("workspace is marked stale")
    if assignment is not None and bool(getattr(assignment, "stale", False)):
        conflict = CONFLICT_STALE
        reasons.append("assignment is stale")
    if tree.resolve() == canonical:
        conflict = CONFLICT_INELIGIBLE
        reasons.append("workspace tree is the canonical workbench")
    changed, added, deleted = _augment_delta(
        tree,
        record.baseline_hashes,
        list(record.changed_files),
        list(record.added_files),
        list(record.deleted_files),
        canonical,
    )
    added_set = set(added)
    deleted_set = set(deleted)
    scope = _scope_paths(assignment, task)
    confidence = _scope_confidence(scope)
    if confidence == SCOPE_POLICY:
        reasons.append(
            "repo_scope empty or unused; ALLOWED_TOPS is the apply boundary"
        )
    elif confidence == SCOPE_WEAK:
        reasons.append(
            "repo_scope is only a top-level allowlist; falling back to "
            "Factory path policy"
        )
        confidence = SCOPE_POLICY
    allowed: list[str] = []
    rejected: list[str] = []
    rejected_reasons: dict[str, str] = {}
    operations: dict[str, str] = {}
    unsafe = False
    overlapping = False
    for rel_raw in changed:
        rel = _norm_rel(rel_raw)
        if rel is None:
            rejected.append(str(rel_raw))
            rejected_reasons[str(rel_raw)] = "traversal"
            unsafe = True
            continue
        op = _operation(rel, added_set, deleted_set)
        why = _classify_path(
            rel,
            tree=tree,
            canonical=canonical,
            op=op,
            scope=scope,
            confidence=confidence,
        )
        if why:
            rejected.append(rel)
            rejected_reasons[rel] = why
            if why in _UNSAFE_REASONS:
                unsafe = True
            continue
        overlap = _overlap_reason(
            rel,
            op,
            baseline=record.baseline_hashes,
            canonical=canonical,
            tree=tree,
        )
        if overlap:
            rejected.append(rel)
            rejected_reasons[rel] = overlap
            overlapping = True
            continue
        allowed.append(rel)
        operations[rel] = op
    if record.isolation_kind == KIND_WORKTREE:
        head = _head_sha(canonical)
        if record.base_revision and head and head != record.base_revision:
            reasons.append(
                "canonical HEAD moved since workspace creation; "
                "overlap is decided per file"
            )
    if conflict == CONFLICT_NONE and overlapping:
        conflict = CONFLICT_OVERLAP
        reasons.append("overlapping canonical change blocks integration")
    if conflict == CONFLICT_NONE and unsafe:
        conflict = CONFLICT_INELIGIBLE
        reasons.append("unsafe path in workspace result")
    if conflict == CONFLICT_NONE and not allowed:
        conflict = CONFLICT_INELIGIBLE
        reasons.append("no eligible files to apply")
    plan = ApplyPlan(
        task_id=record.task_id,
        workspace_id=record.workspace_id,
        intent_revision=record.intent_revision,
        source_base_revision=record.base_revision,
        changed_files=changed,
        added_files=added,
        deleted_files=deleted,
        allowed_changes=sorted(allowed),
        rejected_changes=sorted(set(rejected)),
        conflict_status=conflict,
        apply_status=APPLY_NOT_APPLIED,
        validation_status="not_run",
        scope_confidence=confidence,
        reasons=reasons,
        rejected_reasons=rejected_reasons,
        operations=operations,
    )
    persist_plan(record, plan)
    persist_record(project, root, record)
    return plan


def _backup_root(record: WorkspaceRecord) -> Path:
    return _workspace_home(record) / BACKUP_DIR


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())


def _backup_canonical(
    canonical: Path, rel: str, backup: Path
) -> dict[str, Any]:
    dest = _confined(canonical, rel)
    if dest is None:
        raise IntegrationError(f"cannot backup unsafe path: {rel}")
    entry: dict[str, Any] = {"path": rel, "existed": dest.is_file()}
    if dest.is_file() and not _is_link(dest):
        stored = backup / rel
        _copy_file(dest, stored)
        entry["backup"] = rel
    return entry


def _apply_one(
    rel: str,
    op: str,
    *,
    tree: Path,
    canonical: Path,
) -> None:
    dest = _confined(canonical, rel)
    if dest is None:
        raise IntegrationError(f"apply refused unsafe dest: {rel}")
    if op == OP_DELETE:
        if dest.is_file() or _is_link(dest):
            dest.unlink()
        return
    src = _confined(tree, rel)
    if src is None or _is_link(tree / rel) or not src.is_file():
        raise IntegrationError(f"workspace source missing: {rel}")
    _copy_file(src, dest)


def _rollback(canonical: Path, entries: list[dict[str, Any]], backup: Path) -> None:
    for entry in reversed(entries):
        rel = str(entry.get("path") or "")
        dest = _confined(canonical, rel)
        if dest is None:
            continue
        if entry.get("existed") and entry.get("backup"):
            stored = backup / str(entry["backup"])
            if stored.is_file():
                _copy_file(stored, dest)
            continue
        if dest.is_file() or _is_link(dest):
            dest.unlink()


def integrate_workspace(
    project: dict[str, Any],
    root: Path,
    workspace_id: str,
    *,
    assignment: Any | None = None,
    task: Any | None = None,
    run_checks: bool = True,
) -> ApplyPlan:
    """Apply an eligible plan to the canonical workbench under Factory control."""
    plan = plan_integration(
        project,
        root,
        workspace_id,
        assignment=assignment,
        task=task,
    )
    record = load_workspace(project, root, workspace_id)
    if record is None:
        raise IntegrationError(f"workspace not found: {workspace_id}")
    if plan.conflict_status != CONFLICT_NONE or not plan.allowed_changes:
        plan.apply_status = APPLY_REFUSED
        persist_plan(record, plan)
        return plan
    canonical = _app_dir(project, root)
    tree = Path(record.workspace_path)
    backup = _backup_root(record)
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    applied: list[str] = []
    try:
        for rel in plan.allowed_changes:
            op = plan.operations.get(rel) or OP_MODIFY
            entries.append(_backup_canonical(canonical, rel, backup))
            _apply_one(rel, op, tree=tree, canonical=canonical)
            applied.append(rel)
    except (OSError, ValueError, IntegrationError) as exc:
        _rollback(canonical, entries, backup)
        plan.apply_status = APPLY_ROLLED_BACK
        plan.validation_status = "not_run"
        plan.reasons.append(f"apply failed: {exc}")
        persist_plan(record, plan)
        return plan
    status = "skipped"
    if run_checks:
        status = _validate_canonical(canonical)
    plan.validation_status = status
    if status in {"failed", "error", "blocked"}:
        _rollback(canonical, entries, backup)
        plan.apply_status = APPLY_ROLLED_BACK
        plan.reasons.append(
            f"canonical validation {status}; restored previous files"
        )
        persist_plan(record, plan)
        return plan
    plan.apply_status = APPLY_APPLIED
    plan.reasons.append("applied under Factory authority: " + ", ".join(applied))
    persist_plan(record, plan)
    return plan
