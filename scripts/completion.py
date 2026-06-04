#!/usr/bin/env python3
"""Project completion engine for Crazy Factory.

A single advance builds one increment. On its own that never converges to a
finished app: nothing decomposes the goal into a checklist, nothing tracks which
requirements are done, and the planner has no view of what remains. This module
supplies that connective tissue so the loop can run beat after beat until the
whole project is built:

1. DECOMPOSE — turn the project goal/context into a persisted
   ``MASTER_CHECKLIST.md`` of concrete, verifiable requirements (once, when the
   checklist is missing or empty). AI-first, deterministic fallback.
2. FOCUS — surface the next OPEN item so the planner targets it (not "some small
   task from context").
3. TICK — when a fresh build applies and validates green, mark the worked item
   done.
4. SATISFIED — when no open items remain (and validation passed, no blocker),
   :mod:`satisfaction_checker` already declares the project satisfied and the
   mission loop stops.

This module is pure logic plus a bounded model call; the advance orchestrates
the I/O.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from json_parsing import coerce_str, strip_code_fence
from ollama_client import OllamaClient, OllamaConnectionError

CHECKLIST_FILENAME = "MASTER_CHECKLIST.md"
CHECKLIST_TITLE = "Master Checklist"
_MAX_ITEMS = 20
_OPEN_PREFIX = "- [ ]"
_DONE_PREFIXES = ("- [x]", "- [X]")
_BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*\S)\s*$")


@dataclass(frozen=True)
class ChecklistItem:
    """One checklist requirement.

    Attributes:
        text: The requirement text (without the ``- [ ]`` marker).
        done: Whether it has been completed.
    """

    text: str
    done: bool


def parse_checklist(markdown: str) -> list[ChecklistItem]:
    """Parse ``- [ ]`` / ``- [x]`` lines into checklist items (order kept)."""
    items: list[ChecklistItem] = []
    for line in (markdown or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(_OPEN_PREFIX):
            items.append(
                ChecklistItem(stripped[len(_OPEN_PREFIX) :].strip(), False)
            )
        elif stripped.startswith(_DONE_PREFIXES):
            items.append(ChecklistItem(stripped[len("- [x]") :].strip(), True))
    return items


def open_items(items: list[ChecklistItem]) -> list[ChecklistItem]:
    """Return the not-yet-done items."""
    return [item for item in items if not item.done]


def next_open_item(items: list[ChecklistItem]) -> ChecklistItem | None:
    """Return the first open item, or ``None`` when all are done."""
    pending = open_items(items)
    return pending[0] if pending else None


def is_complete(items: list[ChecklistItem]) -> bool:
    """True when there is at least one item and none remain open."""
    return bool(items) and not open_items(items)


def render_checklist(
    items: list[ChecklistItem], *, title: str = CHECKLIST_TITLE
) -> str:
    """Render items back to a Markdown checklist."""
    lines = [f"# {title}", ""]
    lines.extend(
        f"- [{'x' if item.done else ' '}] {item.text}" for item in items
    )
    return "\n".join(lines) + "\n"


def mark_first_open_done(markdown: str) -> tuple[str, str | None]:
    """Flip the first open item to done.

    Returns ``(updated_markdown, completed_text)``; ``completed_text`` is
    ``None`` (and the markdown is unchanged) when there is nothing open.
    """
    items = parse_checklist(markdown)
    for index, item in enumerate(items):
        if not item.done:
            items[index] = ChecklistItem(item.text, True)
            return render_checklist(items), item.text
    return markdown, None


def _dedupe(texts: list[str]) -> list[str]:
    """Order-preserving de-duplication, capped at ``_MAX_ITEMS``."""
    seen: set[str] = set()
    out: list[str] = []
    for text in texts:
        key = text.strip()
        if key and key.lower() not in seen:
            seen.add(key.lower())
            out.append(key)
        if len(out) >= _MAX_ITEMS:
            break
    return out


def synthesize_checklist(context_text: str) -> list[str]:
    """Deterministically derive checklist items from goal/context bullets.

    The AI-down fallback: pull bullet and numbered lines out of the goal text.
    It is intentionally simple; the AI path produces better-scoped items.
    """
    items: list[str] = []
    for line in (context_text or "").splitlines():
        match = _BULLET_RE.match(line)
        if not match:
            continue
        text = match.group(1).strip().rstrip(":")
        # Skip lines that are themselves checklist markers or section labels.
        if text.startswith(("[ ]", "[x]", "[X]")) or text.endswith(":"):
            continue
        items.append(text)
    return _dedupe(items)


def _request_ai_checklist(
    context_text: str,
    *,
    models_config: dict[str, Any],
    factory_config: dict[str, Any],
    retries: int,
) -> list[str] | None:
    """Ask a model to decompose the goal into requirements; ``None`` if down."""
    models = models_config.get("models", {})
    model = str(models.get("planner") or models.get("architect") or "")
    ollama = factory_config.get("ollama", {})
    if not model or not ollama:
        return None
    client = OllamaClient(
        base_url=str(ollama.get("base_url", "http://localhost:11434")),
        timeout_seconds=int(ollama.get("timeout_seconds", 120)),
        stream=bool(ollama.get("stream", False)),
    )
    instruction = (
        "You decompose a software project goal into a build checklist. Return "
        "ONLY a JSON array of short, concrete, INDEPENDENTLY VERIFIABLE "
        "requirement strings, ordered so earlier items are foundations for "
        "later ones (e.g. data model before storage before UI). Each item is "
        "one buildable+testable increment, not a vague theme. No prose, no "
        f"numbering, at most {_MAX_ITEMS} items."
    )
    messages = [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": f"## Project goal/context\n\n{context_text}",
        },
    ]
    for _ in range(max(1, retries)):
        try:
            response = client.chat(model, messages, response_format="json")
            content = str(response["message"]["content"]).strip()
            data = json.loads(strip_code_fence(content))
            if isinstance(data, dict):
                # Tolerate {"items": [...]} or {"checklist": [...]}.
                for key in ("items", "checklist", "requirements"):
                    if isinstance(data.get(key), list):
                        data = data[key]
                        break
            if isinstance(data, list):
                items = _dedupe([coerce_str(x) for x in data])
                if items:
                    return items
        except (
            KeyError,
            TypeError,
            ValueError,
            OllamaConnectionError,
            json.JSONDecodeError,
        ):
            continue
    return None


def build_checklist_items(
    context_text: str,
    *,
    models_config: dict[str, Any] | None = None,
    factory_config: dict[str, Any] | None = None,
    retries: int = 2,
) -> list[str]:
    """Decompose the goal into requirement strings (AI-first, then fallback).

    Always returns at least one item so the project has a definition of done.
    """
    ai = (
        _request_ai_checklist(
            context_text,
            models_config=models_config or {},
            factory_config=factory_config or {},
            retries=retries,
        )
        if models_config and factory_config
        else None
    )
    items = ai or synthesize_checklist(context_text)
    return items or [
        "Implement the project as described in the goal and make its tests pass."
    ]


def initial_checklist_markdown(
    context_text: str,
    *,
    models_config: dict[str, Any] | None = None,
    factory_config: dict[str, Any] | None = None,
) -> str:
    """Build a fresh ``MASTER_CHECKLIST.md`` body from the goal/context."""
    texts = build_checklist_items(
        context_text,
        models_config=models_config,
        factory_config=factory_config,
    )
    return render_checklist([ChecklistItem(text, False) for text in texts])


def checklist_focus(markdown: str) -> str:
    """Build the planner/coder focus block for the current checklist state.

    Names the single next OPEN item as the task to complete this beat, and lists
    the rest so the model sees the whole arc without drifting off it.
    """
    items = parse_checklist(markdown)
    if not items:
        return ""
    nxt = next_open_item(items)
    lines = ["## Build Checklist (project definition of done)"]
    if nxt is None:
        lines.append(
            "All checklist items are complete. Do not invent new work; the "
            "project is finished unless the owner adds requirements."
        )
    else:
        lines.append(
            "Plan and build ONLY the single next OPEN item below; later items "
            "are out of scope for this task."
        )
        lines.append(f"\n### Next open item (build this now)\n- {nxt.text}")
    lines.append("\n### Full checklist")
    lines.extend(
        f"- [{'x' if item.done else ' '}] {item.text}" for item in items
    )
    return "\n".join(lines) + "\n"


# coerce_str_list is imported for callers that pass already-listed items.
__all__ = [
    "CHECKLIST_FILENAME",
    "ChecklistItem",
    "build_checklist_items",
    "checklist_focus",
    "initial_checklist_markdown",
    "is_complete",
    "mark_first_open_done",
    "next_open_item",
    "open_items",
    "parse_checklist",
    "render_checklist",
    "synthesize_checklist",
]
