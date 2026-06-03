#!/usr/bin/env python3
"""Load and validate Crazy Factory configuration for a advance.

This module isolates configuration concerns: reading ``config/factory.yaml``
and ``config/projects.yaml``, refusing settings that exceed dry-run authority,
and resolving the configured active project. It performs no model calls and no
writes.

Example:
    Load configuration and resolve the active project::

        factory_config, projects_config = load_configuration(root)
        name, project = load_active_project(
            factory_config["factory"], projects_config
        )
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from repo_tools import load_simple_yaml, resolve_repo_path
from settings import load_engine_settings


def selected_active_project(
    factory: dict[str, Any], projects_config: dict[str, Any]
) -> str:
    """Return the explicitly selected active project, or an empty string.

    The factory never picks a project by default; the owner must select one.

    Args:
        factory: Parsed ``factory`` configuration mapping.
        projects_config: Parsed ``config/projects.yaml`` mapping.

    Returns:
        The selected project name, or ``""`` when none is selected.
    """
    return str(
        factory.get("active_project")
        or projects_config.get("active_project")
        or ""
    ).strip()


def workbench_ready(project: dict[str, Any], root: Path) -> bool:
    """Report whether an active project's workbench directories exist.

    Args:
        project: Active project configuration mapping.
        root: Absolute repository root.

    Returns:
        ``True`` when the context, task, and report directories all exist.
    """
    for key in ("context_root", "task_root", "report_root"):
        value = project.get(key)
        if not value or not resolve_repo_path(str(value), root).is_dir():
            return False
    return True


def load_configuration(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load factory and project configuration files.

    Args:
        root: Absolute repository root.

    Returns:
        Tuple containing factory configuration and projects configuration.
    """
    engine = load_engine_settings(root)
    return (
        load_simple_yaml(engine["factory_config_template"], root),
        load_simple_yaml(engine["registry_path"], root),
    )


def validate_dry_run_settings(factory: dict[str, Any]) -> None:
    """Reject settings that exceed Phase 2 authority.

    Args:
        factory: Parsed ``factory`` configuration mapping.

    Raises:
        RuntimeError: If dry-run mode is disabled or a broad write capability
            is enabled.
    """
    mode = str(factory["mode"])
    if mode != "dry_run":
        raise RuntimeError(
            f"Validation advance refuses non-dry-run mode: {mode}"
        )
    if factory.get("allow_commit") or factory.get("allow_push"):
        raise RuntimeError(
            "Validation advance refuses enabled commit or push settings"
        )
    if factory.get("allow_application_writes") or factory.get(
        "allow_factory_writes"
    ):
        raise RuntimeError(
            "Validation advance refuses broad application or factory writes"
        )


def load_active_project(
    factory: dict[str, Any], projects_config: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Resolve the configured active project.

    Args:
        factory: Parsed ``factory`` configuration mapping.
        projects_config: Parsed ``config/projects.yaml`` mapping.

    Returns:
        Active project name and its configuration mapping.

    Raises:
        RuntimeError: If the configured project is missing or malformed.
    """
    project_name = str(
        factory.get("active_project") or projects_config["active_project"]
    )
    projects = projects_config["projects"]
    if not isinstance(projects, dict) or project_name not in projects:
        raise RuntimeError(f"Unknown active project: {project_name}")
    project = projects[project_name]
    if not isinstance(project, dict):
        raise RuntimeError(f"Invalid project configuration: {project_name}")
    return project_name, project
