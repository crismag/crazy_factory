"""Tests for configurable read/write locations.

Config (the ``paths:`` block in ``config/factory.yaml``) provides the defaults;
``CRAZY_FACTORY_*`` environment variables override engine locations; and
``crazy-admin startproject --path`` / ``set-path`` override workbench folders
per project (persisted in the registry). Covers:

1. ``settings``: built-in defaults, config overlay, env override.
2. ``resolve_paths`` honors per-project workbench overrides.
3. The registry round-trips a nested per-project ``paths`` map.
4. ``startproject --path`` scaffolds AND resolves to the overridden folders.
5. ``set-path`` merges and persists overrides; bad values are refused.
6. The seed-staging base is configurable.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import crazy_admin as ca  # noqa: E402
import settings  # noqa: E402
from project_paths import resolve_paths  # noqa: E402
from project_registry import (  # noqa: E402
    dump_registry,
    load_registry,
    register_project,
    resolve_project,
    state_path_for,
)

_PLAIN_CONFIG = "factory:\n  mode: dry_run\n  state_dir: state\n"


def _bootstrap(root: Path, factory_yaml: str = _PLAIN_CONFIG) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "apps").mkdir(parents=True, exist_ok=True)
    (root / "config/factory.yaml").write_text(factory_yaml, encoding="utf-8")
    (root / "config/projects.yaml").write_text(
        'active_project: ""\nprojects:\n', encoding="utf-8"
    )


class SettingsTests(unittest.TestCase):
    """settings layers built-in defaults, config, and env vars."""

    def test_defaults_when_no_paths_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap(root)
            engine = settings.load_engine_settings(root)
            self.assertEqual(engine["registry_path"], "config/projects.yaml")
            self.assertEqual(
                engine["seed_staging_base"], "factory_state/projects"
            )
            wb = settings.workbench_defaults(root)
            self.assertEqual(wb["reports_dir"], "factory_reports")

    def test_config_overrides_defaults(self) -> None:
        cfg = (
            "factory:\n  mode: dry_run\n"
            "paths:\n"
            "  workbench:\n    reports_dir: out\n    state_dir: run\n"
            "  engine:\n    seed_staging_base: staging/projects\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap(root, cfg)
            wb = settings.workbench_defaults(root)
            self.assertEqual(wb["reports_dir"], "out")
            self.assertEqual(wb["state_dir"], "run")
            # Unset keys keep their built-in default.
            self.assertEqual(wb["tasks_dir"], "factory_tasks")
            engine = settings.load_engine_settings(root)
            self.assertEqual(engine["seed_staging_base"], "staging/projects")

    def test_env_overrides_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap(root)
            with patch.dict(
                "os.environ", {"CRAZY_FACTORY_REGISTRY": "custom/reg.yaml"}
            ):
                engine = settings.load_engine_settings(root)
            self.assertEqual(engine["registry_path"], "custom/reg.yaml")


class ResolvePathsOverrideTests(unittest.TestCase):
    """resolve_paths applies per-project workbench overrides."""

    def test_override_one_keeps_others_default(self) -> None:
        paths = resolve_paths("apps/x", {"reports_dir": "out/reports"})
        self.assertEqual(paths.reports_dir, "apps/x/out/reports")
        self.assertEqual(paths.state_dir, "apps/x/state")
        # config_dir is fixed (never configurable).
        self.assertEqual(paths.config_dir, "apps/x/config")

    def test_no_overrides_is_defaults(self) -> None:
        paths = resolve_paths("apps/x")
        self.assertEqual(paths.reports_dir, "apps/x/factory_reports")


class RegistryRoundtripTests(unittest.TestCase):
    """The registry persists and reloads a nested per-project paths map."""

    def test_paths_roundtrip(self) -> None:
        registry: dict = {"active_project": "a", "projects": {}}
        register_project(
            registry,
            project_id="a",
            app_path="apps/a",
            state_path="factory_state/projects/a",
            repo_mode="embedded",
            seed_file="docs/seed.md",
            now="2026-06-03T00:00:00Z",
            paths={"reports_dir": "out", "state_dir": "run"},
        )
        text = dump_registry(registry)
        self.assertIn("    paths:", text)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config/projects.yaml").write_text(text, encoding="utf-8")
            reloaded = load_registry(root)
            entry = reloaded["projects"]["a"]
            self.assertEqual(entry["paths"]["reports_dir"], "out")
            project = resolve_project(reloaded, "a")
            self.assertEqual(project["report_root"], "apps/a/out")
            self.assertEqual(project["state_dir"], "apps/a/run")


class StartProjectPathTests(unittest.TestCase):
    """startproject --path scaffolds and resolves to overridden folders."""

    def test_overridden_layout_is_scaffolded_and_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap(root)
            ca.startproject(
                "widget",
                "apps/widget",
                root=root,
                paths={"reports_dir": "out", "state_dir": "run"},
            )
            base = root / "apps/widget"
            # Scaffold used the overridden folder names…
            self.assertTrue((base / "out/.gitkeep").is_file())
            self.assertTrue((base / "run/factory_state.json").is_file())
            self.assertFalse((base / "factory_reports").exists())
            self.assertFalse((base / "state").exists())
            # …and the resolver agrees.
            project = resolve_project(load_registry(root), "widget")
            self.assertEqual(project["report_root"], "apps/widget/out")
            self.assertEqual(project["state_dir"], "apps/widget/run")

    def test_parse_rejects_bad_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap(root)
            with self.assertRaises(ca.AdminError):
                ca.parse_path_overrides(["bogus_key=x"], root)
            with self.assertRaises(ca.AdminError):
                ca.parse_path_overrides(["reports_dir=/abs"], root)
            with self.assertRaises(ca.AdminError):
                ca.parse_path_overrides(["reports_dir=../escape"], root)

    def test_set_path_merges_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap(root)
            ca.startproject("widget", "apps/widget", root=root)
            ca.set_path("widget", ["reports_dir=out"], root=root)
            project = resolve_project(load_registry(root), "widget")
            self.assertEqual(project["report_root"], "apps/widget/out")


class SeedStagingConfigTests(unittest.TestCase):
    """The seed-staging base is configurable via env/config."""

    def test_state_path_for_honors_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap(root)
            with patch.dict(
                "os.environ",
                {"CRAZY_FACTORY_SEED_STAGING_BASE": "staging"},
            ):
                self.assertEqual(state_path_for("demo", root), "staging/demo")


if __name__ == "__main__":
    unittest.main()
