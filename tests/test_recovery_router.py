"""Tests for deterministic-first recovery routing."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from recovery_router import (  # noqa: E402
    APPLICATION_REJECTED,
    plan_recovery,
    run_recovery_router,
)


def _project(root: Path) -> dict[str, object]:
    task_root = root / "apps/demo/factory_tasks"
    task_root.mkdir(parents=True)
    (root / "apps/demo/crazy_project.yaml").parent.mkdir(
        parents=True, exist_ok=True
    )
    (root / "apps/demo/crazy_project.yaml").write_text(
        "project:\n  id: demo\n", encoding="utf-8"
    )
    return {
        "name": "demo",
        "app_path": "apps/demo",
        "root": "apps/demo",
        "task_root": "apps/demo/factory_tasks",
    }


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


class RecoveryRouterTests(unittest.TestCase):
    def test_missing_tests_revises_proposal_and_retires_artifacts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            project = _project(root)
            task_root = root / "apps/demo/factory_tasks"
            _write_json(
                task_root / "patch_plan.json",
                {
                    "validation": {
                        "status": "rejected",
                        "reasons": [
                            "Implementation patch does not include or declare validation tests"
                        ],
                    }
                },
            )
            for name in (
                "coder_proposal.json",
                "CODER_PROPOSAL.md",
                "PATCH_PLAN.md",
                "APPLICATION_REPORT.md",
            ):
                (task_root / name).write_text("stale", encoding="utf-8")
            _write_json(
                task_root / "approved_proposal.json",
                {"application_approved": True, "proposal_id": "P1"},
            )

            project_state = {
                "current_blocker": APPLICATION_REJECTED,
                "failure_count": 1,
            }
            active_run: dict[str, object] = {}
            decision, changed = run_recovery_router(
                root=root,
                project=project,
                project_state=project_state,
                active_run=active_run,
            )

            self.assertEqual(decision.decision, "revise_proposal")
            self.assertIn("coder_proposal.json", changed)
            self.assertFalse((task_root / "coder_proposal.json").exists())
            self.assertFalse((task_root / "patch_plan.json").exists())
            self.assertTrue((task_root / "recovery_decision.json").is_file())
            self.assertIsNone(project_state["current_blocker"])
            self.assertIn("coder", str(active_run["resume_from"]))

    def test_syntax_error_regenerates_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            project = _project(root)
            task_root = root / "apps/demo/factory_tasks"
            _write_json(
                task_root / "patch_plan.json",
                {
                    "validation": {
                        "status": "rejected",
                        "reasons": [
                            "Python syntax error in src/x.py: invalid syntax"
                        ],
                    }
                },
            )
            project_state = {"current_blocker": APPLICATION_REJECTED}
            decision = plan_recovery(
                root=root, project=project, project_state=project_state
            )
            self.assertEqual(decision.decision, "regenerate_patch")

    def test_unused_import_regenerates_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            project = _project(root)
            task_root = root / "apps/demo/factory_tasks"
            _write_json(
                task_root / "patch_plan.json",
                {
                    "validation": {
                        "status": "rejected",
                        "reasons": [
                            "tests/test_x.py:1: unused import 'pytest'"
                        ],
                    }
                },
            )
            project_state = {"current_blocker": APPLICATION_REJECTED}
            decision = plan_recovery(
                root=root, project=project, project_state=project_state
            )
            self.assertEqual(decision.decision, "regenerate_patch")

    def test_completeness_rejection_revises_proposal(self) -> None:
        # 9D Layer 2 reconciliation: a completeness-review rejection requests a
        # fresh proposal (clear approval) instead of parking for owner review.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            project = _project(root)
            task_root = root / "apps/demo/factory_tasks"
            _write_json(
                task_root / "patch_plan.json",
                {
                    "validation": {
                        "status": "rejected",
                        "reasons": [
                            "missing behavior: load returns [] on missing file",
                            "missing test: test_corrupt_json",
                        ],
                    }
                },
            )
            project_state = {"current_blocker": APPLICATION_REJECTED}
            decision = plan_recovery(
                root=root, project=project, project_state=project_state
            )
            self.assertEqual(decision.decision, "revise_proposal")
            self.assertTrue(
                any(a.type == "clear_approval" for a in decision.actions)
            )
            self.assertTrue(
                any(a.type == "request_new_proposal" for a in decision.actions)
            )


if __name__ == "__main__":
    unittest.main()
