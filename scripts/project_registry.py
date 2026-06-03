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
mapping the advance consumes — workbench at ``app_path``, factory working files
under ``state_path`` — so no stage hardwires ``apps/<active_project>``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_paths import resolve_paths
from repo_tools import load_simple_yaml, safe_write_text
from settings import load_engine_settings

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


def state_path_for(project_id: str, root: Path) -> str:
    """Return the pre-promote seed-staging path for a project.

    Built on the configurable ``seed_staging_base`` engine setting so it stays
    consistent with the seed pipeline (:mod:`seed_context`).
    """
    base = load_engine_settings(root)["seed_staging_base"]
    return f"{base}/{project_id}"


def load_registry(root: Path) -> dict[str, Any]:
    """Load the project registry from the configured registry path.

    Args:
        root: Absolute repository root.

    Returns:
        Registry mapping with ``active_project`` and ``projects``.
    """
    data = load_simple_yaml(load_engine_settings(root)["registry_path"], root)
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
        # Per-project workbench path overrides, when any are set.
        overrides = entry.get("paths")
        if isinstance(overrides, dict) and overrides:
            lines.append("    paths:")
            for okey, ovalue in overrides.items():
                lines.append(f'      {okey}: "{ovalue}"')
    return "\n".join(lines) + "\n"


def save_registry(registry: dict[str, Any], root: Path) -> None:
    """Persist the project registry.

    Args:
        registry: Registry mapping to write.
        root: Absolute repository root.
    """
    registry_path = load_engine_settings(root)["registry_path"]
    safe_write_text(
        registry_path,
        dump_registry(registry),
        repo_root=root,
        allowed_roots=[str(Path(registry_path).parent)],
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
    paths: dict[str, str] | None = None,
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
        paths: Optional per-project workbench sub-folder overrides; preserved
            across updates when not supplied.

    Raises:
        RegistryError: If ``repo_mode`` is not recognized.
    """
    if repo_mode not in REPO_MODES:
        raise RegistryError(f"Unknown repo_mode: {repo_mode}")
    projects = registry.setdefault("projects", {})
    existing = projects.get(project_id, {})
    if paths is None:
        paths = (
            existing.get("paths")
            if isinstance(existing.get("paths"), dict)
            else {}
        )
    projects[project_id] = {
        "app_path": app_path,
        "state_path": state_path,
        "repo_mode": repo_mode,
        "seed_file": seed_file,
        "created_at": str(existing.get("created_at") or now),
        "updated_at": now,
        "paths": dict(paths or {}),
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
    """Resolve a registry entry into the path mapping the advance consumes.

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
    # Legacy registry state_path (e.g. factory_state/projects/<id>); retained
    # only so migrate-project-runtime can find pre-relocation data.
    legacy_state_path = str(entry.get("state_path") or "").rstrip("/")
    overrides = entry.get("paths")
    paths = resolve_paths(
        app_path, overrides if isinstance(overrides, dict) else None
    )
    return {
        "name": project_id,
        "app_path": app_path,
        "legacy_state_path": legacy_state_path,
        "repo_mode": str(entry.get("repo_mode") or "embedded"),
        "seed_file": str(entry.get("seed_file") or "docs/seed.md"),
        # Every runtime path lives inside the workbench (app_path). Nothing here
        # resolves to a root-level folder — that is the engine's space.
        "root": app_path,
        "config_dir": paths.config_dir,
        "factory_config_path": paths.factory_config_path,
        "state_dir": paths.state_dir,
        "factory_state_dir": paths.factory_state_dir,
        "context_root": paths.factory_context_dir,
        "task_root": paths.tasks_dir,
        "report_root": paths.reports_dir,
        # Phase 9A imported-context store: raw imports, extracted archives, and
        # the catalog. Distinct from factory_context (goal + grown context).
        "context_store_root": paths.context_dir,
        "context_imports_root": f"{paths.context_dir}/imports",
        "context_extracted_root": f"{paths.context_dir}/extracted",
        "context_catalog_path": f"{paths.context_dir}/catalog.yaml",
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


def app_is_buildable(app_path: str, root: Path) -> bool:
    """Report whether the factory may build at this app path.

    Buildable means the app lives under the repo (embedded) OR under the
    owner-configured external apps base. An app resolved anywhere else (an
    arbitrary external path that the owner has not approved as the apps base)
    is NOT buildable — the factory refuses rather than writing there.

    Args:
        app_path: Repo-relative or absolute app path.
        root: Absolute repository root.

    Returns:
        ``True`` when the app path is inside an owner-approved build base.
    """
    repo = root.resolve()
    candidate = Path(app_path)
    target = (
        candidate.resolve()
        if candidate.is_absolute()
        else (repo / candidate).resolve()
    )
    bases = [repo]
    try:
        from settings import is_apps_base_external, resolve_apps_base

        if is_apps_base_external(root):
            bases.append(resolve_apps_base(root))
    except Exception:  # noqa: BLE001 - missing/odd config → repo-only
        pass
    return any(target == b or b in target.parents for b in bases)


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
