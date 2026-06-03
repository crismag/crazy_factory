"""Tests for the App Builder Usage Flow (Phase 9 sub-phase).

These cover the project registry and the ``crazy-admin`` CLI that create,
attach, activate, and resolve an app to work on. The factory never picks a
project by default; an owner selects one explicitly. Apps may live under
``apps/<id>`` (embedded) or anywhere on disk (external). No application code is
written, applied, committed, pushed, or merged here.

The eight capabilities under test:

1. ``startproject`` scaffolds a new embedded app and registers it.
2. ``startproject`` into an out-of-repo path registers it as external.
3. ``attachproject`` registers an existing codebase without scaffolding it.
4. Activation requires a registered project (fail-loud otherwise).
5. ``activate`` syncs durable ``state/*.json`` to the active project.
6. ``resolve_project`` maps an entry to an app_path-rooted workbench.
7. The registry round-trips through dump/load (custom serializer).
8. ``factory_tick`` resolves the active project via the registry, with no
   default project and a graceful external-app guard.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import crazy_admin as ca  # noqa: E402
import factory_tick  # noqa: E402
from project_registry import (  # noqa: E402
    RegistryError,
    active_project_id,
    app_is_external,
    dump_registry,
    load_registry,
    register_project,
    resolve_project,
    workbench_exists,
)
from seed_context import SeedError  # noqa: E402


def _bootstrap_repo(root: Path) -> None:
    """Create the minimal repo layout the registry and CLI expect."""
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
    for name in ("factory_state", "active_run", "project_state"):
        (root / f"state/{name}.json").write_text("{}", encoding="utf-8")


class StartProjectTests(unittest.TestCase):
    """startproject scaffolds + registers embedded and external apps."""

    def test_startproject_scaffolds_and_registers_embedded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            info = ca.startproject("widget", "apps/widget", root=root)
            self.assertEqual(info["repo_mode"], "embedded")
            base = root / "apps/widget"
            # Scaffold lays down the workbench the coder + tick consume.
            for rel in (
                "crazy_project.yaml",
                "docs/seed.md",
                "app/.gitkeep",
                "tests/.gitkeep",
                "factory_context/PROJECT_GOAL.md",
                "factory_tasks/.gitkeep",
                "factory_reports/.gitkeep",
            ):
                self.assertTrue((base / rel).exists(), rel)
            registry = load_registry(root)
            self.assertIn("widget", registry["projects"])
            self.assertEqual(
                registry["projects"]["widget"]["app_path"], "apps/widget"
            )

    def test_startproject_outside_repo_is_external(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as out,
        ):
            root = Path(tmp)
            _bootstrap_repo(root)
            external = str(Path(out) / "myapp")
            info = ca.startproject("myapp", external, root=root)
            self.assertEqual(info["repo_mode"], "external")
            self.assertTrue((Path(external) / "crazy_project.yaml").exists())
            self.assertTrue(
                app_is_external(
                    load_registry(root)["projects"]["myapp"]["app_path"], root
                )
            )

    def test_startproject_existing_id_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("widget", "apps/widget", root=root)
            with self.assertRaises(ca.AdminError):
                ca.startproject("widget", "apps/widget", root=root)

    def test_startproject_rejects_bad_project_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            with self.assertRaises(SeedError):
                ca.startproject("../escape", "apps/x", root=root)


class AttachProjectTests(unittest.TestCase):
    """attachproject registers existing code without scaffolding it."""

    def test_attach_registers_without_scaffold(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as ext,
        ):
            root = Path(tmp)
            _bootstrap_repo(root)
            existing = Path(ext) / "legacy"
            (existing / "app").mkdir(parents=True)
            (existing / "app/main.py").write_text("x = 1\n", encoding="utf-8")
            info = ca.attachproject("legacy", str(existing), root=root)
            self.assertEqual(info["repo_mode"], "external")
            # attach does not write a crazy_project.yaml by default.
            self.assertFalse((existing / "crazy_project.yaml").exists())
            # the existing file is untouched.
            self.assertEqual(
                (existing / "app/main.py").read_text(encoding="utf-8"),
                "x = 1\n",
            )
            self.assertIn("legacy", load_registry(root)["projects"])

    def test_attach_missing_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            with self.assertRaises(ca.AdminError):
                ca.attachproject("ghost", "/nope/not/here", root=root)


class ActivateTests(unittest.TestCase):
    """Activation requires a registered project and syncs durable state."""

    def test_activate_unregistered_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            with self.assertRaises(RegistryError):
                ca.activate("nope", root=root)

    def test_activate_sets_active_and_syncs_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("widget", "apps/widget", root=root)
            ca.activate("widget", root=root)
            self.assertEqual(active_project_id(load_registry(root)), "widget")
            # Run-state is project-local under the workbench, not root state/.
            fs = json.loads(
                (root / "apps/widget/state/factory_state.json").read_text()
            )
            ps = json.loads(
                (root / "apps/widget/state/project_state.json").read_text()
            )
            self.assertEqual(fs["active_project"], "widget")
            self.assertEqual(ps["project"], "widget")
            # Root state/ is untouched (engine root stays clean).
            self.assertEqual(
                json.loads((root / "state/factory_state.json").read_text()), {}
            )


class ResolveAndRoundtripTests(unittest.TestCase):
    """resolve_project maps to an app_path workbench; registry round-trips."""

    def test_resolve_uses_app_path_for_workbench(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("widget", "apps/widget", root=root)
            project = resolve_project(load_registry(root), "widget")
            self.assertEqual(project["root"], "apps/widget")
            self.assertEqual(
                project["context_root"], "apps/widget/factory_context"
            )
            self.assertEqual(project["task_root"], "apps/widget/factory_tasks")
            self.assertEqual(
                project["report_root"], "apps/widget/factory_reports"
            )
            self.assertTrue(workbench_exists(project["app_path"], root))

    def test_registry_dump_load_roundtrip(self) -> None:
        registry: dict = {"active_project": "a", "projects": {}}
        register_project(
            registry,
            project_id="a",
            app_path="apps/a",
            state_path="factory_state/projects/a",
            repo_mode="embedded",
            seed_file="docs/seed.md",
            now="2026-06-02T00:00:00Z",
        )
        register_project(
            registry,
            project_id="b",
            app_path="/abs/b",
            state_path="factory_state/projects/b",
            repo_mode="external",
            seed_file="docs/seed.md",
            now="2026-06-02T00:00:00Z",
        )
        text = dump_registry(registry)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config/projects.yaml").write_text(text, encoding="utf-8")
            reloaded = load_registry(root)
        self.assertEqual(reloaded["active_project"], "a")
        self.assertEqual(reloaded["projects"]["b"]["app_path"], "/abs/b")
        self.assertEqual(reloaded["projects"]["a"]["repo_mode"], "embedded")


class FactoryTickResolutionTests(unittest.TestCase):
    """factory_tick resolves via the registry with no default project."""

    def _run_main(self, root: Path) -> tuple[int, str]:
        out = StringIO()
        with (
            patch("factory_tick.find_repo_root", return_value=root),
            patch("sys.stdout", out),
        ):
            code = factory_tick.main()
        return code, out.getvalue()

    def _min_configs(self, root: Path) -> None:
        (root / "config/factory.yaml").write_text(
            "factory:\n"
            '  mode: "dry_run"\n'
            '  state_dir: "state"\n'
            "  max_lines_per_file: 200\n"
            "  max_files_per_run: 5\n",
            encoding="utf-8",
        )
        (root / "config/models.yaml").write_text(
            "models:\n  planner: cogito:14b\n", encoding="utf-8"
        )

    def test_no_active_project_exits_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            self._min_configs(root)
            code, text = self._run_main(root)
            self.assertEqual(code, 0)
            self.assertIn("No active project", text)

    def test_external_active_project_is_guarded(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as ext,
        ):
            root = Path(tmp)
            _bootstrap_repo(root)
            self._min_configs(root)
            ca.startproject("myapp", str(Path(ext) / "a"), root=root)
            ca.activate("myapp", root=root)
            code, text = self._run_main(root)
            self.assertEqual(code, 0)
            self.assertIn("external", text.lower())


if __name__ == "__main__":
    unittest.main()
