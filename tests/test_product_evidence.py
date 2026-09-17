"""Behavioral product evidence: capability, not identifier lists."""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from conversation_delta import (
    STATUS_CLAIMED,
    STATUS_PENDING,
    STATUS_VERIFIED,
    append_delta,
    load_deltas,
    mark_deltas_claimed,
    refresh_delta_verification,
)
from product_evidence import (
    KIND_PERSISTENCE,
    KIND_RUNTIME,
    KIND_VISIBLE,
    evidence_kinds,
)
from product_intent import (
    fallback_capabilities,
    persist_intent,
    score_claims,
    unsatisfied_claims,
)
from prompt_compiler import compile_into_workbench

JOURNAL = '''\
"""Practice log — intentionally not a HabitStore / add_habit clone."""

from __future__ import annotations

import json
from datetime import date, timedelta
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "var" / "log.json"
ARCH = ROOT / "architecture.json"
MEMORY = False
ROWS: list[dict] = []


def _port() -> int:
    data = json.loads(ARCH.read_text(encoding="utf-8"))
    return int(data["listen_port"])


def _load() -> list[dict]:
    if MEMORY:
        return list(ROWS)
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


def _save(rows: list[dict]) -> None:
    if MEMORY:
        ROWS[:] = rows
        return
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(rows), encoding="utf-8")


def _run(ticks: list[str], today: date) -> int:
    days = sorted(
        {date.fromisoformat(item) for item in ticks if item <= today.isoformat()},
        reverse=True,
    )
    if not days or days[0] not in {today, today - timedelta(days=1)}:
        return 0
    length = 1
    for prev, nxt in zip(days, days[1:]):
        if prev - nxt == timedelta(days=1):
            length += 1
        else:
            break
    return length


def _week_table(ticks: list[str], today: date) -> str:
    start = today - timedelta(days=today.weekday())
    rows = ""
    for offset in range(7):
        day = start + timedelta(days=offset)
        iso = day.isoformat()
        mark = "yes" if iso in ticks else "no"
        rows += (
            f"<tr><th>{day.strftime('%A')}</th>"
            f"<td><time datetime='{iso}'>{iso}</time> {mark}</td></tr>"
        )
    return (
        "<section><h2>This week</h2><table>"
        + rows
        + "</table></section>"
    )


def _page(title: str, body: str) -> bytes:
    html = (
        "<!doctype html><html><head><title>"
        + escape(title)
        + "</title></head><body>"
        + f"<h1>{escape(title)}</h1>{body}</body></html>"
    )
    return html.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send(self, status: int, title: str, body: str) -> None:
        payload = _page(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        today = date.today()
        rows = _load()
        if path in ("/", "/entries"):
            items = ""
            for row in rows:
                run = _run(row["ticks"], today)
                items += (
                    f"<li><a href='/entries/{row['id']}'>{escape(row['title'])}"
                    f"</a> run: {run} days</li>"
                )
            week = _week_table(rows[0]["ticks"], today) if rows else ""
            body = (
                "<p>Practice log</p><ul>"
                + (items or "<li>empty</li>")
                + "</ul>"
                + week
                + '<section><h2>Register</h2>'
                '<form method="post" action="/entries">'
                '<label>Title</label>'
                '<input name="title" required>'
                "<button>Register</button></form></section>"
            )
            self._send(200, "Practice log", body)
            return
        parts = path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "entries":
            row = next((r for r in rows if r["id"] == parts[1]), None)
            if row is None:
                self._send(404, "Missing", "<p>nope</p>")
                return
            run = _run(row["ticks"], today)
            stamps = "".join(
                f"<li><time datetime='{d}'>{d}</time></li>"
                for d in row["ticks"]
            )
            body = (
                f"<p>run: {run} days</p>"
                + _week_table(row["ticks"], today)
                + '<form method="post" action="/entries/'
                + row["id"]
                + '/tick"><label>When</label>'
                '<input name="when" type="date" required>'
                "<button>Tick</button></form><ul>"
                + stamps
                + "</ul>"
            )
            self._send(200, row["title"], body)
            return
        self._send(404, "Missing", "<p>nope</p>")

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length", "0") or "0")
        fields = parse_qs(self.rfile.read(length).decode("utf-8"))
        rows = _load()
        parts = path.strip("/").split("/")
        if path == "/entries":
            title = (fields.get("title") or [""])[0].strip()
            row = {"id": uuid4().hex, "title": title, "ticks": []}
            rows.append(row)
            _save(rows)
            self._redirect("/entries/" + row["id"])
            return
        if len(parts) == 3 and parts[0] == "entries" and parts[2] == "tick":
            when = (fields.get("when") or [""])[0]
            for row in rows:
                if row["id"] == parts[1]:
                    if when not in row["ticks"]:
                        row["ticks"].append(when)
                    _save(rows)
                    self._redirect("/entries/" + row["id"])
                    return
            self._send(404, "Missing", "<p>nope</p>")
            return
        self._send(404, "Missing", "<p>nope</p>")


def main() -> None:
    server = HTTPServer(("127.0.0.1", _port()), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
'''


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _project(app: Path) -> dict[str, str]:
    tasks = app / "factory_tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    return {
        "name": app.name,
        "app_path": str(app),
        "task_root": str(tasks),
        "seed_file": "docs/seed.md",
    }


def _practice_app(app: Path, *, memory: bool = False) -> None:
    source = JOURNAL.replace("MEMORY = False", f"MEMORY = {memory}")
    _write(app / "src/__init__.py", "")
    _write(app / "src/journal.py", source)
    port = _free_port()
    _write(
        app / "architecture.json",
        json.dumps(
            {
                "start_command": "python3 -m src.journal",
                "listen_port": port,
                "required_files": ["src/journal.py"],
            }
        )
        + "\n",
    )


class EvidenceKindTests(unittest.TestCase):
    def test_habit_claims_prefer_runtime_not_symbols(self) -> None:
        caps = fallback_capabilities("build a habit tracker")
        kinds = {c.id: evidence_kinds(c) for c in caps}
        self.assertEqual(kinds["define_habits"], (KIND_RUNTIME,))
        self.assertEqual(kinds["persist_habits"], (KIND_PERSISTENCE,))
        self.assertFalse(caps[0].symbols)
        self.assertFalse(caps[0].files)

    def test_streak_delta_uses_visible_evidence(self) -> None:
        caps = fallback_capabilities("add a streak counter and a weekly view")
        kinds = {c.id: evidence_kinds(c) for c in caps}
        self.assertIn(KIND_VISIBLE, kinds["habit_streaks"])
        self.assertIn(KIND_VISIBLE, kinds["weekly_view"])
        self.assertNotIn("current_streak", caps[0].symbols)


class IdentifierBrittlenessTests(unittest.TestCase):
    def test_magic_names_do_not_satisfy_habit_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "habit"
            project = _project(app)
            compile_into_workbench(project, root, "build a habit tracker")
            _write(
                app / "src/habits.py",
                "habits = []\n"
                "def add_habit(name):\n"
                "    return name\n"
                "def complete_habit(habit_id, completed_on):\n"
                "    return completed_on\n"
                "def save_habits():\n"
                "    return load_habits()\n"
                "def load_habits():\n"
                "    return habits\n"
                "def current_streak(history):\n"
                "    return 0\n"
                "def weekly_view(history):\n"
                "    return []\n",
            )
            _write(
                app / "data/habits.json",
                json.dumps(
                    [
                        {
                            "name": "run",
                            "completed_on": "2026-09-16",
                            "current_streak": 1,
                            "week": "2026-W38",
                        }
                    ]
                )
                + "\n",
            )
            gaps = {c.id for c in unsatisfied_claims(project, root)}
            self.assertIn("define_habits", gaps)
            self.assertIn("persist_habits", gaps)


class AlternateImplementationTests(unittest.TestCase):
    def test_differently_named_app_satisfies_habit_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "practice"
            project = _project(app)
            _practice_app(app, memory=False)
            persist_intent(
                project,
                root,
                prompt="build a habit tracker with streaks and a weekly view",
                capabilities=fallback_capabilities(
                    "build a habit tracker with streaks and a weekly view"
                ),
                source="fallback",
                revision=1,
            )
            scores = {s.cap.id: s for s in score_claims(project, root)}
            self.assertTrue(
                scores["define_habits"].ok, scores["define_habits"].detail
            )
            self.assertEqual(scores["define_habits"].kind, KIND_RUNTIME)
            self.assertTrue(
                scores["dated_completion"].ok,
                scores["dated_completion"].detail,
            )
            self.assertTrue(
                scores["record_completion"].ok,
                scores["record_completion"].detail,
            )
            self.assertTrue(
                scores["persist_habits"].ok, scores["persist_habits"].detail
            )
            self.assertEqual(scores["persist_habits"].kind, KIND_PERSISTENCE)
            self.assertTrue(
                scores["habit_streaks"].ok, scores["habit_streaks"].detail
            )
            self.assertTrue(
                scores["weekly_view"].ok, scores["weekly_view"].detail
            )
            self.assertEqual(unsatisfied_claims(project, root), [])

    def test_memory_only_store_fails_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "volatile"
            project = _project(app)
            _practice_app(app, memory=True)
            persist_intent(
                project,
                root,
                prompt="build a habit tracker",
                capabilities=fallback_capabilities("build a habit tracker"),
                source="fallback",
                revision=1,
            )
            scores = {s.cap.id: s for s in score_claims(project, root)}
            self.assertTrue(
                scores["define_habits"].ok, scores["define_habits"].detail
            )
            self.assertFalse(scores["persist_habits"].ok)
            self.assertEqual(scores["persist_habits"].kind, KIND_PERSISTENCE)


class DeltaBehavioralTests(unittest.TestCase):
    def test_delta_verifies_when_streak_and_week_are_evidenced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "practice"
            project = _project(app)
            _practice_app(app, memory=False)
            persist_intent(
                project,
                root,
                prompt="build a habit tracker",
                capabilities=fallback_capabilities("build a habit tracker"),
                source="fallback",
                revision=1,
            )
            append_delta(
                project, root, "add a streak counter and a weekly view"
            )
            self.assertEqual(
                load_deltas(project, root)[0]["status"], STATUS_PENDING
            )
            mark_deltas_claimed(project, root)
            self.assertEqual(
                load_deltas(project, root)[0]["status"], STATUS_CLAIMED
            )
            refresh_delta_verification(project, root)
            self.assertEqual(
                load_deltas(project, root)[0]["status"], STATUS_VERIFIED
            )


if __name__ == "__main__":
    unittest.main()
