#!/usr/bin/env python3
"""Default web stacks Crazy Factory knows how to target.

Lovable-style generation needs one opinionated previewable stack, not
every framework. ``stdlib-web`` is the first default because the
runtime observer, validation allowlist, and path confinement already
understand ``python3 -m …`` and a localhost HTTP probe.

``vite-react`` is the recorded successor (npm allowlist + confined
dev server). It is not executable yet — do not emit npm start
commands until that slice lands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WebStack:
    """One opinionated application shape."""

    id: str
    title: str
    start_command: str
    listen_port: int
    required_files: tuple[str, ...]
    constraints: tuple[str, ...]
    extra_allowed: tuple[str, ...]
    forbidden_imports: tuple[str, ...]
    executable: bool
    notes: str


STDLIB_WEB = WebStack(
    id="stdlib-web",
    title="Python stdlib web (HTML/CSS/JS, JSON file persistence)",
    start_command="python3 -m src.app",
    listen_port=8765,
    required_files=(
        "src/__init__.py",
        "src/app.py",
        "src/model.py",
        "tests/test_model.py",
        "tests/test_app.py",
        "README.md",
        "architecture.json",
        "requirements.txt",
    ),
    constraints=(
        "Python 3 standard library only (http.server, pathlib, json).",
        "No npm, no frameworks, no database server.",
        "Persist application data as JSON under data/.",
        "Keep the implementation small and testable.",
        "Serve a usable HTML UI on localhost.",
    ),
    extra_allowed=(
        "README.md",
        "data",
        "docs",
        "architecture.json",
        "crazy_project.yaml",
        "requirements.txt",
    ),
    forbidden_imports=(
        "sqlalchemy",
        "django",
        "flask",
        "fastapi",
        "react",
    ),
    executable=True,
    notes=(
        "Matches today's runtime observer and validation floor. "
        "First Lovable-style default."
    ),
)

VITE_REACT = WebStack(
    id="vite-react",
    title="Vite + React (preview successor)",
    start_command="python3 -m src.app",
    listen_port=5173,
    required_files=(),
    constraints=(
        "Not executable in this factory yet: npm is not allowlisted.",
    ),
    extra_allowed=(),
    forbidden_imports=(),
    executable=False,
    notes=(
        "Lovable-like SPA preview. Next stack after npm install/start "
        "are confined the same way python3 -m is today."
    ),
)

STACKS: dict[str, WebStack] = {
    STDLIB_WEB.id: STDLIB_WEB,
    VITE_REACT.id: VITE_REACT,
}

DEFAULT_STACK_ID = STDLIB_WEB.id
NEXT_STACK_ID = VITE_REACT.id


def default_stack() -> WebStack:
    return STACKS[DEFAULT_STACK_ID]


def resolve_stack(name: str | None) -> WebStack:
    """Return a known stack; unknown names fall back to the default."""
    key = (name or "").strip().lower()
    stack = STACKS.get(key)
    if stack is None or not stack.executable:
        return default_stack()
    return stack


def stack_record(stack: WebStack) -> dict[str, Any]:
    return {
        "id": stack.id,
        "title": stack.title,
        "executable": stack.executable,
        "notes": stack.notes,
        "next": NEXT_STACK_ID,
    }
