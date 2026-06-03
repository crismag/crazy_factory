#!/usr/bin/env python3
"""Phase 9 project registry for Crazy Factory.

The registry removes the ambiguity around "where does the app live". It maps a
``project_id`` to four things that used to be conflated:

- ``app_path``    where the actual software being built lives (the workbench).
                  May be inside the factory repo (``apps/<id>``), a sibling
                  folder, or a completely separate repository.
- ``state_path``  where the factory keeps its own working memory for the
                  project (contracts, reports, runs) under
                  ``factory_state/projects/<id>/``.
- ``repo_mode``   ``embedded`` (app lives under the factory repo) or
                  ``external`` (app lives elsewhere / its own repo).
- ``seed_file``   the project's seed document, relative to ``app_path``.

The factory never picks a project by default; an owner selects one with
``active_project``. ``resolve_project`` turns a registry entry into the path
mapping the tick consumes — workbench at ``app_path``, factory working files
under ``state_path`` — so no stage hardwires ``apps/<active_project>``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from repo_tools import load_simple_yaml, safe_write_text

REGISTRY_RELPATH = "config/projects.yaml"
REPO_MODES: tuple[str, ...] = ("embedded", "external")
_ENTRY_KEYS: tuple[str, ...] = (
    "app_path",
    "state_path",
    "repo_mode",
    "seed_file",
    "created_at",
    "updated_at",
)


class RegistryError(RuntimeError):
    """Raised when the project registry is missing or inconsistent."""


def state_path_for(project_id: str) -> str:
    """Return the default factory state path for a project."""
    return f"factory_state/projects/{project_id}"


def load_registry(root: Path) -> dict[str, Any]:
    """Load the project registry from ``config/projects.yaml``.

    Args:
        root: Absolute repository root.

    Returns:
        Registry mapping with ``active_project`` and ``projects``.
    """
    data = load_simple_yaml(REGISTRY_RELPATH, root)
    active = str(data.get("active_project") or "")
    projects = data.get("projects")
    if not isinstance(projects, dict):
        projects = {}
    return {"active_project": active, "projects": projects}


def dump_registry(registry: dict[str, Any]) -> str:
    """Serialize the registry to the bootstrap YAML subset.

    Args:
        registry: Registry mapping to serialize.

    Returns:
        YAML text parseable by :func:`repo_tools.load_simple_yaml`.
    """
    active = str(registry.get("active_project") or "")
    lines = [
        "# Project registry. The factory never picks a project by default;",
        "# select one with `crazy-admin activate <project_id>`. Apps may live",
        "# under apps/<id> (embedded) or anywhere on disk (external).",
        f'active_project: "{active}"',
        "",
        "projects:",
    ]
    projects = registry.get("projects") or {}
    if not projects:
        # An empty mapping is represented by the bare `projects:` key.
        return "\n".join(lines) + "\n"
    for project_id, entry in projects.items():
        lines.append(f"  {project_id}:")
        for key in _ENTRY_KEYS:
            value = str(entry.get(key, ""))
            lines.append(f'    {key}: "{value}"')
    return "\n".join(lines) + "\n"


def save_registry(registry: dict[str, Any], root: Path) -> None:
    """Persist the project registry.

    Args:
        registry: Registry mapping to write.
        root: Absolute repository root.
    """
    safe_write_text(
        REGISTRY_RELPATH,
        dump_registry(registry),
        repo_root=root,
        allowed_roots=["config"],
    )


def register_project(
    registry: dict[str, Any],
    *,
    project_id: str,
    app_path: str,
    state_path: str,
    repo_mode: str,
    seed_file: str,
    now: str,
) -> None:
    """Add or update a project entry in the registry (in place).

    Args:
        registry: Registry mapping to update.
        project_id: Stable project identifier.
        app_path: Workbench path (repo-relative or absolute).
        state_path: Factory state path for the project.
        repo_mode: ``"embedded"`` or ``"external"``.
        seed_file: Seed document path relative to ``app_path``.
        now: ISO timestamp for created/updated bookkeeping.

    Raises:
        RegistryError: If ``repo_mode`` is not recognized.
    """
    if repo_mode not in REPO_MODES:
        raise RegistryError(f"Unknown repo_mode: {repo_mode}")
    projects = registry.setdefault("projects", {})
    existing = projects.get(project_id, {})
    projects[project_id] = {
        "app_path": app_path,
        "state_path": state_path,
        "repo_mode": repo_mode,
        "seed_file": seed_file,
        "created_at": str(existing.get("created_at") or now),
        "updated_at": now,
    }


def set_active(registry: dict[str, Any], project_id: str) -> None:
    """Set the active project, validating it is registered.

    Args:
        registry: Registry mapping to update.
        project_id: Project to activate.

    Raises:
        RegistryError: If the project is not registered.
    """
    if project_id not in (registry.get("projects") or {}):
        raise RegistryError(f"Project is not registered: {project_id}")
    registry["active_project"] = project_id


def active_project_id(registry: dict[str, Any]) -> str:
    """Return the active project id, or an empty string when none is set."""
    return str(registry.get("active_project") or "")


def resolve_project(
    registry: dict[str, Any], project_id: str
) -> dict[str, Any]:
    """Resolve a registry entry into the path mapping the tick consumes.

    The workbench is ``app_path``; the factory's own working files live under
    ``state_path``. No path is hardwired to ``apps/<id>``.

    Args:
        registry: Registry mapping.
        project_id: Project to resolve.

    Returns:
        A project mapping with name, app_path, state_path, repo_mode, and the
        ``root``/``context_root``/``task_root``/``report_root`` the stages use.

    Raises:
        RegistryError: If the project is not registered.
    """
    entry = (registry.get("projects") or {}).get(project_id)
    if not isinstance(entry, dict):
        raise RegistryError(f"Project is not registered: {project_id}")
    app_path = str(entry["app_path"]).rstrip("/")
    state_path = str(entry["state_path"]).rstrip("/")
    return {
        "name": project_id,
        "app_path": app_path,
        "state_path": state_path,
        "repo_mode": str(entry.get("repo_mode") or "embedded"),
        "seed_file": str(entry.get("seed_file") or "docs/seed.md"),
        # The workbench root is app_path; the app's code/docs/tests and the
        # per-run factory working files live within it (so the existing
        # path-confinement checks hold). state_path holds the per-project
        # factory_state (seed-grown context ledger, analytics).
        "root": app_path,
        "context_root": f"{app_path}/factory_context",
        "task_root": f"{app_path}/factory_tasks",
        "report_root": f"{app_path}/factory_reports",
        # Phase 9A imported-context store: raw imports, extracted archives, and
        # the catalog. Distinct from factory_context (goal + grown context).
        "context_store_root": f"{app_path}/context",
        "context_imports_root": f"{app_path}/context/imports",
        "context_extracted_root": f"{app_path}/context/extracted",
        "context_catalog_path": f"{app_path}/context/catalog.yaml",
    }


def app_is_external(app_path: str, root: Path) -> bool:
    """Report whether an app path is outside the factory repository.

    Args:
        app_path: Repo-relative or absolute app path.
        root: Absolute repository root.

    Returns:
        ``True`` when the app lives outside the factory repo.
    """
    candidate = Path(app_path)
    target = (
        candidate.resolve()
        if candidate.is_absolute()
        else (root / candidate).resolve()
    )
    return root.resolve() != target and root.resolve() not in target.parents


def workbench_exists(app_path: str, root: Path) -> bool:
    """Report whether the workbench directory exists on disk.

    Args:
        app_path: Repo-relative or absolute app path.
        root: Absolute repository root.

    Returns:
        ``True`` when the workbench directory exists.
    """
    candidate = Path(app_path)
    target = candidate if candidate.is_absolute() else (root / candidate)
    return target.is_dir()
