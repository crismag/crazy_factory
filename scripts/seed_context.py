#!/usr/bin/env python3
"""Phase 9 seed and project-context storage for Crazy Factory.

A project begins life as one small human-written seed document. This module
owns the on-disk layout under ``factory_state/projects/<project_id>/`` — the
seed, the ledger, and the growing ``contexts/`` chain — plus initialization
from a seed and reading recent artifacts back for the growth engine.

It writes only under ``factory_state``; it never touches application code,
git, or the existing pipeline's boundaries.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from context_ledger import (
    append_artifact,
    new_ledger,
    next_artifact_id,
    save_ledger,
)
from repo_tools import (
    RepoSafetyError,
    resolve_repo_path,
    safe_read_text,
    safe_write_text,
)

PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class SeedError(RuntimeError):
    """Raised when a seed or project id is missing or invalid."""


def validate_project_id(project_id: str) -> str:
    """Validate and return a safe project id.

    Args:
        project_id: Candidate identifier.

    Returns:
        The validated identifier.

    Raises:
        SeedError: If the id is not a safe lowercase slug.
    """
    if not PROJECT_ID_PATTERN.match(project_id or ""):
        raise SeedError(
            "project_id must match [a-z0-9][a-z0-9_-]* (no paths): "
            f"{project_id!r}"
        )
    return project_id


def project_root(project_id: str) -> str:
    """Return the repository-relative project root.

    Args:
        project_id: Validated project identifier.

    Returns:
        Repository-relative project directory.
    """
    return f"factory_state/projects/{project_id}"


def contexts_dir(project_id: str) -> str:
    """Return the repository-relative contexts directory for a project."""
    return f"{project_root(project_id)}/contexts"


# Sibling directories created at init for downstream use.
_SUBDIRS: tuple[str, ...] = (
    "contexts",
    "proposals",
    "contracts",
    "runs",
    "reflections",
)


def init_project(
    *, seed_path: str, project_id: str, root: Path
) -> dict[str, Any]:
    """Initialize a project's state from a seed document.

    Copies the seed into the project, seeds the contexts chain with
    ``000_seed.md``, and creates a fresh ledger recording that seed.

    Args:
        seed_path: Repository-relative path to the human seed document.
        project_id: Project identifier (validated).
        root: Absolute repository root.

    Returns:
        The newly created ledger.

    Raises:
        SeedError: If the id is invalid or the seed cannot be read.
    """
    validate_project_id(project_id)
    seed_target = resolve_repo_path(seed_path, root)
    if not seed_target.is_file():
        raise SeedError(f"Seed file not found: {seed_path}")
    seed_text = safe_read_text(seed_path, root)
    if not seed_text.strip():
        raise SeedError(f"Seed file is empty: {seed_path}")

    base = project_root(project_id)
    # Touch the sibling directories so the layout is visible from the start.
    for sub in _SUBDIRS:
        safe_write_text(
            f"{base}/{sub}/.gitkeep",
            "",
            repo_root=root,
            allowed_roots=["factory_state"],
        )
    safe_write_text(
        f"{base}/seed.md",
        seed_text,
        repo_root=root,
        allowed_roots=["factory_state"],
    )
    seed_artifact = f"{contexts_dir(project_id)}/000_seed.md"
    safe_write_text(
        seed_artifact,
        seed_text,
        repo_root=root,
        allowed_roots=["factory_state"],
    )

    ledger = new_ledger(project_id)
    append_artifact(
        ledger,
        artifact_id=next_artifact_id(ledger),
        artifact_type="seed",
        path=seed_artifact,
        summary="Initial project seed",
    )
    save_ledger(ledger, project_id, root)
    return ledger


def load_seed(project_id: str, root: Path) -> str:
    """Read a project's stored seed text.

    Args:
        project_id: Project identifier.
        root: Absolute repository root.

    Returns:
        The seed document text.

    Raises:
        SeedError: If the seed is missing.
    """
    relpath = f"{project_root(project_id)}/seed.md"
    if not resolve_repo_path(relpath, root).is_file():
        raise SeedError(f"No seed stored for project: {project_id}")
    return safe_read_text(relpath, root)


def recent_artifacts(
    ledger: dict[str, Any], root: Path, *, limit: int, max_chars: int = 1200
) -> list[tuple[str, str]]:
    """Read the most recent artifacts' types and (truncated) content.

    Args:
        ledger: Project ledger.
        root: Absolute repository root.
        limit: Maximum number of recent artifacts to read.
        max_chars: Maximum characters read from each artifact.

    Returns:
        List of ``(artifact_type, content)`` for the most recent artifacts,
        oldest first.
    """
    artifacts = ledger.get("artifacts", [])[-limit:]
    out: list[tuple[str, str]] = []
    for entry in artifacts:
        path = str(entry.get("path", ""))
        try:
            text = safe_read_text(path, root)[:max_chars]
        except (RepoSafetyError, OSError):
            # A missing or unreadable artifact is non-fatal for context.
            text = ""
        out.append((str(entry.get("type", "unknown")), text))
    return out
