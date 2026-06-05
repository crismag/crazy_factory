#!/usr/bin/env python3
"""Skill library — bounded, deterministic repair utilities (Phase 9E.S1).

Per the governing principle (scripts are *utility + bounded controls*, not a
brain): skills are small, deterministic, safety-bounded operations the factory
(and later the adjudicator) can invoke to **fix** rather than reject. This first
slice ships the repair skill that unblocks the empty-app failure — auto-fixing
safe lint (e.g. the `unused import 'Optional'` that rejected a whole 5-file
patch) instead of treating it as a hard rejection.

Each skill is content-in / content-out (no filesystem writes here; the apply
stage writes, gated as before). Skills never relax the safety floor.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

_RUFF_TIMEOUT_SECONDS = 15
# Ruff rules that are SAFE to auto-apply (no semantic change): unused imports,
# import sorting, pyflakes/format-level fixes. Kept narrow on purpose.
_SAFE_FIX_SELECT = "F401,F811,I001,W291,W293,W605"


@dataclass(frozen=True)
class SkillResult:
    """Outcome of a content skill: the (possibly) transformed content + note."""

    content: str
    changed: bool
    detail: str


def autofix_lint(content: str, *, path: str = "file.py") -> SkillResult:
    """Deterministically auto-fix safe lint in Python source via ``ruff --fix``.

    Reads ``content`` on stdin, returns ruff's fixed source. Safe-only fixes
    (unused imports, import order, …). On any failure (ruff missing, timeout,
    empty output) the original content is returned unchanged — degrade, never
    corrupt.
    """
    if not content.strip():
        return SkillResult(content, False, "empty content; nothing to fix")
    try:
        completed = subprocess.run(
            [
                "ruff",
                "check",
                "--fix",
                "--select",
                _SAFE_FIX_SELECT,
                "--stdin-filename",
                path,
                "-",
            ],
            input=content,
            capture_output=True,
            text=True,
            timeout=_RUFF_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return SkillResult(content, False, f"ruff unavailable: {exc}")
    fixed = completed.stdout
    if fixed and fixed != content:
        return SkillResult(fixed, True, "ruff --fix applied safe lint fixes")
    return SkillResult(content, False, "no auto-fixable lint")
