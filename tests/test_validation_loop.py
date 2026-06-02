"""Smoke tests for the Crazy Factory Phase 2 planning loop.

These tests cover the dry-run boundaries without calling Ollama or modifying
the demo application's source directory. Temporary directories are used for
report and state-write checks.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from factory_tick import (  # noqa: E402
    RoleResult,
    fallback_architect_result,
    fallback_planner_result,
    load_active_project,
    load_configuration,
    planning_paths,
    render_next_action,
    render_task_expansion,
    requested_control_action,
    request_architect_result,
    request_planner_result,
    update_success_state,
    validate_dry_run_settings,
)
from ollama_client import OllamaConnectionError  # noqa: E402
from repo_tools import read_markdown_directory, safe_write_text  # noqa: E402
from report_writer import append_dry_run_report  # noqa: E402


class ValidationLoopSmokeTests(unittest.TestCase):
    """Verify Phase 2 planning behavior and safety boundaries."""

    def setUp(self) -> None:
        """Store the repository root used by read-only fixture checks."""
        self.repo_root = Path(__file__).resolve().parents[1]

    def test_loads_config_and_active_project(self) -> None:
        """Load configuration and resolve the seeded demo workbench."""
        factory_config, projects_config = load_configuration(self.repo_root)
        project_name, project = load_active_project(
            factory_config["factory"], projects_config
        )
        self.assertEqual(project_name, "demo_app")
        self.assertEqual(project["task_root"], "apps/demo_app/factory_tasks")

    def test_stop_takes_precedence_over_pause(self) -> None:
        """Prefer an explicit stop when both owner control flags are active."""
        state = {"pause_requested": True, "stop_requested": True}
        self.assertEqual(requested_control_action(state), "stopped")
        self.assertEqual(
            requested_control_action({"pause_requested": True}), "paused"
        )
        self.assertIsNone(requested_control_action({}))

    def test_loads_project_context(self) -> None:
        """Load the active project's Markdown context package."""
        contexts = read_markdown_directory(
            "apps/demo_app/factory_context", repo_root=self.repo_root
        )
        self.assertIn(
            "apps/demo_app/factory_context/PROJECT_GOAL.md", contexts
        )

    def test_rejects_broad_write_capabilities(self) -> None:
        """Refuse dry-run configuration that enables broad file writes."""
        with self.assertRaises(RuntimeError):
            validate_dry_run_settings(
                {
                    "mode": "dry_run",
                    "allow_application_writes": True,
                    "allow_factory_writes": False,
                    "allow_commit": False,
                    "allow_push": False,
                }
            )

    def test_success_state_records_resume_information(self) -> None:
        """Update recovery state after a successful planning validation."""
        factory_state: dict[str, object] = {}
        active_run: dict[str, object] = {}
        project_state: dict[str, object] = {}
        architect_result = RoleResult(
            "architect", "Expand only.", "fallback", "offline"
        )
        planner_result = RoleResult(
            "planner", "Plan only.", "fallback", "offline"
        )
        completed_at = update_success_state(
            factory_state,
            active_run,
            {"current_task": "DEMO-002", **project_state},
            architect_result,
            planner_result,
        )
        self.assertTrue(completed_at.endswith("Z"))
        self.assertEqual(factory_state["last_architect_source"], "fallback")
        self.assertEqual(factory_state["last_planner_source"], "fallback")
        self.assertEqual(factory_state["last_role_completed"], "reporter")
        self.assertEqual(active_run["current_phase"], "WAIT")
        self.assertEqual(active_run["task_id"], "DEMO-002")
        self.assertIn("NEXT_ACTION.md", str(active_run["resume_from"]))

    def test_planning_paths_stay_inside_project(self) -> None:
        """Restrict planning writes to two fixed files in the workbench."""
        project = {
            "root": "apps/demo_app",
            "task_root": "apps/demo_app/factory_tasks",
        }
        expansion, next_action = planning_paths(self.repo_root, project)
        self.assertEqual(
            expansion, "apps/demo_app/factory_tasks/TASK_EXPANSION.md"
        )
        self.assertEqual(
            next_action, "apps/demo_app/factory_tasks/NEXT_ACTION.md"
        )
        with self.assertRaises(RuntimeError):
            planning_paths(
                self.repo_root,
                {"root": "apps/demo_app", "task_root": "reports"},
            )

    def test_architect_request_falls_back_when_ollama_is_unavailable(
        self,
    ) -> None:
        """Produce deterministic planning when the local model is offline."""
        factory_config, projects_config = load_configuration(self.repo_root)
        project_name, project = load_active_project(
            factory_config["factory"], projects_config
        )
        models_config = {
            "models": {
                "architect": "cogito:14b",
            }
        }
        project_state = {
            "current_task": "DEMO-002",
            "current_milestone": "DEMO-M2",
        }
        with patch(
            "factory_tick.OllamaClient.chat",
            side_effect=OllamaConnectionError("offline"),
        ):
            result = request_architect_result(
                project_name=project_name,
                project=project,
                project_state=project_state,
                factory_config=factory_config,
                models_config=models_config,
                max_lines=20,
                tasks={"CURRENT_TASK.md": "# Current Task"},
            )
        self.assertEqual(result.source, "fallback")
        self.assertIn("Do not generate application code", result.content)

    def test_planner_request_falls_back_when_ollama_is_unavailable(
        self,
    ) -> None:
        """Produce a fallback next action when the local model is offline."""
        factory_config, projects_config = load_configuration(self.repo_root)
        project_name, project = load_active_project(
            factory_config["factory"], projects_config
        )
        models_config = {"models": {"planner": "cogito:14b"}}
        project_state = {"current_task": "DEMO-002"}
        architect_result = RoleResult(
            "architect", "Review architecture.", "fallback", "offline"
        )
        with patch(
            "factory_tick.OllamaClient.chat",
            side_effect=OllamaConnectionError("offline"),
        ):
            result = request_planner_result(
                project_name=project_name,
                project=project,
                project_state=project_state,
                factory_config=factory_config,
                models_config=models_config,
                max_lines=20,
                tasks={"CURRENT_TASK.md": "# Current Task"},
                architect_result=architect_result,
            )
        self.assertEqual(result.source, "fallback")
        self.assertIn("TASK_EXPANSION.md", result.content)

    def test_writes_task_expansion_and_next_action(self) -> None:
        """Write both fixed planning files inside a temporary task root."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_root = root / "apps/demo/factory_tasks"
            task_root.mkdir(parents=True)
            architect_result = RoleResult(
                "architect", "Expand safely.", "fallback", "offline"
            )
            planner_result = RoleResult(
                "planner", "Review the expansion.", "fallback", "offline"
            )
            expansion_path = "apps/demo/factory_tasks/TASK_EXPANSION.md"
            next_action_path = "apps/demo/factory_tasks/NEXT_ACTION.md"
            safe_write_text(
                expansion_path,
                render_task_expansion(architect_result),
                repo_root=root,
                allowed_roots=["apps/demo/factory_tasks"],
            )
            safe_write_text(
                next_action_path,
                render_next_action(planner_result),
                repo_root=root,
                allowed_roots=["apps/demo/factory_tasks"],
            )
            self.assertIn(
                "Expand safely.",
                (root / expansion_path).read_text(encoding="utf-8"),
            )
            self.assertIn(
                "Review the expansion.",
                (root / next_action_path).read_text(encoding="utf-8"),
            )

    def test_report_writer_creates_app_and_activity_reports(self) -> None:
        """Write reports only inside temporary approved report directories."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "reports").mkdir()
            (root / "apps/demo/factory_reports").mkdir(parents=True)
            (root / "reports/ACTIVITY_BLOG.md").write_text(
                "# Activity Blog\n", encoding="utf-8"
            )
            (root / "reports/DAILY_REPORT.md").write_text(
                "# Daily Report\n", encoding="utf-8"
            )
            report_path = append_dry_run_report(
                project_name="demo",
                project_report_root="apps/demo/factory_reports",
                mode="dry_run",
                context_files=["context.md"],
                task_files=["task.md"],
                git_status="clean",
                factory_state={"last_failed_run": None},
                active_run={"resume_from": "Review planning."},
                project_state={
                    "current_task": "DEMO-TEST",
                    "current_milestone": "DEMO-M",
                    "last_completed_checkpoint": None,
                    "failure_count": 0,
                    "current_blocker": None,
                },
                architect_source="fallback",
                architect_detail="offline",
                planner_source="fallback",
                planner_detail="offline",
                last_role_completed="reporter",
                planning_files=["TASK_EXPANSION.md", "NEXT_ACTION.md"],
                repo_root=root,
            )
            self.assertTrue(report_path.is_file())
            report = report_path.read_text(encoding="utf-8")
            activity = (root / "reports/ACTIVITY_BLOG.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Architect Dry Run", report)
            self.assertIn("fallback", activity)

    def test_fallback_content_is_planning_only(self) -> None:
        """Keep deterministic fallback output inside planning boundaries."""
        result = fallback_architect_result(
            "demo_app",
            {"current_task": "DEMO-002", "current_milestone": "DEMO-M2"},
            "offline",
        )
        self.assertEqual(result.source, "fallback")
        self.assertIn("Do not edit arbitrary files", result.content)

    def test_planner_fallback_content_is_planning_only(self) -> None:
        """Keep deterministic Planner fallback inside planning boundaries."""
        result = fallback_planner_result(
            {"current_task": "DEMO-002"}, "offline"
        )
        self.assertEqual(result.role, "planner")
        self.assertIn("application writes disabled", result.content)


if __name__ == "__main__":
    unittest.main()
