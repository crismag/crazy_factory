#!/usr/bin/env python3
"""Phase 9A context loader for Crazy Factory.

Collects the supported (AI-consumable) files recorded in a project's context
catalog and aggregates them into a single plain-text "context bundle" that the
planning roles include in their prompts. This is simple file aggregation: no
embeddings, no chunking, no semantic search, no ranking. The AI reads the raw
material and does all interpretation.

A volume guard bounds how much context is injected so a large import cannot
overflow the model context window: each file is already line-capped on read,
and the bundle is further bounded by a total file-count and byte budget. When
the budget is exceeded the loader includes what fits and reports exactly what
was dropped (never a silent truncation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from context_manager import load_catalog
from repo_tools import RepoSafetyError, safe_read_text

# Defaults bound how much imported context reaches a single prompt. The caller
# may override these from configuration.
DEFAULT_MAX_CONTEXT_FILES = 50
DEFAULT_MAX_CONTEXT_BYTES = 200_000


@dataclass
class ContextBundle:
    """An assembled context bundle and what it did (or could not) include.

    Attributes:
        text: The aggregated bundle text (empty when no context is available).
        included: Repository-relative paths included, in order.
        dropped: ``(path, reason)`` pairs for files excluded by the guard.
        total_bytes: Size of the assembled bundle text in bytes.
    """

    text: str = ""
    included: list[str] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)
    total_bytes: int = 0


def _supported_paths(catalog: dict[str, Any]) -> list[str]:
    """Return sorted repository-relative paths of supported catalog files."""
    paths = [
        str(entry.get("path", ""))
        for entry in (catalog.get("files") or {}).values()
        if bool(entry.get("supported")) and entry.get("path")
    ]
    return sorted(set(paths))


def load_context_bundle(
    root: Path,
    project: dict[str, Any],
    *,
    max_lines_per_file: int,
    max_files: int = DEFAULT_MAX_CONTEXT_FILES,
    max_total_bytes: int = DEFAULT_MAX_CONTEXT_BYTES,
) -> ContextBundle:
    """Build the imported-context bundle for a project's planning prompt.

    Args:
        root: Absolute repository root.
        project: Resolved project mapping.
        max_lines_per_file: Per-file line cap applied on read.
        max_files: Maximum number of files included in the bundle.
        max_total_bytes: Approximate byte budget for the assembled bundle.

    Returns:
        A :class:`ContextBundle`. ``text`` is empty when no supported context
        exists; ``dropped`` lists anything excluded by the guard or unreadable.
    """
    catalog = load_catalog(root, project)
    bundle = ContextBundle()
    chunks: list[str] = []

    for path in _supported_paths(catalog):
        if len(bundle.included) >= max_files:
            bundle.dropped.append((path, "file-count budget reached"))
            continue
        try:
            text = safe_read_text(path, root, max_lines_per_file)
        except (RepoSafetyError, UnicodeDecodeError, OSError) as exc:
            bundle.dropped.append((path, f"unreadable: {exc}"))
            continue
        chunk = f"===== {path} =====\n{text.rstrip()}\n"
        size = len(chunk.encode("utf-8"))
        # Always allow the first file through so a single large file still
        # contributes (already line-capped); only later files hit the budget.
        if bundle.included and bundle.total_bytes + size > max_total_bytes:
            bundle.dropped.append((path, "byte budget reached"))
            continue
        chunks.append(chunk)
        bundle.included.append(path)
        bundle.total_bytes += size

    if chunks:
        bundle.text = "Project Context\n\n" + "\n".join(chunks)
        bundle.total_bytes = len(bundle.text.encode("utf-8"))
    return bundle


def summarize_drops(bundle: ContextBundle) -> str:
    """Return a one-line human summary of any dropped context, or ``""``."""
    if not bundle.dropped:
        return ""
    reasons = ", ".join(f"{path} ({why})" for path, why in bundle.dropped)
    return f"Context guard dropped {len(bundle.dropped)} file(s): {reasons}"
