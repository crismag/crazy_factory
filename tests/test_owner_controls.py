"""Tests for the owner-control CLI and project control file.

Covers the project-local ``crazy_project.yaml`` model (round-trip, unknown-field
preservation, capability bridge), the owner operations (authorize-task,
approve-proposal, capability toggles, next/status) and their safety refusals,
and the runtime capability overlay. No Ollama and no code generation occur.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import crazy_admin as ca  # noqa: E402
import owner_controls as oc  # noqa: E402
import project_control as pc  # noqa: E402
from project_control import ControlError  # noqa: E402
from repo_tools import safe_write_json  # noqa: E402

_FACTORY_CONFIG = {
    "factory": {"mode": "dry_run", "state_dir": "state"},
    "proposal_application": {"allow_apply": False, "allow_delete": False},
    "validation": {"allow_run": False},
    "git": {"allow_auto_commit": False},
}


def _git_root(tmp: str) -> Path:
    root = Path(tmp)
    (root / ".git").mkdir(exist_ok=True)
    (root / "state").mkdir(exist_ok=True)
    (root / "state/project_state.json").write_text("{}", encoding="utf-8")
    return root


def _project(root: Path) -> dict[str, object]:
    app = "apps/app"
    (root / app / "factory_tasks").mkdir(parents=True, exist_ok=True)
    return {
        "name": "app",
        "app_path": app,
        "repo_mode": "embedded",
        "state_dir": f"{app}/state",
        "task_root": f"{app}/factory_tasks",
    }


def _write_planned(
    root: Path,
    project: dict[str, object],
    *,
    status: str = "valid",
    reasons: list[str] | None = None,
    authorized: bool = False,
) -> None:
    safe_write_json(
        f"{project['task_root']}/planned_task.json",
        {
            "task_id": "T1",
            "authorized": authorized,
            "validation": {"status": status, "reasons": reasons or []},
        },
        repo_root=root,
        allowed_roots=[str(project["task_root"])],
    )


def _write_proposal(
    root: Path,
    project: dict[str, object],
    *,
    proposal_id: str = "CP-001",
    status: str = "valid",
) -> None:
    safe_write_json(
        f"{project['task_root']}/coder_proposal.json",
        {"proposal_id": proposal_id, "validation": {"status": status}},
        repo_root=root,
        allowed_roots=[str(project["task_root"])],
    )


class ControlFileTests(unittest.TestCase):
    """The crazy_project.yaml model round-trips and bridges capabilities."""

    def test_roundtrip_preserves_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            ctrl = pc.load_or_init_control("apps/app", root, project=project)
            ctrl["legacy_marker"] = {"managed_by": "crazy_factory"}
            ctrl["capabilities"]["allow_apply"] = True
            pc.save_control(ctrl, "apps/app", root)
            raw = pc.read_control("apps/app", root)
            assert raw is not None
            self.assertEqual(raw["capabilities"]["allow_apply"], True)
            self.assertEqual(
                raw["legacy_marker"]["managed_by"], "crazy_factory"
            )
            self.assertIsNone(raw["owner_controls"]["approved_proposal_id"])

    def test_effective_capability_project_overrides_global(self) -> None:
        raw = {"capabilities": {"allow_apply": True}}
        self.assertTrue(
            pc.effective_capability(raw, _FACTORY_CONFIG, "allow_apply")
        )

    def test_effective_capability_falls_back_to_global(self) -> None:
        # No control file → global (OFF).
        self.assertFalse(
            pc.effective_capability(None, _FACTORY_CONFIG, "allow_apply")
        )
        # Control file without the key → global.
        self.assertFalse(
            pc.effective_capability(
                {"capabilities": {}}, _FACTORY_CONFIG, "allow_apply"
            )
        )

    def test_apply_project_controls_overlay(self) -> None:
        raw = {"capabilities": {"allow_validation": True}}
        eff = pc.apply_project_controls(_FACTORY_CONFIG, raw)
        self.assertTrue(eff["validation"]["allow_run"])
        # Global config untouched.
        self.assertFalse(_FACTORY_CONFIG["validation"]["allow_run"])
        # No control → unchanged object.
        self.assertIs(
            pc.apply_project_controls(_FACTORY_CONFIG, None), _FACTORY_CONFIG
        )

    def test_enable_apply_capability_flips_mode_to_apply(self) -> None:
        # enable-apply (allow_apply capability) must fully enable application:
        # the application stage gates on mode == "apply" too, so the single
        # owner gate has to flip mode without any hand-edit of config.
        eff = pc.apply_project_controls(
            _FACTORY_CONFIG, {"capabilities": {"allow_apply": True}}
        )
        self.assertTrue(eff["proposal_application"]["allow_apply"])
        self.assertEqual(eff["proposal_application"]["mode"], "apply")

    def test_autonomous_capability_bridges_to_autonomy_enabled(self) -> None:
        eff = pc.apply_project_controls(
            _FACTORY_CONFIG, {"capabilities": {"allow_autonomous": True}}
        )
        self.assertTrue(eff["autonomy"]["enabled"])

    def test_disable_apply_capability_restores_preview_only(self) -> None:
        eff = pc.apply_project_controls(
            _FACTORY_CONFIG, {"capabilities": {"allow_apply": False}}
        )
        self.assertFalse(eff["proposal_application"]["allow_apply"])
        self.assertEqual(eff["proposal_application"]["mode"], "preview_only")


class AuthorizeTaskTests(unittest.TestCase):
    """authorize-task validates before authorizing."""

    def test_fails_when_planned_task_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            with self.assertRaises(ControlError):
                oc.authorize_task(_project(root), root)

    def test_fails_when_validation_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            _write_planned(
                root, project, status="rejected", reasons=["bad field"]
            )
            with self.assertRaises(ControlError):
                oc.authorize_task(project, root)

    def test_succeeds_when_valid_and_sets_both(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            _write_planned(root, project, status="valid")
            oc.authorize_task(project, root)
            task = json.loads(
                (root / "apps/app/factory_tasks/planned_task.json").read_text()
            )
            self.assertTrue(task["authorized"])
            raw = pc.read_control("apps/app", root)
            self.assertTrue(raw["owner_controls"]["task_authorized"])

    def test_fails_when_already_authorized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            _write_planned(root, project, status="valid", authorized=True)
            with self.assertRaises(ControlError):
                oc.authorize_task(project, root)

    def test_revoke_clears_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            _write_planned(root, project, status="valid")
            oc.authorize_task(project, root)
            oc.revoke_task(project, root)
            task = json.loads(
                (root / "apps/app/factory_tasks/planned_task.json").read_text()
            )
            self.assertFalse(task["authorized"])
            raw = pc.read_control("apps/app", root)
            self.assertFalse(raw["owner_controls"]["task_authorized"])


class ApproveProposalTests(unittest.TestCase):
    """approve-proposal records the approval safely."""

    def test_fails_when_proposal_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            with self.assertRaises(ControlError):
                oc.approve_proposal(_project(root), root)

    def test_fails_when_proposal_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            _write_proposal(root, project, status="rejected")
            with self.assertRaises(ControlError):
                oc.approve_proposal(project, root)

    def test_succeeds_writes_approval_and_records_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            _write_proposal(root, project, proposal_id="CP-042")
            result = oc.approve_proposal(project, root)
            self.assertEqual(result["proposal_id"], "CP-042")
            approval = json.loads(
                (
                    root / "apps/app/factory_tasks/approved_proposal.json"
                ).read_text()
            )
            self.assertTrue(approval["application_approved"])
            self.assertEqual(approval["proposal_id"], "CP-042")
            raw = pc.read_control("apps/app", root)
            self.assertEqual(
                raw["owner_controls"]["approved_proposal_id"], "CP-042"
            )

    def test_revoke_invalidates_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            _write_proposal(root, project, proposal_id="CP-1")
            oc.approve_proposal(project, root)
            oc.revoke_proposal(project, root)
            approval = json.loads(
                (
                    root / "apps/app/factory_tasks/approved_proposal.json"
                ).read_text()
            )
            self.assertFalse(approval["application_approved"])
            raw = pc.read_control("apps/app", root)
            self.assertFalse(raw["owner_controls"]["proposal_approved"])


class CapabilityToggleTests(unittest.TestCase):
    """Capability toggles set project-local switches and preserve fields."""

    def test_enable_apply_then_disable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            oc.set_capability(project, root, "allow_apply", True)
            raw = pc.read_control("apps/app", root)
            self.assertTrue(raw["capabilities"]["allow_apply"])
            oc.set_capability(project, root, "allow_apply", False)
            raw = pc.read_control("apps/app", root)
            self.assertFalse(raw["capabilities"]["allow_apply"])

    def test_unknown_capability_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            with self.assertRaises(ControlError):
                oc.set_capability(_project(root), root, "allow_world", True)

    def test_toggle_preserves_other_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            _write_planned(root, project, status="valid")
            oc.authorize_task(project, root)
            oc.set_capability(project, root, "allow_validation", True)
            raw = pc.read_control("apps/app", root)
            # authorization survived the capability write.
            self.assertTrue(raw["owner_controls"]["task_authorized"])
            self.assertTrue(raw["capabilities"]["allow_validation"])


class NextAndStatusTests(unittest.TestCase):
    """next/status report the right state at each stage."""

    def _next(self, root: Path, project: dict[str, object]) -> str:
        return oc.describe_next(project, root, _FACTORY_CONFIG)

    def test_next_reports_rejected_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            _write_planned(root, project, status="rejected", reasons=["x"])
            self.assertIn(
                "planning_contract_rejected", self._next(root, project)
            )

    def test_next_reports_waiting_for_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            _write_planned(root, project, status="valid")
            out = self._next(root, project)
            self.assertIn("contract_valid_waiting_for_owner", out)
            self.assertIn("authorize-task", out)

    def test_next_reports_proposal_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            _write_planned(root, project, status="valid")
            oc.authorize_task(project, root)
            _write_proposal(root, project)
            out = self._next(root, project)
            self.assertIn("proposal_waiting_for_owner", out)
            self.assertIn("approve-proposal", out)

    def test_next_reports_apply_disabled_then_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            _write_planned(root, project, status="valid")
            oc.authorize_task(project, root)
            _write_proposal(root, project)
            oc.approve_proposal(project, root)
            self.assertIn("apply_disabled", self._next(root, project))
            oc.set_capability(project, root, "allow_apply", True)
            self.assertIn("ready_to_apply", self._next(root, project))

    def test_status_includes_contract_and_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            _write_planned(root, project, status="rejected", reasons=["x"])
            info = oc.gather_status(project, root, _FACTORY_CONFIG)
            self.assertTrue(info["contract_exists"])
            self.assertEqual(info["contract_status"], "rejected")
            self.assertFalse(info["contract_authorized"])
            self.assertIn("allow_apply", info["capabilities"])


class CliTests(unittest.TestCase):
    """End-to-end CLI wiring of the owner-control commands."""

    def _bootstrap(self, root: Path) -> None:
        (root / ".git").mkdir(exist_ok=True)
        for d in ("config", "state", "factory_state", "apps"):
            (root / d).mkdir(parents=True, exist_ok=True)
        (root / "config/projects.yaml").write_text(
            'active_project: ""\nprojects:\n', encoding="utf-8"
        )
        (root / "config/factory.yaml").write_text(
            "factory:\n  mode: dry_run\n  state_dir: state\n"
            "proposal_application:\n  allow_apply: false\n"
            "validation:\n  allow_run: false\n"
            "git:\n  allow_auto_commit: false\n",
            encoding="utf-8",
        )
        for name in ("factory_state", "active_run", "project_state"):
            (root / f"state/{name}.json").write_text("{}", encoding="utf-8")

    def _run(self, root: Path, argv: list[str]) -> int:
        with (
            patch("crazy_admin.find_repo_root", return_value=root),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return ca.main(argv)

    def test_authorize_task_refuses_rejected_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._bootstrap(root)
            ca.startproject("todo", "apps/todo", root=root)
            _write_planned(
                root,
                {"task_root": "apps/todo/factory_tasks"},
                status="rejected",
                reasons=["Missing or empty required field: validation_plan"],
            )
            self.assertEqual(self._run(root, ["authorize-task", "todo"]), 2)

    def test_enable_apply_updates_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._bootstrap(root)
            ca.startproject("todo", "apps/todo", root=root)
            self.assertEqual(self._run(root, ["enable-apply", "todo"]), 0)
            raw = pc.read_control("apps/todo", root)
            self.assertTrue(raw["capabilities"]["allow_apply"])

    def test_authorize_task_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._bootstrap(root)
            ca.startproject("todo", "apps/todo", root=root)
            _write_planned(
                root,
                {"task_root": "apps/todo/factory_tasks"},
                status="valid",
            )
            self.assertEqual(self._run(root, ["authorize-task", "todo"]), 0)
            task = json.loads(
                (
                    root / "apps/todo/factory_tasks/planned_task.json"
                ).read_text()
            )
            self.assertTrue(task["authorized"])


if __name__ == "__main__":
    unittest.main()
