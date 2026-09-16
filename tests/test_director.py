"""Director brief: product + mission + recommended next command (P5-01)."""

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
from director import (  # noqa: E402
    ACTION_CONTINUE,
    ACTION_DONE,
    ACTION_HUMAN,
    ACTION_IMPORT,
    ACTION_PICK,
    ACTION_PROVIDE_CONTEXT,
    ACTION_START,
    director_brief,
    mcp_surface,
    render_brief,
)
from mission_runner import (  # noqa: E402
    BUDGET_EXHAUSTED,
    COMPLETE,
    HUMAN_REQUIRED,
)

CLI_TODO_SEED = (ROOT / "examples/seeds/cli_todo_tracker.md").read_text(
    encoding="utf-8"
)


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


def _plant_mission(app: Path, outcome: str, reason: str) -> None:
    dest = app / "factory_reports" / "mission_result.json"
    _write(
        dest,
        json.dumps(
            {
                "outcome": outcome,
                "reason": reason,
                "beats": 2,
                "max_beats": 12,
                "artifact": str(app),
            }
        ),
    )
    _write(app / "factory_reports" / "MISSION_TRACE.md", f"# {outcome}\n")


def _accepted_todo(app: Path) -> None:
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
        "- [x] Implement src/todo.py\n- [x] Write tests/test_todo.py\n",
    )
    _write(
        app / "factory_tasks/validation_result.json",
        json.dumps({"status": "passed", "checks": []}),
    )
    _write(app / "factory_tasks/planned_task.json", "{}")


class CatalogBriefTests(unittest.TestCase):
    def test_empty_registry_recommends_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            payload = director_brief(root)
            self.assertIsNone(payload["project_id"])
            self.assertEqual(payload["next"]["action"], ACTION_IMPORT)
            self.assertEqual(payload["next"]["mcp_tool"], "import_project")

    def test_single_project_briefs_that_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("todo", "apps/todo", root=root)
            (root / "apps/todo/docs/seed.md").write_text(
                CLI_TODO_SEED, encoding="utf-8"
            )
            payload = director_brief(root)
            self.assertEqual(payload["project_id"], "todo")
            self.assertEqual(payload["next"]["action"], ACTION_START)

    def test_many_projects_recommends_pick(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("alpha", "apps/alpha", root=root)
            ca.startproject("beta", "apps/beta", root=root)
            payload = director_brief(root)
            self.assertIsNone(payload["project_id"])
            self.assertEqual(payload["next"]["action"], ACTION_PICK)
            self.assertEqual(payload["next"]["mcp_tool"], "list_projects")
            ids = {row["project_id"] for row in payload["projects"]}
            self.assertEqual(ids, {"alpha", "beta"})


class NextActionTests(unittest.TestCase):
    def test_placeholder_seed_recommends_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("todo", "apps/todo", root=root)
            payload = director_brief(root, project_id="todo")
            self.assertEqual(
                payload["next"]["action"], ACTION_PROVIDE_CONTEXT
            )
            self.assertEqual(payload["next"]["mcp_tool"], "start_mission")
            self.assertTrue(payload["placeholder_intent"])

    def test_real_seed_no_mission_recommends_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("todo", "apps/todo", root=root)
            (root / "apps/todo/docs/seed.md").write_text(
                CLI_TODO_SEED, encoding="utf-8"
            )
            payload = director_brief(root, project_id="todo")
            self.assertEqual(payload["next"]["action"], ACTION_START)
            self.assertEqual(payload["next"]["mcp_tool"], "start_mission")
            self.assertFalse(payload["placeholder_intent"])

    def test_budget_exhausted_recommends_continue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("todo", "apps/todo", root=root)
            (root / "apps/todo/docs/seed.md").write_text(
                CLI_TODO_SEED, encoding="utf-8"
            )
            _plant_mission(
                root / "apps/todo",
                BUDGET_EXHAUSTED,
                "beat budget 2 exhausted",
            )
            payload = director_brief(root, project_id="todo")
            self.assertEqual(payload["next"]["action"], ACTION_CONTINUE)
            self.assertEqual(payload["next"]["mcp_tool"], "continue_mission")
            self.assertIn("max-beats", payload["next"]["why"])

    def test_human_required_does_not_continue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("todo", "apps/todo", root=root)
            _plant_mission(
                root / "apps/todo",
                HUMAN_REQUIRED,
                "needs_owner_decision",
            )
            payload = director_brief(root, project_id="todo")
            self.assertEqual(payload["next"]["action"], ACTION_HUMAN)
            self.assertNotEqual(
                payload["next"]["mcp_tool"], "continue_mission"
            )
            self.assertNotEqual(payload["next"]["mcp_tool"], "start_mission")

    def test_complete_demo_ready_is_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("todo", "apps/todo", root=root)
            _accepted_todo(root / "apps/todo")
            _plant_mission(
                root / "apps/todo",
                COMPLETE,
                "acceptance evidence is complete",
            )
            payload = director_brief(root, project_id="todo")
            self.assertTrue(payload["demo_ready"])
            self.assertEqual(payload["next"]["action"], ACTION_DONE)
            self.assertIsNone(payload["next"]["mcp_tool"])

    def test_unknown_id_recommends_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            payload = director_brief(root, project_id="ghost")
            self.assertEqual(payload["next"]["action"], ACTION_IMPORT)
            self.assertEqual(payload["project_id"], "ghost")


class RenderAndSurfaceTests(unittest.TestCase):
    def test_render_includes_next_and_surface_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("todo", "apps/todo", root=root)
            payload = director_brief(root, project_id="todo")
            text = render_brief(payload)
            self.assertIn("# Director brief", text)
            self.assertIn("## Next", text)
            self.assertIn("start_mission", text)
            surface = mcp_surface()
            self.assertIn("director_brief", surface["featured"])
            self.assertIn("inspect_project", surface["inventory"])
            self.assertNotIn("call_coder", surface["featured"])
            self.assertNotIn("call_coder", surface["inventory"])


class CliBriefTests(unittest.TestCase):
    def test_brief_json_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("todo", "apps/todo", root=root)
            (root / "apps/todo/docs/seed.md").write_text(
                CLI_TODO_SEED, encoding="utf-8"
            )
            with (
                patch("crazy_admin.find_repo_root", return_value=root),
                patch("sys.stdout", new_callable=StringIO) as out,
            ):
                code = ca.main(["brief", "todo", "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["project_id"], "todo")
            self.assertEqual(payload["next"]["action"], ACTION_START)

    def test_brief_catalog_when_no_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            with (
                patch("crazy_admin.find_repo_root", return_value=root),
                patch("crazy_admin.Path.cwd", return_value=root),
                patch("sys.stdout", new_callable=StringIO) as out,
            ):
                code = ca.main(["brief", "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["next"]["action"], ACTION_IMPORT)
