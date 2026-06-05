"""Tests for the 9E.S1 skill library (deterministic repair skills)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from skill_library import (  # noqa: E402
    SKILL_CATALOG,
    autofix_lint,
    is_known_skill,
    scope_down_paths,
)


class AutofixLintTests(unittest.TestCase):
    def test_removes_unused_import(self) -> None:
        res = autofix_lint(
            "from typing import List, Optional\n\nx: List[int] = [1]\n",
            path="src/x.py",
        )
        self.assertTrue(res.changed)
        self.assertNotIn("Optional", res.content)
        self.assertIn("List", res.content)  # still used → kept

    def test_clean_content_unchanged(self) -> None:
        res = autofix_lint("x = 1\n", path="src/x.py")
        self.assertFalse(res.changed)
        self.assertEqual(res.content, "x = 1\n")

    def test_empty_content_safe(self) -> None:
        res = autofix_lint("   ", path="src/x.py")
        self.assertFalse(res.changed)


class CatalogTests(unittest.TestCase):
    def test_scope_down_keeps_only_allowed(self) -> None:
        kept, dropped = scope_down_paths(
            ["src/a.py", "src/b.py", "src/c.py"], ["src/a.py"]
        )
        self.assertEqual(kept, ["src/a.py"])
        self.assertEqual(dropped, ["src/b.py", "src/c.py"])

    def test_known_skill_allowlist(self) -> None:
        self.assertTrue(is_known_skill("autofix_lint"))
        self.assertTrue(is_known_skill("scope_down_paths"))
        self.assertFalse(is_known_skill("rm_rf_everything"))
        self.assertIn("autofix_lint", SKILL_CATALOG)


if __name__ == "__main__":
    unittest.main()
