"""Tests for the 9E.S2 adjudication decision core.

The safety floor wins deterministically; clear cases resolve without a model;
the LLM only judges ambiguous blocking findings and can never accept/fix a block.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from adjudicator import (  # noqa: E402
    ACCEPT,
    ESCALATE,
    FIXIT,
    REJECT_UNSAFE,
    REVISE,
    adjudicate,
)


class FakeClient:
    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.calls = 0

    def chat(self, model: object, messages: object, **_: object) -> dict:
        self.calls += 1
        return {"message": {"content": self._reply}}


class AdjudicateTests(unittest.TestCase):
    def test_no_findings_accept(self) -> None:
        self.assertEqual(adjudicate([]).disposition, ACCEPT)

    def test_safety_floor_always_rejects_even_with_model(self) -> None:
        client = FakeClient('{"disposition": "revise"}')
        result = adjudicate(
            ["references a secret/credential"], client=client, model="m"
        )
        self.assertEqual(result.disposition, REJECT_UNSAFE)
        self.assertEqual(result.source, "deterministic")
        self.assertEqual(client.calls, 0)  # floor never consults the model

    def test_all_lint_is_fix_deterministically(self) -> None:
        result = adjudicate(["src/x.py:1: unused import 'Optional'"])
        self.assertEqual(result.disposition, FIXIT)
        self.assertIn("autofix_lint", result.skills)
        self.assertEqual(result.source, "deterministic")

    def test_only_advisory_accepts(self) -> None:
        result = adjudicate(["prefer src/ layout over app/"])
        self.assertEqual(result.disposition, ACCEPT)

    def test_blocking_without_model_escalates(self) -> None:
        result = adjudicate(["Python syntax error in src/x.py"])
        self.assertEqual(result.disposition, ESCALATE)
        self.assertEqual(result.source, "fallback")

    def test_blocking_with_model_takes_its_disposition(self) -> None:
        client = FakeClient('{"disposition": "revise", "rationale": "broken"}')
        result = adjudicate(
            ["Python syntax error in src/x.py"], client=client, model="m"
        )
        self.assertEqual(result.disposition, REVISE)
        self.assertEqual(result.source, "ollama")

    def test_model_cannot_accept_a_block(self) -> None:
        client = FakeClient('{"disposition": "accept"}')  # not allowed
        result = adjudicate(
            ["Python syntax error in src/x.py"], client=client, model="m"
        )
        self.assertEqual(result.disposition, ESCALATE)


if __name__ == "__main__":
    unittest.main()
