"""L0-05 conversational deltas: follow-ups do not recompile the product."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import crazy_admin as ca
from agent_executor import ExecutorRequest, StdlibWebExecutor
from conversation_delta import (
    append_delta,
    has_specified_product,
    inject_preview_banner,
    latest_delta,
    load_deltas,
)
from execution_assignment import (
    STANCE_IMPLEMENT,
    compile_assignment,
    render_assignment,
)
from mcp_server import call_tool
from mission_runner import MissionResult
from prompt_compiler import compile_into_workbench
from stdlib_preview import generate_stdlib_preview

TASK_BOARD_SEED = (ROOT / "examples/seeds/task_board_web.md").read_text(
    encoding="utf-8"
)


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


def _render_preview(app: Path) -> str:
    inserted = str(app)
    sys.path.insert(0, inserted)
    for key in [k for k in sys.modules if k == "src" or k.startswith("src.")]:
        sys.modules.pop(key)
    try:
        import src.app as preview

        return preview.render_index([])
    finally:
        sys.modules.pop("src.app", None)
        sys.modules.pop("src.model", None)
        sys.modules.pop("src", None)
        if inserted in sys.path:
            sys.path.remove(inserted)


class PersistDeltaTests(unittest.TestCase):
    def test_append_delta_does_not_touch_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "habit"
            project = {
                "name": "habit",
                "app_path": str(app),
                "task_root": str(app / "factory_tasks"),
                "seed_file": "docs/seed.md",
            }
            compile_into_workbench(project, root, "build a habit tracker")
            seed_before = (app / "docs/seed.md").read_text(encoding="utf-8")
            arch_before = (app / "architecture.json").read_text(
                encoding="utf-8"
            )
            written = append_delta(
                project, root, "add a dark mode toggle"
            )
            self.assertTrue(written["delta"])
            self.assertEqual(
                (app / "docs/seed.md").read_text(encoding="utf-8"),
                seed_before,
            )
            self.assertEqual(
                (app / "architecture.json").read_text(encoding="utf-8"),
                arch_before,
            )
            self.assertIn(
                "dark mode", latest_delta(project, root).lower()
            )
            doc = (app / "docs/deltas.md").read_text(encoding="utf-8")
            self.assertIn("dark mode", doc.lower())
            changes = json.loads(
                (app / "data/change_requests.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(changes[-1], "add a dark mode toggle")
            self.assertEqual(len(load_deltas(project, root)), 1)

    def test_placeholder_is_not_specified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("demo", "apps/demo", root=root)
            project = ca.resolve_project(ca.load_registry(root), "demo")
            self.assertFalse(has_specified_product(project, root))


class IngestFollowUpTests(unittest.TestCase):
    def test_second_prompt_appends_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("habit", "apps/habit", root=root)
            project = ca.resolve_project(ca.load_registry(root), "habit")
            first = ca.ingest_start_context(
                project, root, prompt="build a habit tracker"
            )
            self.assertIsNotNone(first["compiled"])
            self.assertIsNone(first["delta"])
            seed = (root / "apps/habit/docs/seed.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Goal:", seed)
            second = ca.ingest_start_context(
                project, root, prompt="add a dark mode toggle"
            )
            self.assertIsNone(second["compiled"])
            self.assertIsNotNone(second["delta"])
            after = (root / "apps/habit/docs/seed.md").read_text(
                encoding="utf-8"
            )
            self.assertEqual(after, seed)
            arch = json.loads(
                (root / "apps/habit/architecture.json").read_text()
            )
            self.assertEqual(arch["stack"], "stdlib-web")
            self.assertIn(
                "dark mode", latest_delta(project, root).lower()
            )

    def test_cli_follow_up_prompt_does_not_recompile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            fake = _fake_mission("habit", str(root / "apps/habit"))
            with (
                patch("crazy_admin.find_repo_root", return_value=root),
                patch("crazy_admin.run_mission", return_value=fake),
                patch("sys.stdout", new_callable=StringIO),
            ):
                ca.main(
                    [
                        "run",
                        "habit",
                        "--prompt",
                        "build a habit tracker",
                        "--max-beats",
                        "1",
                    ]
                )
                seed = (root / "apps/habit/docs/seed.md").read_text(
                    encoding="utf-8"
                )
                ca.main(
                    [
                        "run",
                        "habit",
                        "--prompt",
                        "add a weekly view",
                        "--max-beats",
                        "1",
                    ]
                )
            after = (root / "apps/habit/docs/seed.md").read_text(
                encoding="utf-8"
            )
            self.assertEqual(after, seed)
            project = ca.resolve_project(ca.load_registry(root), "habit")
            self.assertIn("weekly view", latest_delta(project, root))


class AssignmentDeltaTests(unittest.TestCase):
    def test_delta_forces_implement_when_preview_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "habit"
            project = {
                "name": "habit",
                "app_path": str(app),
                "task_root": str(app / "factory_tasks"),
                "seed_file": "docs/seed.md",
            }
            compile_into_workbench(project, root, "build a habit tracker")
            _write(app / "src/app.py", "TITLE = 'habit'\n")
            append_delta(project, root, "add a dark mode toggle")
            assignment = compile_assignment(
                project,
                root,
                SimpleNamespace(
                    id="OBJ-1",
                    kind="code_birth",
                    title="Birth the application",
                    gap="no source",
                    why="greenfield",
                    focus="src/",
                ),
            )
            self.assertEqual(assignment.stance, STANCE_IMPLEMENT)
            self.assertIn("dark mode", assignment.owner_deltas[0].lower())
            body = render_assignment(assignment)
            self.assertIn("## Owner deltas", body)
            self.assertIn("do not replace the product", body.lower())


class McpContinueDeltaTests(unittest.TestCase):
    def test_continue_mission_prompt_is_a_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("habit", "apps/habit", root=root)
            project = ca.resolve_project(ca.load_registry(root), "habit")
            ca.ingest_start_context(
                project, root, prompt="build a habit tracker"
            )
            seed = (root / "apps/habit/docs/seed.md").read_text(
                encoding="utf-8"
            )
            fake = _fake_mission("habit", str(root / "apps/habit"))
            with patch("mcp_server.run_closed_mission", return_value=fake):
                result = call_tool(
                    "continue_mission",
                    {
                        "project_id": "habit",
                        "prompt": "add a dark mode toggle",
                        "max_beats": 1,
                    },
                    root,
                )
            self.assertFalse(result["isError"], result)
            body = json.loads(result["content"][0]["text"])
            self.assertIsNotNone(body["ingested"]["delta"])
            self.assertIsNone(body["ingested"]["compiled"])
            after = (root / "apps/habit/docs/seed.md").read_text(
                encoding="utf-8"
            )
            self.assertEqual(after, seed)
            self.assertIn(
                "dark mode", latest_delta(project, root).lower()
            )

    def test_start_mission_follow_up_is_a_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("habit", "apps/habit", root=root)
            project = ca.resolve_project(ca.load_registry(root), "habit")
            ca.ingest_start_context(
                project, root, prompt="build a habit tracker"
            )
            seed = (root / "apps/habit/docs/seed.md").read_text(
                encoding="utf-8"
            )
            fake = _fake_mission("habit", str(root / "apps/habit"))
            with patch("mcp_server.run_closed_mission", return_value=fake):
                result = call_tool(
                    "start_mission",
                    {
                        "project_id": "habit",
                        "prompt": "show streaks on the home screen",
                        "max_beats": 1,
                    },
                    root,
                )
            self.assertFalse(result["isError"], result)
            body = json.loads(result["content"][0]["text"])
            self.assertIsNone(body["ingested"]["compiled"])
            self.assertIsNotNone(body["ingested"]["delta"])
            after = (root / "apps/habit/docs/seed.md").read_text(
                encoding="utf-8"
            )
            self.assertEqual(after, seed)


class PreviewBannerTests(unittest.TestCase):
    def test_generated_preview_shows_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "habit"
            project = {
                "name": "habit",
                "app_path": str(app),
                "task_root": str(app / "factory_tasks"),
                "seed_file": "docs/seed.md",
            }
            compile_into_workbench(project, root, "build a habit tracker")
            seed = (app / "docs/seed.md").read_text(encoding="utf-8")
            files = generate_stdlib_preview(app, seed)
            for rel, body in files.items():
                _write(app / rel, body)
            append_delta(project, root, "add a dark mode toggle")
            page = _render_preview(app)
            self.assertIn("dark mode", page.lower())
            self.assertIn("owner-deltas", page)

    def test_injects_banner_into_pre_l0_05_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            _write(
                app / "src/app.py",
                "heading = 'App'\n"
                "page = (\n"
                '        f"<h1>{heading}</h1>"\n'
                '        "<form></form>"\n'
                ")\n",
            )
            self.assertTrue(
                inject_preview_banner(app, ["add a dark mode toggle"])
            )
            body = (app / "src/app.py").read_text(encoding="utf-8")
            self.assertIn("dark mode", body.lower())
            self.assertIn("owner-deltas", body)

    def test_task_board_fixture_unchanged(self) -> None:
        out = StdlibWebExecutor().execute(
            ExecutorRequest(
                objective_id="obj-1",
                objective_kind="code_birth",
                objective_title="Birth",
                gap="no source",
                why="proof",
                focus="src/",
                seed_text=TASK_BOARD_SEED,
                app_path="/tmp",
            )
        )
        self.assertTrue(out.ok, out.reason)
        self.assertIn("src/task_board.py", out.files)
        self.assertNotIn("src/app.py", out.files)


if __name__ == "__main__":
    unittest.main()
