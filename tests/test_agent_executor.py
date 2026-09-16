"""P4a AgentExecutor: contract, confinement, stdlib actuator, benchmark."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import crazy_admin as ca  # noqa: E402
from agent_executor import (  # noqa: E402
    CloudCodingExecutor,
    ExecutorRequest,
    ExecutorResult,
    LlmFileExecutor,
    StdlibWebExecutor,
    apply_executor_result,
    build_request,
    default_executor,
    seed_looks_like_stdlib_task_board,
)
from mcp_server import call_tool  # noqa: E402
from mission_runner import COMPLETE, run_mission  # noqa: E402

SEED = ROOT / "examples" / "seeds" / "task_board_web.md"
_CLOUD_ENV = (
    "CRAZY_FACTORY_EXECUTOR",
    "CRAZY_FACTORY_CODING_PROVIDER",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CRAZY_FACTORY_OPENAI_API_KEY",
    "CRAZY_FACTORY_ANTHROPIC_API_KEY",
)


def _env_without_cloud(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _CLOUD_ENV}
    env.update(extra)
    return env


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@contextmanager
def _isolated_workbench(pid: str):
    """Create a throwaway workbench under apps/ and restore the registry."""
    app = ROOT / "apps" / pid
    registry = ROOT / "config" / "projects.yaml"
    backup = registry.read_text(encoding="utf-8")
    if app.exists():
        shutil.rmtree(app)
    try:
        yield app
    finally:
        if app.exists():
            shutil.rmtree(app, ignore_errors=True)
        registry.write_text(backup, encoding="utf-8")


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
        self.assertIn("requirements.txt", result.files)
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

    def test_env_forces_openai_plugin(self) -> None:
        with patch.dict(os.environ, {"CRAZY_FACTORY_EXECUTOR": "openai"}):
            executor = default_executor()
        self.assertIsInstance(executor, CloudCodingExecutor)
        assert isinstance(executor, CloudCodingExecutor)
        self.assertEqual(executor.prefer, "openai")

    def test_env_forces_claude_plugin(self) -> None:
        with patch.dict(os.environ, {"CRAZY_FACTORY_EXECUTOR": "anthropic"}):
            executor = default_executor()
        self.assertIsInstance(executor, CloudCodingExecutor)
        assert isinstance(executor, CloudCodingExecutor)
        self.assertEqual(executor.prefer, "anthropic")

    def test_env_forces_ollama_opt_in(self) -> None:
        with patch.dict(os.environ, {"CRAZY_FACTORY_EXECUTOR": "ollama"}):
            self.assertEqual(default_executor().name, "ollama_files")

    def test_default_chain_falls_through_without_cloud_keys(self) -> None:
        with patch.dict(os.environ, _env_without_cloud(), clear=True):
            executor = default_executor()
            self.assertEqual(executor.name, "chain")
            names = [backend.name for backend in executor.backends]
            self.assertEqual(names, ["cloud_coding", "stdlib_web"])
            result = executor.execute(
                _request(seed=SEED.read_text(encoding="utf-8"))
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "stdlib_web")
        self.assertIn("src/task_board.py", result.files)

    def test_novel_seed_without_keys_does_not_invent_files(self) -> None:
        with patch.dict(os.environ, _env_without_cloud(), clear=True):
            result = default_executor().execute(
                _request(seed="a calendar app")
            )
        self.assertFalse(result.ok)
        self.assertEqual(result.files, {})


class CloudCodingExecutorTests(unittest.TestCase):
    def test_skips_without_calling_network(self) -> None:
        with (
            patch.dict(os.environ, _env_without_cloud(), clear=True),
            patch("coding_llm.urlopen") as mock_open,
        ):
            out = CloudCodingExecutor().execute(_request(seed="x"))
        mock_open.assert_not_called()
        self.assertFalse(out.ok)
        self.assertEqual(out.reason, "no_coding_api_key")
        self.assertEqual(out.provider, "cloud_coding")

    def test_openai_file_map_is_applied(self) -> None:
        payload = {
            "files": {
                "src/hello.py": "X = 1\n",
                "scripts/pwn.py": "print(1)\n",
            }
        }
        with (
            patch.dict(
                os.environ,
                _env_without_cloud(OPENAI_API_KEY="sk-test"),
                clear=True,
            ),
            patch(
                "agent_executor.structured_call",
                return_value=(payload, "ok (attempt 1)"),
            ) as mock_call,
        ):
            out = CloudCodingExecutor(provider="openai").execute(
                _request(seed="novel app")
            )
        mock_call.assert_called_once()
        self.assertTrue(out.ok)
        self.assertEqual(out.provider, "openai")
        self.assertEqual(out.files, {"src/hello.py": "X = 1\n"})
        self.assertNotIn("scripts/pwn.py", out.files)

    def test_anthropic_file_map_is_applied(self) -> None:
        payload = {"files": {"src/app.py": "print('ok')\n"}}
        with (
            patch.dict(
                os.environ,
                _env_without_cloud(ANTHROPIC_API_KEY="ant-test"),
                clear=True,
            ),
            patch(
                "agent_executor.structured_call",
                return_value=(payload, "ok (attempt 1)"),
            ),
        ):
            out = CloudCodingExecutor(provider="anthropic").execute(
                _request(seed="novel app")
            )
        self.assertTrue(out.ok)
        self.assertEqual(out.provider, "anthropic")
        self.assertEqual(out.files["src/app.py"], "print('ok')\n")

    def test_blocked_only_payload_is_rejected(self) -> None:
        payload = {"files": {"scripts/pwn.py": "print(1)\n"}}
        with (
            patch.dict(
                os.environ,
                _env_without_cloud(OPENAI_API_KEY="sk-test"),
                clear=True,
            ),
            patch(
                "agent_executor.structured_call",
                return_value=(payload, "ok (attempt 1)"),
            ),
        ):
            out = CloudCodingExecutor(provider="openai").execute(
                _request(seed="novel app")
            )
        self.assertFalse(out.ok)
        self.assertEqual(out.files, {})


class TaskBoardBenchmarkTests(unittest.TestCase):
    def test_clean_workbench_mission_reaches_complete(self) -> None:
        pid = "p4a_stdlib_board"
        with _isolated_workbench(pid) as app:
            ca.startproject(pid, f"apps/{pid}", root=ROOT, force=True)
            project = ca.resolve_project(ca.load_registry(ROOT), pid)
            ca.install_seed(project, str(SEED), root=ROOT)
            with patch.dict(
                os.environ, {"CRAZY_FACTORY_EXECUTOR": "stdlib_web"}
            ):
                result = run_mission(
                    project,
                    ROOT,
                    max_beats=3,
                    apply_profile=True,
                )
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

    def test_broken_workbench_is_repaired_without_a_human(self) -> None:
        pid = "p4b_repair_board"
        with _isolated_workbench(pid) as app:
            ca.startproject(pid, f"apps/{pid}", root=ROOT, force=True)
            project = ca.resolve_project(ca.load_registry(ROOT), pid)
            ca.install_seed(project, str(SEED), root=ROOT)
            _write(app / "src/task_board.py", "STATUS = 'broken'\n")
            _write(
                app / "tests/test_task_board.py",
                "def test_ok():\n    assert False\n",
            )
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "required_files": [
                            "src/task_board.py",
                            "tests/test_task_board.py",
                        ],
                        "src_dirs": ["src"],
                        "test_dirs": ["tests"],
                        "start_command": "python3 -m src.task_board",
                        "listen_port": 8765,
                    }
                ),
            )
            _write(
                app / "factory_tasks/MASTER_CHECKLIST.md",
                "- [x] Implement src/task_board.py\n",
            )
            _write(
                app / "factory_tasks/validation_result.json",
                json.dumps({"status": "failed", "reason": "assert False"}),
            )
            with patch.dict(
                os.environ, {"CRAZY_FACTORY_EXECUTOR": "stdlib_web"}
            ):
                result = run_mission(
                    project,
                    ROOT,
                    max_beats=3,
                    apply_profile=True,
                )
            self.assertEqual(result.outcome, COMPLETE, result.reason)
            src = (app / "src/task_board.py").read_text(encoding="utf-8")
            self.assertIn("def add_task", src)
            self.assertIn("runtime", result.reason)

    def test_crazy_admin_run_seed_exits_zero(self) -> None:
        pid = "p4b_admin_run"
        with _isolated_workbench(pid):
            out = StringIO()
            with (
                patch("sys.stdout", out),
                patch.dict(
                    os.environ,
                    {**os.environ, "CRAZY_FACTORY_EXECUTOR": "stdlib_web"},
                ),
            ):
                code = ca.main(
                    [
                        "run",
                        pid,
                        "--path",
                        f"apps/{pid}",
                        "--seed",
                        str(SEED),
                        "--max-beats",
                        "3",
                    ]
                )
            self.assertEqual(code, 0, out.getvalue())
            self.assertIn("COMPLETE", out.getvalue())

    def test_mcp_start_mission_seed_completes(self) -> None:
        pid = "p4b_mcp_start"
        with _isolated_workbench(pid) as app:
            with patch.dict(
                os.environ, {"CRAZY_FACTORY_EXECUTOR": "stdlib_web"}
            ):
                result = call_tool(
                    "start_mission",
                    {
                        "project_id": pid,
                        "seed": str(SEED),
                        "target": f"apps/{pid}",
                        "max_beats": 3,
                    },
                    ROOT,
                )
            self.assertFalse(result["isError"], result)
            body = json.loads(result["content"][0]["text"])
            self.assertEqual(body["outcome"], COMPLETE, body)
            self.assertGreaterEqual(int(body["beats"]), 1)
            self.assertTrue((app / "src/task_board.py").is_file())


if __name__ == "__main__":
    unittest.main()
