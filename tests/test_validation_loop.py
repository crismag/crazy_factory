"""Smoke tests for the Crazy Factory Phase 2 planning loop.

These tests cover the dry-run boundaries without calling Ollama or modifying
the demo application's source directory. Temporary directories are used for
report and state-write checks.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from contract_stage import (  # noqa: E402
    ContractResult,
    contract_paths,
    contract_status_label,
    load_existing_contract,
    request_task_contract,
    run_contract_stage,
)
from mission_state import (  # noqa: E402
    requested_control_action,
    update_success_state,
)
from planning_roles import (  # noqa: E402
    RoleResult,
    fallback_architect_result,
    fallback_planner_result,
    planning_paths,
    render_next_action,
    render_task_expansion,
    request_architect_result,
    request_planner_result,
)
from advance_config import validate_dry_run_settings  # noqa: E402
from ollama_client import OllamaConnectionError  # noqa: E402
from repo_tools import read_markdown_directory, safe_write_text  # noqa: E402
from report_writer import append_dry_run_report  # noqa: E402
from task_contract import (  # noqa: E402
    PlannedTask,
    ValidationVerdict,
    contract_to_dict,
    is_contract_actionable,
    parse_planned_task,
    render_planned_task_md,
    validate_planned_task,
)
from task_contract import ContractParseError  # noqa: E402

# Synthetic config/project used by request tests so they do not depend on a
# committed app workbench. context_root points at the committed global
# contexts/ directory so prompt assembly finds a real directory.
_OLLAMA_CONFIG = {
    "ollama": {
        "base_url": "http://localhost:11434",
        "timeout_seconds": 1,
        "stream": False,
    }
}
_TEST_PROJECT = {
    "root": "apps/demo",
    "task_root": "apps/demo/factory_tasks",
    "context_root": "contexts",
}


class ValidationLoopSmokeTests(unittest.TestCase):
    """Verify Phase 2 planning behavior and safety boundaries."""

    def setUp(self) -> None:
        """Store the repository root used by read-only fixture checks."""
        self.repo_root = Path(__file__).resolve().parents[1]

    def test_stop_takes_precedence_over_pause(self) -> None:
        """Prefer an explicit stop when both owner control flags are active."""
        state = {"pause_requested": True, "stop_requested": True}
        self.assertEqual(requested_control_action(state), "stopped")
        self.assertEqual(
            requested_control_action({"pause_requested": True}), "paused"
        )
        self.assertIsNone(requested_control_action({}))

    def test_loads_a_committed_context_directory(self) -> None:
        """Load a committed Markdown context package (global contexts)."""
        contexts = read_markdown_directory(
            "contexts", repo_root=self.repo_root
        )
        self.assertIn("contexts/GLOBAL_MISSION.md", contexts)

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
        factory_config = _OLLAMA_CONFIG
        project_name, project = "demo", _TEST_PROJECT
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
            "planning_roles.OllamaClient.chat",
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
        factory_config = _OLLAMA_CONFIG
        project_name, project = "demo", _TEST_PROJECT
        models_config = {"models": {"planner": "cogito:14b"}}
        project_state = {"current_task": "DEMO-002"}
        architect_result = RoleResult(
            "architect", "Review architecture.", "fallback", "offline"
        )
        with patch(
            "planning_roles.OllamaClient.chat",
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

    def _run_planner(self, reply: str) -> RoleResult:
        architect_result = RoleResult(
            "architect", "Review architecture.", "fallback", "offline"
        )
        with patch(
            "planning_roles.OllamaClient.chat",
            return_value={"message": {"content": reply}},
        ):
            return request_planner_result(
                project_name="demo",
                project=_TEST_PROJECT,
                project_state={"current_task": "DEMO-002"},
                factory_config=_OLLAMA_CONFIG,
                models_config={"models": {"planner": "cogito:14b"}},
                max_lines=20,
                tasks={"CURRENT_TASK.md": "# Current Task"},
                architect_result=architect_result,
            )

    def test_planner_refusal_is_never_stored(self) -> None:
        """9E.7: a model refusal falls back; it is not stored as the action."""
        result = self._run_planner(
            "I'm sorry, I can't complete the request. Feel free to ask!"
        )
        self.assertEqual(result.source, "fallback")
        self.assertNotIn("i'm sorry", result.content.lower())

    def test_planner_valid_json_action_is_used(self) -> None:
        """A well-formed JSON action is rendered into the next-action record."""
        result = self._run_planner(
            '{"next_action": "Implement src/task_model.py", '
            '"kind": "implement", "rationale": "foundation first"}'
        )
        self.assertEqual(result.source, "ollama")
        self.assertIn("Implement src/task_model.py", result.content)
        self.assertIn("Next action:", result.content)

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
            (root / "apps/demo/factory_reports").mkdir(parents=True)
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
            activity = (
                root / "apps/demo/factory_reports/ACTIVITY_BLOG.md"
            ).read_text(encoding="utf-8")
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


def _valid_contract_dict() -> dict[str, object]:
    """Return a well-formed task-contract mapping for tests."""
    return {
        "task_id": "DEMO-002",
        "title": "Document the planning contract format",
        "objective": "Describe the planned_task.json schema in demo docs.",
        "scope": ["Write a short schema description in the docs"],
        "exclusions": ["No application code changes", "No git operations"],
        "inputs": ["PLANNED_TASK_TEMPLATE.md"],
        "acceptance_criteria": [
            "Schema fields are listed",
            "Owner confirms accuracy",
        ],
        "validation_plan": "Owner reads the doc and confirms it is accurate.",
        "risks": ["None significant"],
        "approval_status": "pending",
    }


class TaskContractTests(unittest.TestCase):
    """Verify Phase 3 structured planning-contract behavior."""

    def setUp(self) -> None:
        """Store the repository root for tests that read fixtures."""
        self.repo_root = Path(__file__).resolve().parents[1]

    def test_parse_valid_contract(self) -> None:
        """Parse a well-formed JSON contract into a planned task."""
        task = parse_planned_task(json.dumps(_valid_contract_dict()))
        self.assertEqual(task.task_id, "DEMO-002")
        self.assertEqual(len(task.acceptance_criteria), 2)
        self.assertFalse(task.authorized)

    def test_parse_strips_code_fence(self) -> None:
        """Tolerate JSON wrapped in a Markdown code fence."""
        fenced = "```json\n" + json.dumps(_valid_contract_dict()) + "\n```"
        task = parse_planned_task(fenced)
        self.assertEqual(task.title, "Document the planning contract format")

    def test_parse_coerces_scalar_scope_to_list(self) -> None:
        """Wrap a single scope string into a one-item list."""
        data = _valid_contract_dict()
        data["scope"] = "Write one short doc section"
        task = parse_planned_task(json.dumps(data))
        self.assertEqual(task.scope, ["Write one short doc section"])

    def test_parse_rejects_non_json(self) -> None:
        """Raise a parse error when output is not a JSON object."""
        with self.assertRaises(ContractParseError):
            parse_planned_task("not a contract at all")
        with self.assertRaises(ContractParseError):
            parse_planned_task("[1, 2, 3]")

    def test_validate_accepts_complete_contract(self) -> None:
        """Accept a complete, bounded, unauthorized contract."""
        verdict = validate_planned_task(
            parse_planned_task(json.dumps(_valid_contract_dict()))
        )
        self.assertTrue(verdict.valid)
        self.assertEqual(verdict.reasons, [])

    def test_validate_rejects_missing_acceptance_criteria(self) -> None:
        """Reject a contract that defines no completion criteria."""
        data = _valid_contract_dict()
        data["acceptance_criteria"] = []
        verdict = validate_planned_task(parse_planned_task(json.dumps(data)))
        self.assertFalse(verdict.valid)
        self.assertTrue(
            any("acceptance criteria" in r.lower() for r in verdict.reasons)
        )

    def test_validate_rejects_missing_exclusions(self) -> None:
        """Reject a contract with no explicit exclusions."""
        data = _valid_contract_dict()
        data["exclusions"] = []
        verdict = validate_planned_task(parse_planned_task(json.dumps(data)))
        self.assertFalse(verdict.valid)
        self.assertTrue(any("exclusion" in r.lower() for r in verdict.reasons))

    def test_validate_rejects_forbidden_scope(self) -> None:
        """Reject a contract whose scope references forbidden operations."""
        data = _valid_contract_dict()
        data["scope"] = ["git push to origin and merge into main"]
        verdict = validate_planned_task(parse_planned_task(json.dumps(data)))
        self.assertFalse(verdict.valid)
        self.assertTrue(any("forbidden" in r.lower() for r in verdict.reasons))

    def test_validate_rejects_self_authorization(self) -> None:
        """Reject any contract that arrives pre-authorized."""
        data = _valid_contract_dict()
        data["authorized"] = True
        verdict = validate_planned_task(parse_planned_task(json.dumps(data)))
        self.assertFalse(verdict.valid)
        self.assertTrue(
            any("authorized" in r.lower() for r in verdict.reasons)
        )

    def test_validate_rejects_approved_status(self) -> None:
        """Reject a contract that proposes an already-approved status."""
        data = _valid_contract_dict()
        data["approval_status"] = "approved"
        verdict = validate_planned_task(parse_planned_task(json.dumps(data)))
        self.assertFalse(verdict.valid)

    def test_contract_to_dict_forces_authorized_false(self) -> None:
        """Persist authorized=false even if the task claims otherwise."""
        task = PlannedTask(
            task_id="X",
            title="t",
            objective="o",
            validation_plan="v",
            scope=["s"],
            exclusions=["e"],
            acceptance_criteria=["a"],
            authorized=True,
        )
        verdict = validate_planned_task(task)
        record = contract_to_dict(task, verdict, "ollama")
        self.assertFalse(record["authorized"])
        self.assertEqual(record["approval_status"], "pending")

    def test_contract_to_dict_for_missing_task(self) -> None:
        """Render a rejected record when no contract was produced."""
        from task_contract import ValidationVerdict

        record = contract_to_dict(
            None, ValidationVerdict(False, ["offline"]), "fallback"
        )
        self.assertFalse(record["authorized"])
        self.assertEqual(record["validation"]["status"], "rejected")
        self.assertIsNone(record["task_id"])

    def test_render_planned_task_md_includes_status(self) -> None:
        """Render owner-facing Markdown noting authorized=false."""
        task = parse_planned_task(json.dumps(_valid_contract_dict()))
        verdict = validate_planned_task(task)
        text = render_planned_task_md(
            task, verdict, source="ollama", detail="model"
        )
        self.assertIn("Planned Task Contract", text)
        self.assertIn("authorized: false", text.replace("`", "").lower())

    def test_contract_paths_stay_inside_project(self) -> None:
        """Restrict contract writes to two fixed files in the workbench."""
        project = {
            "root": "apps/demo_app",
            "task_root": "apps/demo_app/factory_tasks",
        }
        json_path, md_path = contract_paths(self.repo_root, project)
        self.assertEqual(
            json_path, "apps/demo_app/factory_tasks/planned_task.json"
        )
        self.assertEqual(
            md_path, "apps/demo_app/factory_tasks/PLANNED_TASK.md"
        )
        with self.assertRaises(RuntimeError):
            contract_paths(
                self.repo_root,
                {"root": "apps/demo_app", "task_root": "reports"},
            )

    def test_contract_request_falls_back_when_ollama_unavailable(
        self,
    ) -> None:
        """Return a rejected contract when the local model is offline."""
        factory_config = _OLLAMA_CONFIG
        project_name, project = "demo", _TEST_PROJECT
        architect_result = RoleResult("architect", "x", "fallback", "off")
        planner_result = RoleResult("planner", "y", "fallback", "off")
        with patch(
            "contract_stage.OllamaClient.chat",
            side_effect=OllamaConnectionError("offline"),
        ):
            result = request_task_contract(
                project_name=project_name,
                project=project,
                factory_config=factory_config,
                models_config={"models": {"planner": "cogito:14b"}},
                max_lines=20,
                tasks={"CURRENT_TASK.md": "# Current Task"},
                architect_result=architect_result,
                planner_result=planner_result,
            )
        self.assertEqual(result.source, "fallback")
        self.assertIsNone(result.task)
        self.assertFalse(result.verdict.valid)

    def test_contract_request_rejects_unparseable_response(self) -> None:
        """Reject an Ollama response that is not a JSON contract."""
        factory_config = _OLLAMA_CONFIG
        project_name, project = "demo", _TEST_PROJECT
        architect_result = RoleResult("architect", "x", "ollama", "m")
        planner_result = RoleResult("planner", "y", "ollama", "m")
        with patch(
            "contract_stage.OllamaClient.chat",
            return_value={"message": {"content": "definitely not json"}},
        ):
            result = request_task_contract(
                project_name=project_name,
                project=project,
                factory_config=factory_config,
                models_config={"models": {"planner": "cogito:14b"}},
                max_lines=20,
                tasks={"CURRENT_TASK.md": "# Current Task"},
                architect_result=architect_result,
                planner_result=planner_result,
            )
        self.assertEqual(result.source, "ollama")
        self.assertIsNone(result.task)
        self.assertFalse(result.verdict.valid)

    def test_contract_request_validates_ollama_contract(self) -> None:
        """Validate a well-formed contract returned by Ollama."""
        factory_config = _OLLAMA_CONFIG
        project_name, project = "demo", _TEST_PROJECT
        architect_result = RoleResult("architect", "x", "ollama", "m")
        planner_result = RoleResult("planner", "y", "ollama", "m")
        content = json.dumps(_valid_contract_dict())
        with patch(
            "contract_stage.OllamaClient.chat",
            return_value={"message": {"content": content}},
        ):
            result = request_task_contract(
                project_name=project_name,
                project=project,
                factory_config=factory_config,
                models_config={"models": {"planner": "cogito:14b"}},
                max_lines=20,
                tasks={"CURRENT_TASK.md": "# Current Task"},
                architect_result=architect_result,
                planner_result=planner_result,
            )
        self.assertEqual(result.source, "ollama")
        self.assertIsNotNone(result.task)
        self.assertTrue(result.verdict.valid)

    def test_rejected_contract_increments_failure_and_blocks(self) -> None:
        """Record a rejection as a failure with a blocker, not a crash."""
        from task_contract import ValidationVerdict

        factory_state: dict[str, object] = {"failure_count": 0}
        active_run: dict[str, object] = {}
        project_state: dict[str, object] = {
            "current_task": "DEMO-002",
            "failure_count": 0,
        }
        contract = ContractResult(
            None, ValidationVerdict(False, ["bad"]), "ollama", "m"
        )
        update_success_state(
            factory_state,
            active_run,
            project_state,
            RoleResult("architect", "x", "ollama", "m"),
            RoleResult("planner", "y", "ollama", "m"),
            contract_result=contract,
        )
        self.assertEqual(project_state["failure_count"], 1)
        self.assertEqual(
            project_state["current_blocker"], "planning_contract_rejected"
        )
        self.assertEqual(project_state["last_contract_status"], "rejected")
        self.assertIn("rejected", str(active_run["resume_from"]).lower())

    def test_valid_contract_sets_owner_review_resume(self) -> None:
        """A valid contract waits for owner authorization, no failure bump."""
        task = parse_planned_task(json.dumps(_valid_contract_dict()))
        contract = ContractResult(
            task, validate_planned_task(task), "ollama", "m"
        )
        factory_state: dict[str, object] = {"failure_count": 0}
        active_run: dict[str, object] = {}
        project_state: dict[str, object] = {
            "current_task": "DEMO-002",
            "failure_count": 0,
        }
        update_success_state(
            factory_state,
            active_run,
            project_state,
            RoleResult("architect", "x", "ollama", "m"),
            RoleResult("planner", "y", "ollama", "m"),
            contract_result=contract,
        )
        self.assertEqual(project_state["failure_count"], 0)
        self.assertIsNone(project_state["current_blocker"])
        self.assertFalse(project_state["contract_authorized"])
        self.assertIn("authorized=true", str(active_run["resume_from"]))

    def test_report_includes_contract_section(self) -> None:
        """Write a Task Contract section into the session report."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "apps/demo/factory_reports").mkdir(parents=True)
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
                contract_status="rejected",
                contract_source="ollama",
                contract_detail="model",
                contract_reasons=["No acceptance criteria define completion"],
                contract_files=["planned_task.json", "PLANNED_TASK.md"],
                repo_root=root,
            )
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("Task Contract", report)
            self.assertIn("authorized: false", report.replace("`", "").lower())
            self.assertIn("No acceptance criteria", report)


class ContractHardeningTests(unittest.TestCase):
    """Verify the fixes for unwired/unhandled Phase 3 corners."""

    def setUp(self) -> None:
        """Store the repository root for tests that read fixtures."""
        self.repo_root = Path(__file__).resolve().parents[1]

    def test_nested_object_in_text_field_is_rejected(self) -> None:
        """Fix #3: an object in a text field is empty, not stringified."""
        data = _valid_contract_dict()
        data["validation_plan"] = {"checklist_items": ["a", "b"]}
        task = parse_planned_task(json.dumps(data))
        self.assertEqual(task.validation_plan, "")
        verdict = validate_planned_task(task)
        self.assertFalse(verdict.valid)
        self.assertTrue(any("validation_plan" in r for r in verdict.reasons))

    def test_nested_objects_in_list_are_dropped(self) -> None:
        """Fix #3: object elements in a list field are discarded."""
        data = _valid_contract_dict()
        data["acceptance_criteria"] = [{"k": "v"}, "real criterion"]
        task = parse_planned_task(json.dumps(data))
        self.assertEqual(task.acceptance_criteria, ["real criterion"])

    def test_actionable_requires_authorized_and_revalidated(self) -> None:
        """#2/P1: actionable needs authorized=true AND current content valid.

        The cached ``validation.status`` is never trusted; the record's
        current fields are revalidated on every check.
        """
        authorized = {
            **_valid_contract_dict(),
            "authorized": True,
            "validation": {"status": "valid"},
        }
        self.assertTrue(is_contract_actionable(authorized))

        # Valid content but unauthorized is not actionable.
        self.assertFalse(
            is_contract_actionable({**authorized, "authorized": False})
        )
        # P1: authorized but body tampered after the fact (scope emptied),
        # while a stale "valid" status remains -> not actionable.
        self.assertFalse(is_contract_actionable({**authorized, "scope": []}))
        # P1: authorized but a forbidden op slipped into acceptance_criteria.
        self.assertFalse(
            is_contract_actionable(
                {**authorized, "acceptance_criteria": ["git push to origin"]}
            )
        )
        # A stale "valid" status cannot rescue missing required content.
        self.assertFalse(
            is_contract_actionable(
                {"authorized": True, "validation": {"status": "valid"}}
            )
        )
        # Non-mapping input is never actionable.
        self.assertFalse(is_contract_actionable(["not", "a", "dict"]))
        self.assertFalse(is_contract_actionable(None))

    def test_forbidden_op_in_acceptance_criteria_is_rejected(self) -> None:
        """Forbidden ops cannot bypass the scan via acceptance_criteria."""
        data = _valid_contract_dict()
        data["acceptance_criteria"] = ["git push to origin"]
        verdict = validate_planned_task(parse_planned_task(json.dumps(data)))
        self.assertFalse(verdict.valid)
        self.assertTrue(any("forbidden" in r.lower() for r in verdict.reasons))

    def test_forbidden_op_in_validation_plan_is_rejected(self) -> None:
        """Forbidden ops cannot bypass the scan via validation_plan."""
        data = _valid_contract_dict()
        data["validation_plan"] = "merge into main and force push"
        verdict = validate_planned_task(parse_planned_task(json.dumps(data)))
        self.assertFalse(verdict.valid)
        self.assertTrue(any("forbidden" in r.lower() for r in verdict.reasons))

    def test_exclusions_may_mention_forbidden_ops(self) -> None:
        """Exclusions remain the safe harbor for negative statements."""
        data = _valid_contract_dict()
        data["exclusions"] = [
            "Do not push to origin",
            "Do not merge into main",
        ]
        verdict = validate_planned_task(parse_planned_task(json.dumps(data)))
        self.assertTrue(verdict.valid)

    def test_preserves_authorized_contract_without_regenerating(self) -> None:
        """#1/P2: an authorized valid contract is kept; Markdown refreshed."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_root = root / "apps/demo/factory_tasks"
            task_root.mkdir(parents=True)
            project = {
                "root": "apps/demo",
                "task_root": "apps/demo/factory_tasks",
                "context_root": "apps/demo/factory_context",
            }
            authorized = {
                **_valid_contract_dict(),
                "authorized": True,
                "validation": {"status": "valid", "reasons": []},
            }
            contract_file = task_root / "planned_task.json"
            original = json.dumps(authorized, indent=2)
            contract_file.write_text(original, encoding="utf-8")
            # A stale Markdown view still claiming approval is required.
            md_file = task_root / "PLANNED_TASK.md"
            md_file.write_text(
                "# stale\n- Authorized: `false` (owner approval required)\n",
                encoding="utf-8",
            )

            # chat must never be called when a contract is preserved.
            with patch(
                "contract_stage.OllamaClient.chat",
                side_effect=AssertionError("must not regenerate"),
            ):
                result, _, _ = run_contract_stage(
                    project_name="demo",
                    root=root,
                    project=project,
                    factory_config={"ollama": {}},
                    models_config={"models": {"planner": "cogito:14b"}},
                    max_lines=20,
                    tasks={"CURRENT_TASK.md": "# Current Task"},
                    architect_result=RoleResult("a", "x", "ollama", "m"),
                    planner_result=RoleResult("p", "y", "ollama", "m"),
                )
            self.assertTrue(result.preserved)
            self.assertEqual(result.source, "preserved")
            # JSON is untouched (owner authorization survives verbatim).
            self.assertEqual(
                contract_file.read_text(encoding="utf-8"), original
            )
            # P2: Markdown is refreshed to reflect the authorized status.
            md = md_file.read_text(encoding="utf-8").replace("`", "").lower()
            self.assertIn("authorized: true", md)
            self.assertNotIn("owner approval required", md)

    def test_load_existing_contract_handles_missing_and_corrupt(self) -> None:
        """Fix #1: missing or corrupt contracts load as absent."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "t").mkdir()
            self.assertIsNone(
                load_existing_contract("t/planned_task.json", root)
            )
            corrupt = root / "t/planned_task.json"
            corrupt.write_text("not json", encoding="utf-8")
            self.assertIsNone(
                load_existing_contract("t/planned_task.json", root)
            )

    def test_preserved_state_marks_authorized_and_clears_failures(
        self,
    ) -> None:
        """Fix #1/#5: preserved run is healthy and clears failure state."""
        contract = ContractResult(
            None,
            ValidationVerdict(True, []),
            "preserved",
            "kept",
            preserved=True,
        )
        factory_state: dict[str, object] = {"failure_count": 3}
        active_run: dict[str, object] = {"current_blocker": "x"}
        project_state: dict[str, object] = {
            "current_task": "DEMO-002",
            "failure_count": 3,
            "current_blocker": "planning_contract_rejected",
        }
        update_success_state(
            factory_state,
            active_run,
            project_state,
            RoleResult("a", "x", "ollama", "m"),
            RoleResult("p", "y", "ollama", "m"),
            contract_result=contract,
        )
        self.assertEqual(project_state["last_contract_status"], "authorized")
        self.assertTrue(project_state["contract_authorized"])
        self.assertEqual(project_state["failure_count"], 0)
        self.assertIsNone(project_state["current_blocker"])
        self.assertEqual(contract_status_label(contract), "authorized")

    def test_valid_contract_resets_prior_failures(self) -> None:
        """Fix #5: a clean valid contract clears earlier failure counters."""
        task = parse_planned_task(json.dumps(_valid_contract_dict()))
        contract = ContractResult(
            task, validate_planned_task(task), "ollama", "m"
        )
        factory_state: dict[str, object] = {"failure_count": 2}
        active_run: dict[str, object] = {}
        project_state: dict[str, object] = {
            "current_task": "DEMO-002",
            "failure_count": 2,
            "current_blocker": "planning_contract_rejected",
        }
        update_success_state(
            factory_state,
            active_run,
            project_state,
            RoleResult("a", "x", "ollama", "m"),
            RoleResult("p", "y", "ollama", "m"),
            contract_result=contract,
        )
        self.assertEqual(project_state["failure_count"], 0)
        self.assertEqual(factory_state["failure_count"], 0)
        self.assertIsNone(project_state["current_blocker"])

    def test_report_includes_authorized_preserved_contract(self) -> None:
        """P2/report: preserved contract shows authorized + preserved labels."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "apps/demo/factory_reports").mkdir(parents=True)
            report_path = append_dry_run_report(
                project_name="demo",
                project_report_root="apps/demo/factory_reports",
                mode="dry_run",
                context_files=["context.md"],
                task_files=["task.md"],
                git_status="clean",
                factory_state={"last_failed_run": None},
                active_run={"resume_from": "Holding for Coder."},
                project_state={
                    "current_task": "DEMO-TEST",
                    "current_milestone": "DEMO-M",
                    "last_completed_checkpoint": None,
                    "failure_count": 0,
                    "current_blocker": None,
                },
                architect_source="ollama",
                architect_detail="m",
                planner_source="ollama",
                planner_detail="m",
                last_role_completed="reporter",
                planning_files=["TASK_EXPANSION.md", "NEXT_ACTION.md"],
                contract_status="authorized",
                contract_source="preserved",
                contract_detail="kept",
                contract_reasons=[],
                contract_files=["planned_task.json", "PLANNED_TASK.md"],
                contract_authorized=True,
                repo_root=root,
            )
            report = (
                report_path.read_text(encoding="utf-8")
                .replace("`", "")
                .lower()
            )
            self.assertIn(
                "authorized: true (owner-authorized; preserved)", report
            )
            self.assertIn("contract files preserved", report)
            self.assertNotIn("contract files written", report)


if __name__ == "__main__":
    unittest.main()
