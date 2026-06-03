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

from context_growth import (  # noqa: E402
    PromoteError,
    grow,
    promote,
    request_growth,
)
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


def _task_proposal_record(*, valid: bool, authorized: bool) -> dict:
    """Return a grown task-proposal contract record."""
    return {
        "task_id": "T1",
        "title": "Create the schema module",
        "objective": "Add a db module.",
        "scope": ["apps/demo/app/db.py"],
        "exclusions": ["No UI"],
        "inputs": [],
        "acceptance_criteria": ["A db module exists"],
        "validation_plan": "Run the unit tests.",
        "risks": [],
        "approval_status": "pending",
        "authorized": authorized,
        "source_layer": "context_growth",
        "validation": {
            "status": "valid" if valid else "rejected",
            "source": "context_growth",
            "reasons": [],
        },
    }


def _promote_fixture(
    root: Path,
    *,
    with_proposal: bool = True,
    proposal_valid: bool = True,
    authorized_in_record: bool = False,
    preexisting_app: bool = False,
) -> None:
    """Lay down config, state, and a grown project for promote tests."""
    (root / "config").mkdir()
    (root / "config/factory.yaml").write_text(
        "factory:\n  mode: dry_run\n  active_project: olddemo\n"
        "  state_dir: state\n",
        encoding="utf-8",
    )
    projects = (
        "active_project: olddemo\n\nprojects:\n  olddemo:\n"
        "    root: apps/olddemo\n    task_root: apps/olddemo/factory_tasks\n"
    )
    if preexisting_app:
        projects += (
            "  demo:\n    root: apps/demo\n"
            "    task_root: apps/demo/factory_tasks\n"
        )
        (root / "apps/demo/app").mkdir(parents=True)
        (root / "apps/demo/app/keep.py").write_text("x = 1\n")
    (root / "config/projects.yaml").write_text(projects, encoding="utf-8")

    (root / "state").mkdir()
    (root / "state/factory_state.json").write_text(
        json.dumps({"active_project": "olddemo", "mode": "dry_run"}),
        encoding="utf-8",
    )
    (root / "state/project_state.json").write_text(
        json.dumps(
            {"project": "olddemo", "current_task": "OLD", "failure_count": 3}
        ),
        encoding="utf-8",
    )
    (root / "state/active_run.json").write_text(
        json.dumps({"active_project": "olddemo", "current_task": "OLD"}),
        encoding="utf-8",
    )

    base = root / "factory_state/projects/demo"
    (base / "contexts").mkdir(parents=True)
    (base / "seed.md").write_text(_SEED, encoding="utf-8")
    artifacts = [
        {
            "id": "000",
            "type": "seed",
            "path": "factory_state/projects/demo/contexts/000_seed.md",
            "summary": "seed",
        }
    ]
    if with_proposal:
        rel = "factory_state/projects/demo/contexts/001_task_proposal.json"
        (root / rel).write_text(
            json.dumps(
                _task_proposal_record(
                    valid=proposal_valid, authorized=authorized_in_record
                )
            ),
            encoding="utf-8",
        )
        artifacts.append(
            {
                "id": "001",
                "type": "task_proposal",
                "path": rel,
                "summary": "impl",
            }
        )
    (base / "context_ledger.json").write_text(
        json.dumps(
            {"project_id": "demo", "current_cycle": 1, "artifacts": artifacts}
        ),
        encoding="utf-8",
    )


class PromoteTests(unittest.TestCase):
    """Verify the owner-driven promote bridge to the build pipeline."""

    def test_no_task_proposal_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _promote_fixture(root, with_proposal=False)
            with self.assertRaises(PromoteError):
                promote("demo", root)

    def test_rejected_task_proposal_not_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _promote_fixture(root, proposal_valid=False)
            with self.assertRaises(PromoteError):
                promote("demo", root)

    def test_config_registers_and_switches_active_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _promote_fixture(root)
            promote("demo", root)
            projects = (root / "config/projects.yaml").read_text()
            # promote writes a registry entry in the App Builder schema and
            # makes it active; factory.yaml is no longer the source of truth.
            self.assertIn('active_project: "demo"', projects)
            self.assertIn("  demo:", projects)
            self.assertIn('app_path: "apps/demo"', projects)
            self.assertIn('repo_mode: "embedded"', projects)

    def test_state_repointed_to_new_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _promote_fixture(root)
            promote("demo", root)
            fs = json.loads((root / "state/factory_state.json").read_text())
            ps = json.loads((root / "state/project_state.json").read_text())
            self.assertEqual(fs["active_project"], "demo")
            self.assertEqual(ps["project"], "demo")
            self.assertEqual(ps["current_task"], "T1")
            self.assertEqual(ps["failure_count"], 0)

    def test_contract_forced_unauthorized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            # Even a tampered record claiming authorized:true is forced false.
            _promote_fixture(root, authorized_in_record=True)
            promote("demo", root)
            contract = json.loads(
                (
                    root / "apps/demo/factory_tasks/planned_task.json"
                ).read_text()
            )
            self.assertIs(contract["authorized"], False)
            self.assertEqual(contract["task_id"], "T1")
            self.assertEqual(contract["promoted_from"], "context_growth")

    def test_existing_app_not_duplicated_or_clobbered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _promote_fixture(root, preexisting_app=True)
            promote("demo", root)
            projects = (root / "config/projects.yaml").read_text()
            # The demo block is not added twice.
            self.assertEqual(projects.count("\n  demo:"), 1)
            # Existing app code is untouched.
            self.assertEqual(
                (root / "apps/demo/app/keep.py").read_text(), "x = 1\n"
            )

    def test_promote_does_not_build_or_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _promote_fixture(root)
            promote("demo", root)
            # No git repo and no coder/proposal/checkpoint artifacts created.
            self.assertFalse((root / ".git").exists())
            tasks = root / "apps/demo/factory_tasks"
            self.assertFalse((tasks / "coder_proposal.json").exists())
            self.assertFalse((tasks / "patch_plan.json").exists())
            self.assertFalse(
                (
                    root / "apps/demo/factory_reports/CHECKPOINT_REPORT.md"
                ).exists()
            )


if __name__ == "__main__":
    unittest.main()
