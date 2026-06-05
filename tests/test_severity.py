"""Tests for the 9E.S0 severity policy — lint is soft, only floor/unrunnable hard."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from severity import (  # noqa: E402
    BLOCK,
    FIX,
    WARN,
    classify_reasons,
    is_blocking,
    overall_severity,
    severity_of,
)


class SeverityTests(unittest.TestCase):
    def test_block_tier(self) -> None:
        for reason in (
            "Python syntax error in src/x.py: invalid syntax",
            "Destination escapes context store: ../x",
            "references a secret/credential",
            "git push attempted",
            "forbidden import sqlalchemy",
            "src/x.py:23: placeholder function body in delete()",
            "No content provided for create: src/x.py",
            "Patch plan proposal_id '3' does not match the approved proposal '2'",
        ):
            self.assertEqual(severity_of(reason), BLOCK, reason)

    def test_fix_tier(self) -> None:
        for reason in (
            "src/x.py:2: unused import 'json'",
            "tests/test_x.py:1: F401 'pytest' imported but unused",
            "I001 import block is un-sorted",
            "line too long (98 > 88)",
        ):
            self.assertEqual(severity_of(reason), FIX, reason)

    def test_warn_default_for_noncritical(self) -> None:
        # Unknown / style / guideline findings are soft — they never hard-block.
        self.assertEqual(severity_of("prefer src/ layout over app/"), WARN)
        self.assertEqual(severity_of("variable name could be clearer"), WARN)

    def test_classify_and_overall(self) -> None:
        reasons = [
            "src/x.py:2: unused import 'json'",  # FIX
            "prefer src/ layout",  # WARN
            "Python syntax error",  # BLOCK
        ]
        buckets = classify_reasons(reasons)
        self.assertEqual(len(buckets[BLOCK]), 1)
        self.assertEqual(len(buckets[FIX]), 1)
        self.assertEqual(len(buckets[WARN]), 1)
        self.assertEqual(overall_severity(reasons), BLOCK)
        self.assertTrue(is_blocking(reasons))

    def test_lint_only_is_not_blocking(self) -> None:
        reasons = [
            "src/x.py:1: unused import 'Optional'"
        ]  # the task-board case
        self.assertFalse(is_blocking(reasons))
        self.assertEqual(overall_severity(reasons), FIX)

    def test_empty_is_info(self) -> None:
        self.assertEqual(overall_severity([]), WARN if False else "info")
        self.assertFalse(is_blocking([]))


if __name__ == "__main__":
    unittest.main()
