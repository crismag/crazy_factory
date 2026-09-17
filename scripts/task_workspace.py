#!/usr/bin/env python3
"""Isolated task workspace lifecycle (orchestration Slice 4).

A selected TaskNode plus bounded ExecutionAssignment can run in a
Factory-owned tree that is not the canonical workbench. The Factory
owns integration; this module does not merge, cherry-pick, or push.

Isolation:

- ``worktree`` when the workbench itself is a Git repository
  (``<app>/.git`` exists);
- ``copy`` of application allowed tops otherwise.

A workbench that merely lives inside the Factory repo is **not** a Git
base — a Factory worktree would include engine source. That case is
recorded as ``git_base_available=False`` rather than pretending.

Live AgentExecutor / Codex paths are not switched here.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from execution_assignment import ALLOWED_TOPS, BLOCKED_PARTS
from product_intent import intent_revision
from repo_tools import BLOCKED_NAMES, BLOCKED_SUFFIXES

WORKSPACES_DIR = "factory_workspaces"
RECORD_FILE = "workspace.json"
TREE_DIR = "tree"
INDEX_FILE = "index.json"

STATUS_CREATED = "created"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_STALE = "stale"

KIND_WORKTREE = "worktree"
KIND_COPY = "copy"

_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")
_GIT_TIMEOUT = 15
_SKIP_DIR_NAMES = frozenset(BLOCKED_PARTS) | {
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
}


class WorkspaceError(RuntimeError):
    """Refused or failed workspace lifecycle operation."""


@dataclass
class WorkspaceRecord:
    """Durable identity for one isolated task tree."""

    workspace_id: str
    task_id: str
    intent_revision: int
    base_revision: str
    source_project: str
    workspace_path: str
    status: str
    created_at: str
    changed_files: list[str] = field(default_factory=list)
    isolation_kind: str = KIND_COPY
    git_base_available: bool = False
    git_base_reason: str = ""
    canonical_path: str = ""
    canonical_dirty: bool = False
    added_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    git_diff_available: bool = False
    validation_status: str = "not_run"
    baseline_hashes: dict[str, str] = field(default_factory=dict)


def _as_path(value: object, root: Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (root / path)


def _app_dir(project: dict[str, Any], root: Path) -> Path:
    return _as_path(project["app_path"], root).resolve()


def _project_name(project: dict[str, Any]) -> str:
    name = str(project.get("name") or "").strip()
    if name:
        return _safe_id(name)
    return _safe_id(Path(str(project["app_path"])).name)


def _safe_id(text: str) -> str:
    cleaned = _SAFE_ID.sub("-", str(text or "").strip()).strip("-._")
    return (cleaned or "workspace")[:80]


def _now(created_at: str | None) -> str:
    if created_at:
        return str(created_at)
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def workspaces_root(root: Path) -> Path:
    return Path(root).resolve() / WORKSPACES_DIR


def project_workspaces_dir(project: dict[str, Any], root: Path) -> Path:
    return workspaces_root(root) / _project_name(project)


def _assert_under_workspaces(path: Path, root: Path) -> Path:
    target = path.resolve()
    base = workspaces_root(root)
    if target != base and base not in target.parents:
        raise WorkspaceError(
            f"refusing path outside {WORKSPACES_DIR}: {path}"
        )
    return target


def _git(
    args: list[str], cwd: Path, *, check: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
        check=check,
    )


def workbench_is_git_repo(app: Path) -> bool:
    """True only when the workbench root itself is a Git repository."""
    return (app / ".git").exists()


def _canonical_dirty(app: Path) -> bool:
    if not workbench_is_git_repo(app):
        return False
    result = _git(["status", "--porcelain"], app)
    return bool((result.stdout or "").strip())


def _head_sha(app: Path) -> str:
    result = _git(["rev-parse", "HEAD"], app)
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _sensitive(path: Path) -> bool:
    name = path.name.lower()
    if name in BLOCKED_NAMES or name in {n.lower() for n in BLOCKED_NAMES}:
        return True
    return any(name.endswith(suffix) for suffix in BLOCKED_SUFFIXES)


def _iter_app_files(app: Path) -> list[Path]:
    found: list[Path] = []
    if not app.is_dir():
        return found
    for top in ALLOWED_TOPS:
        item = app / top
        if not item.exists() or _sensitive(item):
            continue
        if item.is_file():
            found.append(item)
            continue
        if not item.is_dir():
            continue
        for path in sorted(item.rglob("*")):
            if path.is_symlink():
                continue
            if not path.is_file() or _sensitive(path):
                continue
            if any(part in _SKIP_DIR_NAMES for part in path.parts):
                continue
            found.append(path)
    return found


def _rel(app: Path, path: Path) -> str:
    return path.resolve().relative_to(app.resolve()).as_posix()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _baseline_hashes(app: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in _iter_app_files(app):
        hashes[_rel(app, path)] = _file_hash(path)
    return hashes


def _copy_workbench(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for top in ALLOWED_TOPS:
        item = src / top
        if not item.exists() or _sensitive(item):
            continue
        target = dest / top
        if item.is_dir():
            shutil.copytree(
                item,
                target,
                ignore=shutil.ignore_patterns(*_SKIP_DIR_NAMES),
                dirs_exist_ok=True,
            )
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _load_index(folder: Path) -> list[str]:
    path = folder / INDEX_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if isinstance(data, dict) and isinstance(data.get("workspaces"), list):
        return [str(item) for item in data["workspaces"] if str(item)]
    return []


def _save_index(folder: Path, ids: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"workspaces": ids}
    (folder / INDEX_FILE).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _workspace_home(project: dict[str, Any], root: Path, workspace_id: str) -> Path:
    return project_workspaces_dir(project, root) / workspace_id


def record_path(project: dict[str, Any], root: Path, workspace_id: str) -> Path:
    return _workspace_home(project, root, workspace_id) / RECORD_FILE


def record_from_dict(raw: dict[str, Any]) -> WorkspaceRecord:
    hashes = raw.get("baseline_hashes") or {}
    if not isinstance(hashes, dict):
        hashes = {}
    return WorkspaceRecord(
        workspace_id=str(raw.get("workspace_id") or ""),
        task_id=str(raw.get("task_id") or ""),
        intent_revision=int(raw.get("intent_revision") or 0),
        base_revision=str(raw.get("base_revision") or ""),
        source_project=str(raw.get("source_project") or ""),
        workspace_path=str(raw.get("workspace_path") or ""),
        status=str(raw.get("status") or STATUS_CREATED),
        created_at=str(raw.get("created_at") or ""),
        changed_files=[str(x) for x in (raw.get("changed_files") or [])],
        isolation_kind=str(raw.get("isolation_kind") or KIND_COPY),
        git_base_available=bool(raw.get("git_base_available")),
        git_base_reason=str(raw.get("git_base_reason") or ""),
        canonical_path=str(raw.get("canonical_path") or ""),
        canonical_dirty=bool(raw.get("canonical_dirty")),
        added_files=[str(x) for x in (raw.get("added_files") or [])],
        deleted_files=[str(x) for x in (raw.get("deleted_files") or [])],
        git_diff_available=bool(raw.get("git_diff_available")),
        validation_status=str(raw.get("validation_status") or "not_run"),
        baseline_hashes={str(k): str(v) for k, v in hashes.items()},
    )


def persist_record(
    project: dict[str, Any], root: Path, record: WorkspaceRecord
) -> Path:
    home = _workspace_home(project, root, record.workspace_id)
    _assert_under_workspaces(home, root)
    home.mkdir(parents=True, exist_ok=True)
    path = home / RECORD_FILE
    path.write_text(json.dumps(asdict(record), indent=2) + "\n", encoding="utf-8")
    return path


def load_workspace(
    project: dict[str, Any], root: Path, workspace_id: str
) -> WorkspaceRecord | None:
    path = record_path(project, root, workspace_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return record_from_dict(raw)


def list_workspace_ids(project: dict[str, Any], root: Path) -> list[str]:
    return _load_index(project_workspaces_dir(project, root))


def inspect_workspace(
    project: dict[str, Any], root: Path, workspace_id: str
) -> WorkspaceRecord | None:
    record = load_workspace(project, root, workspace_id)
    if record is None:
        return None
    return collect_workspace_result(project, root, record)


def _allocate_id(
    project: dict[str, Any],
    root: Path,
    task_id: str,
    revision: int,
) -> str:
    existing = set(list_workspace_ids(project, root))
    stem = _safe_id(task_id)
    n = 0
    while True:
        payload = f"{task_id}|{revision}|{n}".encode()
        suffix = hashlib.sha256(payload).hexdigest()[:8]
        workspace_id = f"{stem}-{suffix}"
        if workspace_id not in existing:
            return workspace_id
        n += 1


def _refuse_stale(task: Any, assignment: Any | None, current_rev: int) -> None:
    task_rev = int(getattr(task, "intent_revision", 0) or 0)
    if task_rev != int(current_rev):
        raise WorkspaceError(
            f"stale task revision {task_rev} != current {current_rev}"
        )
    if assignment is not None and bool(getattr(assignment, "stale", False)):
        raise WorkspaceError("stale assignment cannot create a workspace")


def create_workspace(
    project: dict[str, Any],
    root: Path,
    *,
    task: Any,
    assignment: Any | None = None,
    created_at: str | None = None,
) -> WorkspaceRecord:
    """Create an isolated tree for ``task``. Does not modify the canonical app."""
    current_rev = intent_revision(project, root)
    _refuse_stale(task, assignment, current_rev)
    task_id = str(getattr(task, "task_id", "") or "").strip()
    if not task_id:
        raise WorkspaceError("task_id is required")
    app = _app_dir(project, root)
    if not app.is_dir():
        raise WorkspaceError(f"canonical workbench missing: {app}")
    workspace_id = _allocate_id(project, root, task_id, current_rev)
    home = _assert_under_workspaces(
        _workspace_home(project, root, workspace_id), root
    )
    tree = home / TREE_DIR
    if tree.resolve() == app:
        raise WorkspaceError("workspace tree must not be the canonical app")
    isolation = KIND_COPY
    base_revision = ""
    git_ok = False
    git_reason = (
        "workbench is not its own git repository; a Factory worktree "
        "would include engine source"
    )
    dirty = False
    if workbench_is_git_repo(app):
        dirty = _canonical_dirty(app)
        sha = _head_sha(app)
        if not sha:
            git_reason = "workbench git repository has no HEAD commit"
        else:
            isolation = KIND_WORKTREE
            git_ok = True
            git_reason = ""
            base_revision = sha
            if dirty:
                git_reason = (
                    "worktree is HEAD; uncommitted canonical changes "
                    "are not included"
                )
            home.mkdir(parents=True, exist_ok=True)
            added = _git(
                ["worktree", "add", "--detach", str(tree), "HEAD"],
                app,
            )
            if added.returncode != 0:
                raise WorkspaceError(
                    "git worktree add failed: "
                    + (added.stderr or added.stdout or "unknown").strip()
                )
    if isolation == KIND_COPY:
        _copy_workbench(app, tree)
    hashes = _baseline_hashes(tree)
    record = WorkspaceRecord(
        workspace_id=workspace_id,
        task_id=task_id,
        intent_revision=int(getattr(task, "intent_revision", 0) or current_rev),
        base_revision=base_revision,
        source_project=_project_name(project),
        workspace_path=str(tree),
        status=STATUS_CREATED,
        created_at=_now(created_at),
        isolation_kind=isolation,
        git_base_available=git_ok,
        git_base_reason=git_reason,
        canonical_path=str(app),
        canonical_dirty=dirty,
        git_diff_available=isolation == KIND_WORKTREE,
        baseline_hashes=hashes,
    )
    persist_record(project, root, record)
    folder = project_workspaces_dir(project, root)
    ids = _load_index(folder)
    if workspace_id not in ids:
        ids.append(workspace_id)
        _save_index(folder, ids)
    return record


def bind_project_to_workspace(
    project: dict[str, Any], record: WorkspaceRecord
) -> dict[str, Any]:
    """Point a project mapping at the isolated tree. Does not write registry."""
    bound = dict(project)
    bound["app_path"] = record.workspace_path
    bound["canonical_app_path"] = record.canonical_path
    bound["workspace_id"] = record.workspace_id
    return bound


def mark_workspace(
    project: dict[str, Any],
    root: Path,
    record: WorkspaceRecord,
    status: str,
) -> WorkspaceRecord:
    allowed = {
        STATUS_CREATED,
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_STALE,
    }
    if status not in allowed:
        raise WorkspaceError(f"unknown workspace status: {status}")
    record.status = status
    persist_record(project, root, record)
    return record


def refresh_workspace_staleness(
    project: dict[str, Any],
    root: Path,
    record: WorkspaceRecord,
) -> WorkspaceRecord:
    """Mark superseded when owner intent has moved on. Does not reuse it."""
    current = intent_revision(project, root)
    if int(record.intent_revision) != int(current):
        record.status = STATUS_STALE
        persist_record(project, root, record)
    return record


def reusable_workspace(
    project: dict[str, Any],
    root: Path,
    *,
    task_id: str,
    intent_revision_value: int,
) -> WorkspaceRecord | None:
    """Return a live workspace for this task+revision, never a stale one."""
    for workspace_id in list_workspace_ids(project, root):
        record = load_workspace(project, root, workspace_id)
        if record is None:
            continue
        record = refresh_workspace_staleness(project, root, record)
        if record.task_id != task_id:
            continue
        if int(record.intent_revision) != int(intent_revision_value):
            continue
        if record.status == STATUS_STALE:
            continue
        return record
    return None


def _porcelain_files(tree: Path) -> tuple[list[str], list[str], list[str]]:
    result = _git(["status", "--porcelain"], tree)
    changed: list[str] = []
    added: list[str] = []
    deleted: list[str] = []
    for line in (result.stdout or "").splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[-1]
        if code.strip() == "??" or "A" in code:
            added.append(path)
            changed.append(path)
        elif "D" in code:
            deleted.append(path)
            changed.append(path)
        else:
            changed.append(path)
    return changed, added, deleted


def _copy_delta(
    tree: Path, baseline: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    current = _baseline_hashes(tree)
    changed: list[str] = []
    added: list[str] = []
    deleted: list[str] = []
    for rel, digest in current.items():
        if rel not in baseline:
            added.append(rel)
            changed.append(rel)
        elif baseline[rel] != digest:
            changed.append(rel)
    for rel in baseline:
        if rel not in current:
            deleted.append(rel)
            changed.append(rel)
    return sorted(changed), sorted(added), sorted(deleted)


def collect_workspace_result(
    project: dict[str, Any],
    root: Path,
    record: WorkspaceRecord,
) -> WorkspaceRecord:
    """Derive changed files from Git/filesystem, not worker prose."""
    tree = Path(record.workspace_path)
    if record.isolation_kind == KIND_WORKTREE and workbench_is_git_repo(tree):
        changed, added, deleted = _porcelain_files(tree)
        record.git_diff_available = True
    else:
        changed, added, deleted = _copy_delta(tree, record.baseline_hashes)
        record.git_diff_available = False
    record.changed_files = changed
    record.added_files = added
    record.deleted_files = deleted
    persist_record(project, root, record)
    return record


def cleanup_workspace(
    project: dict[str, Any],
    root: Path,
    workspace_id: str,
) -> None:
    """Remove one workspace tree. Never touches the canonical app or siblings."""
    record = load_workspace(project, root, workspace_id)
    home = _assert_under_workspaces(
        _workspace_home(project, root, workspace_id), root
    )
    canonical = _app_dir(project, root)
    if home == canonical or canonical in home.parents:
        raise WorkspaceError("cleanup refused: path is the canonical workbench")
    if record is not None:
        tree = Path(record.workspace_path).resolve()
        _assert_under_workspaces(tree, root)
        if tree == canonical:
            raise WorkspaceError("cleanup refused: tree is canonical")
        if record.isolation_kind == KIND_WORKTREE and workbench_is_git_repo(
            canonical
        ):
            _git(["worktree", "remove", "--force", str(tree)], canonical)
            _git(["worktree", "prune"], canonical)
    if home.exists():
        shutil.rmtree(home)
    folder = project_workspaces_dir(project, root)
    ids = [item for item in _load_index(folder) if item != workspace_id]
    _save_index(folder, ids)
