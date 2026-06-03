#!/usr/bin/env python3
"""Central project-local runtime path resolver for Crazy Factory.

The Crazy Factory root is the *engine* (code, templates, global defaults, docs).
A project's *runtime* — its config, state, reports, factory memory, tasks, and
context — lives entirely inside the project workbench (``app_path``). Nothing in
this module ever resolves a project-runtime path to a root-level folder.

Every script that needs a runtime path should derive it from here rather than
reconstructing ``state/`` or ``reports/`` by hand. This keeps ownership
unambiguous (each project owns its files) and makes the fail-loud guard
(:func:`assert_project_local`) the single chokepoint for "am I about to write a
project file outside its folder?".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repo_tools import (
    RepoSafetyError,
    load_simple_yaml,
    resolve_repo_path,
)
from settings import WORKBENCH_DEFAULTS, load_engine_settings


class RuntimePathError(RuntimeError):
    """Raised when a project-runtime write would escape the project folder."""


@dataclass(frozen=True)
class ProjectPaths:
    """Repository-relative runtime paths for one project, all under app_path.

    Attributes:
        project_root: The project workbench root (``app_path``).
        config_dir: Project-local config directory.
        factory_config_path: Project-local active ``factory.yaml``.
        state_dir: Run-state (json, flags, mission lock).
        factory_state_dir: Factory memory / seed-grown context / checkpoints.
        reports_dir: Project reports.
        tasks_dir: Planning + proposal + patch-plan artifacts.
        factory_context_dir: Project goal + grown build context.
        context_dir: Imported-knowledge store (Phase 9A).
    """

    project_root: str
    config_dir: str
    factory_config_path: str
    state_dir: str
    factory_state_dir: str
    reports_dir: str
    tasks_dir: str
    factory_context_dir: str
    context_dir: str


def resolve_paths(
    app_path: str, overrides: dict | None = None
) -> ProjectPaths:
    """Resolve every project-local runtime path from a workbench path.

    Sub-folder names come from ``overrides`` (the per-project registry entry)
    when present, else the built-in :data:`settings.WORKBENCH_DEFAULTS`. The
    ``config_dir``/``factory_config_path`` are fixed: the project config file
    lives at a resolved path, so making them configurable would recurse.

    Args:
        app_path: Repository-relative (or absolute) project workbench path.
        overrides: Optional per-project sub-folder name overrides.

    Returns:
        The project's :class:`ProjectPaths`.
    """
    base = str(app_path).rstrip("/")
    names = overrides or {}

    def sub(key: str) -> str:
        return f"{base}/{names.get(key) or WORKBENCH_DEFAULTS[key]}"

    return ProjectPaths(
        project_root=base,
        config_dir=f"{base}/config",
        factory_config_path=f"{base}/config/factory.yaml",
        state_dir=sub("state_dir"),
        factory_state_dir=sub("factory_state_dir"),
        reports_dir=sub("reports_dir"),
        tasks_dir=sub("tasks_dir"),
        factory_context_dir=sub("factory_context_dir"),
        context_dir=sub("context_dir"),
    )


def assert_project_local(rel_path: str, app_path: str, root: Path) -> None:
    """Fail loudly if a project-runtime path is outside the project folder.

    Args:
        rel_path: The repository-relative path about to be written.
        app_path: The project's workbench path.
        root: Absolute repository root.

    Raises:
        RuntimePathError: If ``rel_path`` does not sit inside ``app_path``.
    """
    # resolve_repo_path admits the owner-configured external app base for
    # absolute paths; the containment check below still confines to app_path.
    try:
        app_abs = resolve_repo_path(app_path, root)
        target = resolve_repo_path(rel_path, root)
    except RepoSafetyError as exc:
        raise RuntimePathError(str(exc)) from exc
    if target != app_abs and app_abs not in target.parents:
        raise RuntimePathError(
            "Refusing to write project runtime outside the project folder.\n"
            f"Target:\n  {rel_path}\n"
            f"Expected under:\n  {app_path}/"
        )


def project_config_exists(app_path: str, root: Path) -> bool:
    """Report whether a project has its own ``config/factory.yaml`` yet."""
    paths = resolve_paths(app_path)
    try:
        return resolve_repo_path(paths.factory_config_path, root).is_file()
    except RepoSafetyError:
        return False


def load_project_factory_config(app_path: str, root: Path) -> dict:
    """Load a project's active factory config, falling back to root defaults.

    The project-local ``<app>/config/factory.yaml`` is authoritative once it
    exists (it is created at ``startproject``). When it is missing — e.g. a
    project created before this layout — the root default template is used and
    a clear warning is printed rather than silently writing to root.

    Args:
        app_path: Repository-relative project workbench path.
        root: Absolute repository root.

    Returns:
        The parsed factory configuration mapping.
    """
    paths = resolve_paths(app_path)
    if project_config_exists(app_path, root):
        return load_simple_yaml(paths.factory_config_path, root)
    template = load_engine_settings(root)["factory_config_template"]
    print(
        f"WARNING: no project config at {paths.factory_config_path}; "
        f"using the default template ({template}). Run "
        "`crazy-admin migrate-project-runtime <id>` to materialize it."
    )
    return load_simple_yaml(template, root)
