"""Bounded, revision-aware context packet (Slice 3)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_executor import build_request
from execution_assignment import (
    ASSIGNMENT_JSON,
    STANCE_BIRTH,
    compile_assignment,
    is_stale_assignment,
    load_assignment,
    persist_assignment,
    render_assignment,
)
from product_intent import (
    bump_revision,
    fallback_capabilities,
    persist_intent,
)
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


def _caps():
    return fallback_capabilities("build a habit tracker")


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


class ContextPacketTests(unittest.TestCase):
    def test_selected_task_identity_and_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            persist_intent(
                _project(app),
                root,
                prompt="build a habit tracker",
                capabilities=_caps(),
                source="compile",
                revision=1,
            )
            _write(app / "src/habits.py", "def add():\n    return 1\n")
            _write(app / "src/ui.py", "TITLE = 'habit'\n")
            assignment = compile_assignment(
                _project(app), root, OBJ, task=_claim_task()
            )
            self.assertEqual(assignment.task_id, "TASK-CLAIM-define_habits")
            self.assertEqual(assignment.parent_objective_id, "OBJ-PRODUCT")
            self.assertEqual(assignment.intent_revision, 1)
            self.assertFalse(assignment.stale)
            self.assertIn("claim:define_habits", assignment.context_refs)
            self.assertIn(
                "product_intent@revision-1", assignment.context_refs
            )

    def test_stale_assignment_is_detectable_and_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            project = _project(app)
            persist_intent(
                project,
                root,
                prompt="build a habit tracker",
                capabilities=_caps(),
                source="compile",
                revision=1,
            )
            task = _claim_task(intent_revision=1)
            first = compile_assignment(project, root, OBJ, task=task)
            persist_assignment(first, Path(project["task_root"]))
            self.assertEqual(first.intent_revision, 1)
            bump_revision(project, root, [])
            loaded = load_assignment(Path(project["task_root"]))
            assert loaded is not None
            self.assertEqual(loaded.intent_revision, 1)
            self.assertTrue(is_stale_assignment(loaded, 2))
            self.assertEqual(loaded.task_id, first.task_id)
            stale = compile_assignment(project, root, OBJ, task=task)
            self.assertTrue(stale.stale)
            self.assertEqual(stale.intent_revision, 1)
            self.assertIn("revision 1", stale.stale_reason)
            self.assertEqual(stale.owner_intent_slice, "")
            self.assertEqual(stale.seed_excerpt, "")
            body = render_assignment(stale)
            self.assertIn("STALE CONTEXT", body)
            req = build_request(project, root, objective=OBJ, task=task)
            self.assertNotIn("STALE CONTEXT", req.assignment_text)
            self.assertIn("intent_revision: `2`", req.assignment_text)

    def test_task_claims_omit_unrelated_and_keep_evidence_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            persist_intent(
                _project(app),
                root,
                prompt="build a habit tracker",
                capabilities=_caps(),
                source="compile",
                revision=1,
            )
            _write(app / "src/habits.py", "def add():\n    return 1\n")
            _write(app / "src/ui.py", "TITLE = 'habit'\n")
            assignment = compile_assignment(
                _project(app), root, OBJ, task=_claim_task()
            )
            self.assertEqual(assignment.claim_ids, ("define_habits",))
            self.assertNotIn("persist_habits", assignment.claim_ids)
            self.assertNotIn("dated_completion", assignment.claim_ids)
            self.assertIn("runtime", assignment.evidence_targets)
            self.assertTrue(
                any(
                    "define habits" in item.lower()
                    for item in assignment.success
                )
            )
            self.assertFalse(
                any(
                    "survive restart" in item.lower()
                    for item in assignment.success
                )
            )
            self.assertIn(
                "Factory evidence, not this assignment, verifies claims.",
                assignment.success,
            )

    def test_repo_and_architecture_are_sliced_not_dumped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            persist_intent(
                _project(app),
                root,
                prompt="build a habit tracker",
                capabilities=_caps(),
                source="compile",
                revision=1,
            )
            secret = "UNIQUE_SOURCE_TOKEN_XYZ"
            _write(app / "src/habits.py", f"{secret} = 1\n")
            _write(app / "src/ui.py", "DASHBOARD = True\n")
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "stack": "stdlib-web",
                        "start_command": "python3 -m src.app",
                        "forbidden_imports": ["flask"],
                        "required_files": ["src/habits.py", "src/ui.py"],
                    }
                ),
            )
            assignment = compile_assignment(
                _project(app), root, OBJ, task=_claim_task()
            )
            self.assertIn("file:src/habits.py", assignment.repo_scope)
            self.assertNotIn("file:src/ui.py", assignment.repo_scope)
            self.assertIn("src/habits.py", assignment.inventory)
            self.assertNotIn("src/ui.py", assignment.inventory)
            self.assertNotIn(secret, assignment.architecture_excerpt)
            self.assertNotIn(secret, assignment.owner_intent_slice)
            self.assertNotIn(secret, "\n".join(assignment.inventory))
            self.assertIn("src/habits.py", assignment.architecture_excerpt)
            self.assertNotIn("src/ui.py", assignment.architecture_excerpt)
            self.assertIn(
                "architecture:architecture.json", assignment.context_refs
            )
            self.assertIn("monolithic", " ".join(assignment.selection_notes))

    def test_legacy_objective_still_builds_and_executor_path_holds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            _write(app / "docs/seed.md", "Goal: calendar app\n")
            _write(app / "src/task_board.py", "STATUS = 'broken'\n")
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "required_files": ["src/task_board.py"],
                        "start_command": "python3 -m src.task_board",
                    }
                ),
            )
            obj = SimpleNamespace(
                id="OBJ-BIRTH",
                kind="code_birth",
                title="Reach code birth",
                gap="ZERO_CODE_OUTPUT",
                why="greenfield",
                focus="src/",
            )
            assignment = compile_assignment(_project(app), root, obj)
            self.assertEqual(assignment.task_id, "")
            self.assertFalse(assignment.stale)
            self.assertIn(
                "legacy objective packet",
                " ".join(assignment.selection_notes),
            )
            self.assertIn("src/task_board.py", assignment.inventory)
            body = render_assignment(assignment)
            self.assertIn("# Engineering assignment", body)
            self.assertIn("python3 -m src.task_board", body)
            req = build_request(_project(app), root, objective=obj)
            self.assertEqual(req.stance, STANCE_BIRTH)
            self.assertIn("Engineering assignment", req.assignment_text)
            self.assertEqual(req.objective_id, "OBJ-BIRTH")

    def test_product_evidence_is_not_assignment_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            persist_intent(
                _project(app),
                root,
                prompt="build a habit tracker",
                capabilities=_caps(),
                source="compile",
                revision=1,
            )
            _write(
                app / "factory_tasks/product_evidence.json",
                json.dumps(
                    {
                        "claims": [
                            {
                                "id": "define_habits",
                                "ok": True,
                                "kind": "runtime",
                                "detail": "created",
                            }
                        ]
                    }
                ),
            )
            assignment = compile_assignment(
                _project(app), root, OBJ, task=_claim_task()
            )
            blob = json.dumps(
                {
                    "success": assignment.success,
                    "evidence_targets": list(assignment.evidence_targets),
                    "stale": assignment.stale,
                }
            )
            self.assertNotIn('"ok": true', blob.lower())
            self.assertIn("runtime", assignment.evidence_targets)
            self.assertIn(
                "Factory evidence, not this assignment, verifies claims.",
                assignment.success,
            )
            raw = (app / "factory_tasks/product_evidence.json").read_text(
                encoding="utf-8"
            )
            self.assertIn('"ok": true', raw)

    def test_persist_json_roundtrip_keeps_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            root = Path(tmp)
            persist_intent(
                _project(app),
                root,
                prompt="build a habit tracker",
                capabilities=_caps(),
                source="compile",
                revision=4,
            )
            assignment = compile_assignment(
                _project(app),
                root,
                OBJ,
                task=_claim_task(intent_revision=4),
            )
            persist_assignment(assignment, Path(_project(app)["task_root"]))
            path = Path(_project(app)["task_root"]) / ASSIGNMENT_JSON
            self.assertTrue(path.is_file())
            loaded = load_assignment(Path(_project(app)["task_root"]))
            assert loaded is not None
            self.assertEqual(loaded.intent_revision, 4)
            self.assertEqual(loaded.task_id, assignment.task_id)
            self.assertFalse(is_stale_assignment(loaded, 4))


if __name__ == "__main__":
    unittest.main()
