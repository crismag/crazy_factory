"""P2 execute-objective generator tests (no Ollama)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from objective_generator import (  # noqa: E402
    KIND_CODE_BIRTH,
    KIND_REPAIR_PROGRESS,
    KIND_REPAIR_RUNTIME,
    KIND_REPAIR_VALIDATION,
    MODULE_FILE,
    load_focus_module,
    load_objective,
    next_execute_objective,
    persist_objective,
    progress_repair_objective,
    render_objective_focus,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(app: Path) -> dict[str, object]:
    return {
        "name": "demo",
        "app_path": str(app),
        "task_root": str(app / "factory_tasks"),
        "factory_state_dir": str(app / "factory_state"),
        "context_root": str(app / "factory_context"),
        "state_dir": str(app / "state"),
        "seed_file": "docs/seed.md",
    }


class GeneratorTests(unittest.TestCase):
    def test_greenfield_is_code_birth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(
                app / "docs/seed.md",
                "Goal:\nBuild a todo tracker.\n\nSuccess:\nAdd tasks.\n",
            )
            obj = next_execute_objective(_project(app), Path(tmp))
            self.assertEqual(obj.kind, KIND_CODE_BIRTH)
            self.assertIn("ZERO_CODE", obj.gap)

    def test_runtime_failure_outranks_greenfield(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(
                app / "factory_tasks/runtime_result.json",
                json.dumps(
                    {
                        "required": True,
                        "ok": False,
                        "safe": True,
                        "reason": (
                            "module src.task_board is not in the workbench"
                        ),
                        "status": "missing",
                    }
                ),
            )
            obj = next_execute_objective(_project(app), Path(tmp))
            self.assertEqual(obj.kind, KIND_REPAIR_RUNTIME)
            self.assertIn("task_board", obj.gap)

    def test_validation_failure_becomes_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(
                app / "factory_tasks/validation_result.json",
                json.dumps(
                    {
                        "status": "failed",
                        "checks": [
                            {
                                "command": "python3 -m pytest",
                                "status": "failed",
                            }
                        ],
                    }
                ),
            )
            obj = next_execute_objective(_project(app), Path(tmp))
            self.assertEqual(obj.kind, KIND_REPAIR_VALIDATION)
            self.assertIn("pytest", obj.gap)

    def test_persist_and_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks = Path(tmp) / "factory_tasks"
            obj = progress_repair_objective("5 silent beats")
            self.assertEqual(obj.kind, KIND_REPAIR_PROGRESS)
            path = persist_objective(obj, tasks)
            loaded = load_objective(tasks)
            assert loaded is not None
            self.assertEqual(loaded.id, obj.id)
            text = render_objective_focus(loaded)
            self.assertIn("Current execute objective", text)
            self.assertIn("OBJ-PROGRESS", text)
            self.assertTrue(path.is_file())

    def test_unsafe_runtime_outranks_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            tasks = app / "factory_tasks"
            _write(
                tasks / "runtime_result.json",
                json.dumps(
                    {
                        "required": True,
                        "ok": False,
                        "safe": False,
                        "reason": "start command uses python3 -c",
                    }
                ),
            )
            _write(
                tasks / "validation_result.json",
                json.dumps({"status": "failed", "checks": []}),
            )
            obj = next_execute_objective(_project(app), Path(tmp))
            self.assertEqual(obj.kind, KIND_REPAIR_RUNTIME)
            self.assertEqual(obj.id, "OBJ-RUNTIME-UNSAFE")


class NestedModuleLoopTests(unittest.TestCase):
    def test_execute_stays_on_first_open_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(
                app / "docs/seed.md",
                "Goal:\nBuild a todo tracker.\n\nSuccess:\nAdd tasks.\n",
            )
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "required_files": [
                            "src/todo.py",
                            "src/storage.py",
                            "tests/test_todo.py",
                            "tests/test_storage.py",
                        ]
                    }
                ),
            )
            _write(app / "src/todo.py", "def add(item):\n    return item\n")
            _write(
                app / "src/storage.py",
                "def save_data(data):\n    pass\n",
            )
            obj = next_execute_objective(_project(app), Path(tmp))
            self.assertEqual(obj.module, "todo")
            self.assertIn("todo", obj.title.lower())
            self.assertNotIn("storage", obj.title.lower())
            persisted = load_focus_module(app / "factory_tasks")
            assert persisted is not None
            self.assertEqual(persisted["id"], "todo")
            self.assertTrue((app / "factory_tasks" / MODULE_FILE).is_file())

    def test_verified_module_releases_the_next(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(
                app / "docs/seed.md",
                "Goal:\nBuild a todo tracker.\n\nSuccess:\nAdd tasks.\n",
            )
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "required_files": [
                            "src/todo.py",
                            "src/storage.py",
                            "tests/test_todo.py",
                            "tests/test_storage.py",
                        ]
                    }
                ),
            )
            _write(
                app / "src/todo.py",
                "def add(item, items):\n"
                "    items.append(item)\n"
                "    return items\n",
            )
            _write(
                app / "tests/test_todo.py",
                "from src.todo import add\n\n"
                "def test_add():\n    assert add('a', []) == ['a']\n",
            )
            _write(
                app / "src/storage.py",
                "def save_data(data):\n    pass\n",
            )
            obj = next_execute_objective(_project(app), Path(tmp))
            self.assertEqual(obj.module, "storage")
            self.assertIn("storage", obj.title.lower())
            text = render_objective_focus(obj)
            self.assertIn("module: `storage`", text)
