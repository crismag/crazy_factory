#!/usr/bin/env python3
"""Advisory pattern library (orchestration Slice 5).

Archetypes, feature patterns, UX patterns, and references live in a
Factory-owned catalog. Search is deterministic token overlap.

Patterns do not schedule work, do not verify claims, do not override
owner intent or architecture, and do not fetch remote repositories.
Task expansion may *read* these entries in a later slice.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

KIND_ARCHETYPE = "archetype"
KIND_FEATURE = "feature"
KIND_UX = "ux"
KIND_REFERENCE = "reference"
KINDS = frozenset(
    {KIND_ARCHETYPE, KIND_FEATURE, KIND_UX, KIND_REFERENCE}
)
AUTHORITY = "advisory"
CATALOG_REL = "factory/patterns/catalog.json"
REPO_ROOT = Path(__file__).resolve().parents[1]
_WORD = re.compile(r"[a-z0-9]{3,}")


@dataclass(frozen=True)
class PatternEntry:
    """One catalog row. Every field has a search or later-packet consumer."""

    pattern_id: str
    kind: str
    title: str
    summary: str
    tags: tuple[str, ...] = ()
    applies_to: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    authority: str = AUTHORITY


@dataclass(frozen=True)
class PatternHit:
    """Ranked search result. Score is overlap only, not quality."""

    entry: PatternEntry
    score: int
    matched: tuple[str, ...] = ()


def catalog_path(root: Path | None = None) -> Path:
    return Path(root or REPO_ROOT).resolve() / CATALOG_REL


def _tuple_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip()
    return (text,) if text else ()


def entry_from_dict(raw: dict[str, Any]) -> PatternEntry | None:
    pattern_id = str(raw.get("pattern_id") or "").strip()
    kind = str(raw.get("kind") or "").strip().lower()
    title = str(raw.get("title") or "").strip()
    if not pattern_id or kind not in KINDS or not title:
        return None
    return PatternEntry(
        pattern_id=pattern_id,
        kind=kind,
        title=title,
        summary=str(raw.get("summary") or "").strip(),
        tags=_tuple_str(raw.get("tags")),
        applies_to=_tuple_str(raw.get("applies_to")),
        source_refs=_tuple_str(raw.get("source_refs")),
        authority=AUTHORITY,
    )


def load_catalog(root: Path | None = None) -> tuple[PatternEntry, ...]:
    """Load the Factory catalog. Missing/invalid → empty, never a crash."""
    path = catalog_path(root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ()
    if not isinstance(raw, dict):
        return ()
    rows = raw.get("patterns")
    if not isinstance(rows, list):
        return ()
    entries: list[PatternEntry] = []
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        entry = entry_from_dict(item)
        if entry is None or entry.pattern_id in seen:
            continue
        seen.add(entry.pattern_id)
        entries.append(entry)
    return tuple(entries)


def _tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower().replace("-", " ").replace("_", " "))


def _score(entry: PatternEntry, needles: list[str]) -> tuple[int, tuple[str, ...]]:
    if not needles:
        return 0, ()
    hay = {
        "id": _tokens(entry.pattern_id),
        "tag": _tokens(" ".join(entry.tags)),
        "title": _tokens(entry.title),
        "summary": _tokens(entry.summary),
        "applies": _tokens(" ".join(entry.applies_to)),
    }
    score = 0
    matched: list[str] = []
    for word in needles:
        hit = False
        if word in hay["id"] or word in hay["tag"]:
            score += 3
            hit = True
        if word in hay["title"]:
            score += 2
            hit = True
        if word in hay["summary"] or word in hay["applies"]:
            score += 1
            hit = True
        if hit:
            matched.append(word)
    return score, tuple(matched)


def search_patterns(
    query: str,
    *,
    root: Path | None = None,
    kind: str | None = None,
    applies_to: str | None = None,
    limit: int = 16,
    catalog: tuple[PatternEntry, ...] | None = None,
) -> list[PatternHit]:
    """Deterministic overlap search. Empty query lists by id (capped)."""
    entries = catalog if catalog is not None else load_catalog(root)
    kind_key = str(kind or "").strip().lower()
    apply_key = str(applies_to or "").strip().lower()
    filtered: list[PatternEntry] = []
    for entry in entries:
        if kind_key and entry.kind != kind_key:
            continue
        if apply_key and apply_key not in {item.lower() for item in entry.applies_to}:
            continue
        filtered.append(entry)
    needles = _tokens(query)
    if not needles:
        hits = [PatternHit(entry=item, score=0) for item in filtered]
        return hits[: max(0, int(limit))]
    ranked: list[PatternHit] = []
    for entry in filtered:
        score, matched = _score(entry, needles)
        if score <= 0:
            continue
        ranked.append(PatternHit(entry=entry, score=score, matched=matched))
    ranked.sort(key=lambda hit: (-hit.score, hit.entry.pattern_id))
    return ranked[: max(0, int(limit))]


def match_for_intent(
    prompt: str,
    *,
    stack_id: str | None = None,
    root: Path | None = None,
    limit: int = 6,
) -> list[PatternHit]:
    """Convenience search for a later packet slice. Advisory only."""
    query = " ".join(part for part in (prompt, stack_id) if part)
    return search_patterns(
        query,
        root=root,
        limit=limit,
    )


def hit_to_dict(hit: PatternHit) -> dict[str, Any]:
    payload = asdict(hit.entry)
    payload["score"] = hit.score
    payload["matched"] = list(hit.matched)
    return payload


def render_hits(hits: list[PatternHit]) -> str:
    if not hits:
        return "No advisory patterns matched.\n"
    lines = ["Advisory patterns (do not override owner intent or architecture):", ""]
    for hit in hits:
        entry = hit.entry
        lines.append(
            f"- `{entry.pattern_id}` [{entry.kind}] {entry.title}"
        )
        if hit.score:
            lines.append(f"  score={hit.score} matched={','.join(hit.matched)}")
        if entry.summary:
            lines.append(f"  {entry.summary}")
        if entry.source_refs:
            lines.append("  refs: " + ", ".join(entry.source_refs))
    lines.append("")
    return "\n".join(lines)
