"""Tests for the seed-derived project contract (Phase 9E.ST6)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from project_contract import (  # noqa: E402
    Seed,
    contract_from_seed,
    derive_tech,
    parse_seed,
    to_architecture_contract,
    validate_contract,
)

CLI_TODO_SEED = (ROOT / "examples/seeds/cli_todo_tracker.md").read_text(
    encoding="utf-8"
)
SQLITE_SEED = (ROOT / "examples/seeds/sqlite_project_manager.md").read_text(
    encoding="utf-8"
)


class ParseSeedTests(unittest.TestCase):
    def test_parses_labelled_sections(self) -> None:
        seed = parse_seed(CLI_TODO_SEED)
        self.assertIn("command-line todo tracker", seed.goal)
        self.assertIn("Python", seed.constraints)
        self.assertTrue(
            any("JSON file" in c for c in seed.constraints), seed.constraints
        )
        self.assertTrue(
            any("complete" in s.lower() for s in seed.success), seed.success
        )

    def test_skips_none_yet_and_titles(self) -> None:
        seed = parse_seed(SQLITE_SEED)
        # "Known Context: None yet." must not leak into any section.
        blob = " ".join(seed.constraints + seed.success).lower()
        self.assertNotIn("none yet", blob)
        self.assertNotIn("factory seed", seed.goal.lower())

    def test_missing_sections_degrade_to_empty(self) -> None:
        seed = parse_seed("Goal:\nBuild a thing.\n")
        self.assertEqual(seed.constraints, [])
        self.assertEqual(seed.success, [])
        self.assertEqual(seed.goal, "Build a thing.")


class DeriveTechTests(unittest.TestCase):
    def test_stdlib_only_forbids_everything(self) -> None:
        seed = parse_seed(CLI_TODO_SEED)  # "Standard library only"
        forbidden, allowed = derive_tech(seed)
        self.assertEqual(allowed, [])
        self.assertIn("flask", forbidden)
        self.assertIn("sqlite3", forbidden)
        self.assertIn("sqlalchemy", forbidden)

    def test_named_tech_is_allowed_by_group(self) -> None:
        seed = parse_seed(SQLITE_SEED)  # names "SQLite"
        forbidden, allowed = derive_tech(seed)
        # Naming SQLite allows the whole database group...
        self.assertIn("sqlite3", allowed)
        self.assertIn("sqlalchemy", allowed)
        self.assertNotIn("sqlite3", forbidden)
        # ...but web/auth stay forbidden (not named).
        self.assertIn("flask", forbidden)
        self.assertIn("jwt", forbidden)


class ContractTests(unittest.TestCase):
    def test_behaviors_default_to_success_criteria(self) -> None:
        seed = parse_seed(CLI_TODO_SEED)
        contract = contract_from_seed(seed)
        self.assertEqual(contract.required_behaviors, seed.success)
        self.assertIn("pytest the test suite", contract.validation)
        self.assertEqual(contract.required_tree, [])

    def test_tree_drives_validation_and_persistence(self) -> None:
        seed = parse_seed(CLI_TODO_SEED)
        tree = [
            "README.md",
            "src/main.py",
            "src/storage.py",
            "data/tasks.json",
            "tests/test_storage.py",
        ]
        contract = contract_from_seed(seed, required_tree=tree)
        self.assertEqual(contract.persistence_target, "data/tasks.json")
        self.assertIn("launch src/main.py", contract.validation)

    def test_validate_flags_persistence_outside_tree(self) -> None:
        seed = parse_seed(CLI_TODO_SEED)
        contract = contract_from_seed(
            seed, required_tree=["src/app.py", "data/db.json"]
        )
        # data/db.json is the persistence target and IS in the tree -> clean.
        self.assertEqual(validate_contract(contract), [])

    def test_validate_flags_non_relative_path(self) -> None:
        seed = Seed(goal="g", constraints=[], success=[])
        contract = contract_from_seed(seed, required_tree=["/etc/passwd"])
        reasons = validate_contract(contract)
        self.assertTrue(any("workbench-relative" in r for r in reasons), reasons)

    def test_validate_flags_missing_goal(self) -> None:
        seed = Seed(goal="", constraints=[], success=[])
        contract = contract_from_seed(seed)
        self.assertTrue(
            any("no goal" in r for r in validate_contract(contract))
        )


class RenderTests(unittest.TestCase):
    def test_renders_architecture_schema(self) -> None:
        seed = parse_seed(CLI_TODO_SEED)
        tree = [
            "README.md",
            "src/todo.py",
            "data/tasks.json",
            "tests/test_todo.py",
        ]
        arch = to_architecture_contract(contract_from_seed(seed, required_tree=tree))
        self.assertEqual(arch["src_dirs"], ["src"])
        self.assertEqual(arch["test_dirs"], ["tests"])
        self.assertIn("README.md", arch["extra_allowed"])
        self.assertIn("data", arch["extra_allowed"])
        self.assertEqual(arch["required_files"], tree)
        self.assertIn("flask", arch["forbidden_imports"])


if __name__ == "__main__":
    unittest.main()
