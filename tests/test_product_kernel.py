"""Tests for the Crazy Factory 2.0 product intelligence kernel (Slice A)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from product_kernel import (  # noqa: E402
    assess_project,
    assessment_to_dict,
    inspect_project,
    load_persisted,
    render_assessment,
)

CLI_TODO_SEED = (ROOT / "examples/seeds/cli_todo_tracker.md").read_text(
    encoding="utf-8"
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(app: Path) -> dict[str, object]:
    return {
        "name": "todo",
        "app_path": str(app),
        "task_root": str(app / "factory_tasks"),
        "factory_state_dir": str(app / "factory_state"),
        "context_root": str(app / "factory_context"),
        "state_dir": str(app / "state"),
        "seed_file": "docs/seed.md",
    }


class GreenfieldTests(unittest.TestCase):
    def test_placeholder_seed_is_not_demo_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(
                app / "docs/seed.md",
                "Goal:\nDescribe what todo should do.\n\nSuccess:\n"
                "Describe what 'done' looks like.\n",
            )
            _write(app / "app/.gitkeep", "")
            assessment = inspect_project(_project(app), Path(tmp))
            self.assertFalse(assessment.convergence.demo_ready)
            self.assertTrue(assessment.model.placeholder_intent)
            self.assertIn(
                "placeholder", assessment.convergence.blocking_question
            )
            titles = [o.title.lower() for o in assessment.objectives]
            self.assertTrue(any("intended product" in t for t in titles))
            self.assertTrue(any("code birth" in t for t in titles))

    def test_real_seed_discovers_product_without_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(app / "docs/seed.md", CLI_TODO_SEED)
            assessment = inspect_project(_project(app), Path(tmp))
            self.assertFalse(assessment.convergence.demo_ready)
            self.assertFalse(assessment.model.placeholder_intent)
            self.assertIn("todo tracker", assessment.model.intended_goal)
            self.assertTrue(assessment.model.success_criteria)
            self.assertIn(
                "ZERO_CODE_OUTPUT",
                assessment.convergence.blocking_question,
            )
            self.assertTrue(
                any(o.id.startswith("OBJ-") for o in assessment.objectives)
            )
            birth = [
                o
                for o in assessment.objectives
                if "code birth" in o.title.lower()
            ]
            self.assertEqual(len(birth), 1)
            self.assertTrue(birth[0].blocking)
            self.assertIn("coder", birth[0].required_roles)


class PartialProductTests(unittest.TestCase):
    def test_stub_and_missing_tests_produce_module_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(app / "docs/seed.md", CLI_TODO_SEED)
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "src_dirs": ["src"],
                        "test_dirs": ["tests"],
                        "required_files": [
                            "src/todo.py",
                            "src/storage.py",
                            "tests/test_todo.py",
                            "tests/test_storage.py",
                        ],
                    }
                ),
            )
            _write(
                app / "src/todo.py",
                "def add(item):\n    return item\n",
            )
            _write(
                app / "src/storage.py",
                "def save_data(data):\n    pass\n\n"
                "def load_data():\n    pass\n",
            )
            _write(
                app / "factory_tasks/MASTER_CHECKLIST.md",
                "# Master Checklist\n\n"
                "- [x] Implement src/todo.py\n"
                "- [ ] Implement src/storage.py\n",
            )
            assessment = inspect_project(_project(app), Path(tmp))
            modules = {m.id: m for m in assessment.model.modules}
            self.assertIn("todo", modules)
            self.assertIn("storage", modules)
            self.assertEqual(modules["todo"].maturity, "IMPLEMENTED")
            self.assertEqual(modules["storage"].maturity, "IMPLEMENTED")
            self.assertTrue(any("stub" in g for g in modules["storage"].gaps))
            self.assertTrue(any("no tests" in g for g in modules["todo"].gaps))
            titles = [o.title.lower() for o in assessment.objectives]
            self.assertTrue(any("stub" in t for t in titles))
            self.assertTrue(any("verify module todo" in t for t in titles))
            demo = next(
                d
                for d in assessment.convergence.dimensions
                if d.name == "demo_readiness"
            )
            self.assertEqual(demo.status, "partial")
            self.assertFalse(assessment.convergence.demo_ready)

    def test_assess_persists_and_reloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(app / "docs/seed.md", CLI_TODO_SEED)
            project = _project(app)
            first = assess_project(project, Path(tmp))
            stored = load_persisted(project, Path(tmp))
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(
                stored["product_model.json"]["intended_goal"],
                first.model.intended_goal,
            )
            self.assertEqual(
                stored["convergence.json"]["blocking_question"],
                first.convergence.blocking_question,
            )
            self.assertTrue(stored["objectives.json"]["objectives"])


class AcceptedShapedTests(unittest.TestCase):
    def test_complete_evidence_is_demo_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(app / "docs/seed.md", CLI_TODO_SEED)
            _write(app / "README.md", "# Todo\n\nCLI tracker.\n")
            _write(
                app / "architecture.json",
                json.dumps(
                    {"required_files": ["src/todo.py", "tests/test_todo.py"]}
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
                app / "factory_tasks/MASTER_CHECKLIST.md",
                "- [x] Implement src/todo.py\n"
                "- [x] Write tests/test_todo.py\n",
            )
            _write(
                app / "factory_tasks/validation_result.json",
                json.dumps({"status": "passed", "checks": []}),
            )
            _write(app / "factory_tasks/planned_task.json", "{}")
            assessment = inspect_project(_project(app), Path(tmp))
            self.assertTrue(
                assessment.convergence.demo_ready,
                render_assessment(assessment),
            )
            self.assertEqual(assessment.objectives, [])
            demo = next(
                d
                for d in assessment.convergence.dimensions
                if d.name == "demo_readiness"
            )
            self.assertEqual(demo.status, "ready")
            snapshot = assessment_to_dict(assessment)
            self.assertTrue(snapshot["demo_ready"])
            todo = next(m for m in snapshot["modules"] if m["id"] == "todo")
            self.assertEqual(todo["maturity"], "VERIFIED")


class RenderTests(unittest.TestCase):
    def test_render_includes_blocking_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(app / "docs/seed.md", CLI_TODO_SEED)
            text = render_assessment(inspect_project(_project(app), Path(tmp)))
            self.assertIn("Blocking question", text)
            self.assertIn("Objectives", text)
            self.assertIn("OBJ-", text)
