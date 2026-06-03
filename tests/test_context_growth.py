"""Tests for the Phase 9 seed-grown context engine.

These cover seed initialization, the ledger, one-artifact-per-grow, the
implementation-task contract bridge (authorized: false, no apply), safe
failure on bad seeds, and the no-auto-apply / no-auto-commit boundary. Model
calls are mocked; no Ollama and no application writes occur.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from context_growth import grow, request_growth  # noqa: E402
from context_ledger import LedgerError, load_ledger  # noqa: E402
from ollama_client import OllamaConnectionError  # noqa: E402
from seed_context import SeedError, init_project  # noqa: E402

_FACTORY_CONFIG = {
    "ollama": {
        "base_url": "http://localhost:11434",
        "timeout_seconds": 1,
        "stream": False,
    }
}
_MODELS_CONFIG = {"models": {"planner": "cogito:14b"}}

_SEED = (
    "# Factory Seed\n\nGoal:\nBuild a small SQLite app.\n\n"
    "Success:\nCreate, list, update, search.\n"
)


def _seeded_project(root: Path) -> str:
    """Initialize a demo project from a seed and return its id."""
    (root / "seeds").mkdir()
    (root / "seeds/seed.md").write_text(_SEED, encoding="utf-8")
    init_project(seed_path="seeds/seed.md", project_id="demo", root=root)
    return "demo"


def _grow_with(
    root: Path, decision: dict[str, object]
) -> tuple[str, str, dict]:
    """Run one grow cycle with a mocked model decision."""
    with patch(
        "context_growth.OllamaClient.chat",
        return_value={"message": {"content": json.dumps(decision)}},
    ):
        return grow(
            project_id="demo",
            root=root,
            factory_config=_FACTORY_CONFIG,
            models_config=_MODELS_CONFIG,
        )


class SeedInitTests(unittest.TestCase):
    """Seed initialization and ledger creation."""

    def test_seed_initializes_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _seeded_project(root)
            base = root / "factory_state/projects/demo"
            self.assertTrue((base / "seed.md").is_file())
            self.assertTrue((base / "contexts/000_seed.md").is_file())
            for sub in ("proposals", "contracts", "runs", "reflections"):
                self.assertTrue((base / sub).is_dir(), sub)

    def test_ledger_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _seeded_project(root)
            ledger = load_ledger("demo", root)
            self.assertEqual(ledger["project_id"], "demo")
            self.assertEqual(len(ledger["artifacts"]), 1)
            self.assertEqual(ledger["artifacts"][0]["type"], "seed")

    def test_invalid_seed_fails_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(SeedError):
                init_project(
                    seed_path="nope/missing.md", project_id="demo", root=root
                )
            # Empty seed is also rejected.
            (root / "empty.md").write_text("   \n", encoding="utf-8")
            with self.assertRaises(SeedError):
                init_project(
                    seed_path="empty.md", project_id="demo", root=root
                )

    def test_invalid_project_id_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "s.md").write_text(_SEED, encoding="utf-8")
            for bad in ["../escape", "Has Space", "UPPER", "a/b"]:
                with self.assertRaises(SeedError):
                    init_project(seed_path="s.md", project_id=bad, root=root)

    def test_grow_requires_existing_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(LedgerError):
                grow(
                    project_id="demo",
                    root=root,
                    factory_config=_FACTORY_CONFIG,
                    models_config=_MODELS_CONFIG,
                )


class GrowTests(unittest.TestCase):
    """One grow cycle produces exactly one recorded artifact."""

    def test_grow_creates_exactly_one_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _seeded_project(root)
            contexts = root / "factory_state/projects/demo/contexts"
            before = len(list(contexts.glob("*")))
            atype, path, ledger = _grow_with(
                root,
                {
                    "next_artifact_type": "observation",
                    "reason": "Interpret the seed goal.",
                    "requires_user_input": False,
                    "safe_to_continue": True,
                    "content": "The goal is a small SQLite app.",
                },
            )
            after = len(list(contexts.glob("*")))
            self.assertEqual(after - before, 1)
            self.assertEqual(atype, "observation")
            self.assertTrue((root / path).is_file())

    def test_artifact_recorded_in_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _seeded_project(root)
            _, path, _ = _grow_with(
                root,
                {
                    "next_artifact_type": "requirements",
                    "reason": "Define feature boundaries.",
                    "requires_user_input": False,
                    "safe_to_continue": True,
                    "content": "- create\n- list\n- update\n- search\n",
                },
            )
            ledger = load_ledger("demo", root)
            self.assertEqual(ledger["current_cycle"], 1)
            self.assertEqual(len(ledger["artifacts"]), 2)
            last = ledger["artifacts"][-1]
            self.assertEqual(last["type"], "requirements")
            self.assertEqual(last["path"], path)

    def test_unknown_type_degrades_to_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _seeded_project(root)
            atype, _, _ = _grow_with(
                root,
                {
                    "next_artifact_type": "make_me_a_sandwich",
                    "reason": "x",
                    "content": "body",
                },
            )
            self.assertEqual(atype, "observation")

    def test_model_unavailable_falls_back_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _seeded_project(root)
            with patch(
                "context_growth.OllamaClient.chat",
                side_effect=OllamaConnectionError("offline"),
            ):
                atype, path, ledger = grow(
                    project_id="demo",
                    root=root,
                    factory_config=_FACTORY_CONFIG,
                    models_config=_MODELS_CONFIG,
                )
            self.assertEqual(len(ledger["artifacts"]), 2)
            self.assertTrue((root / path).is_file())
            self.assertIn("fallback", (root / path).read_text().lower())


class BridgeAndBoundaryTests(unittest.TestCase):
    """The implementation bridge stays unauthorized and never applies."""

    def test_task_proposal_routes_to_unauthorized_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _seeded_project(root)
            contract = {
                "task_id": "SQL-001",
                "title": "Create the SQLite schema module",
                "objective": "Add a db module that creates the schema.",
                "scope": ["Add apps/demo/app/db.py with a schema creator"],
                "exclusions": ["No UI", "No git operations"],
                "inputs": [],
                "acceptance_criteria": ["A db module exists", "Owner reviews"],
                "validation_plan": "Run the unit tests for the db module.",
                "risks": ["None significant"],
                "approval_status": "pending",
            }
            atype, path, _ = _grow_with(
                root,
                {
                    "next_artifact_type": "task_proposal",
                    "reason": "The architecture is ready to implement.",
                    "requires_user_input": False,
                    "safe_to_continue": True,
                    "content": json.dumps(contract),
                },
            )
            self.assertEqual(atype, "task_proposal")
            record = json.loads((root / path).read_text())
            # The bridge never authorizes; owner must do so downstream.
            self.assertIs(record["authorized"], False)
            self.assertEqual(record["task_id"], "SQL-001")
            self.assertEqual(record["source_layer"], "context_growth")

    def test_growth_never_writes_application_code_or_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _seeded_project(root)
            _grow_with(
                root,
                {
                    "next_artifact_type": "task_proposal",
                    "reason": "implement",
                    "content": json.dumps(
                        {
                            "task_id": "SQL-001",
                            "title": "t",
                            "objective": "o",
                            "scope": ["apps/demo/app/db.py"],
                            "exclusions": ["x"],
                            "acceptance_criteria": ["a"],
                            "validation_plan": "v",
                        }
                    ),
                },
            )
            # Nothing was written outside factory_state: no app code, no git.
            self.assertFalse((root / "apps").exists())
            self.assertFalse((root / ".git").exists())
            written = {
                p.relative_to(root).parts[0]
                for p in root.rglob("*")
                if p.is_file()
            }
            self.assertTrue(written <= {"factory_state", "seeds"}, written)

    def test_malformed_task_proposal_is_unauthorized_not_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _seeded_project(root)
            _, path, _ = _grow_with(
                root,
                {
                    "next_artifact_type": "task_proposal",
                    "reason": "implement",
                    "content": "this is not valid contract json",
                },
            )
            record = json.loads((root / path).read_text())
            self.assertIs(record["authorized"], False)
            self.assertEqual(record["validation"]["status"], "rejected")


class RequestGrowthTests(unittest.TestCase):
    """The request layer parses and bounds model output."""

    def test_parses_valid_decision(self) -> None:
        decision = {
            "next_artifact_type": "architecture",
            "reason": "Sketch the modules.",
            "requires_user_input": False,
            "safe_to_continue": True,
            "content": "## Modules\n- app\n- db\n",
        }
        with patch(
            "context_growth.OllamaClient.chat",
            return_value={"message": {"content": json.dumps(decision)}},
        ):
            result = request_growth(
                seed=_SEED,
                recent=[("seed", _SEED)],
                factory_config=_FACTORY_CONFIG,
                models_config=_MODELS_CONFIG,
            )
        self.assertEqual(result.artifact_type, "architecture")
        self.assertEqual(result.source, "ollama")

    def test_unparseable_response_falls_back(self) -> None:
        with patch(
            "context_growth.OllamaClient.chat",
            return_value={"message": {"content": "not json"}},
        ):
            result = request_growth(
                seed=_SEED,
                recent=[],
                factory_config=_FACTORY_CONFIG,
                models_config=_MODELS_CONFIG,
            )
        self.assertEqual(result.source, "fallback")
        self.assertNotEqual(result.artifact_type, "task_proposal")


if __name__ == "__main__":
    unittest.main()
