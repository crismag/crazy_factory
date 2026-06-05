"""Tests for the 9E.S1 skill library (deterministic repair skills)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from skill_library import autofix_lint  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
