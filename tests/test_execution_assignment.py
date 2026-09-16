"""Task intelligence: purpose-built execution assignments from evidence."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_executor import build_request
from diagnosis_packet import build_packet, executor_slice
from execution_assignment import (
    STANCE_BIRTH,
    STANCE_INVESTIGATE,
    STANCE_NEED_CONTEXT,
    STANCE_REPAIR,
    classify_stance,
    compile_assignment,
    render_assignment,
    validation_summary,
)

_NOW = "2026-09-16T00:00:00Z"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(root: Path) -> dict[str, str]:
    app = root / "apps" / "board"
    tasks = app / "factory_tasks"
    tasks.mkdir(parents=True)
    (app / "src").mkdir(parents=True)
    return {
        "app_path": str(app),
        "task_root": str(tasks),
        "seed_file": "docs/seed.md",
        "name": "board",
        "factory_state_dir": "factory_state",
    }


class ValidationSummaryTests(unittest.TestCase):
    def test_uses_failing_check_detail_not_bare_failed(self) -> None:
        raw = {
            "status": "failed",
            "checks": [
                {
                    "command": "python3 -m pytest tests",
                    "status": "failed",
                    "detail": "AssertionError: add_task",
                }
            ],
        }
        text = validation_summary(raw)
        self.assertIn("pytest", text)
        self.assertIn("AssertionError", text)
        self.assertNotEqual(text, "failed")

    def test_ignores_passed_validation(self) -> None:
        self.assertEqual(
            validation_summary({"status": "passed", "checks": []}),
            "",
        )


class StanceTests(unittest.TestCase):
    def test_placeholder_needs_context(self) -> None:
        self.assertEqual(
            classify_stance(
                "specify_intent",
                previous_files=[],
                still_failing=False,
            ),
            STANCE_NEED_CONTEXT,
        )

    def test_repeat_failure_investigates(self) -> None:
        self.assertEqual(
            classify_stance(
                "repair_validation",
                previous_files=["src/app.py"],
                still_failing=True,
            ),
            STANCE_INVESTIGATE,
        )

    def test_first_repair_is_targeted(self) -> None:
        self.assertEqual(
            classify_stance(
                "repair_runtime",
                previous_files=[],
                still_failing=True,
            ),
            STANCE_REPAIR,
        )

    def test_birth(self) -> None:
        self.assertEqual(
            classify_stance(
                "code_birth",
                previous_files=[],
                still_failing=False,
            ),
            STANCE_BIRTH,
        )


class CompileAssignmentTests(unittest.TestCase):
    def test_assignment_answers_task_intelligence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = _project(root)
            app = Path(project["app_path"])
            _write(
                app / "docs/seed.md",
                "# Task board\nPython http.server + tasks.json\n",
            )
            _write(app / "src/task_board.py", "STATUS = 'broken'\n")
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "required_files": ["src/task_board.py"],
                        "start_command": "python3 -m src.task_board",
                    }
                ),
            )
            _write(
                Path(project["task_root"]) / "validation_result.json",
                json.dumps(
                    {
                        "status": "failed",
                        "checks": [
                            {
                                "command": "python3 -m pytest tests",
                                "status": "failed",
                                "detail": "assert False",
                            }
                        ],
                    }
                ),
            )
            _write(
                Path(project["task_root"]) / "executor_result.json",
                json.dumps(
                    {
                        "ok": True,
                        "provider": "openai",
                        "files": ["src/task_board.py"],
                    }
                ),
            )
            obj = SimpleNamespace(
                id="OBJ-VALIDATE",
                kind="repair_validation",
                title="Repair automated validation",
                gap="pytest failed",
                why="not demoable",
                focus="fix tests",
            )
            assignment = compile_assignment(project, root, obj)
            self.assertEqual(assignment.stance, STANCE_INVESTIGATE)
            self.assertIn("src/task_board.py", assignment.inventory)
            self.assertIn("pytest", assignment.validation_summary)
            body = render_assignment(assignment)
            self.assertIn("# Engineering assignment", body)
            self.assertIn("Do not emit the same files unchanged", body)
            self.assertIn("Executor completion is not acceptance", body)
            self.assertIn("assert False", body)
            self.assertIn("python3 -m src.task_board", body)

    def test_build_request_carries_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = _project(root)
            app = Path(project["app_path"])
            _write(app / "docs/seed.md", "Goal: calendar app\n")
            _write(
                Path(project["task_root"]) / "validation_result.json",
                json.dumps(
                    {
                        "status": "failed",
                        "checks": [
                            {
                                "command": "python3 -m compileall src",
                                "status": "failed",
                                "detail": "SyntaxError",
                            }
                        ],
                    }
                ),
            )
            req = build_request(
                project,
                root,
                objective=SimpleNamespace(
                    id="OBJ-1",
                    kind="code_birth",
                    title="Birth the application",
                    gap="no source",
                    why="greenfield",
                    focus="src/",
                ),
            )
            self.assertIn("Engineering assignment", req.assignment_text)
            self.assertIn("SyntaxError", req.validation_failure)
            self.assertEqual(req.stance, STANCE_BIRTH)
            self.assertNotEqual(req.validation_failure, "failed")


class ExecutorSliceTests(unittest.TestCase):
    def test_slice_includes_snapshot_and_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            tasks = app / "factory_tasks"
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "src_dirs": ["src"],
                        "test_dirs": ["tests"],
                        "required_files": ["src/a.py", "src/b.py"],
                    }
                ),
            )
            _write(app / "src/a.py", "X = 1\n")
            _write(
                tasks / "planned_task.json",
                json.dumps(
                    {
                        "task_id": "T-1",
                        "objective": "OBJ-MARK",
                        "scope": ["scope-1"],
                        "acceptance_criteria": ["AC-ALPHA"],
                        "validation_plan": ["python3 -m pytest tests"],
                        "validation": {"status": "valid", "reasons": []},
                    }
                ),
            )
            _write(
                tasks / "validation_result.json",
                json.dumps(
                    {
                        "status": "failed",
                        "checks": [
                            {
                                "command": "pytest",
                                "status": "failed",
                                "detail": "FAILCHECK-MARK",
                            }
                        ],
                    }
                ),
            )
            project = {
                "app_path": str(app),
                "task_root": str(tasks),
                "name": "board",
                "factory_state_dir": "factory_state",
            }
            packet = build_packet(
                project=project, root=root, project_state={}, now=_NOW
            )
            text = executor_slice(packet)
            self.assertIn("AC-ALPHA", text)
            self.assertIn("FAILCHECK-MARK", text)
            self.assertIn("src/b.py", text)


if __name__ == "__main__":
    unittest.main()
