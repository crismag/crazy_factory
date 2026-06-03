"""Tests for the Phase 7 checkpoint commit engine.

These tests exercise the eligibility gate, path classification, commit-message
construction, and the actual commit in an isolated temporary git repository.
Auto-commit is off by default; the commit path is exercised explicitly.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from checkpoint_commit import (  # noqa: E402
    allowed_commit_prefixes,
    build_commit_message,
    checkpoint_gate,
    checkpoint_status_label,
    classify_changes,
    run_checkpoint_stage,
)
from mission_state import update_success_state  # noqa: E402
from planning_roles import RoleResult  # noqa: E402


def _authorized_contract() -> dict[str, object]:
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


def _valid_proposal() -> dict[str, object]:
    return {"proposal_id": "CP-001", "validation": {"status": "valid"}}


def _application(status: str = "applied") -> dict[str, object]:
    return {"validation": {"status": status}}


def _validation(status: str = "passed") -> dict[str, object]:
    return {"status": status}


class GateTests(unittest.TestCase):
    """Verify checkpoint eligibility."""

    def test_eligible_when_all_pass(self) -> None:
        eligible, reasons = checkpoint_gate(
            contract_record=_authorized_contract(),
            proposal_record=_valid_proposal(),
            application_record=_application("applied"),
            validation_record=_validation("passed"),
        )
        self.assertTrue(eligible, reasons)

    def test_ineligible_when_validation_not_passed(self) -> None:
        eligible, reasons = checkpoint_gate(
            contract_record=_authorized_contract(),
            proposal_record=_valid_proposal(),
            application_record=_application("applied"),
            validation_record=_validation("skipped"),
        )
        self.assertFalse(eligible)
        self.assertTrue(any("validation" in r.lower() for r in reasons))

    def test_ineligible_when_application_rejected(self) -> None:
        eligible, _ = checkpoint_gate(
            contract_record=_authorized_contract(),
            proposal_record=_valid_proposal(),
            application_record=_application("rejected"),
            validation_record=_validation("passed"),
        )
        self.assertFalse(eligible)

    def test_ineligible_without_authorized_contract(self) -> None:
        eligible, _ = checkpoint_gate(
            contract_record={"authorized": False},
            proposal_record=_valid_proposal(),
            application_record=_application(),
            validation_record=_validation(),
        )
        self.assertFalse(eligible)


class PathTests(unittest.TestCase):
    """Verify path classification and config resolution."""

    def test_classify_allowed_and_excluded(self) -> None:
        allowed_prefixes = [
            "apps/demo/app",
            "apps/demo/factory_tasks",
        ]
        allowed, excluded = classify_changes(
            [
                "apps/demo/app/x.py",
                "apps/demo/factory_tasks/planned_task.json",
                "scripts/factory_advance.py",
                "config/factory.yaml",
            ],
            allowed_prefixes,
        )
        self.assertEqual(len(allowed), 2)
        self.assertIn("scripts/factory_advance.py", excluded)
        self.assertIn("config/factory.yaml", excluded)

    def test_allowed_commit_prefixes_substitutes_project(self) -> None:
        config = {
            "git": {
                "allowed_auto_commit_paths": [
                    "apps/<active_project>/app",
                    "apps/<active_project>/docs",
                ]
            }
        }
        prefixes = allowed_commit_prefixes(config, "demo_app")
        self.assertEqual(prefixes, ["apps/demo_app/app", "apps/demo_app/docs"])

    def test_build_commit_message(self) -> None:
        msg = build_commit_message(
            prefix="factory:", task_id="DEMO-002", summary="add status note"
        )
        self.assertEqual(msg, "factory: checkpoint DEMO-002 add status note")


class StageTests(unittest.TestCase):
    """Verify the checkpoint stage in an isolated git repository."""

    def _init_repo(self, root: Path) -> dict[str, object]:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "t@example.com"],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"], cwd=root, check=True
        )
        task_root = root / "apps/demo/factory_tasks"
        report_root = root / "apps/demo/factory_reports"
        task_root.mkdir(parents=True)
        report_root.mkdir(parents=True)
        (task_root / "planned_task.json").write_text(
            json.dumps(_authorized_contract()), encoding="utf-8"
        )
        (task_root / "coder_proposal.json").write_text(
            json.dumps(_valid_proposal()), encoding="utf-8"
        )
        (task_root / "patch_plan.json").write_text(
            json.dumps(_application("applied")), encoding="utf-8"
        )
        (task_root / "validation_result.json").write_text(
            json.dumps(_validation("passed")), encoding="utf-8"
        )
        return {
            "root": "apps/demo",
            "task_root": "apps/demo/factory_tasks",
            "report_root": "apps/demo/factory_reports",
        }

    def _config(self, *, allow: bool) -> dict[str, object]:
        return {
            "git": {
                "allow_auto_commit": allow,
                "commit_prefix": "factory:",
                "allowed_auto_commit_paths": [
                    "apps/demo/app",
                    "apps/demo/docs",
                    "apps/demo/factory_tasks",
                    "apps/demo/factory_reports",
                ],
            }
        }

    def _run(self, root: Path, project: dict, config: dict):
        return run_checkpoint_stage(
            project_name="demo",
            root=root,
            project=project,
            factory_config=config,
            contract_json_path="apps/demo/factory_tasks/planned_task.json",
            proposal_json_path="apps/demo/factory_tasks/coder_proposal.json",
            application_json_path="apps/demo/factory_tasks/patch_plan.json",
            validation_json_path="apps/demo/factory_tasks/"
            "validation_result.json",
            summary="add status note",
        )

    def test_preview_when_auto_commit_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._init_repo(root)
            head_before = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            result, report = self._run(
                root, project, self._config(allow=False)
            )
            self.assertTrue(result.eligible)
            self.assertFalse(result.committed)
            # No commit exists yet (repo had no initial commit).
            self.assertNotEqual(head_before.returncode, 0)
            self.assertTrue((root / report).is_file())

    def test_commits_when_enabled_and_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._init_repo(root)
            result, _ = self._run(root, project, self._config(allow=True))
            self.assertTrue(result.committed)
            self.assertIsNotNone(result.commit_sha)
            # The commit exists and the message is contract-derived.
            log = subprocess.run(
                ["git", "log", "-1", "--pretty=%s"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertIn("checkpoint DEMO-002", log.stdout)
            # Engine files were never staged (only allowed paths).
            self.assertTrue(
                all("scripts/" not in f for f in result.staged_files)
            )
            # Checkpoint log was recorded.
            self.assertTrue(
                (root / "checkpoints/checkpoint_log.jsonl").is_file()
            )

    def test_not_eligible_does_not_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._init_repo(root)
            # Break the gate: validation not passed.
            (
                root / "apps/demo/factory_tasks/validation_result.json"
            ).write_text(json.dumps(_validation("failed")), encoding="utf-8")
            result, _ = self._run(root, project, self._config(allow=True))
            self.assertFalse(result.eligible)
            self.assertFalse(result.committed)

    def test_pre_staged_forbidden_file_is_not_committed(self) -> None:
        """A forbidden file already in the index never rides the commit."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._init_repo(root)
            # An engine file pre-staged in the index by something else.
            (root / "scripts").mkdir()
            (root / "scripts/evil.py").write_text("x = 1\n")
            subprocess.run(
                ["git", "add", "scripts/evil.py"], cwd=root, check=True
            )
            result, _ = self._run(root, project, self._config(allow=True))
            self.assertTrue(result.committed)
            files = subprocess.run(
                ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
            ).stdout
            self.assertNotIn("scripts/evil.py", files)
            self.assertIn("apps/demo/factory_tasks/", files)


class StateTests(unittest.TestCase):
    """Verify checkpoint state transitions."""

    def test_committed_advances_marker(self) -> None:
        from checkpoint_commit import CheckpointResult

        factory_state: dict[str, object] = {}
        active_run: dict[str, object] = {}
        project_state: dict[str, object] = {"current_task": "DEMO-002"}
        result = CheckpointResult(
            eligible=True,
            committed=True,
            commit_sha="abc123",
            checkpoint_id="CKPT-X",
        )
        update_success_state(
            factory_state,
            active_run,
            project_state,
            RoleResult("a", "x", "ollama", "m"),
            RoleResult("p", "y", "ollama", "m"),
            checkpoint_result=result,
        )
        self.assertEqual(project_state["last_completed_checkpoint"], "CKPT-X")
        self.assertEqual(project_state["last_checkpoint_status"], "committed")

    def test_status_labels(self) -> None:
        from checkpoint_commit import CheckpointResult

        self.assertEqual(
            checkpoint_status_label(CheckpointResult(eligible=False)),
            "not_eligible",
        )
        self.assertEqual(
            checkpoint_status_label(CheckpointResult(eligible=True)),
            "eligible",
        )
        self.assertEqual(
            checkpoint_status_label(
                CheckpointResult(eligible=True, committed=True)
            ),
            "committed",
        )


if __name__ == "__main__":
    unittest.main()
