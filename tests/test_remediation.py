"""Tests for the owner-gated, bounded validation-remediation loop.

The loop only triggers when the owner enabled ``allow_remediation``, a prior
advance left a ``validation_failed`` blocker, and the attempt budget remains. A
pass clears the blocker and resets the counter; a failure with budget remaining
keeps retrying; a failure on the last attempt parks on the terminal
``remediation_exhausted`` blocker for owner review.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from mission_state import _apply_validation_state  # noqa: E402
from remediation import (  # noqa: E402
    REMEDIATION_EXHAUSTED,
    VALIDATION_FAILED,
    fix_approval_record,
    plan_remediation,
    remediation_settings,
)
from validation_runner import ValidationResult  # noqa: E402

_ENABLED = {
    "validation": {"allow_remediation": True, "max_remediation_attempts": 3}
}
_DISABLED = {"validation": {"allow_remediation": False}}


def _result(status: str) -> ValidationResult:
    return ValidationResult(
        test_plan_id="TP1", checks=[], status=status, executed=True
    )


class PlanRemediationTests(unittest.TestCase):
    def test_inactive_when_disabled(self) -> None:
        plan = plan_remediation(
            _DISABLED, {"current_blocker": VALIDATION_FAILED}, "report"
        )
        self.assertFalse(plan.active)

    def test_inactive_without_validation_failed_blocker(self) -> None:
        plan = plan_remediation(_ENABLED, {"current_blocker": None}, "report")
        self.assertFalse(plan.active)

    def test_active_when_enabled_and_blocked_with_budget(self) -> None:
        plan = plan_remediation(
            _ENABLED,
            {"current_blocker": VALIDATION_FAILED, "remediation_attempt": 0},
            "the report",
        )
        self.assertTrue(plan.active)
        self.assertEqual(plan.attempt, 1)
        self.assertIn("the report", plan.context)
        self.assertFalse(plan.is_last_attempt)

    def test_inactive_when_budget_exhausted(self) -> None:
        plan = plan_remediation(
            _ENABLED,
            {"current_blocker": VALIDATION_FAILED, "remediation_attempt": 3},
            "report",
        )
        self.assertFalse(plan.active)

    def test_last_attempt_flag(self) -> None:
        plan = plan_remediation(
            _ENABLED,
            {"current_blocker": VALIDATION_FAILED, "remediation_attempt": 2},
            "report",
        )
        self.assertTrue(plan.active)
        self.assertEqual(plan.attempt, 3)
        self.assertTrue(plan.is_last_attempt)

    def test_settings_defaults(self) -> None:
        allow, max_attempts = remediation_settings({})
        self.assertFalse(allow)
        self.assertEqual(max_attempts, 3)


class ValidationStateTests(unittest.TestCase):
    def _apply(self, status, remediation):
        fs: dict = {}
        ar: dict = {}
        ps: dict = {"failure_count": 0}
        _apply_validation_state(fs, ar, ps, _result(status), "t0", remediation)
        return ps

    def test_remediation_pass_clears_blocker_and_resets_counter(self) -> None:
        plan = plan_remediation(
            _ENABLED,
            {"current_blocker": VALIDATION_FAILED, "remediation_attempt": 1},
            "r",
        )
        ps = self._apply("passed", plan)
        self.assertIsNone(ps["current_blocker"])
        self.assertEqual(ps["remediation_attempt"], 0)

    def test_remediation_fail_with_budget_keeps_retrying(self) -> None:
        plan = plan_remediation(
            _ENABLED,
            {"current_blocker": VALIDATION_FAILED, "remediation_attempt": 1},
            "r",
        )
        ps = self._apply("failed", plan)
        self.assertEqual(ps["current_blocker"], VALIDATION_FAILED)
        self.assertEqual(ps["remediation_attempt"], 2)

    def test_remediation_fail_on_last_attempt_is_terminal(self) -> None:
        plan = plan_remediation(
            _ENABLED,
            {"current_blocker": VALIDATION_FAILED, "remediation_attempt": 2},
            "r",
        )
        ps = self._apply("failed", plan)
        self.assertEqual(ps["current_blocker"], REMEDIATION_EXHAUSTED)
        self.assertEqual(ps["remediation_attempt"], 3)

    def test_first_failure_without_remediation_sets_plain_blocker(
        self,
    ) -> None:
        # No remediation plan (disabled) → behaves as before: validation_failed.
        ps = self._apply("failed", None)
        self.assertEqual(ps["current_blocker"], VALIDATION_FAILED)


class ApprovalRecordTests(unittest.TestCase):
    def test_fix_approval_record_marks_source(self) -> None:
        rec = fix_approval_record("P007")
        self.assertTrue(rec["application_approved"])
        self.assertEqual(rec["proposal_id"], "P007")
        self.assertEqual(rec["approved_by"], "remediation")


if __name__ == "__main__":
    unittest.main()
