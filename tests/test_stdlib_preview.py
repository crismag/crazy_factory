"""L0-04 stdlib-web preview: generated app answers HTTP."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_executor import (  # noqa: E402
    ExecutorRequest,
    StdlibWebExecutor,
)
from prompt_compiler import compile_into_workbench, compile_prompt
from runtime_observer import observe_runtime, persist_runtime, preview_record
from stdlib_preview import generate_stdlib_preview, wants_stdlib_preview

TASK_BOARD_SEED = (ROOT / "examples/seeds/task_board_web.md").read_text(
    encoding="utf-8"
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _request(
    app: Path, seed: str, kind: str = "code_birth"
) -> ExecutorRequest:
    return ExecutorRequest(
        objective_id="obj-1",
        objective_kind=kind,
        objective_title="Birth the preview",
        gap="no source yet",
        why="need a reachable HTTP UI",
        focus="src/app.py",
        seed_text=seed,
        app_path=str(app),
    )


class GeneratePreviewTests(unittest.TestCase):
    def test_compiled_habit_prompt_is_a_preview_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "apps" / "habit"
            app.mkdir(parents=True)
            project = {
                "name": "habit",
                "app_path": str(app),
                "task_root": str(app / "factory_tasks"),
            }
            compile_into_workbench(
                project, Path(tmp), "build a habit tracker"
            )
            self.assertTrue(wants_stdlib_preview(app, ""))
            seed = (app / "docs/seed.md").read_text(encoding="utf-8")
            files = generate_stdlib_preview(app, seed)
            self.assertIn("src/app.py", files)
            self.assertIn("python3 -m src.app", files["README.md"])
            for rel, body in files.items():
                _write(app / rel, body)
            report = observe_runtime(app)
            self.assertTrue(report.ok, report.reason)
            self.assertEqual(report.status, "running")
            self.assertEqual(report.http_status, 200)
            preview = preview_record(report)
            self.assertTrue(preview["ok"])
            self.assertEqual(preview["url"], "http://127.0.0.1:8765/")

    def test_executor_writes_preview_not_task_board(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            (app / "factory_tasks").mkdir(parents=True)
            product = compile_prompt("build a notes app")
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "stack": "stdlib-web",
                        "start_command": "python3 -m src.app",
                        "listen_port": 18766,
                        "source": "prompt-compiler",
                        "title": product.title,
                    }
                ),
            )
            _write(app / "docs/seed.md", "Goal:\nNotes.\n\nSuccess:\nShip.\n")
            out = StdlibWebExecutor().execute(
                _request(app, (app / "docs/seed.md").read_text())
            )
            self.assertTrue(out.ok, out.reason)
            self.assertIn("src/app.py", out.files)
            self.assertNotIn("src/task_board.py", out.files)
            self.assertIn("18766", out.files["src/app.py"])

    def test_task_board_seed_still_uses_fixture(self) -> None:
        out = StdlibWebExecutor().execute(
            _request(Path("/tmp"), TASK_BOARD_SEED)
        )
        self.assertTrue(out.ok, out.reason)
        self.assertIn("src/task_board.py", out.files)

    def test_does_not_clobber_existing_app_on_implement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "stack": "stdlib-web",
                        "start_command": "python3 -m src.app",
                    }
                ),
            )
            _write(app / "src/app.py", "TITLE = 'mine'\n")
            out = StdlibWebExecutor().execute(
                _request(app, "build notes", kind="implement")
            )
            self.assertFalse(out.ok)
            self.assertEqual(out.reason, "preview already present")
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "TITLE = 'mine'\n",
            )

    def test_persist_preview_json_on_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            tasks = app / "factory_tasks"
            product = compile_prompt("build a habit tracker")
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "stack": "stdlib-web",
                        "start_command": "python3 -m src.app",
                        "listen_port": 18767,
                        "title": product.title,
                    }
                ),
            )
            files = generate_stdlib_preview(app, product.goal)
            for rel, body in files.items():
                _write(app / rel, body)
            report = observe_runtime(app)
            persist_runtime(report, tasks)
            preview = json.loads(
                (tasks / "preview.json").read_text(encoding="utf-8")
            )
            self.assertEqual(preview["url"], "http://127.0.0.1:18767/")
            self.assertTrue(preview["ok"], preview)
