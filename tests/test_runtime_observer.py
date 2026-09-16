"""P1 workbench runtime observer tests (no Ollama)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from runtime_observer import (  # noqa: E402
    confine_start,
    discover_start,
    observe_runtime,
    persist_runtime,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class DiscoverTests(unittest.TestCase):
    def test_reads_architecture_start_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "start_command": "python3 -m src.task_board",
                        "listen_port": 8000,
                    }
                ),
            )
            argv, port = discover_start(app)
            self.assertEqual(argv, ["python3", "-m", "src.task_board"])
            self.assertEqual(port, 8000)

    def test_readme_backticks_when_no_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            _write(app / "README.md", "Start with `python3 -m src.server`.\n")
            argv, port = discover_start(app)
            self.assertEqual(argv, ["python3", "-m", "src.server"])
            self.assertIsNone(port)


class ConfineTests(unittest.TestCase):
    def test_missing_module_is_not_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            verdict, reason = confine_start(
                ["python3", "-m", "src.task_board"], app
            )
            self.assertEqual(verdict, "missing")
            self.assertIn("task_board", reason)

    def test_rejects_python_c_and_pip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            self.assertEqual(
                confine_start(["python3", "-c", "print(1)"], app)[0],
                "unsafe",
            )
            self.assertEqual(
                confine_start(["python3", "-m", "pip", "install", "x"], app)[
                    0
                ],
                "unsafe",
            )
            self.assertEqual(
                confine_start(["npm", "start"], app)[0],
                "unsafe",
            )

    def test_accepts_workbench_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            _write(app / "src/task_board.py", "VALUE = 1\n")
            verdict, reason = confine_start(
                ["python3", "-m", "src.task_board"], app
            )
            self.assertEqual(verdict, "ok", reason)


class ObserveTests(unittest.TestCase):
    def test_unspecified_start_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            report = observe_runtime(app)
            self.assertFalse(report.required)
            self.assertTrue(report.ok)
            self.assertEqual(report.status, "unspecified")

    def test_cli_module_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            _write(app / "src/cli.py", "print('hello')\n")
            _write(
                app / "architecture.json",
                json.dumps({"start_command": "python3 -m src.cli"}),
            )
            report = observe_runtime(app)
            self.assertTrue(report.ok, report.reason)
            self.assertEqual(report.status, "exited")

    def test_http_server_is_probed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            port = 18765
            _write(
                app / "src/tiny_http.py",
                "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
                "\n"
                "class H(BaseHTTPRequestHandler):\n"
                "    def do_GET(self):\n"
                "        self.send_response(200)\n"
                "        self.end_headers()\n"
                "        self.wfile.write(b'ok')\n"
                "    def log_message(self, *args):\n"
                "        pass\n"
                "\n"
                "if __name__ == '__main__':\n"
                f"    HTTPServer(('127.0.0.1', {port}), H).serve_forever()\n",
            )
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "start_command": "python3 -m src.tiny_http",
                        "listen_port": port,
                    }
                ),
            )
            report = observe_runtime(app)
            self.assertTrue(report.ok, report.reason)
            self.assertEqual(report.status, "running")
            self.assertEqual(report.http_status, 200)

    def test_persist_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            tasks = app / "factory_tasks"
            report = observe_runtime(app)
            path = persist_runtime(report, tasks)
            self.assertTrue(path.is_file())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "unspecified")
            preview = json.loads(
                (tasks / "preview.json").read_text(encoding="utf-8")
            )
            self.assertIsNone(preview["url"])
            self.assertFalse(preview["ok"])
