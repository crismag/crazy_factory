"""Tests for owner-configured external app workbench support.

Crazy Factory builds apps under an owner-configured ``apps_base``. The default
(``apps``) is in-repo and fully backward-compatible; an absolute base lets apps
build OUTSIDE the factory repo. Either way, each project is confined to its own
``<apps_base>/<id>`` folder — it cannot escape to a sibling project, the factory
repo, ``/etc``, the home directory, ``..``, or through a symlink.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import crazy_admin as ca  # noqa: E402
import repo_tools  # noqa: E402
import settings  # noqa: E402
from project_registry import (  # noqa: E402
    app_is_buildable,
    load_registry,
    resolve_project,
)


def _bootstrap(root: Path, apps_base: str = "apps") -> None:
    (root / ".git").mkdir()
    (root / "config").mkdir()
    (root / "apps").mkdir()
    (root / "config/factory.yaml").write_text(
        "factory:\n  mode: dry_run\n"
        "paths:\n"
        "  engine:\n"
        f"    apps_base: {apps_base}\n",
        encoding="utf-8",
    )
    (root / "config/projects.yaml").write_text(
        'active_project: ""\nprojects:\n', encoding="utf-8"
    )


class PathCompositionTests(unittest.TestCase):
    def test_default_app_path_is_in_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap(root)  # default apps_base = apps
            self.assertFalse(settings.is_apps_base_external(root))
            self.assertEqual(
                settings.project_app_path("demo", root), "apps/demo"
            )

    def test_external_app_path_composition(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as ext,
        ):
            root = Path(tmp)
            _bootstrap(root, apps_base=ext)
            self.assertTrue(settings.is_apps_base_external(root))
            self.assertEqual(
                settings.project_app_path("tic-tac-toe", root),
                str(Path(ext) / "tic-tac-toe"),
            )

    def test_env_overrides_config(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as ext,
        ):
            root = Path(tmp)
            _bootstrap(root)  # config says in-repo
            with mock.patch.dict(
                "os.environ", {"CRAZY_FACTORY_APPS_BASE": ext}
            ):
                self.assertEqual(
                    settings.project_app_path("demo", root),
                    str(Path(ext) / "demo"),
                )


class ConfinementTests(unittest.TestCase):
    """An external project can write in its folder, but cannot escape it."""

    def _ctx(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._ext = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        _bootstrap(root, apps_base=self._ext.name)
        app = str(Path(self._ext.name) / "tic-tac-toe")
        return root, app

    def _cleanup(self) -> None:
        self._tmp.cleanup()
        self._ext.cleanup()

    def test_write_inside_project_allowed(self) -> None:
        root, app = self._ctx()
        try:
            repo_tools.safe_write_text(
                app + "/src/x.py",
                "print(1)\n",
                repo_root=root,
                allowed_roots=[app],
            )
            self.assertTrue((Path(app) / "src/x.py").is_file())
        finally:
            self._cleanup()

    def test_escapes_are_blocked(self) -> None:
        root, app = self._ctx()
        sibling = str(Path(self._ext.name) / "other_project")
        rogue = [
            app + "/../other_project/x.py",  # parent traversal to sibling
            sibling + "/x.py",  # sibling project directly
            "/etc/cf_test_x",  # system path
            str(Path.home() / ".ssh/id_rsa"),  # home + sensitive
        ]
        try:
            for bad in rogue:
                with self.assertRaises(repo_tools.RepoSafetyError, msg=bad):
                    repo_tools.safe_write_text(
                        bad, "x", repo_root=root, allowed_roots=[app]
                    )
        finally:
            self._cleanup()

    def test_symlink_escape_is_blocked(self) -> None:
        root, app = self._ctx()
        try:
            Path(app).mkdir(parents=True)
            outside = Path(self._ext.name) / "outside"
            outside.mkdir()
            link = Path(app) / "link"
            os.symlink(outside, link)  # link -> sibling outside the project
            with self.assertRaises(repo_tools.RepoSafetyError):
                repo_tools.safe_write_text(
                    str(link / "x.py"),
                    "x",
                    repo_root=root,
                    allowed_roots=[app],
                )
        finally:
            self._cleanup()


class BuildabilityTests(unittest.TestCase):
    def test_buildable_matrix(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as ext,
        ):
            root = Path(tmp)
            _bootstrap(root, apps_base=ext)
            # embedded under repo -> buildable
            self.assertTrue(app_is_buildable("apps/demo", root))
            # external under the configured base -> buildable
            self.assertTrue(app_is_buildable(str(Path(ext) / "demo"), root))
            # arbitrary external (not under base) -> NOT buildable
            with tempfile.TemporaryDirectory() as other:
                self.assertFalse(
                    app_is_buildable(str(Path(other) / "demo"), root)
                )


class StartProjectExternalTests(unittest.TestCase):
    def test_apps_base_flag_persists_and_composes(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as ext,
        ):
            root = Path(tmp)
            _bootstrap(root)  # starts in-repo
            info = ca.startproject(
                "tic-tac-toe", None, root=root, apps_base=ext
            )
            # app path composed under the external base (no silent apps/<id>).
            self.assertEqual(info["app_path"], str(Path(ext) / "tic-tac-toe"))
            # persisted so the runtime honors the same base.
            self.assertIn(
                f"apps_base: {ext}",
                (root / "config/factory.yaml").read_text(),
            )
            # registry records the exact external path; it is buildable.
            project = resolve_project(load_registry(root), "tic-tac-toe")
            self.assertEqual(
                project["app_path"], str(Path(ext) / "tic-tac-toe")
            )
            self.assertTrue(app_is_buildable(project["app_path"], root))

    def test_target_location_is_honored_not_substituted(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as ext,
        ):
            root = Path(tmp)
            _bootstrap(root, apps_base=ext)
            target = str(Path(ext) / "tic-tac-toe")
            info = ca.startproject(
                "tic-tac-toe", None, root=root, target_location=target
            )
            self.assertEqual(info["app_path"], target)
            # The factory built the workbench AT the target — no apps/ copy.
            self.assertTrue((Path(target) / "crazy_project.yaml").is_file())
            self.assertFalse((root / "apps/tic-tac-toe").exists())


if __name__ == "__main__":
    unittest.main()
