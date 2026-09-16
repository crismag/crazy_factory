"""P4a AgentExecutor: contract, confinement, stdlib actuator, benchmark."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import crazy_admin as ca  # noqa: E402
from agent_executor import (  # noqa: E402
    ExecutorRequest,
    ExecutorResult,
    LlmFileExecutor,
    StdlibWebExecutor,
    apply_executor_result,
    build_request,
    default_executor,
    seed_looks_like_stdlib_task_board,
)
from mission_runner import COMPLETE, run_mission  # noqa: E402

SEED = ROOT / "examples" / "seeds" / "task_board_web.md"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
    (root / "config/models.yaml").write_text(
        "models:\n  planner: cogito:14b\n  architect: cogito:14b\n"
        "  coder: cogito:14b\n  test_builder: cogito:14b\n",
        encoding="utf-8",
    )


def _request(*, seed: str = "") -> ExecutorRequest:
    return ExecutorRequest(
        objective_id="obj-1",
        objective_kind="code_birth",
        objective_title="Birth the application",
        gap="no source",
        why="greenfield",
        focus="implement src/task_board.py",
        seed_text=seed,
        app_path="apps/board",
    )


class SeedMatchTests(unittest.TestCase):
    def test_task_board_seed_matches(self) -> None:
        text = SEED.read_text(encoding="utf-8")
        self.assertTrue(seed_looks_like_stdlib_task_board(text))

    def test_placeholder_seed_does_not_match(self) -> None:
        self.assertFalse(
            seed_looks_like_stdlib_task_board(
                "# Factory Seed\n\nGoal:\nDescribe what board should do.\n"
            )
        )


class StdlibExecutorTests(unittest.TestCase):
    def test_copies_verified_files(self) -> None:
        result = StdlibWebExecutor().execute(
            _request(seed=SEED.read_text(encoding="utf-8"))
        )
        self.assertTrue(result.ok)
        self.assertIn("src/task_board.py", result.files)
        self.assertIn("tests/test_task_board.py", result.files)
        self.assertIn("architecture.json", result.files)
        self.assertIn("def add_task", result.files["src/task_board.py"])
        self.assertNotIn("scripts/factory_advance.py", result.files)

    def test_skips_unrelated_seed(self) -> None:
        result = StdlibWebExecutor().execute(_request(seed="a calendar app"))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "seed mismatch")
        self.assertEqual(result.files, {})


class ConfinementTests(unittest.TestCase):
    def test_blocks_engine_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("board", "apps/board", root=root)
            project = ca.resolve_project(ca.load_registry(root), "board")
            result = ExecutorResult(
                ok=True,
                provider="probe",
                summary="escape",
                files={"scripts/pwn.py": "print(1)\n"},
            )
            written, err = apply_executor_result(result, project, root)
            self.assertEqual(written, [])
            self.assertIsNotNone(err)
            self.assertIn("blocked path", str(err))
            self.assertFalse((root / "apps/board/scripts/pwn.py").exists())
            self.assertFalse((root / "scripts/pwn.py").exists())

    def test_writes_only_under_workbench(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("board", "apps/board", root=root)
            project = ca.resolve_project(ca.load_registry(root), "board")
            result = ExecutorResult(
                ok=True,
                provider="probe",
                summary="ok",
                files={"src/hello.py": "X = 1\n"},
            )
            written, err = apply_executor_result(result, project, root)
            self.assertIsNone(err)
            self.assertEqual(written, ["src/hello.py"])
            self.assertEqual(
                (root / "apps/board/src/hello.py").read_text(encoding="utf-8"),
                "X = 1\n",
            )


class BuildRequestTests(unittest.TestCase):
    def test_packs_seed_and_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("board", "apps/board", root=root)
            project = ca.resolve_project(ca.load_registry(root), "board")
            ca.install_seed(project, str(SEED), root)
            task = root / "apps/board/factory_tasks"
            _write(
                task / "validation_result.json",
                json.dumps({"status": "failed", "reason": "pytest exploded"}),
            )
            req = build_request(
                project,
                root,
                objective=SimpleNamespace(
                    id="obj-1",
                    kind="code_birth",
                    title="Birth the application",
                    gap="no source",
                    why="greenfield",
                    focus="implement src/task_board.py",
                ),
            )
            self.assertIn("http.server", req.seed_text)
            self.assertIn("pytest exploded", req.validation_failure)


class LlmSkipTests(unittest.TestCase):
    @patch("agent_executor.structured_call", return_value=(None, "down"))
    def test_skips_when_ollama_unavailable(self, _mock: object) -> None:
        out = LlmFileExecutor().execute(_request(seed="x"))
        self.assertFalse(out.ok)
        self.assertEqual(out.provider, "ollama_files")


class DefaultExecutorTests(unittest.TestCase):
    def test_env_forces_stdlib_web(self) -> None:
        with patch.dict(os.environ, {"CRAZY_FACTORY_EXECUTOR": "stdlib_web"}):
            self.assertEqual(default_executor().name, "stdlib_web")


class TaskBoardBenchmarkTests(unittest.TestCase):
    def test_clean_workbench_mission_reaches_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("board", "apps/board", root=root)
            project = ca.resolve_project(ca.load_registry(root), "board")
            ca.install_seed(project, str(SEED), root)
            cwd = Path.cwd()
            try:
                os.chdir(root)
                with (
                    patch(
                        "factory_advance.find_repo_root",
                        return_value=root,
                    ),
                    patch("factory_advance.Path.cwd", return_value=root),
                    patch.dict(
                        os.environ,
                        {"CRAZY_FACTORY_EXECUTOR": "stdlib_web"},
                    ),
                ):
                    result = run_mission(
                        project,
                        root,
                        max_beats=3,
                        apply_profile=True,
                    )
            finally:
                os.chdir(cwd)
            app = root / "apps/board"
            validation = app / "factory_tasks/validation_result.json"
            detail = ""
            if validation.is_file():
                detail = validation.read_text(encoding="utf-8")
            self.assertEqual(
                result.outcome,
                COMPLETE,
                f"{result.outcome}: {result.reason}\n{detail}",
            )
            self.assertTrue((app / "src/task_board.py").is_file())
            self.assertTrue((app / "tests/test_task_board.py").is_file())
            self.assertIn("runtime", result.reason)


if __name__ == "__main__":
    unittest.main()
