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
from repo_tools import load_simple_yaml, resolve_repo_path, safe_write_text
from settings import load_engine_settings

REGISTRY_RELPATH = "config/projects.yaml"
# A project carries its own identity/control inside its workbench. Same file
# project_control manages; named here to avoid an import cycle.
CONTROL_FILENAME = "crazy_project.yaml"
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
    projects = data.get("projects")
    if not isinstance(projects, dict):
        projects = {}
    # The registry is a pure id->path DIRECTORY for discovery and --all sweeps.
    # There is no global "active project": selection is per invocation (id,
    # path, or cwd) so projects are independently addressable and concurrent.
    return {"projects": projects}


def dump_registry(registry: dict[str, Any]) -> str:
    """Serialize the registry to the bootstrap YAML subset.

    Args:
        registry: Registry mapping to serialize.

    Returns:
        YAML text parseable by :func:`repo_tools.load_simple_yaml`.
    """
    lines = [
        "# Project registry: a pure id->path directory for discovery and",
        "# `--all` sweeps. There is NO active project — every command targets a",
        "# project by id, by --path, or by the workbench it runs inside. Apps",
        "# may live under apps/<id> (embedded) or anywhere on disk (external).",
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
    return _build_project(project_id, entry)


def _build_project(project_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Build the resolved project mapping from a registry-style entry."""
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


def resolve_project_at(app_path: str, root: Path) -> dict[str, Any]:
    """Resolve a project directly from its own ``crazy_project.yaml``.

    This is registry-independent: a project carries its own identity inside its
    workbench, so it can be targeted by path (or discovered from the cwd)
    without any global selector. Missing optional fields fall back to sensible
    defaults (``state_path`` derives, ``seed_file`` = ``docs/seed.md``).

    Raises:
        RegistryError: If the path has no readable ``crazy_project.yaml``.
    """
    app_path = str(app_path).rstrip("/")
    control_rel = f"{app_path}/{CONTROL_FILENAME}"
    if not resolve_repo_path(control_rel, root).is_file():
        raise RegistryError(f"No {CONTROL_FILENAME} found at: {app_path}")
    data = load_simple_yaml(control_rel, root)
    proj_raw = data.get("project")
    proj: dict[str, Any] = proj_raw if isinstance(proj_raw, dict) else {}
    ov_raw = data.get("paths")
    overrides: dict[str, Any] = ov_raw if isinstance(ov_raw, dict) else {}
    project_id = str(proj.get("id") or Path(app_path).name)
    is_abs = Path(app_path).is_absolute()
    entry = {
        "app_path": app_path,
        "state_path": str(proj.get("state_path") or ""),
        "repo_mode": str(
            proj.get("mode") or ("external" if is_abs else "embedded")
        ),
        "seed_file": str(proj.get("seed_file") or "docs/seed.md"),
        "paths": overrides,
    }
    return _build_project(project_id, entry)


def find_workbench_from_cwd(cwd: Path, root: Path) -> str | None:
    """Walk up from ``cwd`` to find a workbench (a dir with a control file).

    Returns the workbench path (the dir containing ``crazy_project.yaml``), or
    ``None`` when the cwd is not inside any project. The factory repo root
    itself is never treated as a project workbench.
    """
    current = cwd.resolve()
    for candidate in [current, *current.parents]:
        if candidate == root.resolve():
            return None
        if (candidate / CONTROL_FILENAME).is_file():
            return str(candidate)
    return None


def all_project_ids(registry: dict[str, Any]) -> list[str]:
    """Return every registered project id (for a ``--all`` sweep)."""
    projects = registry.get("projects")
    return list(projects) if isinstance(projects, dict) else []


def resolve_target(
    registry: dict[str, Any],
    root: Path,
    *,
    project_id: str | None = None,
    path: str | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Resolve which project a command acts on, by id, path, or cwd.

    Precedence: an explicit ``project_id`` (registry lookup), else an explicit
    ``path`` (the project's own control file), else discovery from ``cwd``.
    There is no global "active project" — selection is always per invocation.

    Raises:
        RegistryError: If no project can be resolved from the inputs.
    """
    if project_id:
        return resolve_project(registry, project_id)
    if path:
        return resolve_project_at(path, root)
    if cwd is not None:
        workbench = find_workbench_from_cwd(cwd, root)
        if workbench:
            return resolve_project_at(workbench, root)
    raise RegistryError(
        "No project specified. Name one (<id>), pass --path <dir>, or run "
        "from inside a project workbench."
    )


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
