#!/usr/bin/env python3
"""Workbench growth metrics + code-birth gating (Issue #38).

A software factory that produces no software has failed — even when every
internal review completed. This module is the deterministic **rail + observability**
for that truth (per the governing principle: scripts measure and gate, the LLM
authors the code):

- It counts what actually exists in the workbench (real source/test files, not
  ``.gitkeep`` placeholders or factory runtime).
- It answers the one question every report must: *did the workbench grow?*
- It defines the **code-birth** gate: while a project is greenfield (no real
  code yet), only the deterministic safety/syntax floor may reject a patch —
  the **completeness/acceptance review is deferred** so the first scaffold can
  land and real validation (pytest) can take over. A project cannot be judged
  incomplete before it has been allowed to exist.

It writes nothing and authors no code; it inspects the workbench and returns
facts the caller acts on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Workbench directories that are factory-managed runtime, never app product.
_RUNTIME_DIRS = frozenset(
    {
        "config",
        "state",
        "factory_state",
        "factory_reports",
        "factory_tasks",
        "factory_context",
        "context",
        "docs",
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
    }
)
def _is_test_file(rel: Path) -> bool:
    name = rel.name.lower()
    return (
        name.endswith(".py")
        and (name.startswith("test_") or name[:-3].endswith("_test"))
    ) or "tests" in rel.parts


def _is_real_source(path: Path) -> bool:
    """A non-empty Python file (a ``.gitkeep`` / empty stub is not product)."""
    if path.suffix != ".py":
        return False
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeDecodeError):
        return False


def _iter_product_files(app_path: str) -> list[Path]:
    """All non-runtime files in the workbench, relative paths."""
    base = Path(app_path)
    if not base.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base)
        if any(part in _RUNTIME_DIRS for part in rel.parts):
            continue
        if rel.name == ".gitkeep":
            continue
        out.append(rel)
    return out


@dataclass(frozen=True)
class WorkbenchMetrics:
    """A deterministic snapshot of what product code exists in the workbench."""

    source_files: int
    test_files: int
    non_gitkeep_files: int
    lines_of_code: int

    @property
    def has_real_code(self) -> bool:
        """True once at least one real source AND one real test file exist —
        the Minimum Viable Code Birth condition (Issue #38)."""
        return self.source_files >= 1 and self.test_files >= 1

    @property
    def is_greenfield(self) -> bool:
        """True while no real product code exists yet (only placeholders)."""
        return self.source_files == 0 and self.test_files == 0


def workbench_metrics(app_path: str) -> WorkbenchMetrics:
    """Count real source/test files (and LOC) in the workbench, deterministically.

    Excludes factory runtime dirs, ``.gitkeep`` placeholders, and empty files —
    so the counts reflect actual product, not scaffolding noise.
    """
    files = _iter_product_files(app_path)
    base = Path(app_path)
    source = test = loc = 0
    for rel in files:
        abs_path = base / rel
        if not _is_real_source(abs_path):
            continue
        try:
            loc += len(abs_path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError):
            pass
        if _is_test_file(rel):
            test += 1
        else:
            source += 1
    return WorkbenchMetrics(
        source_files=source,
        test_files=test,
        non_gitkeep_files=len(files),
        lines_of_code=loc,
    )


def is_code_birth_pending(app_path: str) -> bool:
    """True when the workbench has no real source code yet (greenfield).

    The completeness/acceptance review must be DEFERRED while this holds, so the
    first scaffold can land instead of being rejected for incompleteness before
    any code exists (Issue #38, capabilities #1–#3, #6, #9).
    """
    return workbench_metrics(app_path).source_files == 0
