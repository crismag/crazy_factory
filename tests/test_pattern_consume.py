"""Slice 6 — bounded packet consumes advisory pattern hits."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from execution_assignment import (
    ADVISORY_PATTERN_CONSTRAINT,
    ADVISORY_PATTERN_HEADING,
    ASSIGNMENT_JSON,
    compile_assignment,
    load_assignment,
    persist_assignment,
    render_assignment,
)
from product_intent import bump_revision, fallback_capabilities, persist_intent
from task_graph import STATUS_READY, TaskNode

OBJ = SimpleNamespace(
    id="OBJ-PRODUCT",
    kind="implement",
    title="Implement requested product capabilities",
    gap="define_habits",
    why="product intent",
    focus="Implement: User can define habits.",
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(app: Path) -> dict[str, str]:
    return {
        "name": "demo",
        "app_path": str(app),
        "task_root": str(app / "factory_tasks"),
        "seed_file": "docs/seed.md",
        "factory_state_dir": str(app / "factory_state"),
    }


def _claim_task(**overrides: object) -> TaskNode:
    data = {
        "task_id": "TASK-CLAIM-define_habits",
        "parent_objective_id": "OBJ-PRODUCT",
        "intent_revision": 1,
        "title": "Implement claim: User can define habits.",
        "purpose": "Advances product claim `define_habits`.",
        "status": STATUS_READY,
        "kind": "implement",
        "claim_ids": ("define_habits",),
        "evidence_targets": ("runtime",),
        "context_refs": (
            "product_intent@revision-1",
            "claim:define_habits",
        ),
        "affected_scope": ("src/habits.py",),
    }
    data.update(overrides)
    return TaskNode(**data)  # type: ignore[arg-type]


def _habit_workbench(app: Path, root: Path, *, revision: int = 1) -> None:
    persist_intent(
        _project(app),
        root,
        prompt="build a habit tracker",
        capabilities=fallback_capabilities("build a habit tracker"),
        source="compile",
        revision=revision,
    )
    _write(app / "src/habits.py", "def add():\n    return 1\n")
    _write(app / "src/ui.py", "TITLE = 'habit'\n")
    _write(
        app / "architecture.json",
        json.dumps(
            {
                "stack": "stdlib-web",
                "title": "keep-me",
                "forbidden_imports": ["flask"],
                "required_files": ["src/habits.py", "src/ui.py"],
            }
        ),
    )


class PatternConsumeTests(unittest.TestCase):
    def test_habit_packet_attaches_catalog_hits_from_engine_not_workbench(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            _habit_workbench(app, root)
            assignment = compile_assignment(
                _project(app), root, OBJ, task=_claim_task()
            )
            self.assertTrue(assignment.pattern_ids)
            self.assertLessEqual(len(assignment.pattern_ids), 4)
            joined = " ".join(assignment.pattern_ids)
            self.assertTrue(
                "habit" in joined or "stdlib-web" in joined,
                assignment.pattern_ids,
            )
            self.assertTrue(assignment.pattern_notes)
            self.assertEqual(
                len(assignment.pattern_ids), len(assignment.pattern_notes)
            )
            self.assertNotIn(
                "pattern:archetype.habit-tracker", assignment.context_refs
            )

    def test_patterns_do_not_rewrite_authority_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            _habit_workbench(app, root)
            assignment = compile_assignment(
                _project(app), root, OBJ, task=_claim_task()
            )
            self.assertEqual(assignment.claim_ids, ("define_habits",))
            self.assertEqual(assignment.repo_scope, ("file:src/habits.py",))
            self.assertIn("keep-me", assignment.architecture_excerpt)
            self.assertIn("flask", assignment.architecture_excerpt)
            self.assertIn(
                "build a habit tracker", assignment.owner_intent_slice
            )
            self.assertNotIn("pattern_id", assignment.architecture_excerpt)
            self.assertNotIn("archetype.", assignment.architecture_excerpt)
            self.assertIn(ADVISORY_PATTERN_CONSTRAINT, assignment.constraints)
            contract = json.loads(
                (app / "architecture.json").read_text(encoding="utf-8")
            )
            self.assertEqual(contract["title"], "keep-me")
            intent = json.loads(
                (app / "factory_tasks" / "product_intent.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                intent["original_prompt"], "build a habit tracker"
            )

    def test_stale_packet_omits_current_catalog_hits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            project = _project(app)
            _habit_workbench(app, root, revision=1)
            task = _claim_task(intent_revision=1)
            current = compile_assignment(project, root, OBJ, task=task)
            self.assertTrue(current.pattern_ids)
            bump_revision(project, root, [])
            stale = compile_assignment(project, root, OBJ, task=task)
            self.assertTrue(stale.stale)
            self.assertEqual(stale.pattern_ids, ())
            self.assertEqual(stale.pattern_notes, ())
            self.assertEqual(stale.owner_intent_slice, "")

    def test_render_places_patterns_below_intent_and_architecture(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            _habit_workbench(app, root)
            assignment = compile_assignment(
                _project(app), root, OBJ, task=_claim_task()
            )
            body = render_assignment(assignment)
            heading = ADVISORY_PATTERN_HEADING
            self.assertIn(heading, body)
            arch_at = body.find("## architecture.json")
            intent_at = body.find("## Owner intent")
            pattern_at = body.find(heading)
            expected_at = body.find("## Expected artifacts")
            self.assertGreater(arch_at, 0)
            self.assertGreater(intent_at, arch_at)
            self.assertGreater(pattern_at, intent_at)
            self.assertGreater(expected_at, pattern_at)
            self.assertIn(ADVISORY_PATTERN_CONSTRAINT, body)

    def test_empty_query_attaches_no_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            _write(app / "docs/seed.md", "Goal: calendar app\n")
            _write(app / "src/app.py", "X = 1\n")
            obj = SimpleNamespace(
                id="OBJ-BIRTH",
                kind="code_birth",
                title="Reach code birth",
                gap="ZERO_CODE_OUTPUT",
                why="greenfield",
                focus="src/",
            )
            assignment = compile_assignment(_project(app), root, obj)
            self.assertEqual(assignment.pattern_ids, ())
            self.assertEqual(assignment.pattern_notes, ())
            self.assertNotIn(
                ADVISORY_PATTERN_HEADING, render_assignment(assignment)
            )

    def test_missing_catalog_does_not_block_the_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            _habit_workbench(app, root)
            with patch(
                "execution_assignment.match_for_intent", return_value=[]
            ):
                assignment = compile_assignment(
                    _project(app), root, OBJ, task=_claim_task()
                )
            self.assertEqual(assignment.pattern_ids, ())
            self.assertEqual(assignment.task_id, "TASK-CLAIM-define_habits")
            self.assertEqual(assignment.claim_ids, ("define_habits",))
            self.assertFalse(assignment.stale)

    def test_persist_roundtrip_keeps_pattern_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            _habit_workbench(app, root)
            assignment = compile_assignment(
                _project(app), root, OBJ, task=_claim_task()
            )
            persist_assignment(assignment, Path(_project(app)["task_root"]))
            raw = json.loads(
                (Path(_project(app)["task_root"]) / ASSIGNMENT_JSON).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(raw["pattern_ids"], list(assignment.pattern_ids))
            loaded = load_assignment(Path(_project(app)["task_root"]))
            assert loaded is not None
            self.assertEqual(loaded.pattern_ids, assignment.pattern_ids)
            self.assertEqual(loaded.pattern_notes, assignment.pattern_notes)

    def test_old_json_without_pattern_fields_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_root = Path(tmp) / "factory_tasks"
            task_root.mkdir()
            (task_root / ASSIGNMENT_JSON).write_text(
                json.dumps(
                    {
                        "objective_id": "OBJ-PRODUCT",
                        "kind": "implement",
                        "title": "t",
                        "why": "w",
                        "gap": "g",
                        "focus": "f",
                        "stance": "implement",
                        "intent_revision": 1,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            loaded = load_assignment(task_root)
            assert loaded is not None
            self.assertEqual(loaded.pattern_ids, ())
            self.assertEqual(loaded.pattern_notes, ())

    def test_live_paths_other_than_the_packet_stay_uncoupled(self) -> None:
        for rel in (
            "scripts/factory_advance.py",
            "scripts/isolated_task_run.py",
            "scripts/product_evidence.py",
            "scripts/task_graph.py",
        ):
            src = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("pattern_library", src)
            self.assertNotIn("match_for_intent", src)
            self.assertNotIn("search_patterns", src)


if __name__ == "__main__":
    unittest.main()
