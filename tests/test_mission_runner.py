"""P0 closed-loop mission runner tests (no Ollama required)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import crazy_admin as ca  # noqa: E402
from mission_runner import (  # noqa: E402
    BUDGET_EXHAUSTED,
    COMPLETE,
    HUMAN_REQUIRED,
    enable_workbench_profile,
    evaluate_mission,
    run_mission,
)
from project_control import read_control  # noqa: E402


def _bootstrap_repo(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "apps").mkdir(parents=True, exist_ok=True)
    (root / "config/projects.yaml").write_text("projects:\n", encoding="utf-8")
    (root / "config/factory.yaml").write_text(
        "factory:\n"
        '  mode: "dry_run"\n'
        '  state_dir: "state"\n'
        "  max_lines_per_file: 200\n"
        "  max_files_per_run: 5\n"
        "proposal_application:\n  allow_apply: false\n"
        "validation:\n  allow_run: false\n"
        "git:\n  allow_auto_commit: false\n",
        encoding="utf-8",
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_accepted(app: Path) -> None:
    _write(app / "README.md", "# Todo\n")
    _write(
        app / "architecture.json",
        json.dumps({"required_files": ["src/todo.py", "tests/test_todo.py"]}),
    )
    _write(
        app / "src/todo.py",
        "def add(item, items):\n    items.append(item)\n    return items\n",
    )
    _write(
        app / "tests/test_todo.py",
        "from src.todo import add\n\n"
        "def test_add():\n    assert add('a', []) == ['a']\n",
    )
    _write(
        app / "factory_tasks/MASTER_CHECKLIST.md",
        "- [x] Implement src/todo.py\n- [x] Write tests/test_todo.py\n",
    )
    _write(
        app / "factory_tasks/validation_result.json",
        json.dumps({"status": "passed", "checks": []}),
    )
    _write(app / "factory_tasks/planned_task.json", "{}")


class ProfileTests(unittest.TestCase):
    def test_profile_enables_isolated_caps_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("demo", "apps/demo", root=root)
            project = ca.resolve_project(ca.load_registry(root), "demo")
            enabled = enable_workbench_profile(project, root)
            self.assertEqual(
                set(enabled),
                {
                    "allow_apply",
                    "allow_validation",
                    "allow_remediation",
                    "allow_autonomous",
                },
            )
            control = read_control("apps/demo", root)
            assert control is not None
            caps = control["capabilities"]
            self.assertTrue(caps["allow_apply"])
            self.assertTrue(caps["allow_validation"])
            self.assertTrue(caps["allow_remediation"])
            self.assertTrue(caps["allow_autonomous"])
            self.assertFalse(caps.get("allow_delete", False))
            self.assertFalse(caps.get("allow_auto_commit", False))


class LoopTests(unittest.TestCase):
    def test_already_accepted_does_not_advance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("demo", "apps/demo", root=root)
            _make_accepted(root / "apps/demo")
            project = ca.resolve_project(ca.load_registry(root), "demo")
            calls: list[int] = []

            def boom(_project: dict) -> int:
                calls.append(1)
                raise AssertionError("advance must not run when complete")

            result = run_mission(
                project,
                root,
                max_beats=5,
                apply_profile=False,
                advance=boom,
            )
            self.assertEqual(result.outcome, COMPLETE)
            self.assertEqual(result.beats, 0)
            self.assertEqual(calls, [])

    def test_continues_until_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("demo", "apps/demo", root=root)
            project = ca.resolve_project(ca.load_registry(root), "demo")
            calls: list[int] = []

            def tick(_project: dict) -> int:
                calls.append(1)
                return 0

            result = run_mission(
                project,
                root,
                max_beats=3,
                apply_profile=False,
                advance=tick,
            )
            self.assertEqual(result.outcome, BUDGET_EXHAUSTED)
            self.assertEqual(result.beats, 3)
            self.assertEqual(len(calls), 3)
            trace = Path(result.trace_path)
            self.assertTrue(trace.is_file())
            text = trace.read_text(encoding="utf-8")
            self.assertIn("BUDGET_EXHAUSTED", text)
            self.assertIn("beat 3", text)

    def test_human_blocker_stops_without_more_beats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("demo", "apps/demo", root=root)
            state = json.loads(
                (root / "apps/demo/state/project_state.json").read_text(
                    encoding="utf-8"
                )
            )
            state["current_blocker"] = "self_rejection"
            _write(
                root / "apps/demo/state/project_state.json",
                json.dumps(state, indent=2),
            )
            project = ca.resolve_project(ca.load_registry(root), "demo")
            calls: list[int] = []

            def tick(_project: dict) -> int:
                calls.append(1)
                return 0

            result = run_mission(
                project,
                root,
                max_beats=8,
                apply_profile=False,
                advance=tick,
            )
            self.assertEqual(result.outcome, HUMAN_REQUIRED)
            self.assertEqual(result.beats, 0)
            self.assertEqual(calls, [])
            self.assertIn("self_rejection", result.reason)

    def test_completes_when_advance_produces_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("demo", "apps/demo", root=root)
            project = ca.resolve_project(ca.load_registry(root), "demo")
            app = root / "apps/demo"

            def land(_project: dict) -> int:
                _make_accepted(app)
                return 0

            result = run_mission(
                project,
                root,
                max_beats=4,
                apply_profile=True,
                advance=land,
            )
            self.assertEqual(result.outcome, COMPLETE, result.reason)
            self.assertEqual(result.beats, 1)
            self.assertIn("allow_apply", result.profile_enabled)

    def test_declared_start_without_module_is_more_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("demo", "apps/demo", root=root)
            _make_accepted(root / "apps/demo")
            arch_path = root / "apps/demo/architecture.json"
            arch = json.loads(arch_path.read_text(encoding="utf-8"))
            arch["start_command"] = "python3 -m src.task_board"
            arch_path.write_text(json.dumps(arch), encoding="utf-8")
            calls: list[int] = []

            def tick(_project: dict) -> int:
                calls.append(1)
                return 0

            result = run_mission(
                project=ca.resolve_project(ca.load_registry(root), "demo"),
                root=root,
                max_beats=2,
                apply_profile=False,
                advance=tick,
            )
            self.assertEqual(result.outcome, BUDGET_EXHAUSTED)
            self.assertIn("not in the workbench", result.reason)
            self.assertEqual(len(calls), 2)
            runtime_path = root / "apps/demo/factory_tasks/runtime_result.json"
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            self.assertEqual(runtime["status"], "missing")
            obj_path = root / "apps/demo/factory_tasks/current_objective.json"
            objective = json.loads(obj_path.read_text(encoding="utf-8"))
            self.assertEqual(objective["kind"], "repair_runtime")

    def test_no_progress_blocker_is_human_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("demo", "apps/demo", root=root)
            state = json.loads(
                (root / "apps/demo/state/project_state.json").read_text(
                    encoding="utf-8"
                )
            )
            state["current_blocker"] = "no_progress"
            _write(
                root / "apps/demo/state/project_state.json",
                json.dumps(state, indent=2),
            )
            project = ca.resolve_project(ca.load_registry(root), "demo")
            calls: list[int] = []

            def tick(_project: dict) -> int:
                calls.append(1)
                return 0

            result = run_mission(
                project,
                root,
                max_beats=8,
                apply_profile=False,
                advance=tick,
            )
            self.assertEqual(result.outcome, HUMAN_REQUIRED)
            self.assertEqual(result.beats, 0)
            self.assertEqual(calls, [])
            self.assertIn("repair retry", result.reason)
            self.assertNotEqual(result.outcome, BUDGET_EXHAUSTED)

    def test_greenfield_writes_current_objective(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("demo", "apps/demo", root=root)
            project = ca.resolve_project(ca.load_registry(root), "demo")

            def tick(_project: dict) -> int:
                return 0

            result = run_mission(
                project,
                root,
                max_beats=1,
                apply_profile=False,
                advance=tick,
            )
            self.assertEqual(result.outcome, BUDGET_EXHAUSTED)
            obj_path = root / "apps/demo/factory_tasks/current_objective.json"
            self.assertTrue(obj_path.is_file())
            payload = json.loads(obj_path.read_text(encoding="utf-8"))
            # Placeholder seed → specify_intent; empty code → code_birth.
            self.assertIn(payload["kind"], {"code_birth", "specify_intent"})
            self.assertTrue(payload["id"])
            trace = Path(result.trace_path).read_text(encoding="utf-8")
            self.assertIn("objective=", trace)
            self.assertTrue(any(rec.objective for rec in result.records))


class CliRunTests(unittest.TestCase):
    def test_run_cli_completes_without_advance_when_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("demo", "apps/demo", root=root)
            _make_accepted(root / "apps/demo")
            with (
                patch("crazy_admin.find_repo_root", return_value=root),
                patch("sys.stdout", new_callable=StringIO) as out,
            ):
                code = ca.main(
                    ["run", "demo", "--keep-gates", "--max-beats", "2"]
                )
            self.assertEqual(code, 0, out.getvalue())
            self.assertIn("COMPLETE", out.getvalue())
            self.assertIn("after 0 beat", out.getvalue())


class EvaluateTests(unittest.TestCase):
    def test_greenfield_is_more_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("demo", "apps/demo", root=root)
            project = ca.resolve_project(ca.load_registry(root), "demo")
            status, reason = evaluate_mission(
                project, root, beat=0, max_beats=5
            )
            self.assertEqual(status, "MORE_WORK")
            self.assertIn("ZERO_CODE_OUTPUT", reason)
