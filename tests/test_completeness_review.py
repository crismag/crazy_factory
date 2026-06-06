"""Tests for Phase 9D Layer 2 — pre-apply completeness reviewer.

The reviewer must: skip when there are no criteria; deterministically require a
test (floor); honour the model's revise/valid verdict; and never fake a pass or
hard-block when the model is unavailable.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from completeness_review import (  # noqa: E402
    DECISION_REVISE,
    DECISION_VALID,
    review_completeness,
)
from ollama_client import OllamaConnectionError  # noqa: E402

_MODELS = {"models": {"reviewer": "gemma:latest"}}
_FACTORY = {"ollama": {"base_url": "http://x", "timeout_seconds": 1}}

_SRC = ("src/storage.py", "def save(): return 1\n")
_TEST = ("tests/test_storage.py", "def test_save():\n    assert save() == 1\n")


def _ai(verdict: str, **extra: object) -> dict:
    return {"message": {"content": json.dumps({"verdict": verdict, **extra})}}


class ReviewTests(unittest.TestCase):
    def test_no_criteria_is_skipped_valid(self) -> None:
        v = review_completeness(acceptance_criteria=[], patch_files=[_SRC])
        self.assertEqual(v.decision, DECISION_VALID)
        self.assertEqual(v.source, "skipped")
        self.assertFalse(v.blocking)

    def test_floor_requires_a_test_without_calling_model(self) -> None:
        def _boom(*_a: object, **_k: object) -> dict:
            raise AssertionError(
                "model must not be called when floor triggers"
            )

        with patch("completeness_review.OllamaClient.chat", side_effect=_boom):
            v = review_completeness(
                acceptance_criteria=["save persists data"],
                patch_files=[_SRC],  # no test file
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(v.decision, DECISION_REVISE)
        self.assertEqual(v.source, "floor")
        self.assertTrue(v.blocking)

    def test_model_revise_is_blocking(self) -> None:
        with patch(
            "completeness_review.OllamaClient.chat",
            return_value=_ai(
                DECISION_REVISE, missing_behaviors=["handle missing file"]
            ),
        ):
            v = review_completeness(
                acceptance_criteria=["load returns [] on missing file"],
                patch_files=[_SRC, _TEST],
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(v.decision, DECISION_REVISE)
        self.assertEqual(v.source, "ollama")
        self.assertIn("handle missing file", v.missing_behaviors)
        self.assertTrue(v.blocking)

    def test_optional_findings_do_not_block(self) -> None:
        # Issue #38 #7: a revise verdict whose findings are all optional /
        # nice-to-have suggestions is downgraded to valid (advisory, not block).
        with patch(
            "completeness_review.OllamaClient.chat",
            return_value=_ai(
                DECISION_REVISE,
                missing_tests=[
                    "Test missing task id (although optional, robustness "
                    "suggests it)"
                ],
                missing_behaviors=["Consider adding input validation"],
            ),
        ):
            v = review_completeness(
                acceptance_criteria=["save persists data"],
                patch_files=[_SRC, _TEST],
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(v.decision, DECISION_VALID)
        self.assertFalse(v.blocking)
        self.assertEqual(v.missing_tests, [])
        self.assertEqual(v.missing_behaviors, [])

    def test_required_gap_still_blocks_after_dropping_optional(self) -> None:
        with patch(
            "completeness_review.OllamaClient.chat",
            return_value=_ai(
                DECISION_REVISE,
                missing_behaviors=[
                    "load returns [] on missing file",  # required -> blocks
                    "Consider extra logging",  # optional -> dropped
                ],
            ),
        ):
            v = review_completeness(
                acceptance_criteria=["load returns [] on missing file"],
                patch_files=[_SRC, _TEST],
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(v.decision, DECISION_REVISE)
        self.assertTrue(v.blocking)
        self.assertEqual(v.missing_behaviors, ["load returns [] on missing file"])

    def test_model_valid_passes(self) -> None:
        with patch(
            "completeness_review.OllamaClient.chat",
            return_value=_ai(DECISION_VALID),
        ):
            v = review_completeness(
                acceptance_criteria=["save persists data"],
                patch_files=[_SRC, _TEST],
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(v.decision, DECISION_VALID)
        self.assertFalse(v.blocking)

    def test_model_down_is_non_blocking_floor_only(self) -> None:
        with patch(
            "completeness_review.OllamaClient.chat",
            side_effect=OllamaConnectionError("offline"),
        ):
            v = review_completeness(
                acceptance_criteria=["save persists data"],
                patch_files=[
                    _SRC,
                    _TEST,
                ],  # has a test, so floor does not fire
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(v.decision, DECISION_VALID)
        self.assertEqual(v.source, "floor_only")
        self.assertFalse(v.blocking)


if __name__ == "__main__":
    unittest.main()
