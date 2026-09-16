"""Agentic control intelligence: persistence, rails, model decisions."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from control_intelligence import (  # noqa: E402
    COMPLETE,
    HUMAN_REQUIRED,
    MORE_WORK,
    ControlDecision,
    apply_rails,
    assemble_monitor,
    control_model_enabled,
    fallback_decision,
    load_attempts,
    persist_decision,
    reason_control,
)
from execution_assignment import compile_assignment  # noqa: E402
from objective_generator import (  # noqa: E402
    KIND_CODE_BIRTH,
    KIND_REPAIR_RUNTIME,
    next_execute_objective,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(app: Path) -> dict[str, object]:
    return {
        "name": "demo",
        "app_path": str(app),
        "task_root": str(app / "factory_tasks"),
        "factory_state_dir": str(app / "factory_state"),
        "context_root": str(app / "factory_context"),
        "state_dir": str(app / "state"),
        "seed_file": "docs/seed.md",
    }


class RailsTests(unittest.TestCase):
    def test_model_can_block_complete_on_quality(self) -> None:
        decision = ControlDecision(
            outcome=MORE_WORK,
            quality_ok=False,
            kind="implement",
            stance="investigate",
            rationale="tests do not cover the start path",
            source="model",
        )
        status, reason = apply_rails(
            decision,
            candidate_outcome=COMPLETE,
            candidate_reason="acceptance evidence is complete",
            accepted=True,
            runtime_safe=True,
        )
        self.assertEqual(status, MORE_WORK)
        self.assertIn("start path", reason)

    def test_model_cannot_force_complete(self) -> None:
        decision = ControlDecision(
            outcome=COMPLETE,
            quality_ok=True,
            kind="complete",
            stance="implement",
            source="model",
        )
        status, reason = apply_rails(
            decision,
            candidate_outcome=MORE_WORK,
            candidate_reason="ZERO_CODE_OUTPUT",
            accepted=False,
            runtime_safe=True,
        )
        self.assertEqual(status, MORE_WORK)
        self.assertIn("ZERO_CODE", reason)

    def test_budget_and_human_are_vetoes(self) -> None:
        decision = ControlDecision(
            outcome=MORE_WORK,
            quality_ok=True,
            kind="implement",
            stance="implement",
            source="model",
        )
        status, _reason = apply_rails(
            decision,
            candidate_outcome=HUMAN_REQUIRED,
            candidate_reason="owner stop flag is set",
            accepted=False,
            runtime_safe=True,
        )
        self.assertEqual(status, HUMAN_REQUIRED)


class PersistenceTests(unittest.TestCase):
    def test_evaluate_writes_attempt_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(
                app / "docs/seed.md",
                "Goal:\nBuild a todo tracker.\n\nSuccess:\nAdd tasks.\n",
            )
            project = _project(app)
            reason_control(
                project,
                Path(tmp),
                beat=0,
                max_beats=5,
                candidate_outcome=MORE_WORK,
                candidate_reason="ZERO_CODE_OUTPUT",
                accepted=False,
                runtime_status="unspecified",
                heuristic_kind=KIND_CODE_BIRTH,
                heuristic_stance="birth",
            )
            tasks = app / "factory_tasks"
            self.assertTrue((tasks / "attempts.jsonl").is_file())
            self.assertTrue((tasks / "control_memory.json").is_file())
            rows = load_attempts(tasks)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source"], "fallback")


class OverlayTests(unittest.TestCase):
    def test_model_decision_replaces_greenfield_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(
                app / "docs/seed.md",
                "Goal:\nBuild a todo tracker.\n\nSuccess:\nAdd tasks.\n",
            )
            persist_decision(
                ControlDecision(
                    outcome=MORE_WORK,
                    quality_ok=False,
                    kind=KIND_REPAIR_RUNTIME,
                    stance="repair",
                    title="Make the application start",
                    focus="Implement src.task_board",
                    rationale="declared start module is missing",
                    source="model",
                    provider="anthropic",
                ),
                app / "factory_tasks",
            )
            obj = next_execute_objective(_project(app), Path(tmp))
            self.assertEqual(obj.kind, KIND_REPAIR_RUNTIME)
            self.assertEqual(obj.source, "control")
            self.assertIn("task_board", obj.focus)

    def test_model_stance_reaches_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(
                app / "docs/seed.md",
                "Goal:\nBuild a todo tracker.\n\nSuccess:\nAdd tasks.\n",
            )
            persist_decision(
                ControlDecision(
                    outcome=MORE_WORK,
                    quality_ok=False,
                    kind=KIND_CODE_BIRTH,
                    stance="investigate",
                    source="model",
                ),
                app / "factory_tasks",
            )
            obj = next_execute_objective(_project(app), Path(tmp))
            assignment = compile_assignment(_project(app), Path(tmp), obj)
            self.assertEqual(assignment.stance, "investigate")


class ModelCallTests(unittest.TestCase):
    def test_reason_control_uses_structured_reply(self) -> None:
        payload = {
            "outcome": MORE_WORK,
            "quality_ok": False,
            "kind": "repair_validation",
            "stance": "investigate",
            "title": "Fix pytest",
            "focus": "the failing assertion in tests/test_todo.py",
            "rationale": "same files rewritten, same pytest failure",
            "recovery": "retry",
            "director_why": "continue; tests still fail",
            "memory_notes": "pytest still asserts False on add()",
        }
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(app / "src/todo.py", "def add(x):\n    return x\n")
            project = _project(app)
            env = {
                k: v
                for k, v in os.environ.items()
                if k != "CRAZY_FACTORY_CONTROL"
            }
            env["CRAZY_FACTORY_CONTROL"] = "1"
            with (
                patch.dict(os.environ, env, clear=True),
                patch(
                    "control_intelligence.resolve_coding_backend",
                    return_value=("anthropic", object(), "claude"),
                ),
                patch(
                    "control_intelligence.structured_call",
                    return_value=(payload, "ok"),
                ),
            ):
                self.assertTrue(control_model_enabled())
                decision = reason_control(
                    project,
                    Path(tmp),
                    beat=1,
                    max_beats=8,
                    candidate_outcome=MORE_WORK,
                    candidate_reason="pytest failed",
                    accepted=False,
                    runtime_status="unspecified",
                )
            self.assertEqual(decision.source, "model")
            self.assertEqual(decision.kind, "repair_validation")
            self.assertEqual(decision.stance, "investigate")
            saved = json.loads(
                (app / "factory_tasks/control_decision.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(saved["provider"], "anthropic")
            memory = json.loads(
                (app / "factory_tasks/control_memory.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn("pytest", memory["notes"])

    def test_monitor_packet_includes_attempts_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(app / "src/todo.py", "def add(x):\n    return x\n")
            tasks = app / "factory_tasks"
            _write(
                tasks / "executor_result.json",
                json.dumps(
                    {
                        "ok": True,
                        "files": ["src/todo.py"],
                        "provider": "openai",
                    }
                ),
            )
            packet = assemble_monitor(
                _project(app),
                Path(tmp),
                beat=2,
                max_beats=8,
                candidate_outcome=MORE_WORK,
                candidate_reason="work remains",
                accepted=False,
                runtime_status="missing",
            )
            self.assertEqual(packet["executor"]["files"], ["src/todo.py"])
            self.assertIn("src/todo.py", packet["executor"]["hashes"])
            self.assertNotEqual(
                packet["executor"]["hashes"]["src/todo.py"], "missing"
            )
            fallback = fallback_decision(
                outcome=MORE_WORK, reason="work remains"
            )
            self.assertEqual(fallback.source, "fallback")
