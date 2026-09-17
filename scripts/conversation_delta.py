#!/usr/bin/env python3
"""Conversational deltas on a specified product.

A follow-up owner prompt is a change request, not a new product.
This module appends the request, leaves Goal/architecture alone, and
surfaces the latest deltas to the coding assignment and (when the
stdlib preview exists) to the HTTP page so a no-key run still shows
what the owner asked for next.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prompt_compiler import SEED_REL, needs_compile

DELTA_FILE = "deltas.jsonl"
DELTA_DOC = "docs/deltas.md"
CHANGE_FILE = "data/change_requests.json"
MAX_PROMPT = 4000
BANNER_START = "<!-- owner-deltas -->"
BANNER_END = "<!-- /owner-deltas -->"


def _app_dir(project: dict[str, Any], root: Path) -> Path:
    path = Path(str(project["app_path"]))
    return path if path.is_absolute() else (root / path)


def _task_dir(project: dict[str, Any], root: Path) -> Path:
    raw = project.get("task_root") or "factory_tasks"
    path = Path(str(raw))
    return path if path.is_absolute() else (root / path)


def _seed_text(project: dict[str, Any], root: Path) -> str:
    app = _app_dir(project, root)
    rel = str(project.get("seed_file") or SEED_REL)
    try:
        return (app / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def has_specified_product(project: dict[str, Any], root: Path) -> bool:
    """True when the workbench seed already has Goal + Success."""
    text = _seed_text(project, root).strip()
    if not text:
        return False
    return not needs_compile(text)


def load_deltas(project: dict[str, Any], root: Path) -> list[dict[str, str]]:
    """Return persisted follow-up prompts, oldest first."""
    path = _task_dir(project, root) / DELTA_FILE
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    entries: list[dict[str, str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            continue
        entries.append(
            {
                "at": str(data.get("at") or ""),
                "prompt": prompt,
            }
        )
    return entries


def latest_delta(project: dict[str, Any], root: Path) -> str:
    """Return the most recent follow-up prompt, or empty."""
    entries = load_deltas(project, root)
    if not entries:
        return ""
    return entries[-1]["prompt"]


def delta_prompts(project: dict[str, Any], root: Path) -> list[str]:
    """Prompts only, oldest first."""
    return [entry["prompt"] for entry in load_deltas(project, root)]


def _render_delta_doc(entries: list[dict[str, str]]) -> str:
    lines = [
        "# Owner deltas",
        "",
        "Follow-up requests after the product was specified.",
        "These do not replace the Goal.",
        "",
    ]
    for entry in entries:
        stamp = entry["at"] or "undated"
        lines.append(f"- {stamp}: {entry['prompt']}")
    return "\n".join(lines) + "\n"


def render_banner_html(prompts: list[str]) -> str:
    """HTML snippet a stdlib preview can embed after the heading."""
    if not prompts:
        return (
            f"<aside class='owner-deltas'>{BANNER_START}"
            f"{BANNER_END}</aside>"
        )
    items = "".join(
        f"<li>{html.escape(text)}</li>" for text in prompts[-5:]
    )
    return (
        f"<aside class='owner-deltas'>{BANNER_START}"
        "<p>Requested changes</p>"
        f"<ul>{items}</ul>"
        f"{BANNER_END}</aside>"
    )


def inject_preview_banner(app: Path, prompts: list[str]) -> bool:
    """Patch a pre-L0-05 ``src/app.py`` so HTTP shows the follow-up.

    Generated previews that already load ``change_requests.json`` are
    left alone — writing that file is enough.
    """
    path = app / "src" / "app.py"
    if not path.is_file():
        return False
    try:
        body = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if "load_change_requests" in body:
        return False
    banner = render_banner_html(prompts)
    safe = banner.replace("\\", "").replace('"', "&quot;")
    if BANNER_START in body and BANNER_END in body:
        inner_start = body.index(BANNER_START) + len(BANNER_START)
        inner_end = body.index(BANNER_END)
        inner = ""
        if prompts:
            items = "".join(
                f"<li>{html.escape(text)}</li>" for text in prompts[-5:]
            )
            inner = f"<p>Requested changes</p><ul>{items}</ul>"
        path.write_text(
            body[:inner_start] + inner + body[inner_end:],
            encoding="utf-8",
        )
        return True
    needle = "</h1>"
    if needle not in body:
        return False
    cut = body.find("\n", body.index(needle))
    if cut < 0:
        cut = len(body)
    insertion = f'\n        "{safe}"'
    path.write_text(body[:cut] + insertion + body[cut:], encoding="utf-8")
    return True


def append_delta(
    project: dict[str, Any],
    root: Path,
    prompt: str,
) -> dict[str, str]:
    """Persist a follow-up prompt. Does not rewrite the seed."""
    text = (prompt or "").strip()[:MAX_PROMPT]
    if not text:
        return {}
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {"at": stamp, "prompt": text}
    app = _app_dir(project, root)
    task_root = _task_dir(project, root)
    task_root.mkdir(parents=True, exist_ok=True)
    jsonl = task_root / DELTA_FILE
    with jsonl.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
    entries = load_deltas(project, root)
    prompts = [item["prompt"] for item in entries]
    doc = app / DELTA_DOC
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(_render_delta_doc(entries), encoding="utf-8")
    change_path = app / CHANGE_FILE
    change_path.parent.mkdir(parents=True, exist_ok=True)
    change_path.write_text(
        json.dumps(prompts, indent=2) + "\n", encoding="utf-8"
    )
    inject_preview_banner(app, prompts)
    return {
        "delta": str(jsonl),
        "doc": str(doc),
        "changes": str(change_path),
    }
