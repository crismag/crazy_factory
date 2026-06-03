"""Tests for the AI-reviewed contract decision ladder.

The contract decision is graded, not binary: a deterministic safety floor the AI
can never relax, then AI analysis that repairs safe completeness gaps, then a
deterministic repair fallback, then an owner-review checklist. A safe-but-
incomplete contract must be repaired (not hard-rejected); an unsafe one must be
rejected even if the AI says otherwise; the AI being down must never fake-pass.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from contract_review import (  # noqa: E402
    DECISION_NEEDS_OWNER_REVIEW,
    DECISION_REJECT_UNSAFE,
    DECISION_REPAIR,
    DECISION_VALID,
    review_contract,
)
from ollama_client import OllamaConnectionError  # noqa: E402
from task_contract import parse_planned_task  # noqa: E402

_MODELS = {"models": {"reviewer": "gemma4:latest"}}
_FACTORY = {
    "ollama": {
        "base_url": "http://localhost:11434",
        "timeout_seconds": 1,
        "stream": False,
    }
}


def _task(**over: object):
    data: dict[str, object] = {
        "task_id": "T-1",
        "title": "Add a status note",
        "objective": "Document the build status in docs",
        "scope": ["Add a status note to the docs"],
        "exclusions": ["No application code changes"],
        "acceptance_criteria": ["A status note exists"],
        "inputs": [],
        "validation_plan": "Owner reads the docs and confirms.",
        "risks": [],
        "approval_status": "pending",
        "authorized": False,
    }
    data.update(over)
    return parse_planned_task(json.dumps(data))


def _ai(decision: str, **extra: object):
    payload = {"decision": decision, **extra}
    return {"message": {"content": json.dumps(payload)}}


class ReviewTests(unittest.TestCase):
    def test_complete_safe_contract_is_valid_without_ai(self) -> None:
        # No completeness gaps → valid; the reviewer is never consulted.
        with patch(
            "contract_review.OllamaClient.chat",
            side_effect=AssertionError("AI must not be called when complete"),
        ):
            v = review_contract(
                _task(), models_config=_MODELS, factory_config=_FACTORY
            )
        self.assertEqual(v.decision, DECISION_VALID)
        self.assertTrue(v.valid)

    def test_floor_wins_over_ai(self) -> None:
        # Unsafe (forbidden op in scope) → reject_unsafe even if the AI says
        # valid. The floor runs first and the AI is never consulted.
        with patch(
            "contract_review.OllamaClient.chat", return_value=_ai("valid")
        ):
            v = review_contract(
                _task(scope=["git push to origin main"]),
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(v.decision, DECISION_REJECT_UNSAFE)
        self.assertFalse(v.valid)
        self.assertEqual(v.status, "rejected")

    def test_self_authorization_is_rejected(self) -> None:
        v = review_contract(
            _task(authorized=True),
            models_config=_MODELS,
            factory_config=_FACTORY,
        )
        self.assertEqual(v.decision, DECISION_REJECT_UNSAFE)

    def test_ai_repair_fills_missing_validation_plan(self) -> None:
        with patch(
            "contract_review.OllamaClient.chat",
            return_value=_ai(
                "repair",
                repairs={"validation_plan": "Run pytest and confirm."},
            ),
        ):
            v = review_contract(
                _task(validation_plan=""),
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(v.decision, DECISION_REPAIR)
        self.assertTrue(v.valid)
        self.assertEqual(v.task.validation_plan, "Run pytest and confirm.")
        self.assertIn("validation_plan", v.repairs_applied)

    def test_ai_down_falls_back_to_deterministic_repair(self) -> None:
        # Reviewer unreachable → synthesize validation_plan from acceptance
        # criteria; safe+incomplete is repaired, never hard-rejected or faked.
        with patch(
            "contract_review.OllamaClient.chat",
            side_effect=OllamaConnectionError("down"),
        ):
            v = review_contract(
                _task(validation_plan=""),
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(v.decision, DECISION_REPAIR)
        self.assertTrue(v.valid)
        self.assertTrue(v.task.validation_plan)  # synthesized, non-empty

    def test_indeterminate_escalates_to_owner_checklist(self) -> None:
        # A gap deterministic repair cannot fill (empty objective) + AI down →
        # owner-review checklist, not a fake valid.
        with patch(
            "contract_review.OllamaClient.chat",
            side_effect=OllamaConnectionError("down"),
        ):
            v = review_contract(
                _task(objective=""),
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(v.decision, DECISION_NEEDS_OWNER_REVIEW)
        self.assertFalse(v.valid)
        self.assertEqual(v.status, "needs_owner_review")
        self.assertTrue(v.checklist)

    def test_ai_can_escalate_to_owner_review(self) -> None:
        with patch(
            "contract_review.OllamaClient.chat",
            return_value=_ai(
                "needs_owner_review",
                owner_review_reasons=["Scope is ambiguous"],
            ),
        ):
            v = review_contract(
                _task(validation_plan=""),
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(v.decision, DECISION_NEEDS_OWNER_REVIEW)
        self.assertIn("Scope is ambiguous", v.checklist)

    def test_no_configs_uses_deterministic_repair(self) -> None:
        # Without model/factory config (e.g. unit context), still repairs.
        v = review_contract(_task(validation_plan=""))
        self.assertEqual(v.decision, DECISION_REPAIR)
        self.assertTrue(v.valid)


class MissionStateCheckpointTests(unittest.TestCase):
    """needs_owner_review is a waiting checkpoint, not a stall-failure."""

    def test_needs_owner_review_is_not_a_failure(self) -> None:
        from contract_stage import ContractResult
        from mission_state import update_success_state
        from planning_roles import RoleResult
        from task_contract import ValidationVerdict

        factory_state = {"failure_count": 2}
        active_run: dict = {}
        project_state = {"current_task": "T-1", "failure_count": 2}
        contract = ContractResult(
            task=_task(objective=""),
            verdict=ValidationVerdict(False, ["Missing objective"]),
            source="ollama",
            detail="needs review",
            decision="needs_owner_review",
        )
        update_success_state(
            factory_state,
            active_run,
            project_state,
            RoleResult("architect", "x", "ollama", "m"),
            RoleResult("planner", "y", "ollama", "m"),
            contract_result=contract,
        )
        # Not counted as a failure; no persistent blocker; recorded as waiting.
        self.assertEqual(project_state["failure_count"], 0)
        self.assertNotEqual(
            project_state.get("current_blocker"), "planning_contract_rejected"
        )
        self.assertEqual(
            project_state["last_contract_status"], "needs_owner_review"
        )

    def test_reject_unsafe_is_still_a_failure(self) -> None:
        from contract_stage import ContractResult
        from mission_state import update_success_state
        from planning_roles import RoleResult
        from task_contract import ValidationVerdict

        factory_state = {"failure_count": 0}
        active_run = {}
        project_state = {"current_task": "T-1", "failure_count": 0}
        contract = ContractResult(
            task=_task(scope=["git push to origin"]),
            verdict=ValidationVerdict(False, ["forbidden op"]),
            source="ollama",
            detail="unsafe",
            decision="reject_unsafe",
        )
        update_success_state(
            factory_state,
            active_run,
            project_state,
            RoleResult("architect", "x", "ollama", "m"),
            RoleResult("planner", "y", "ollama", "m"),
            contract_result=contract,
        )
        self.assertEqual(project_state["failure_count"], 1)
        self.assertEqual(
            project_state["current_blocker"], "planning_contract_rejected"
        )


if __name__ == "__main__":
    unittest.main()
