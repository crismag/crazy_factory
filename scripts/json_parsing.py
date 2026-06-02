#!/usr/bin/env python3
"""Tolerant, safety-conscious helpers for parsing local-model JSON output.

These helpers are shared by every module that turns a local model's JSON into
structured records (task contracts, coder proposals). They are deliberately
conservative: nested objects and arrays are discarded rather than ``repr``-ed,
so a malformed structure surfaces as missing content and is rejected by a
validator instead of passing as garbage. Keeping a single implementation here
prevents the hardened coercion rules from drifting between callers.
"""

from __future__ import annotations

from typing import Any


def strip_code_fence(raw: str) -> str:
    """Remove a surrounding Markdown code fence if present.

    Local models frequently wrap JSON in ```` ```json ```` fences. Stripping a
    single outer fence keeps the parser tolerant without interpreting content.

    Args:
        raw: Raw model output.

    Returns:
        Text with one outer code fence removed when detected.
    """
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    # Drop the opening fence line (e.g. "```" or "```json").
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def coerce_str(value: Any) -> str:
    """Coerce a JSON scalar to a trimmed string.

    Only genuine scalars (str, int, float, bool) become text. Objects and
    arrays are discarded to an empty string rather than ``repr``-ed, so a
    nested structure in a text field surfaces as missing content and is
    rejected by the validator instead of passing as garbage.

    Args:
        value: Arbitrary parsed JSON value.

    Returns:
        Stripped string, or an empty string for ``None`` or non-scalar values.
    """
    # ``bool`` is intentionally covered here via its ``int`` subclass.
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def coerce_str_list(value: Any) -> list[str]:
    """Coerce a JSON value into a list of non-empty scalar strings.

    A single string is wrapped as a one-item list so loosely structured model
    output still parses. Empty entries and non-scalar elements (nested objects
    or arrays) are dropped, so validation can rely on list length to mean "has
    real, usable content".

    Args:
        value: Arbitrary parsed JSON value.

    Returns:
        List of trimmed, non-empty strings.
    """
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        items = [coerce_str(item) for item in value]
        return [item for item in items if item]
    # A lone scalar (number/bool) becomes a single descriptive entry; objects
    # and null coerce to an empty string and yield an empty list.
    text = coerce_str(value)
    return [text] if text else []
