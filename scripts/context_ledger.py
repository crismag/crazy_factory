#!/usr/bin/env python3
"""Phase 9 context ledger for Crazy Factory.

The ledger is a small JSON index of the context artifacts a project has grown
from its seed. It records, in order, each artifact's id, type, path, and a one-
line summary, plus how many grow cycles have run. It is the durable memory the
growth engine reads to decide what is missing and what to build next.

The ledger never holds artifact content — only pointers — so the growing chain
stays inspectable as plain files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from repo_tools import resolve_repo_path, safe_load_json, safe_write_json


class LedgerError(RuntimeError):
    """Raised when a project ledger is missing or malformed."""


def new_ledger(project_id: str) -> dict[str, Any]:
    """Create an empty ledger for a project.

    Args:
        project_id: Stable project identifier.

    Returns:
        A fresh ledger mapping with no artifacts.
    """
    return {"project_id": project_id, "current_cycle": 0, "artifacts": []}


def append_artifact(
    ledger: dict[str, Any],
    *,
    artifact_id: str,
    artifact_type: str,
    path: str,
    summary: str,
) -> None:
    """Append one artifact record to the ledger in place.

    Args:
        ledger: Ledger mapping to update.
        artifact_id: Zero-padded sequential id (e.g. ``"001"``).
        artifact_type: Artifact type label (e.g. ``"observation"``).
        path: Repository-relative artifact path.
        summary: One-line human-readable summary.
    """
    artifacts = ledger.setdefault("artifacts", [])
    artifacts.append(
        {
            "id": artifact_id,
            "type": artifact_type,
            "path": path,
            "summary": summary,
        }
    )


def next_artifact_id(ledger: dict[str, Any]) -> str:
    """Return the next zero-padded sequential artifact id.

    Args:
        ledger: Ledger mapping.

    Returns:
        The next id as a 3-digit string.
    """
    return f"{len(ledger.get('artifacts', [])):03d}"


def ledger_path(project_id: str) -> str:
    """Return the repository-relative ledger path for a project.

    Args:
        project_id: Stable project identifier.

    Returns:
        Repository-relative ``context_ledger.json`` path.
    """
    return f"factory_state/projects/{project_id}/context_ledger.json"


def load_ledger(project_id: str, root: Path) -> dict[str, Any]:
    """Load a project's ledger.

    Args:
        project_id: Stable project identifier.
        root: Absolute repository root.

    Returns:
        The parsed ledger mapping.

    Raises:
        LedgerError: If the ledger is missing or not a valid object.
    """
    relpath = ledger_path(project_id)
    if not resolve_repo_path(relpath, root).is_file():
        raise LedgerError(f"No context ledger for project: {project_id}")
    try:
        return safe_load_json(relpath, root)
    except ValueError as exc:
        raise LedgerError(f"Malformed ledger for {project_id}: {exc}") from exc


def save_ledger(ledger: dict[str, Any], project_id: str, root: Path) -> None:
    """Persist a project's ledger.

    Args:
        ledger: Ledger mapping to write.
        project_id: Stable project identifier.
        root: Absolute repository root.
    """
    safe_write_json(
        ledger_path(project_id),
        ledger,
        repo_root=root,
        allowed_roots=["factory_state"],
    )
