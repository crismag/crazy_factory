"""Protocol tests for the Crazy Factory MCP server (Slice A)."""

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

import mcp_server  # noqa: E402
from crazy_admin import startproject  # noqa: E402
from mcp_server import (  # noqa: E402
    PROTOCOL,
    TOOLS,
    call_tool,
    handle_message,
    list_resources,
    serve,
)
from mission_runner import MissionResult  # noqa: E402


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
        "models:\n  planner: x\n", encoding="utf-8"
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


class ProtocolTests(unittest.TestCase):
    def test_initialize_and_tool_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            init = handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": PROTOCOL},
                },
                root,
            )
            assert init is not None
            self.assertEqual(init["result"]["protocolVersion"], PROTOCOL)
            self.assertEqual(
                init["result"]["serverInfo"]["name"], "crazy-factory"
            )
            listed = handle_message(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                root,
            )
            assert listed is not None
            names = [t["name"] for t in listed["result"]["tools"]]
            self.assertIn("director_brief", names)
            self.assertIn("list_projects", names)
            self.assertIn("inspect_project", names)
            self.assertIn("assess_project", names)
            self.assertNotIn("call_coder", names)
            self.assertNotIn("call_architect", names)
            self.assertEqual(names[:6], list(mcp_server.FEATURED_TOOLS))
            self.assertEqual(names[6:], list(mcp_server.INVENTORY_TOOLS))
            self.assertEqual(len(TOOLS), 14)
            self.assertIn(
                "Director",
                init["result"].get("instructions", ""),
            )

    def test_notification_has_no_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            self.assertIsNone(
                handle_message(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                    },
                    root,
                )
            )


class InspectViaMcpTests(unittest.TestCase):
    def test_import_inspect_assess_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            created = call_tool(
                "import_project",
                {"project_id": "todo", "path": "apps/todo"},
                root,
            )
            self.assertFalse(created["isError"], created)
            seed = (ROOT / "examples/seeds/cli_todo_tracker.md").read_text(
                encoding="utf-8"
            )
            (root / "apps/todo/docs/seed.md").write_text(
                seed, encoding="utf-8"
            )
            inspected = call_tool(
                "inspect_project", {"project_id": "todo"}, root
            )
            self.assertFalse(inspected["isError"], inspected)
            body = json.loads(inspected["content"][0]["text"])
            self.assertFalse(body["demo_ready"])
            self.assertIn("ZERO_CODE_OUTPUT", body["blocking_question"])
            self.assertTrue(body["objectives"])
            self.assertIn("mission", body)
            self.assertIsNone(body["mission"]["outcome"])

            assessed = call_tool(
                "assess_project", {"project_id": "todo"}, root
            )
            self.assertFalse(assessed["isError"], assessed)
            persist = root / "apps/todo/factory_state/product_model.json"
            self.assertTrue(persist.is_file(), persist)

            resources = handle_message(
                {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
                root,
            )
            assert resources is not None
            uris = [r["uri"] for r in resources["result"]["resources"]]
            self.assertIn("crazy://projects/todo/product", uris)
            read = handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "resources/read",
                    "params": {"uri": "crazy://projects/todo/findings"},
                },
                root,
            )
            assert read is not None
            text = read["result"]["contents"][0]["text"]
            findings = json.loads(text)
            self.assertIn("blocking_question", findings)
            self.assertTrue(findings["material_gaps"])

            listed = list_resources(root)
            self.assertTrue(
                any(r["uri"] == "crazy://projects" for r in listed)
            )

    def test_unknown_tool_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            result = call_tool("call_coder", {}, root)
            self.assertTrue(result["isError"])

    def test_jsonl_stdio_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            startproject("todo", "apps/todo", root=root)
            stdin = StringIO(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {},
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "inspect_project",
                            "arguments": {"project_id": "todo"},
                        },
                    }
                )
                + "\n"
            )
            stdout = StringIO()
            code = serve(root=root, stdin=stdin, stdout=stdout, jsonl=True)
            self.assertEqual(code, 0)
            lines = [ln for ln in stdout.getvalue().splitlines() if ln]
            self.assertEqual(len(lines), 2)
            init = json.loads(lines[0])
            self.assertEqual(init["id"], 1)
            called = json.loads(lines[1])
            payload = json.loads(called["result"]["content"][0]["text"])
            self.assertIn("blocking_question", payload)


class NoWorkerLeakTests(unittest.TestCase):
    def test_public_tools_are_intent_shaped(self) -> None:
        names = {t["name"] for t in TOOLS}
        for forbidden in (
            "call_architect",
            "call_planner",
            "call_coder",
            "call_reviewer",
        ):
            self.assertNotIn(forbidden, names)
        self.assertIn("start_mission", names)
        self.assertIn("continue_mission", names)
        self.assertIn("stop_mission", names)
        self.assertIn("director_brief", names)
        self.assertIn("list_projects", names)
        # Silence unused import lint on mcp_server helper access.
        self.assertTrue(mcp_server.SERVER_NAME)


class MissionToolTests(unittest.TestCase):
    def test_start_mission_completes_when_already_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            startproject("demo", "apps/demo", root=root)
            _make_accepted(root / "apps/demo")
            result = call_tool(
                "start_mission",
                {"project_id": "demo", "max_beats": 2},
                root,
            )
            self.assertFalse(result["isError"], result)
            body = json.loads(result["content"][0]["text"])
            self.assertEqual(body["outcome"], "COMPLETE")
            self.assertEqual(body["beats"], 0)
            self.assertTrue(body["artifact"])

    def test_start_mission_ingests_seed_and_creates_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            seed = root / "brief.md"
            seed.write_text(
                "Goal:\nBuild a task board.\n\nSuccess:\nAdd tasks.\n",
                encoding="utf-8",
            )
            fake = _fake_mission("board", str(root / "apps/board"))
            with patch(
                "mcp_server.run_closed_mission", return_value=fake
            ) as run:
                result = call_tool(
                    "start_mission",
                    {
                        "project_id": "board",
                        "seed": str(seed),
                        "target": "apps/board",
                        "max_beats": 1,
                    },
                    root,
                )
            self.assertFalse(result["isError"], result)
            run.assert_called_once()
            body = json.loads(result["content"][0]["text"])
            self.assertEqual(body["outcome"], "BUDGET_EXHAUSTED")
            self.assertEqual(
                (root / "apps/board/docs/seed.md").read_text(encoding="utf-8"),
                seed.read_text(encoding="utf-8"),
            )
            self.assertIsNotNone(body["ingested"]["seed"])

    def test_start_mission_inline_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            text = "Goal:\nInline board.\n\nSuccess:\nShip it.\n"
            fake = _fake_mission("inline", str(root / "apps/inline"))
            with patch("mcp_server.run_closed_mission", return_value=fake):
                result = call_tool(
                    "start_mission",
                    {
                        "project_id": "inline",
                        "context": text,
                        "max_beats": 1,
                    },
                    root,
                )
            self.assertFalse(result["isError"], result)
            written = (root / "apps/inline/docs/seed.md").read_text(
                encoding="utf-8"
            )
            self.assertEqual(written, text)

    def test_start_mission_missing_seed_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            result = call_tool(
                "start_mission",
                {
                    "project_id": "ghost",
                    "seed": "no-such-seed.md",
                    "max_beats": 1,
                },
                root,
            )
            self.assertTrue(result["isError"])
            body = json.loads(result["content"][0]["text"])
            self.assertIn("not found", body["error"])

    def test_status_and_inspect_include_mission_after_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            startproject("demo", "apps/demo", root=root)
            app = root / "apps/demo"
            _make_accepted(app)
            started = call_tool(
                "start_mission",
                {"project_id": "demo", "max_beats": 2},
                root,
            )
            self.assertFalse(started["isError"], started)
            status = call_tool("get_status", {"project_id": "demo"}, root)
            self.assertFalse(status["isError"], status)
            status_body = json.loads(status["content"][0]["text"])
            mission = status_body["mission"]
            self.assertEqual(mission["outcome"], "COMPLETE")
            self.assertTrue(mission["artifact"])
            self.assertTrue(mission["trace"])
            self.assertTrue(Path(mission["trace"]).is_file())
            inspected = call_tool(
                "inspect_project", {"project_id": "demo"}, root
            )
            inspect_body = json.loads(inspected["content"][0]["text"])
            self.assertEqual(inspect_body["mission"]["outcome"], "COMPLETE")
            self.assertEqual(
                inspect_body["mission"]["trace"], mission["trace"]
            )


class DirectorMcpTests(unittest.TestCase):
    def test_list_projects_and_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            startproject("todo", "apps/todo", root=root)
            seed = (ROOT / "examples/seeds/cli_todo_tracker.md").read_text(
                encoding="utf-8"
            )
            (root / "apps/todo/docs/seed.md").write_text(
                seed, encoding="utf-8"
            )
            listed = call_tool("list_projects", {}, root)
            self.assertFalse(listed["isError"], listed)
            body = json.loads(listed["content"][0]["text"])
            self.assertEqual(body["projects"][0]["project_id"], "todo")
            self.assertIn("director_brief", body["featured"])
            briefed = call_tool(
                "director_brief", {"project_id": "todo"}, root
            )
            self.assertFalse(briefed["isError"], briefed)
            payload = json.loads(briefed["content"][0]["text"])
            self.assertEqual(payload["next"]["action"], "start")
            self.assertEqual(payload["next"]["mcp_tool"], "start_mission")
            catalog = call_tool("director_brief", {}, root)
            catalog_body = json.loads(catalog["content"][0]["text"])
            self.assertEqual(catalog_body["project_id"], "todo")
