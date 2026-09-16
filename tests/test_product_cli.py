"""CLI wiring tests for inspect / assess (Slice A)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import crazy_admin as ca  # noqa: E402


def _bootstrap_repo(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "apps").mkdir(parents=True, exist_ok=True)
    (root / "config/projects.yaml").write_text("projects:\n", encoding="utf-8")
    (root / "config/factory.yaml").write_text(
        "factory:\n"
        '  mode: "dry_run"\n'
        '  state_dir: "state"\n'
        "  max_lines_per_file: 200\n"
        "  max_files_per_run: 5\n"
        "proposal_application:\n  allow_apply: false\n"
        "validation:\n  allow_run: false\n"
        "git:\n  allow_auto_commit: false\n",
        encoding="utf-8",
    )


class InspectAssessCliTests(unittest.TestCase):
    def test_inspect_and_assess_cli_on_seeded_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("todo", "apps/todo", root=root)
            seed = (ROOT / "examples/seeds/cli_todo_tracker.md").read_text(
                encoding="utf-8"
            )
            (root / "apps/todo/docs/seed.md").write_text(
                seed, encoding="utf-8"
            )
            with (
                patch("crazy_admin.find_repo_root", return_value=root),
                patch("sys.stdout", new_callable=StringIO) as out,
            ):
                code = ca.main(["inspect", "todo", "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["project_id"], "todo")
            self.assertFalse(payload["demo_ready"])
            self.assertTrue(payload["objectives"])
            self.assertIn("mission", payload)
            self.assertIsNone(payload["mission"]["outcome"])

            with (
                patch("crazy_admin.find_repo_root", return_value=root),
                patch("sys.stdout", new_callable=StringIO),
            ):
                code = ca.main(["assess", "todo"])
            self.assertEqual(code, 0)
            persisted = root / "apps/todo/factory_state/objectives.json"
            self.assertTrue(persisted.is_file())
            data = json.loads(persisted.read_text(encoding="utf-8"))
            self.assertTrue(data["objectives"])
