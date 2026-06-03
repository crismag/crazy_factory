"""Tests for project-local runtime folders.

The Crazy Factory root is the *engine*; a project's *runtime* (config, run
state, factory memory, reports, tasks, context) lives entirely inside its
workbench (``app_path``). These tests pin that invariant down:

1. ``startproject`` materializes project-local ``config/factory.yaml``,
   ``state/*.json``, and ``factory_state/`` — and writes nothing under root
   ``factory_state/projects/<id>``.
2. ``activate`` syncs run-state under the workbench, leaving root ``state/``
   untouched.
3. ``assert_project_local`` (the advance's fail-loud guard) rejects engine-root
   runtime paths and accepts every workbench path, and the report writer lands
   reports inside the workbench rather than a root ``reports/`` folder.
4. ``status`` reads project-local run-state.
5. ``migrate-project-runtime`` copies legacy root runtime into the workbench,
   non-destructively, and materializes a project-local config when missing.
6. ``migrate-project-runtime`` refuses external projects.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import crazy_admin as ca  # noqa: E402
from project_paths import (  # noqa: E402
    RuntimePathError,
    assert_project_local,
)
from project_registry import resolve_project  # noqa: E402
from report_writer import append_dry_run_report  # noqa: E402


def _bootstrap_repo(root: Path) -> None:
    """Create the minimal engine-root layout the CLI and advance expect."""
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "factory_state").mkdir(parents=True, exist_ok=True)
    (root / "apps").mkdir(parents=True, exist_ok=True)
    (root / "config/projects.yaml").write_text(
        'active_project: ""\nprojects:\n', encoding="utf-8"
    )
    # Root config/factory.yaml is the default template copied into each project.
    (root / "config/factory.yaml").write_text(
        "factory:\n"
        '  mode: "dry_run"\n'
        '  state_dir: "state"\n'
        "  max_lines_per_file: 200\n"
        "  max_files_per_run: 5\n"
        "proposal_application:\n  allow_apply: false\n  allow_delete: false\n"
        "validation:\n  allow_run: false\n"
        "git:\n  allow_auto_commit: false\n",
        encoding="utf-8",
    )
    (root / "config/models.yaml").write_text(
        "models:\n  planner: cogito:14b\n", encoding="utf-8"
    )
    for name in ("factory_state", "active_run", "project_state"):
        (root / f"state/{name}.json").write_text("{}", encoding="utf-8")


def _snapshot(directory: Path) -> dict[str, str]:
    """Map every file under ``directory`` to its content (relative paths)."""
    if not directory.is_dir():
        return {}
    return {
        item.relative_to(directory).as_posix(): item.read_text(
            encoding="utf-8"
        )
        for item in sorted(directory.rglob("*"))
        if item.is_file()
    }


class StartProjectRuntimeTests(unittest.TestCase):
    """startproject materializes project-local runtime, not root runtime."""

    def test_creates_project_local_config_state_and_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("widget", "apps/widget", root=root)
            base = root / "apps/widget"
            self.assertTrue((base / "config/factory.yaml").is_file())
            for name in (
                "factory_state.json",
                "active_run.json",
                "project_state.json",
            ):
                self.assertTrue((base / "state" / name).is_file(), name)
            self.assertTrue((base / "factory_state").is_dir())
            # The project's run-state is bootstrapped to itself.
            fs = json.loads((base / "state/factory_state.json").read_text())
            self.assertEqual(fs["active_project"], "widget")

    def test_writes_nothing_under_root_factory_state_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("widget", "apps/widget", root=root)
            # The legacy per-project root memory dir must not be created.
            self.assertFalse((root / "factory_state/projects").exists())
            # Root run-state stays the empty engine-root placeholder.
            self.assertEqual(
                json.loads((root / "state/factory_state.json").read_text()), {}
            )


class ActivateRuntimeTests(unittest.TestCase):
    """activate syncs run-state under the workbench, not root."""

    def test_activate_leaves_root_state_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("widget", "apps/widget", root=root)
            root_state_before = _snapshot(root / "state")
            ca.activate("widget", root=root)
            self.assertEqual(_snapshot(root / "state"), root_state_before)
            ps = json.loads(
                (root / "apps/widget/state/project_state.json").read_text()
            )
            self.assertEqual(ps["project"], "widget")


class RuntimeGuardTests(unittest.TestCase):
    """assert_project_local is the fail-loud chokepoint the advance relies on."""

    def test_rejects_root_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            # The engine-root runtime folders must never be project targets.
            for rogue in (
                "state/factory_state.json",
                "reports",
                "factory_state",
            ):
                with self.assertRaises(RuntimePathError):
                    assert_project_local(rogue, "apps/widget", root)

    def test_accepts_workbench_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            project = resolve_project(
                {
                    "active_project": "widget",
                    "projects": {
                        "widget": {"app_path": "apps/widget"},
                    },
                },
                "widget",
            )
            for key in (
                "state_dir",
                "report_root",
                "task_root",
                "context_root",
                "factory_state_dir",
            ):
                # Must not raise — every runtime path is inside the workbench.
                assert_project_local(str(project[key]), "apps/widget", root)


class ReportNoRootWriteTests(unittest.TestCase):
    """Reports land inside the workbench, never in a root reports/ folder."""

    def test_report_writes_under_app_not_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
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
            # The report + activity blog live inside the workbench.
            self.assertTrue(report_path.is_file())
            self.assertTrue(
                (root / "apps/demo/factory_reports/ACTIVITY_BLOG.md").is_file()
            )
            # The engine root has no reports/ folder.
            self.assertFalse((root / "reports").exists())


class StatusRuntimeTests(unittest.TestCase):
    """status reads project-local run-state."""

    def test_status_reflects_project_local_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("widget", "apps/widget", root=root)
            ca.activate("widget", root=root)
            info = ca.status(root)
            self.assertEqual(info["active_project"], "widget")
            self.assertEqual(info["state_path"], "apps/widget/state")


class MigrateRuntimeTests(unittest.TestCase):
    """migrate-project-runtime copies legacy root runtime into the workbench."""

    def test_copies_legacy_runtime_non_destructively(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("widget", "apps/widget", root=root)
            base = root / "apps/widget"

            # Stage legacy root runtime as a pre-relocation project would have.
            (root / "state/legacy_extra.json").write_text(
                '{"legacy": true}', encoding="utf-8"
            )
            (root / "factory_state/projects/widget").mkdir(parents=True)
            (
                root / "factory_state/projects/widget/context_ledger.json"
            ).write_text('{"entries": []}', encoding="utf-8")
            (root / "reports").mkdir()
            (root / "reports/ACTIVITY_BLOG.md").write_text(
                "# legacy blog\n", encoding="utf-8"
            )
            # A project-local file that must win over any legacy namesake.
            (base / "state/factory_state.json").write_text(
                '{"active_project": "widget", "kept": true}', encoding="utf-8"
            )

            summary = ca.migrate_project_runtime("widget", root=root)

            # Legacy-only files are brought into the workbench.
            self.assertEqual(
                (base / "state/legacy_extra.json").read_text(),
                '{"legacy": true}',
            )
            self.assertTrue(
                (base / "factory_state/context_ledger.json").is_file()
            )
            self.assertEqual(
                (base / "factory_reports/ACTIVITY_BLOG.md").read_text(),
                "# legacy blog\n",
            )
            # Existing project file is never overwritten by a legacy namesake.
            self.assertIn(
                "kept",
                (base / "state/factory_state.json").read_text(),
            )
            self.assertTrue(
                any(
                    s.endswith("state/factory_state.json")
                    for s in summary["areas"]["state"]["skipped"]
                )
            )
            # Config already exists (startproject made it) → not materialized.
            self.assertFalse(summary["config_materialized"])
            # Legacy root folders are left in place for the owner to remove.
            self.assertTrue((root / "state/legacy_extra.json").is_file())

    def test_materializes_missing_project_config(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as ext,
        ):
            root = Path(tmp)
            _bootstrap_repo(root)
            # An embedded codebase attached without a scaffold has no config.
            existing = root / "apps/legacy"
            (existing / "app").mkdir(parents=True)
            (existing / "app/main.py").write_text("x = 1\n", encoding="utf-8")
            ca.attachproject("legacy", "apps/legacy", root=root)
            self.assertFalse((existing / "config/factory.yaml").exists())
            summary = ca.migrate_project_runtime("legacy", root=root)
            self.assertTrue(summary["config_materialized"])
            self.assertTrue((existing / "config/factory.yaml").is_file())
            _ = ext  # second tempdir kept for symmetry with attach flows

    def test_refuses_external_project(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as ext,
        ):
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("myapp", str(Path(ext) / "a"), root=root)
            with self.assertRaises(ca.AdminError):
                ca.migrate_project_runtime("myapp", root=root)


if __name__ == "__main__":
    unittest.main()
