#!/usr/bin/env python3
"""Conversational deltas on a specified product.

A follow-up owner prompt is a change request, not a new product.
Goal and architecture stay put. Each delta has a lifecycle:

    PENDING → CLAIMED → VERIFIED
              ↘ BLOCKED

Only VERIFIED deltas may contribute to COMPLETE. A new PENDING
delta increments the product intent revision so prior acceptance
is stale. Banner HTML is owner-visible, never verification.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from product_intent import (
    bump_revision,
    fallback_capabilities,
    persist_acceptance,
    unsatisfied_claims,
)
from prompt_compiler import SEED_REL, needs_compile

DELTA_FILE = "deltas.jsonl"
DELTA_STATE = "deltas.json"
DELTA_DOC = "docs/deltas.md"
CHANGE_FILE = "data/change_requests.json"
MAX_PROMPT = 4000
BANNER_START = "<!-- owner-deltas -->"
BANNER_END = "<!-- /owner-deltas -->"

STATUS_PENDING = "PENDING"
STATUS_CLAIMED = "CLAIMED"
STATUS_VERIFIED = "VERIFIED"
STATUS_BLOCKED = "BLOCKED"
OPEN_STATUSES = frozenset({STATUS_PENDING, STATUS_CLAIMED})


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


def _normalize(entry: dict[str, Any]) -> dict[str, Any] | None:
    prompt = str(entry.get("prompt") or "").strip()
    if not prompt:
        return None
    status = str(entry.get("status") or STATUS_PENDING).upper()
    if status not in {
        STATUS_PENDING,
        STATUS_CLAIMED,
        STATUS_VERIFIED,
        STATUS_BLOCKED,
    }:
        status = STATUS_PENDING
    cap_raw = entry.get("capabilities")
    capabilities: list[dict[str, Any]] = []
    if isinstance(cap_raw, list):
        capabilities = [c for c in cap_raw if isinstance(c, dict)]
    return {
        "id": str(entry.get("id") or ""),
        "at": str(entry.get("at") or ""),
        "prompt": prompt,
        "status": status,
        "intent_revision": int(entry.get("intent_revision") or 0),
        "capabilities": capabilities,
    }


def load_deltas(project: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    """Return persisted follow-up records, oldest first."""
    task = _task_dir(project, root)
    state_path = task / DELTA_STATE
    if state_path.is_file():
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, list):
            entries = [_normalize(e) for e in raw if isinstance(e, dict)]
            return [e for e in entries if e]
    path = task / DELTA_FILE
    try:
        body = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    entries: list[dict[str, Any]] = []
    for line in body.splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        item = _normalize(data)
        if item:
            entries.append(item)
    return entries


def latest_delta(project: dict[str, Any], root: Path) -> str:
    """Return the most recent follow-up prompt, or empty."""
    entries = load_deltas(project, root)
    if not entries:
        return ""
    return str(entries[-1]["prompt"])


def delta_prompts(project: dict[str, Any], root: Path) -> list[str]:
    """Prompts only, oldest first."""
    return [str(entry["prompt"]) for entry in load_deltas(project, root)]


def open_deltas(project: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    """Deltas that are not VERIFIED or BLOCKED."""
    return [
        entry
        for entry in load_deltas(project, root)
        if entry["status"] in OPEN_STATUSES
    ]


def _save_state(
    project: dict[str, Any], root: Path, entries: list[dict[str, Any]]
) -> None:
    task = _task_dir(project, root)
    task.mkdir(parents=True, exist_ok=True)
    (task / DELTA_STATE).write_text(
        json.dumps(entries, indent=2) + "\n", encoding="utf-8"
    )


def _render_delta_doc(entries: list[dict[str, Any]]) -> str:
    lines = [
        "# Owner deltas",
        "",
        "Follow-up requests after the product was specified.",
        "These do not replace the Goal.",
        "",
    ]
    for entry in entries:
        stamp = entry.get("at") or "undated"
        status = entry.get("status") or STATUS_PENDING
        lines.append(f"- [{status}] {stamp}: {entry['prompt']}")
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
    left alone — writing that file is enough. Banner text is not
    product evidence.
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
    entries = load_deltas(project, root)
    delta_id = f"delta-{len(entries) + 1}"
    caps = fallback_capabilities(text, origin=delta_id)
    rev = bump_revision(project, root, caps)
    entry = {
        "id": delta_id,
        "at": stamp,
        "prompt": text,
        "status": STATUS_PENDING,
        "intent_revision": rev,
        "capabilities": [asdict(c) for c in caps],
    }
    entries.append(entry)
    app = _app_dir(project, root)
    task_root = _task_dir(project, root)
    task_root.mkdir(parents=True, exist_ok=True)
    jsonl = task_root / DELTA_FILE
    with jsonl.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
    _save_state(project, root, entries)
    doc = app / DELTA_DOC
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(_render_delta_doc(entries), encoding="utf-8")
    change_path = app / CHANGE_FILE
    change_path.parent.mkdir(parents=True, exist_ok=True)
    prompts = [str(item["prompt"]) for item in entries]
    change_path.write_text(
        json.dumps(prompts, indent=2) + "\n", encoding="utf-8"
    )
    inject_preview_banner(app, prompts)
    persist_acceptance(
        project,
        root,
        {
            "intent_revision": rev,
            "accepted_revision": None,
            "stale": True,
            "reason": f"owner delta {delta_id} invalidated prior acceptance",
        },
    )
    return {
        "delta": str(jsonl),
        "state": str(task_root / DELTA_STATE),
        "doc": str(doc),
        "changes": str(change_path),
    }


def mark_deltas_claimed(project: dict[str, Any], root: Path) -> None:
    """An execute beat attempted the open deltas. Not VERIFIED."""
    entries = load_deltas(project, root)
    changed = False
    for entry in entries:
        if entry["status"] == STATUS_PENDING:
            entry["status"] = STATUS_CLAIMED
            changed = True
    if changed:
        _save_state(project, root, entries)
        app = _app_dir(project, root)
        (app / DELTA_DOC).write_text(
            _render_delta_doc(entries), encoding="utf-8"
        )


def refresh_delta_verification(
    project: dict[str, Any], root: Path
) -> list[dict[str, Any]]:
    """Promote CLAIMED/PENDING to VERIFIED only when probes pass."""
    entries = load_deltas(project, root)
    if not entries:
        return entries
    unsatisfied_ids = {cap.id for cap in unsatisfied_claims(project, root)}
    changed = False
    for entry in entries:
        if entry["status"] not in OPEN_STATUSES:
            continue
        own_ids = [
            str(item.get("id") or "")
            for item in (entry.get("capabilities") or [])
            if isinstance(item, dict)
        ]
        own_ids = [i for i in own_ids if i]
        if not own_ids:
            continue
        if any(cap_id in unsatisfied_ids for cap_id in own_ids):
            continue
        entry["status"] = STATUS_VERIFIED
        changed = True
    if changed:
        _save_state(project, root, entries)
        app = _app_dir(project, root)
        doc = app / DELTA_DOC
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(_render_delta_doc(entries), encoding="utf-8")
    return entries
