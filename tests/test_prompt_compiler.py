"""Prompt compiler: raw owner prompt → specified seed + architecture."""

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

import crazy_admin as ca
from director import ACTION_PROVIDE_CONTEXT, director_brief
from mcp_server import call_tool
from mission_runner import MissionResult
from prompt_compiler import (
    compile_into_workbench,
    compile_prompt,
    maybe_compile_workbench,
    needs_compile,
    persist_compiled,
    render_seed,
)
from web_stack import (
    DEFAULT_STACK_ID,
    NEXT_STACK_ID,
    STACKS,
    default_stack,
    resolve_stack,
)

STRUCTURED_SEED = "Goal:\nBuild a task board.\n\nSuccess:\nAdd tasks.\n"


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


def _project(app: Path) -> dict[str, str]:
    tasks = app / "factory_tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    return {
        "name": app.name,
        "app_path": str(app),
        "task_root": str(tasks),
        "seed_file": "docs/seed.md",
    }


def _fake_mission(project_id: str, artifact: str) -> MissionResult:
    return MissionResult(
        project_id=project_id,
        outcome="BUDGET_EXHAUSTED",
        reason="beat budget 1 exhausted",
        beats=1,
        max_beats=1,
        profile_enabled=["allow_apply"],
        records=[],
        artifact=artifact,
        trace_path=str(Path(artifact) / "factory_reports/MISSION_TRACE.md"),
    )


class NeedsCompileTests(unittest.TestCase):
    def test_empty_is_not_compiled(self) -> None:
        self.assertFalse(needs_compile(""))
        self.assertFalse(needs_compile("   "))

    def test_structured_seed_is_left_alone(self) -> None:
        self.assertFalse(needs_compile(STRUCTURED_SEED))

    def test_placeholder_seed_needs_compile(self) -> None:
        text = ca._seed_template("demo")
        self.assertTrue(needs_compile(text))

    def test_one_liner_needs_compile(self) -> None:
        self.assertTrue(needs_compile("build a habit tracker"))


class FallbackCompileTests(unittest.TestCase):
    def test_habit_tracker_fallback_is_specified(self) -> None:
        product = compile_prompt("build a habit tracker")
        self.assertEqual(product.stack, DEFAULT_STACK_ID)
        self.assertEqual(product.source, "fallback")
        self.assertFalse(needs_compile(render_seed(product)))
        self.assertTrue(product.success)
        self.assertTrue(product.start_command.startswith("python3"))
        self.assertEqual(product.listen_port, 8765)
        self.assertIn("habit", product.title.lower())

    def test_unknown_stack_falls_back_to_default(self) -> None:
        product = compile_prompt("make a notes app", stack_id="vite-react")
        self.assertEqual(product.stack, DEFAULT_STACK_ID)
        self.assertEqual(product.start_command, default_stack().start_command)

    def test_model_compile_uses_sanitized_payload(self) -> None:
        payload = {
            "title": "Habit Tracker",
            "goal": "Build a local habit tracker with a calendar view.",
            "success": ["Log a habit", "See a streak"],
            "constraints": ["Python 3 stdlib only"],
            "screens": ["home", "log"],
            "data": "JSON under data/",
            "required_files": ["src/app.py", "/etc/passwd", "../escape.py"],
            "start_command": "npm run dev",
            "listen_port": 5173,
            "known_context": "Single user.",
        }
        with (
            patch("prompt_compiler.control_model_enabled", return_value=True),
            patch(
                "prompt_compiler.resolve_coding_backend",
                return_value=("anthropic", object(), "claude"),
            ),
            patch(
                "prompt_compiler.structured_call",
                return_value=(payload, "ok"),
            ),
        ):
            product = compile_prompt("build a habit tracker")
        self.assertEqual(product.source, "model")
        self.assertEqual(product.provider, "anthropic")
        self.assertEqual(product.title, "Habit Tracker")
        self.assertTrue(product.start_command.startswith("python3"))
        self.assertEqual(product.listen_port, 8765)
        self.assertEqual(product.required_files, ["src/app.py"])
        self.assertEqual(product.stack, DEFAULT_STACK_ID)


class PersistTests(unittest.TestCase):
    def test_writes_seed_architecture_and_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "apps" / "habit"
            project = _project(app)
            paths = compile_into_workbench(
                project, Path(tmp), "build a habit tracker"
            )
            seed = Path(paths["seed"]).read_text(encoding="utf-8")
            self.assertIn("Goal:", seed)
            self.assertIn("Success:", seed)
            self.assertNotIn("describe what", seed.lower())
            arch = json.loads(Path(paths["architecture"]).read_text())
            self.assertEqual(arch["source"], "prompt-compiler")
            self.assertEqual(arch["stack"], DEFAULT_STACK_ID)
            self.assertEqual(arch["start_command"], "python3 -m src.app")
            record = json.loads(Path(paths["record"]).read_text())
            self.assertEqual(record["stack"], DEFAULT_STACK_ID)
            self.assertEqual(
                record["original_prompt"], "build a habit tracker"
            )

    def test_does_not_overwrite_hand_authored_architecture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "apps" / "board"
            project = _project(app)
            original = {"required_files": ["src/task_board.py"]}
            arch = app / "architecture.json"
            arch.parent.mkdir(parents=True, exist_ok=True)
            arch.write_text(json.dumps(original), encoding="utf-8")
            persist_compiled(
                compile_prompt("build a habit tracker"),
                project,
                Path(tmp),
            )
            kept = json.loads(arch.read_text(encoding="utf-8"))
            self.assertEqual(kept, original)

    def test_overwrites_previous_compiler_architecture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "apps" / "habit"
            project = _project(app)
            compile_into_workbench(project, Path(tmp), "build a notes app")
            compile_into_workbench(project, Path(tmp), "build a habit tracker")
            arch = json.loads((app / "architecture.json").read_text())
            self.assertIn("habit", arch["title"].lower())


class WebStackTests(unittest.TestCase):
    def test_default_is_executable_stdlib_web(self) -> None:
        stack = default_stack()
        self.assertEqual(stack.id, "stdlib-web")
        self.assertTrue(stack.executable)
        self.assertEqual(NEXT_STACK_ID, "vite-react")
        self.assertFalse(STACKS[NEXT_STACK_ID].executable)
        self.assertEqual(resolve_stack("vite-react").id, "stdlib-web")
        self.assertEqual(resolve_stack("unknown").id, "stdlib-web")


class IngestCliTests(unittest.TestCase):
    def test_run_prompt_compiles_one_liner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            fake = _fake_mission("habit", str(root / "apps/habit"))
            with (
                patch("crazy_admin.find_repo_root", return_value=root),
                patch("crazy_admin.run_mission", return_value=fake),
                patch("sys.stdout", new_callable=StringIO),
            ):
                code = ca.main(
                    [
                        "run",
                        "habit",
                        "--prompt",
                        "build a habit tracker",
                        "--max-beats",
                        "1",
                    ]
                )
            self.assertEqual(code, 1)
            seed = (root / "apps/habit/docs/seed.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Goal:", seed)
            self.assertNotIn("describe what", seed.lower())
            arch = json.loads(
                (root / "apps/habit/architecture.json").read_text()
            )
            self.assertEqual(arch["stack"], DEFAULT_STACK_ID)
            compile_path = (
                root / "apps/habit/factory_tasks/prompt_compile.json"
            )
            record = json.loads(compile_path.read_text(encoding="utf-8"))
            self.assertEqual(
                record["original_prompt"], "build a habit tracker"
            )

    def test_startproject_scaffold_is_not_compiled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("demo", "apps/demo", root=root)
            app = root / "apps/demo"
            project = ca.resolve_project(ca.load_registry(root), "demo")
            self.assertIsNone(maybe_compile_workbench(project, root))
            seed = (app / "docs/seed.md").read_text(encoding="utf-8")
            self.assertIn("Describe what demo should do", seed)
            self.assertFalse((app / "architecture.json").exists())
            self.assertFalse(
                (app / "factory_tasks/prompt_compile.json").exists()
            )

    def test_structured_seed_is_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("board", "apps/board", root=root)
            seed_path = root / "brief.md"
            seed_path.write_text(STRUCTURED_SEED, encoding="utf-8")
            project = ca.resolve_project(ca.load_registry(root), "board")
            ingested = ca.ingest_start_context(
                project, root, seed=str(seed_path)
            )
            self.assertIsNone(ingested["compiled"])
            written = (root / "apps/board/docs/seed.md").read_text(
                encoding="utf-8"
            )
            self.assertEqual(written, STRUCTURED_SEED)

    def test_director_still_asks_for_context_on_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("todo", "apps/todo", root=root)
            payload = director_brief(root, project_id="todo")
            self.assertEqual(payload["next"]["action"], ACTION_PROVIDE_CONTEXT)
            self.assertIn("prompt", payload["next"]["cli"])


class McpPromptTests(unittest.TestCase):
    def test_start_mission_prompt_compiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            fake = _fake_mission("habit", str(root / "apps/habit"))
            with patch("mcp_server.run_closed_mission", return_value=fake):
                result = call_tool(
                    "start_mission",
                    {
                        "project_id": "habit",
                        "prompt": "build a habit tracker",
                        "max_beats": 1,
                    },
                    root,
                )
            self.assertFalse(result["isError"], result)
            body = json.loads(result["content"][0]["text"])
            self.assertIsNotNone(body["ingested"]["compiled"])
            seed = (root / "apps/habit/docs/seed.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("habit", seed.lower())
            self.assertNotIn("describe what", seed.lower())

    def test_unstructured_inline_context_is_compiled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            fake = _fake_mission("notes", str(root / "apps/notes"))
            with patch("mcp_server.run_closed_mission", return_value=fake):
                result = call_tool(
                    "start_mission",
                    {
                        "project_id": "notes",
                        "context": "make a notes app",
                        "max_beats": 1,
                    },
                    root,
                )
            self.assertFalse(result["isError"], result)
            written = (root / "apps/notes/docs/seed.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Goal:", written)
            self.assertNotEqual(written, "make a notes app")
