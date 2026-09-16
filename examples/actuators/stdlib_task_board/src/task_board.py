"""Stdlib task-board web application."""

from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "tasks.json"
DEFAULT_PORT = 8765


def load_tasks(path: Path = DATA_PATH) -> list[dict]:
    """Return persisted tasks, or [] if missing/corrupt."""
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def save_tasks(tasks: list[dict], path: Path = DATA_PATH) -> None:
    """Write tasks as JSON, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(tasks, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def add_task(title: str, path: Path = DATA_PATH) -> dict:
    """Append a new open task and persist it."""
    tasks = load_tasks(path)
    task = {
        "id": uuid4().hex[:8],
        "title": title.strip() or "Untitled",
        "done": False,
    }
    tasks.append(task)
    save_tasks(tasks, path)
    return task


def edit_task(task_id: str, title: str, path: Path = DATA_PATH) -> dict | None:
    """Rename a task. Returns the updated task, or None if missing."""
    tasks = load_tasks(path)
    for task in tasks:
        if str(task.get("id")) == task_id:
            task["title"] = title.strip() or str(task.get("title") or "")
            save_tasks(tasks, path)
            return task
    return None


def complete_task(task_id: str, path: Path = DATA_PATH) -> dict | None:
    """Toggle a task's done flag."""
    tasks = load_tasks(path)
    for task in tasks:
        if str(task.get("id")) == task_id:
            task["done"] = not bool(task.get("done"))
            save_tasks(tasks, path)
            return task
    return None


def delete_task(task_id: str, path: Path = DATA_PATH) -> bool:
    """Remove a task. True when something was deleted."""
    tasks = load_tasks(path)
    kept = [task for task in tasks if str(task.get("id")) != task_id]
    if len(kept) == len(tasks):
        return False
    save_tasks(kept, path)
    return True


def render_index(tasks: list[dict]) -> str:
    """Return a narrow-viewport HTML UI for the task list."""
    rows: list[str] = []
    for task in tasks:
        tid = html.escape(str(task.get("id") or ""))
        title = html.escape(str(task.get("title") or ""))
        done = bool(task.get("done"))
        mark = "Undo" if done else "Complete"
        css = "task done" if done else "task"
        rows.append(
            f'<li class="{css}">'
            f'<form method="post" action="/complete">'
            f'<input type="hidden" name="id" value="{tid}"/>'
            f'<button type="submit">{mark}</button>'
            f"</form>"
            f'<form method="post" action="/edit">'
            f'<input type="hidden" name="id" value="{tid}"/>'
            f'<input name="title" value="{title}" required/>'
            f'<button type="submit">Save</button>'
            f"</form>"
            f'<form method="post" action="/delete">'
            f'<input type="hidden" name="id" value="{tid}"/>'
            f'<button type="submit">Delete</button>'
            f"</form>"
            f"</li>"
        )
    body = "\n".join(rows) or "<li class='empty'>No tasks yet.</li>"
    return (
        "<!doctype html><html lang='en'><head>"
        "<meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        "<title>Task board</title>"
        "<style>"
        "body{font:16px/1.4 system-ui,sans-serif;margin:0;padding:12px;"
        "max-width:40rem;}"
        "h1{font-size:1.25rem;margin:0 0 12px;}"
        "form{display:flex;gap:8px;flex-wrap:wrap;margin:0;}"
        "input[name=title]{flex:1 1 10rem;min-width:8rem;}"
        "ul{list-style:none;padding:0;margin:12px 0;}"
        "li.task{display:flex;flex-direction:column;gap:8px;"
        "border:1px solid #ccc;padding:8px;margin:0 0 8px;}"
        "li.done input[name=title]{text-decoration:line-through;}"
        "button{min-height:2rem;}"
        "</style></head><body>"
        "<h1>Task board</h1>"
        "<form method='post' action='/add'>"
        "<input name='title' placeholder='New task' required/>"
        "<button type='submit'>Add</button>"
        "</form>"
        f"<ul>{body}</ul>"
        "</body></html>"
    )


class TaskBoardHandler(BaseHTTPRequestHandler):
    """Tiny POST/GET front for the JSON store."""

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _redirect(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        page = render_index(load_tasks())
        blob = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        fields = {k: v[0] for k, v in parse_qs(raw).items() if v}
        path = self.path.split("?", 1)[0]
        if path == "/add":
            add_task(fields.get("title") or "")
        elif path == "/edit":
            edit_task(fields.get("id") or "", fields.get("title") or "")
        elif path == "/complete":
            complete_task(fields.get("id") or "")
        elif path == "/delete":
            delete_task(fields.get("id") or "")
        self._redirect()


def serve(port: int = DEFAULT_PORT) -> None:
    """Serve the UI on 127.0.0.1 (runtime observer probes this)."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), TaskBoardHandler)
    httpd.serve_forever()


if __name__ == "__main__":
    serve()
