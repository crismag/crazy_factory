#!/usr/bin/env python3
"""Generate a previewable stdlib-web app from compiled intent.

The prompt compiler names the stack and start command. This module
writes a small Python 3 HTTP UI so the runtime observer can probe
``python3 -m src.app`` without a coding-plugin key. It is not the
task-board fixture and it does not emit npm.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PORT = 8765
COMPILE_FILE = "prompt_compile.json"


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def preview_meta(app: Path, seed: str) -> tuple[str, int]:
    """Return ``(title, listen_port)`` from compile record or architecture."""
    title = ""
    port = DEFAULT_PORT
    task = app / "factory_tasks" / COMPILE_FILE
    record = _load_json(task)
    if record.get("title"):
        title = str(record["title"]).strip()
    if isinstance(record.get("listen_port"), int):
        port = int(record["listen_port"])
    arch = _load_json(app / "architecture.json")
    if not title and arch.get("title"):
        title = str(arch["title"]).strip()
    raw_port = arch.get("listen_port")
    if isinstance(raw_port, int) and 1 <= raw_port <= 65535:
        port = raw_port
    if not title:
        for line in (seed or "").splitlines():
            low = line.strip()
            if low.lower().startswith("goal:"):
                continue
            if low and not low.startswith("#") and not low.startswith("-"):
                title = low[:80]
                break
    return (title or "App")[:80], port


def wants_stdlib_preview(app: Path, seed: str) -> bool:
    """True when this workbench is the default stdlib-web stack."""
    arch = _load_json(app / "architecture.json")
    stack = str(arch.get("stack") or "").strip().lower()
    start = str(arch.get("start_command") or "").strip()
    if stack == "stdlib-web":
        return True
    if start.startswith("python3 -m src.app"):
        return True
    text = (seed or "").lower()
    return "stdlib" in text and "python3 -m src.app" in text


def generate_stdlib_preview(app: Path, seed: str) -> dict[str, str]:
    """Return confined workbench files for a reachable HTML preview."""
    title, port = preview_meta(app, seed)
    title_lit = json.dumps(title)
    return {
        "src/__init__.py": "",
        "src/model.py": _MODEL,
        "src/app.py": _APP.replace("__TITLE__", title_lit).replace(
            "__PORT__", str(port)
        ),
        "tests/test_model.py": _TEST_MODEL,
        "tests/test_app.py": _TEST_APP,
        "data/items.json": "[]\n",
        "data/change_requests.json": "[]\n",
        "requirements.txt": "# Python 3 standard library only\n",
        "README.md": (
            f"# {title}\n\n"
            f"Start with `python3 -m src.app` (port {port}).\n"
        ),
    }


_MODEL = '''"""JSON item store for the stdlib-web preview app."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "items.json"


def list_items(path: Path = DATA_PATH) -> list[dict]:
    """Return persisted items, or [] if missing/corrupt."""
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def save_items(items: list[dict], path: Path = DATA_PATH) -> None:
    """Write items as JSON, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2) + "\\n", encoding="utf-8")


def add_item(title: str, path: Path = DATA_PATH) -> dict:
    """Append a new item and persist it."""
    items = list_items(path)
    item = {
        "id": uuid4().hex[:8],
        "title": title.strip() or "Untitled",
        "done": False,
    }
    items.append(item)
    save_items(items, path)
    return item


def update_item(
    item_id: str, title: str, path: Path = DATA_PATH
) -> dict | None:
    """Rename an item. Returns the updated item, or None if missing."""
    items = list_items(path)
    for item in items:
        if str(item.get("id")) == item_id:
            item["title"] = title.strip() or str(item.get("title") or "")
            save_items(items, path)
            return item
    return None


def toggle_item(item_id: str, path: Path = DATA_PATH) -> dict | None:
    """Toggle an item's done flag."""
    items = list_items(path)
    for item in items:
        if str(item.get("id")) == item_id:
            item["done"] = not bool(item.get("done"))
            save_items(items, path)
            return item
    return None


def delete_item(item_id: str, path: Path = DATA_PATH) -> bool:
    """Remove an item. True when something was deleted."""
    items = list_items(path)
    kept = [item for item in items if str(item.get("id")) != item_id]
    if len(kept) == len(items):
        return False
    save_items(kept, path)
    return True
'''

_APP = '''"""Stdlib-web preview application."""

from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from src.model import (
    add_item,
    delete_item,
    list_items,
    toggle_item,
    update_item,
)

TITLE = __TITLE__
DEFAULT_PORT = __PORT__
ROOT = Path(__file__).resolve().parents[1]
CHANGE_PATH = ROOT / "data" / "change_requests.json"


def load_change_requests(path: Path = CHANGE_PATH) -> list[str]:
    """Return owner follow-up prompts persisted beside the item store."""
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]
    return []


def render_index(items: list[dict]) -> str:
    """Return a narrow-viewport HTML UI for the item list."""
    heading = html.escape(TITLE)
    requests = load_change_requests()
    banner = ""
    if requests:
        items_html = "".join(
            f"<li>{html.escape(req)}</li>" for req in requests[-5:]
        )
        banner = (
            "<aside class='owner-deltas'><!-- owner-deltas -->"
            "<p>Requested changes</p>"
            f"<ul>{items_html}</ul>"
            "<!-- /owner-deltas --></aside>"
        )
    rows: list[str] = []
    for item in items:
        iid = html.escape(str(item.get("id") or ""))
        name = html.escape(str(item.get("title") or ""))
        done = bool(item.get("done"))
        mark = "Undo" if done else "Done"
        css = "item done" if done else "item"
        rows.append(
            f'<li class="{css}">'
            f'<form method="post" action="/toggle">'
            f'<input type="hidden" name="id" value="{iid}"/>'
            f'<button type="submit">{mark}</button>'
            f"</form>"
            f'<form method="post" action="/edit">'
            f'<input type="hidden" name="id" value="{iid}"/>'
            f'<input name="title" value="{name}" required/>'
            f'<button type="submit">Save</button>'
            f"</form>"
            f'<form method="post" action="/delete">'
            f'<input type="hidden" name="id" value="{iid}"/>'
            f'<button type="submit">Delete</button>'
            f"</form>"
            f"</li>"
        )
    body = "\\n".join(rows) or "<li class='empty'>Nothing yet.</li>"
    return (
        "<!doctype html><html lang='en'><head>"
        "<meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        f"<title>{heading}</title>"
        "<style>"
        "body{font:16px/1.4 system-ui,sans-serif;margin:0;padding:12px;"
        "max-width:40rem;}"
        "h1{font-size:1.25rem;margin:0 0 12px;}"
        "form{display:flex;gap:8px;flex-wrap:wrap;margin:0;}"
        "input[name=title]{flex:1 1 10rem;min-width:8rem;}"
        "ul{list-style:none;padding:0;margin:12px 0;}"
        "li.item{display:flex;flex-direction:column;gap:8px;"
        "border:1px solid #ccc;padding:8px;margin:0 0 8px;}"
        "li.done input[name=title]{text-decoration:line-through;}"
        "button{min-height:2rem;}"
        "aside.owner-deltas{border:1px dashed #888;padding:8px;"
        "margin:0 0 12px;font-size:0.9rem;}"
        "</style></head><body>"
        f"<h1>{heading}</h1>"
        f"{banner}"
        "<form method='post' action='/add'>"
        "<input name='title' placeholder='New item' required/>"
        "<button type='submit'>Add</button>"
        "</form>"
        f"<ul>{body}</ul>"
        "</body></html>"
    )


class PreviewHandler(BaseHTTPRequestHandler):
    """Tiny POST/GET front for the JSON store."""

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _redirect(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def do_GET(self) -> None:
        page = render_index(list_items())
        blob = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        fields = {k: v[0] for k, v in parse_qs(raw).items() if v}
        path = self.path.split("?", 1)[0]
        if path == "/add":
            add_item(fields.get("title") or "")
        elif path == "/edit":
            update_item(fields.get("id") or "", fields.get("title") or "")
        elif path == "/toggle":
            toggle_item(fields.get("id") or "")
        elif path == "/delete":
            delete_item(fields.get("id") or "")
        self._redirect()


def serve(port: int = DEFAULT_PORT) -> None:
    """Serve the UI on 127.0.0.1 (runtime observer probes this)."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), PreviewHandler)
    httpd.serve_forever()


if __name__ == "__main__":
    serve()
'''

_TEST_MODEL = '''"""CRUD tests for the stdlib-web preview store."""

from pathlib import Path

from src.model import add_item, delete_item, list_items, update_item


def test_crud_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "items.json"
    item = add_item("alpha", path)
    assert list_items(path)[0]["title"] == "alpha"
    updated = update_item(item["id"], "beta", path)
    assert updated is not None
    assert updated["title"] == "beta"
    assert delete_item(item["id"], path) is True
    assert list_items(path) == []
'''

_TEST_APP = '''"""UI smoke tests for the stdlib-web preview."""

from src.app import TITLE, render_index


def test_index_includes_title() -> None:
    page = render_index([])
    assert TITLE in page
    assert "New item" in page
'''
