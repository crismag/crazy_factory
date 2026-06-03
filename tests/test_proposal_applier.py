"""Tests for the Phase 5 proposal application engine.

These tests exercise the approval gate, patch-plan parsing, the safety
validator, preview vs apply behavior, state transitions, and report
generation. Apply mode is exercised explicitly; it is off by default.
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

from mission_state import update_success_state  # noqa: E402
from ollama_client import OllamaConnectionError  # noqa: E402
from planning_roles import RoleResult  # noqa: E402
from prompt_builder import PromptPackage  # noqa: E402
from proposal_applier import (  # noqa: E402
    ApplicationResult,
    ApplicationVerdict,
    PatchFile,
    PatchPlan,
    PatchPlanParseError,
    application_paths,
    application_status_label,
    apply_patch_plan,
    is_application_approved,
    is_proposal_valid,
    parse_patch_plan,
    patch_plan_to_dict,
    request_patch_plan,
    run_application_stage,
    validate_patch_plan,
)
from report_writer import append_dry_run_report  # noqa: E402


def _proposal_record() -> dict[str, object]:
    """Return a valid coder_proposal.json-style record."""
    return {
        "proposal_id": "CP-001",
        "task_id": "DEMO-002",
        "files_to_create": ["apps/demo/app/status.py"],
        "files_to_modify": ["apps/demo/docs/README.md"],
        "files_to_delete": [],
        "validation": {"status": "valid", "reasons": []},
    }


def _authorized_contract() -> dict[str, object]:
    """Return a valid, owner-authorized contract record."""
    return {
        "task_id": "DEMO-002",
        "title": "t",
        "objective": "o",
        "validation_plan": "v",
        "scope": ["s"],
        "exclusions": ["e"],
        "acceptance_criteria": ["a"],
        "inputs": [],
        "risks": [],
        "approval_status": "pending",
        "authorized": True,
        "validation": {"status": "valid", "reasons": []},
    }


def _valid_plan_dict() -> dict[str, object]:
    """Return a well-formed, in-bounds patch plan mapping for demo."""
    return {
        "plan_id": "PP-001",
        "task_id": "DEMO-002",
        "proposal_id": "CP-001",
        "files": [
            {
                "path": "apps/demo/app/status.py",
                "action": "create",
                "content": "STATUS = 'ok'\n",
            }
        ],
        "notes": "",
    }


def _valid_plan() -> PatchPlan:
    return parse_patch_plan(json.dumps(_valid_plan_dict()))


class GateTests(unittest.TestCase):
    """Verify the application gate predicates."""

    def test_is_proposal_valid(self) -> None:
        self.assertTrue(is_proposal_valid(_proposal_record()))
        self.assertFalse(
            is_proposal_valid({"validation": {"status": "rejected"}})
        )
        self.assertFalse(is_proposal_valid({}))
        self.assertFalse(is_proposal_valid(["not", "a", "dict"]))

    def test_is_application_approved_matches_proposal_id(self) -> None:
        proposal = _proposal_record()
        self.assertTrue(
            is_application_approved(
                {"proposal_id": "CP-001", "application_approved": True},
                proposal,
            )
        )
        # Wrong id, not approved, or non-dict are all not approved.
        self.assertFalse(
            is_application_approved(
                {"proposal_id": "OTHER", "application_approved": True},
                proposal,
            )
        )
        self.assertFalse(
            is_application_approved(
                {"proposal_id": "CP-001", "application_approved": False},
                proposal,
            )
        )
        self.assertFalse(is_application_approved(None, proposal))


class ParseTests(unittest.TestCase):
    """Verify patch-plan parsing."""

    def test_parse_valid_plan(self) -> None:
        plan = _valid_plan()
        self.assertEqual(plan.plan_id, "PP-001")
        self.assertEqual(len(plan.files), 1)
        self.assertEqual(plan.files[0].action, "create")

    def test_parse_rejects_non_json(self) -> None:
        with self.assertRaises(PatchPlanParseError):
            parse_patch_plan("not json")
        with self.assertRaises(PatchPlanParseError):
            parse_patch_plan("[1, 2]")

    def test_parse_drops_non_dict_file_items(self) -> None:
        data = _valid_plan_dict()
        data["files"] = [
            "bogus",
            {
                "path": "apps/demo/app/x.py",
                "action": "create",
                "content": "y\n",
            },
        ]
        plan = parse_patch_plan(json.dumps(data))
        self.assertEqual(len(plan.files), 1)


class ValidateTests(unittest.TestCase):
    """Verify the patch-plan safety validator."""

    def _validate(
        self, plan: PatchPlan | None, **kwargs: object
    ) -> ApplicationVerdict:
        params: dict[str, object] = {
            "app_path": "apps/demo",
            "proposal_record": _proposal_record(),
            "approved": True,
            "max_files": 5,
            "max_lines": 300,
        }
        params.update(kwargs)
        return validate_patch_plan(plan, **params)  # type: ignore[arg-type]

    def test_accepts_valid_plan(self) -> None:
        self.assertTrue(self._validate(_valid_plan()).valid)

    def test_rejects_when_not_approved(self) -> None:
        self.assertFalse(self._validate(_valid_plan(), approved=False).valid)

    def test_rejects_none_plan(self) -> None:
        self.assertFalse(self._validate(None).valid)

    def test_rejects_empty_plan(self) -> None:
        data = _valid_plan_dict()
        data["files"] = []
        self.assertFalse(
            self._validate(parse_patch_plan(json.dumps(data))).valid
        )

    def test_rejects_path_outside_workbench(self) -> None:
        data = _valid_plan_dict()
        data["files"] = [
            {"path": "src/x.py", "action": "create", "content": "a\n"}
        ]
        verdict = self._validate(parse_patch_plan(json.dumps(data)))
        self.assertFalse(verdict.valid)
        self.assertIn("src/x.py", verdict.blocked_paths)

    def test_rejects_protected_paths(self) -> None:
        for bad in [
            "factory/x.py",
            "README.md",
            "state/x.json",
            "scripts/y.py",
        ]:
            data = _valid_plan_dict()
            data["files"] = [
                {"path": bad, "action": "modify", "content": "a\n"}
            ]
            verdict = self._validate(parse_patch_plan(json.dumps(data)))
            self.assertFalse(verdict.valid, bad)
            self.assertIn(bad, verdict.blocked_paths)

    def test_rejects_missing_content(self) -> None:
        data = _valid_plan_dict()
        data["files"] = [
            {"path": "apps/demo/app/x.py", "action": "create", "content": ""}
        ]
        verdict = self._validate(parse_patch_plan(json.dumps(data)))
        self.assertFalse(verdict.valid)
        self.assertTrue(any("content" in r.lower() for r in verdict.reasons))

    def test_rejects_secret_content(self) -> None:
        data = _valid_plan_dict()
        data["files"] = [
            {
                "path": "apps/demo/app/x.py",
                "action": "create",
                "content": "password = 'hunter2'\n",
            }
        ]
        verdict = self._validate(parse_patch_plan(json.dumps(data)))
        self.assertFalse(verdict.valid)
        self.assertTrue(any("secret" in r.lower() for r in verdict.reasons))

    def test_rejects_over_line_limit(self) -> None:
        data = _valid_plan_dict()
        data["files"] = [
            {
                "path": "apps/demo/app/x.py",
                "action": "create",
                "content": "\n".join(f"line{i}" for i in range(10)),
            }
        ]
        verdict = self._validate(
            parse_patch_plan(json.dumps(data)), max_lines=3
        )
        self.assertFalse(verdict.valid)

    def test_rejects_over_file_limit(self) -> None:
        data = _valid_plan_dict()
        data["files"] = [
            {
                "path": f"apps/demo/app/f{i}.py",
                "action": "create",
                "content": "x\n",
            }
            for i in range(3)
        ]
        verdict = self._validate(
            parse_patch_plan(json.dumps(data)), max_files=2
        )
        self.assertFalse(verdict.valid)

    def test_rejects_proposal_id_mismatch(self) -> None:
        data = _valid_plan_dict()
        data["proposal_id"] = "CP-999"
        verdict = self._validate(parse_patch_plan(json.dumps(data)))
        self.assertFalse(verdict.valid)

    def test_warns_on_undeclared_path(self) -> None:
        data = _valid_plan_dict()
        data["files"] = [
            {
                "path": "apps/demo/tests/test_extra.py",
                "action": "create",
                "content": "x\n",
            }
        ]
        verdict = self._validate(parse_patch_plan(json.dumps(data)))
        self.assertTrue(verdict.valid)
        self.assertTrue(
            any("not declared" in w.lower() for w in verdict.warnings)
        )


class RequestTests(unittest.TestCase):
    """Verify the model request path with Ollama mocked."""

    def _factory_config(self) -> dict[str, object]:
        return {
            "ollama": {
                "base_url": "http://localhost:11434",
                "timeout_seconds": 1,
                "stream": False,
            }
        }

    def _call(
        self, *, side_effect: object = None, return_value: object = None
    ) -> ApplicationResult:
        with (
            patch(
                "proposal_applier.build_prompt_package",
                return_value=PromptPackage("coder", "demo", "P", []),
            ),
            patch(
                "proposal_applier.OllamaClient.chat",
                side_effect=side_effect,
                return_value=return_value,
            ),
        ):
            return request_patch_plan(
                app_path="apps/demo",
                project={
                    "root": "apps/demo",
                    "task_root": "apps/demo/factory_tasks",
                    "context_root": "apps/demo/factory_context",
                },
                proposal_record=_proposal_record(),
                factory_config=self._factory_config(),
                models_config={"models": {"coder": "qwen2.5-coder:14b"}},
                max_lines=300,
                max_files=5,
                mode="preview_only",
            )

    def test_falls_back_when_ollama_unavailable(self) -> None:
        result = self._call(side_effect=OllamaConnectionError("offline"))
        self.assertEqual(result.source, "fallback")
        self.assertIsNone(result.plan)
        self.assertFalse(result.verdict.valid)
        self.assertTrue(result.activated)

    def test_rejects_unparseable(self) -> None:
        result = self._call(return_value={"message": {"content": "nope"}})
        self.assertEqual(result.source, "ollama")
        self.assertIsNone(result.plan)
        self.assertFalse(result.verdict.valid)

    def test_validates_ollama_plan(self) -> None:
        content = json.dumps(_valid_plan_dict())
        result = self._call(return_value={"message": {"content": content}})
        self.assertEqual(result.source, "ollama")
        self.assertIsNotNone(result.plan)
        self.assertTrue(result.verdict.valid, result.verdict.reasons)
        self.assertFalse(result.applied)


class StageTests(unittest.TestCase):
    """Verify the approval gate, preview, and apply behavior."""

    def _setup(self, root: Path) -> dict[str, object]:
        task_root = root / "apps/demo/factory_tasks"
        task_root.mkdir(parents=True)
        (task_root / "planned_task.json").write_text(
            json.dumps(_authorized_contract()), encoding="utf-8"
        )
        (task_root / "coder_proposal.json").write_text(
            json.dumps(_proposal_record()), encoding="utf-8"
        )
        return {
            "root": "apps/demo",
            "task_root": "apps/demo/factory_tasks",
            "context_root": "apps/demo/factory_context",
        }

    def _run(
        self, root: Path, project: dict[str, object], pa: dict[str, object]
    ) -> tuple[ApplicationResult, str]:
        result, plan_json, _, _ = run_application_stage(
            app_path="apps/demo",
            root=root,
            project=project,
            factory_config={"ollama": {}, "proposal_application": pa},
            models_config={"models": {"coder": "x"}},
            max_lines=300,
            max_files=5,
            contract_json_path="apps/demo/factory_tasks/planned_task.json",
            proposal_json_path="apps/demo/factory_tasks/coder_proposal.json",
        )
        return result, plan_json

    def test_skips_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._setup(root)
            with patch(
                "proposal_applier.request_patch_plan",
                side_effect=AssertionError("must not call model"),
            ):
                result, plan_json = self._run(
                    root, project, {"mode": "preview_only"}
                )
            self.assertFalse(result.activated)
            self.assertEqual(result.source, "skipped")
            self.assertFalse((root / plan_json).exists())

    def test_preview_when_approved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._setup(root)
            (
                root / "apps/demo/factory_tasks/approved_proposal.json"
            ).write_text(
                json.dumps(
                    {"proposal_id": "CP-001", "application_approved": True}
                ),
                encoding="utf-8",
            )
            fake = ApplicationResult(
                _valid_plan(),
                ApplicationVerdict(True, [], [], []),
                "ollama",
                "m",
                "preview_only",
                activated=True,
            )
            with patch(
                "proposal_applier.request_patch_plan", return_value=fake
            ):
                result, plan_json = self._run(
                    root,
                    project,
                    {"mode": "preview_only", "allow_apply": False},
                )
            self.assertTrue(result.activated)
            self.assertFalse(result.applied)
            self.assertTrue((root / plan_json).is_file())
            # No application code written in preview mode.
            self.assertFalse((root / "apps/demo/app/status.py").exists())

    def test_apply_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._setup(root)
            (
                root / "apps/demo/factory_tasks/approved_proposal.json"
            ).write_text(
                json.dumps(
                    {"proposal_id": "CP-001", "application_approved": True}
                ),
                encoding="utf-8",
            )
            fake = ApplicationResult(
                _valid_plan(),
                ApplicationVerdict(True, [], [], []),
                "ollama",
                "m",
                "apply",
                activated=True,
            )
            with patch(
                "proposal_applier.request_patch_plan", return_value=fake
            ):
                result, _ = self._run(
                    root, project, {"mode": "apply", "allow_apply": True}
                )
            self.assertTrue(result.applied)
            written = root / "apps/demo/app/status.py"
            self.assertTrue(written.is_file())
            self.assertIn("STATUS", written.read_text(encoding="utf-8"))

    def test_apply_writes_and_skips_delete_by_default(self) -> None:
        """Deletes are skipped unless allow_delete is set; writes apply."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "apps/demo/app").mkdir(parents=True)
            (root / "apps/demo/app/old.py").write_text("old\n")
            project = {"root": "apps/demo", "task_root": "apps/demo/x"}
            plan = PatchPlan(
                "PP",
                "T",
                "CP-001",
                [
                    PatchFile("apps/demo/app/new.py", "create", "new\n"),
                    PatchFile("apps/demo/app/old.py", "delete", ""),
                ],
            )
            touched, error = apply_patch_plan(plan, root=root, project=project)
            self.assertIsNone(error)
            self.assertIn("apps/demo/app/new.py", touched)
            self.assertTrue((root / "apps/demo/app/new.py").is_file())
            # Delete was skipped because allow_delete defaults to False.
            self.assertTrue((root / "apps/demo/app/old.py").exists())

    def test_apply_deletes_only_when_enabled(self) -> None:
        """A delete runs only when allow_delete is explicitly enabled."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "apps/demo/app").mkdir(parents=True)
            (root / "apps/demo/app/old.py").write_text("old\n")
            project = {"root": "apps/demo", "task_root": "apps/demo/x"}
            plan = PatchPlan(
                "PP",
                "T",
                "CP-001",
                [PatchFile("apps/demo/app/old.py", "delete", "")],
            )
            touched, error = apply_patch_plan(
                plan, root=root, project=project, allow_delete=True
            )
            self.assertIsNone(error)
            self.assertFalse((root / "apps/demo/app/old.py").exists())

    def test_validate_rejects_delete_by_default(self) -> None:
        """A plan with a delete is invalid unless allow_delete is set."""
        from proposal_applier import validate_patch_plan

        plan = PatchPlan(
            "PP",
            "T",
            "CP-001",
            [PatchFile("apps/demo/app/x.py", "delete", "")],
        )
        rejected = validate_patch_plan(
            plan,
            app_path="apps/demo",
            proposal_record={"proposal_id": "CP-001"},
            approved=True,
            max_files=5,
            max_lines=300,
        )
        self.assertFalse(rejected.valid)
        self.assertTrue(any("delete" in r.lower() for r in rejected.reasons))
        allowed = validate_patch_plan(
            plan,
            app_path="apps/demo",
            proposal_record={"proposal_id": "CP-001"},
            approved=True,
            max_files=5,
            max_lines=300,
            allow_delete=True,
        )
        self.assertTrue(allowed.valid, allowed.reasons)

    def test_application_paths_inside_project(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        project = {
            "root": "apps/demo_app",
            "task_root": "apps/demo_app/factory_tasks",
        }
        approved, plan_json, plan_md, report_md = application_paths(
            repo_root, project
        )
        self.assertTrue(approved.endswith("approved_proposal.json"))
        self.assertTrue(plan_json.endswith("patch_plan.json"))
        self.assertTrue(plan_md.endswith("PATCH_PLAN.md"))
        self.assertTrue(report_md.endswith("APPLICATION_REPORT.md"))
        with self.assertRaises(RuntimeError):
            application_paths(
                repo_root,
                {"root": "apps/demo_app", "task_root": "reports"},
            )


class StateAndReportTests(unittest.TestCase):
    """Verify application state transitions and report rendering."""

    def _update(self, result: ApplicationResult) -> tuple[dict, dict]:
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
            RoleResult("a", "x", "ollama", "m"),
            RoleResult("p", "y", "ollama", "m"),
            application_result=result,
        )
        return active_run, project_state

    def test_status_labels(self) -> None:
        skipped = ApplicationResult(
            None, ApplicationVerdict(False), "skipped", "d", "preview_only"
        )
        self.assertEqual(application_status_label(skipped), "not_approved")
        preview = ApplicationResult(
            _valid_plan(),
            ApplicationVerdict(True),
            "ollama",
            "d",
            "preview_only",
            activated=True,
        )
        self.assertEqual(application_status_label(preview), "preview")
        applied = ApplicationResult(
            _valid_plan(),
            ApplicationVerdict(True),
            "ollama",
            "d",
            "apply",
            activated=True,
            applied=True,
        )
        self.assertEqual(application_status_label(applied), "applied")

    def test_state_skipped_not_a_failure(self) -> None:
        result = ApplicationResult(
            None, ApplicationVerdict(False), "skipped", "d", "preview_only"
        )
        _, project_state = self._update(result)
        self.assertEqual(
            project_state["last_application_status"], "not_approved"
        )
        self.assertEqual(project_state["failure_count"], 0)

    def test_state_preview_points_to_review(self) -> None:
        result = ApplicationResult(
            _valid_plan(),
            ApplicationVerdict(True),
            "ollama",
            "d",
            "preview_only",
            activated=True,
        )
        active_run, project_state = self._update(result)
        self.assertEqual(project_state["last_application_status"], "preview")
        self.assertEqual(project_state["last_patch_plan_id"], "PP-001")
        self.assertIn("application", str(active_run["resume_from"]))
        self.assertEqual(project_state["failure_count"], 0)

    def test_state_rejected_increments_failure(self) -> None:
        result = ApplicationResult(
            None,
            ApplicationVerdict(False, ["bad"]),
            "ollama",
            "d",
            "preview_only",
            activated=True,
        )
        active_run, project_state = self._update(result)
        self.assertEqual(project_state["last_application_status"], "rejected")
        self.assertEqual(project_state["failure_count"], 1)
        self.assertEqual(
            project_state["current_blocker"], "application_rejected"
        )

    def test_patch_plan_to_dict_marks_applied(self) -> None:
        result = ApplicationResult(
            _valid_plan(),
            ApplicationVerdict(True),
            "ollama",
            "d",
            "apply",
            activated=True,
            applied=True,
            applied_files=["apps/demo/app/x.py"],
        )
        record = patch_plan_to_dict(result)
        self.assertTrue(record["applied"])
        self.assertEqual(record["validation"]["status"], "applied")
        self.assertEqual(record["files"][0]["action"], "create")

    def test_report_includes_application_section(self) -> None:
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
                context_files=["c.md"],
                task_files=["t.md"],
                git_status="clean",
                factory_state={"last_failed_run": None},
                active_run={"resume_from": "review"},
                project_state={
                    "current_task": "DEMO",
                    "current_milestone": "M",
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
                application_status="rejected",
                application_mode="preview_only",
                application_applied=False,
                application_reasons=["bad path"],
                application_blocked_paths=["factory/x.py"],
                application_files=["patch_plan.json", "PATCH_PLAN.md"],
                repo_root=root,
            )
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("Proposal Application", report)
            self.assertIn("preview_only", report)
            self.assertIn("factory/x.py", report)


if __name__ == "__main__":
    unittest.main()
