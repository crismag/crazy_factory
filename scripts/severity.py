#!/usr/bin/env python3
"""Severity policy for gate findings (Phase 9E.S0).

A finding's *type* — not a blanket pass/fail — decides whether it blocks, gets
auto-fixed, or is just noted. Lint/style/guideline issues are SOFT (fix or warn)
and must never cripple flow; only the safety floor and genuine direction
divergence are HARD blocks.

This module is a small, deterministic **policy utility** (per the governing
principle: scripts are rails, not a brain). It maps a finding string to a tier;
gates consult it instead of treating every reason as fatal. The defaults live
here for now; 9E.S0c will externalize them to owner-editable config.
"""

from __future__ import annotations

import re

# Tiers, lowest → highest severity.
INFO = "info"
WARN = "warn"
FIX = "fix"
BLOCK = "block"

_ORDER: dict[str, int] = {INFO: 0, WARN: 1, FIX: 2, BLOCK: 3}

# HARD — the safety floor + unrunnable code + direction divergence. These block.
_BLOCK_MARKERS: tuple[str, ...] = (
    "syntax error",  # unrunnable; cannot apply
    "escapes",  # path escape
    "outside the project",
    "outside the workbench",
    "secret",
    "credential",
    "password",
    "private key",
    "api key",
    "token",
    " push",
    "force push",
    "merge",
    "reset --hard",
    "rm -rf",
    "sudo",
    "history rewrite",
    "forbidden",  # forbidden dir/name/import (incl. forbidden tech)
    "self-authoriz",
    "placeholder function body",  # a stub is not real code; do not apply
    "no content provided",
    "does not match the approved proposal",
)

# FIX — deterministically auto-repairable (the autofix skill handles these).
_FIX_MARKERS: tuple[str, ...] = (
    "unused import",
    "import order",
    "unsorted import",
    "trailing whitespace",
    "blank line",
    "line too long",
    "missing newline",
    "would reformat",
)
# Ruff codes that are safe auto-fixes (F401 unused import, I001 import sort, …).
_FIX_CODE_RE = re.compile(r"\b(f401|i001|w29\d|w605|e7?0\d)\b")


def severity_of(reason: str) -> str:
    """Classify one finding string into a severity tier.

    Order matters: BLOCK (floor/unrunnable) wins, then FIX (auto-repairable);
    anything else is a soft WARN (non-critical / guideline) — never a hard stop.
    """
    low = reason.lower()
    if any(marker in low for marker in _BLOCK_MARKERS):
        return BLOCK
    if any(marker in low for marker in _FIX_MARKERS) or _FIX_CODE_RE.search(
        low
    ):
        return FIX
    return WARN


def classify_reasons(reasons: list[str]) -> dict[str, list[str]]:
    """Bucket findings by tier: ``{block:[...], fix:[...], warn:[...]}``."""
    buckets: dict[str, list[str]] = {BLOCK: [], FIX: [], WARN: [], INFO: []}
    for reason in reasons:
        buckets[severity_of(reason)].append(reason)
    return buckets


def overall_severity(reasons: list[str]) -> str:
    """Highest tier among the findings (``info`` when there are none)."""
    if not reasons:
        return INFO
    return max((severity_of(r) for r in reasons), key=lambda t: _ORDER[t])


def is_blocking(reasons: list[str]) -> bool:
    """True only when at least one finding is BLOCK-tier (a hard stop)."""
    return any(severity_of(r) == BLOCK for r in reasons)
