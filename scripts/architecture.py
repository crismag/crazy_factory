#!/usr/bin/env python3
"""Per-project architecture contract — deterministic coherence gates.

A project may declare an architecture contract at ``<workbench>/architecture.json``
that freezes its canonical structure and forbidden dependencies. The engine
reads it and enforces it generically; the contract content is project data, not
engine logic, so nothing here is specific to any one app.

The contract is the deterministic guardrail behind the v2 governance rule: a
task is complete only when the whole project still obeys the contract and
validates together — not because a file was written. Two gates use it:

- PATCH gate (before write): reject a patch that creates a file outside the
  canonical tree, in a forbidden directory, with a forbidden name, or whose
  content imports a forbidden dependency. Broken architecture never lands.
- COHERENCE gate (before a checklist tick / satisfaction): the whole project
  must compile, its tests pass, lint clean, and contain no forbidden
  files/imports.

Contract schema (all keys optional)::

    {
        "src_dirs": ["src"],
        "test_dirs": ["tests"],
        "extra_allowed": ["README.md", "data"],
        "forbidden_dirs": ["app", "migrations"],
        "forbidden_names": ["models.py", "*.db", "*.sqlite"],
        "forbidden_imports": ["sqlalchemy", "django", "flask", "fastapi"],
        "required_files": ["src/task_model.py", "tests/test_task_model.py"],
    }
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

CONTRACT_FILENAME = "architecture.json"
# Workbench dirs that are factory-managed, never application source.
_SKIP_DIRS = frozenset(
    {
        "config",
        "state",
        "factory_state",
        "factory_reports",
        "factory_tasks",
        "factory_context",
        "context",
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
    }
)


def load_contract(app_path: str) -> dict[str, Any] | None:
    """Load ``<workbench>/architecture.json``, or ``None`` when absent.

    Read directly from the workbench so it works for external (absolute) app
    paths too. A malformed contract is treated as absent (gates stay lenient).
    """
    path = Path(app_path) / CONTRACT_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _list(contract: dict[str, Any], key: str) -> list[str]:
    value = contract.get(key)
    return [str(v) for v in value] if isinstance(value, list) else []


def _allowed_tops(contract: dict[str, Any]) -> set[str]:
    """Top-level workbench names a path may live under/in."""
    return set(
        _list(contract, "src_dirs")
        + _list(contract, "test_dirs")
        + _list(contract, "extra_allowed")
    )


def _rel_parts(path: str) -> list[str]:
    """Normalize a workbench-relative path into its components."""
    return [p for p in Path(path.strip().lstrip("/")).parts if p not in (".",)]


def path_violations(paths: list[str], contract: dict[str, Any]) -> list[str]:
    """Return reasons a proposed path set violates the canonical tree.

    A path is rejected when its top-level component is a forbidden dir, its
    basename matches a forbidden name, or (when an allow-list is declared) it
    falls outside the allowed top-level names.
    """
    forbidden_dirs = set(_list(contract, "forbidden_dirs"))
    forbidden_names = _list(contract, "forbidden_names")
    allowed_tops = _allowed_tops(contract)
    reasons: list[str] = []
    for raw in paths:
        parts = _rel_parts(raw)
        if not parts:
            continue
        top, name = parts[0], parts[-1]
        if top in forbidden_dirs:
            reasons.append(f"{raw}: forbidden directory '{top}/'")
            continue
        if any(fnmatch.fnmatch(name, pat) for pat in forbidden_names):
            reasons.append(f"{raw}: forbidden file name '{name}'")
            continue
        if allowed_tops and top not in allowed_tops:
            reasons.append(
                f"{raw}: outside the canonical tree (allowed: "
                f"{', '.join(sorted(allowed_tops))})"
            )
    return reasons


def import_violations(content: str, contract: dict[str, Any]) -> list[str]:
    """Return forbidden-dependency markers found in file content."""
    lowered = (content or "").lower()
    return [
        marker
        for marker in _list(contract, "forbidden_imports")
        if marker.lower() in lowered
    ]


def patch_contract_violations(
    files: list[tuple[str, str]], contract: dict[str, Any]
) -> list[str]:
    """Validate proposed (path, content) pairs against the contract."""
    reasons = path_violations([p for p, _ in files], contract)
    for path, content in files:
        if path.endswith(".py"):
            hits = import_violations(content, contract)
            if hits:
                reasons.append(
                    f"{path}: forbidden dependency: {', '.join(hits)}"
                )
    return reasons


def _iter_source_files(app_path: str) -> list[Path]:
    base = Path(app_path)
    if not base.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if path.is_file():
            out.append(path)
    return out


def existing_violations(app_path: str, contract: dict[str, Any]) -> list[str]:
    """Scan the current workbench for real contract violations on disk.

    Flags only forbidden CONTENT the coder could have introduced: a forbidden
    directory holding a real file, a forbidden file name, or a forbidden import.
    The "outside the canonical tree" rule is intentionally NOT applied here — it
    is a patch-time rule; on disk the scaffold legitimately holds config, docs,
    and empty ``.gitkeep`` placeholders, which must not trip the gate.
    """
    base = Path(app_path)
    forbidden_dirs = set(_list(contract, "forbidden_dirs"))
    forbidden_names = _list(contract, "forbidden_names")
    reasons: list[str] = []
    for path in _iter_source_files(app_path):
        rel = path.relative_to(base)
        if rel.name == ".gitkeep":  # scaffold placeholder, not content
            continue
        if rel.parts[0] in forbidden_dirs:
            reasons.append(f"{rel}: in forbidden directory '{rel.parts[0]}/'")
            continue
        if any(fnmatch.fnmatch(rel.name, pat) for pat in forbidden_names):
            reasons.append(f"{rel}: forbidden file name '{rel.name}'")
            continue
        if path.suffix == ".py":
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            hits = import_violations(content, contract)
            if hits:
                reasons.append(
                    f"{rel}: forbidden dependency: {', '.join(hits)}"
                )
    return reasons


def missing_required(app_path: str, contract: dict[str, Any]) -> list[str]:
    """Return declared required files that do not yet exist (satisfaction)."""
    base = Path(app_path)
    return [
        rel
        for rel in _list(contract, "required_files")
        if not (base / rel).is_file()
    ]


# Markers emitted by path_violations / patch_contract_violations. A rejection
# carrying any of these means the work broke the architecture contract — i.e. a
# SELF_REJECTION when the factory itself produced that work upstream.
_CONFLICT_MARKERS = (
    "forbidden directory",
    "forbidden file name",
    "outside the canonical tree",
    "forbidden dependency",
)


def is_contract_conflict(reasons: list[str]) -> bool:
    """Whether any reason indicates an architecture-contract violation."""
    blob = " ".join(reasons).lower()
    return any(marker in blob for marker in _CONFLICT_MARKERS)


def render_contract_brief(contract: dict[str, Any]) -> str:
    """Render the contract as MANDATORY guidance for the coder/planner.

    The patch gate enforces these rules deterministically; telling the model up
    front lets it propose conforming files instead of being rejected in a loop.
    """
    allowed = sorted(_allowed_tops(contract))
    forbidden_dirs = _list(contract, "forbidden_dirs")
    forbidden_names = _list(contract, "forbidden_names")
    forbidden_imports = _list(contract, "forbidden_imports")
    required = _list(contract, "required_files")
    lines = [
        "## MANDATORY Architecture Contract "
        "(overrides any general path guidance)",
        "Proposals violating ANY rule below are rejected before they apply — "
        "conform exactly.",
    ]
    if allowed:
        lines.append(f"- Place files ONLY under: {', '.join(allowed)}")
    if forbidden_dirs:
        lines.append(
            f"- NEVER create these directories: {', '.join(forbidden_dirs)}"
        )
    if forbidden_names:
        lines.append(
            f"- NEVER create files named: {', '.join(forbidden_names)}"
        )
    if forbidden_imports:
        lines.append(
            f"- NEVER import these dependencies: {', '.join(forbidden_imports)}"
        )
    if required:
        lines.append(
            f"- The project's canonical files are: {', '.join(required)}"
        )
    return "\n".join(lines) + "\n"


def coherence_commands(app_path: str, contract: dict[str, Any]) -> list[str]:
    """Build the deterministic whole-project validation commands.

    Scoped to the contract's source/test dirs (those that exist), never narrow
    to a single file. Commands run from the workbench (the validation cwd).
    """
    base = Path(app_path)
    src = [d for d in _list(contract, "src_dirs") if (base / d).is_dir()]
    tests = [d for d in _list(contract, "test_dirs") if (base / d).is_dir()]
    dirs = src + tests
    if not dirs:
        return []
    joined = " ".join(dirs)
    commands = [f"python3 -m compileall -q {joined}"]
    if tests:
        commands.append(f"python3 -m pytest {' '.join(tests)}")
    commands.append(f"ruff check {joined}")
    return commands
