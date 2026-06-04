"""Tests for the per-project architecture contract gates.

The contract freezes a project's canonical tree and forbidden dependencies. The
engine enforces it generically (no app-specific logic): a patch that breaks the
tree or imports a forbidden dep is rejected before it lands, and the whole-
project coherence commands are scoped to the contract's source/test dirs.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from architecture import (  # noqa: E402
    coherence_commands,
    existing_violations,
    import_violations,
    is_contract_conflict,
    load_contract,
    missing_required,
    patch_contract_violations,
    path_violations,
    render_contract_brief,
)

_CONTRACT = {
    "src_dirs": ["src"],
    "test_dirs": ["tests"],
    "extra_allowed": ["README.md", "data"],
    "forbidden_dirs": ["app", "migrations"],
    "forbidden_names": ["models.py", "*.db"],
    "forbidden_imports": ["sqlalchemy", "from .models", "flask"],
    "required_files": ["src/task_model.py", "tests/test_task_model.py"],
}


class PathGateTests(unittest.TestCase):
    def test_allows_canonical_paths(self) -> None:
        ok = ["src/task_model.py", "tests/test_task_model.py", "README.md"]
        self.assertEqual(path_violations(ok, _CONTRACT), [])

    def test_rejects_forbidden_dir(self) -> None:
        v = path_violations(["app/task.py"], _CONTRACT)
        self.assertTrue(v and "forbidden directory" in v[0])

    def test_rejects_forbidden_name(self) -> None:
        v = path_violations(["src/models.py"], _CONTRACT)
        self.assertTrue(v and "forbidden file name" in v[0])

    def test_rejects_outside_canonical_tree(self) -> None:
        v = path_violations(["lib/util.py"], _CONTRACT)
        self.assertTrue(v and "outside the canonical tree" in v[0])


class ImportGateTests(unittest.TestCase):
    def test_detects_forbidden_imports(self) -> None:
        content = (
            "from sqlalchemy.orm import Session\nfrom .models import Task\n"
        )
        hits = import_violations(content, _CONTRACT)
        self.assertIn("sqlalchemy", hits)
        self.assertIn("from .models", hits)

    def test_clean_content_has_no_hits(self) -> None:
        self.assertEqual(import_violations("x = 1\n", _CONTRACT), [])

    def test_patch_contract_violations_combines_path_and_import(self) -> None:
        files = [
            ("app/x.py", "import os\n"),  # forbidden dir
            ("src/task_model.py", "import sqlalchemy\n"),  # forbidden import
            ("src/ok.py", "x = 1\n"),  # clean
        ]
        v = patch_contract_violations(files, _CONTRACT)
        self.assertEqual(len(v), 2)


class WorkbenchScanTests(unittest.TestCase):
    def test_existing_violations_and_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "src").mkdir()
            (base / "tests").mkdir()
            (base / "app").mkdir()
            (base / "src/task_model.py").write_text(
                "from sqlalchemy import x\n", encoding="utf-8"
            )
            (base / "app/legacy.py").write_text("y = 1\n", encoding="utf-8")
            # factory-managed dir must be ignored by the scan.
            (base / "factory_tasks").mkdir()
            (base / "factory_tasks/planned_task.json").write_text(
                "{}", encoding="utf-8"
            )
            v = existing_violations(str(base), _CONTRACT)
            self.assertTrue(any("forbidden directory" in r for r in v))
            self.assertTrue(any("sqlalchemy" in r for r in v))
            self.assertNotIn(
                "planned_task.json", " ".join(v)
            )  # factory dir skipped
            missing = missing_required(str(base), _CONTRACT)
            self.assertIn("tests/test_task_model.py", missing)
            self.assertNotIn("src/task_model.py", missing)  # exists


class CommandsAndLoadTests(unittest.TestCase):
    def test_coherence_commands_scope_to_existing_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "src").mkdir()
            (base / "tests").mkdir()
            cmds = coherence_commands(str(base), _CONTRACT)
            self.assertTrue(any("compileall" in c for c in cmds))
            self.assertTrue(
                any(c.startswith("python3 -m pytest") for c in cmds)
            )
            self.assertTrue(any(c.startswith("ruff check") for c in cmds))
            self.assertTrue(all("src" in c or "tests" in c for c in cmds))

    def test_coherence_commands_empty_when_no_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(coherence_commands(tmp, _CONTRACT), [])

    def test_load_contract_present_absent_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.assertIsNone(load_contract(str(base)))  # absent
            (base / "architecture.json").write_text(
                json.dumps(_CONTRACT), encoding="utf-8"
            )
            self.assertEqual(load_contract(str(base))["src_dirs"], ["src"])
            (base / "architecture.json").write_text("{ not json", "utf-8")
            self.assertIsNone(load_contract(str(base)))  # malformed -> absent


class ConflictAndBriefTests(unittest.TestCase):
    def test_is_contract_conflict_detects_markers(self) -> None:
        self.assertTrue(
            is_contract_conflict(["app/x.py: forbidden directory 'app/'"])
        )
        self.assertTrue(
            is_contract_conflict(["src/x.py: forbidden dependency: sqlalchemy"])
        )
        # A non-contract rejection (e.g. plain syntax/limit) is not a conflict.
        self.assertFalse(is_contract_conflict(["over the file limit of 5"]))
        self.assertFalse(is_contract_conflict([]))

    def test_render_brief_states_allowed_and_forbidden(self) -> None:
        brief = render_contract_brief(_CONTRACT)
        self.assertIn("src", brief)
        self.assertIn("app", brief)  # forbidden dir surfaced
        self.assertIn("sqlalchemy", brief)  # forbidden import surfaced
        self.assertIn("MANDATORY", brief)


if __name__ == "__main__":
    unittest.main()
