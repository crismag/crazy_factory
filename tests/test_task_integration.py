"""Factory-owned task-result integration — no merge, no worker apply."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from execution_assignment import compile_assignment
from product_intent import (
    bump_revision,
    fallback_capabilities,
    persist_intent,
    score_claims,
)
from task_graph import STATUS_READY, TaskNode
from task_integration import (
    APPLY_APPLIED,
    APPLY_NOT_APPLIED,
    APPLY_REFUSED,
    APPLY_ROLLED_BACK,
    CONFLICT_NONE,
    CONFLICT_OVERLAP,
    CONFLICT_STALE,
    SCOPE_POLICY,
    SCOPE_STRONG,
    integrate_workspace,
    plan_integration,
)
from task_workspace import (
    KIND_COPY,
    KIND_WORKTREE,
    create_workspace,
    inspect_workspace,
)

OBJ = SimpleNamespace(
    id="OBJ-PRODUCT",
    kind="implement",
    title="Implement",
    gap="gap",
    why="why",
    focus="focus",
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
    }


def _task(**overrides: object) -> TaskNode:
    data: dict[str, object] = {
        "task_id": "TASK-CLAIM-define_habits",
        "parent_objective_id": "OBJ-PRODUCT",
        "intent_revision": 1,
        "title": "Implement claim",
        "purpose": "Advances define_habits",
        "status": STATUS_READY,
        "kind": "implement",
        "claim_ids": ("define_habits",),
        "evidence_targets": ("runtime",),
        "context_refs": ("claim:define_habits",),
        "affected_scope": ("src/app.py",),
    }
    data.update(overrides)
    return TaskNode(**data)  # type: ignore[arg-type]


def _intent(project: dict[str, str], root: Path, revision: int = 1) -> None:
    persist_intent(
        project,
        root,
        prompt="build a habit tracker",
        capabilities=fallback_capabilities("build a habit tracker"),
        source="compile",
        revision=revision,
    )


def _git_init(app: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=app, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=app,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=app, check=True
    )
    subprocess.run(["git", "add", "-A"], cwd=app, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=app, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=app,
        check=True,
        capture_output=True,
        text=True,
    )
    return sha.stdout.strip()


def _prepare(app: Path, root: Path) -> dict[str, str]:
    _write(app / "src/app.py", "CANON = 1\n")
    _write(app / "src/keep.py", "KEEP = 1\n")
    project = _project(app)
    _intent(project, root)
    return project


class CopyApplyTests(unittest.TestCase):
    def test_modify_add_delete_and_plan_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            project = _prepare(app, root)
            _write(app / "src/gone.py", "GONE = 1\n")
            record = create_workspace(project, root, task=_task())
            self.assertEqual(record.isolation_kind, KIND_COPY)
            tree = Path(record.workspace_path)
            (tree / "src/app.py").write_text("CANON = 2\n", encoding="utf-8")
            _write(tree / "src/new.py", "NEW = 1\n")
            (tree / "src/gone.py").unlink()
            plan = plan_integration(project, root, record.workspace_id)
            self.assertEqual(plan.apply_status, APPLY_NOT_APPLIED)
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 1\n",
            )
            self.assertFalse((app / "src/new.py").exists())
            self.assertTrue((app / "src/gone.py").is_file())
            result = integrate_workspace(project, root, record.workspace_id)
            self.assertEqual(result.apply_status, APPLY_APPLIED)
            self.assertEqual(result.conflict_status, CONFLICT_NONE)
            self.assertEqual(result.validation_status, "passed")
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 2\n",
            )
            self.assertEqual(
                (app / "src/new.py").read_text(encoding="utf-8"),
                "NEW = 1\n",
            )
            self.assertFalse((app / "src/gone.py").exists())
            self.assertIn("src/app.py", result.allowed_changes)
            self.assertIn("src/new.py", result.added_files)
            self.assertIn("src/gone.py", result.deleted_files)
            self.assertEqual(result.operations["src/app.py"], "modify")
            self.assertEqual(result.operations["src/new.py"], "add")
            self.assertEqual(result.operations["src/gone.py"], "delete")

    def test_blocked_and_traversal_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            project = _prepare(app, root)
            outside = root / "secret.txt"
            outside.write_text("SECRET\n", encoding="utf-8")
            record = create_workspace(project, root, task=_task())
            tree = Path(record.workspace_path)
            _write(tree / "scripts/hack.py", "BAD = 1\n")
            (tree / "src" / "escape.py").symlink_to(outside)
            _write(tree / "src" / ".." / ".." / "outside.py", "X = 1\n")
            plan = plan_integration(project, root, record.workspace_id)
            self.assertNotEqual(plan.conflict_status, CONFLICT_NONE)
            self.assertTrue(
                any(
                    reason in {"engine_path", "blocked_path", "symlink_escape", "out_of_root", "traversal"}
                    for reason in plan.rejected_reasons.values()
                )
            )
            result = integrate_workspace(project, root, record.workspace_id)
            self.assertEqual(result.apply_status, APPLY_REFUSED)
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 1\n",
            )
            self.assertFalse((app / "scripts").exists())
            self.assertFalse((app / "src/escape.py").exists())

    def test_overlap_blocks_unrelated_dirty_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            project = _prepare(app, root)
            record = create_workspace(project, root, task=_task())
            tree = Path(record.workspace_path)
            (tree / "src/app.py").write_text("CANON = 2\n", encoding="utf-8")
            (app / "src/app.py").write_text("DIRTY = 9\n", encoding="utf-8")
            blocked = integrate_workspace(project, root, record.workspace_id)
            self.assertEqual(blocked.conflict_status, CONFLICT_OVERLAP)
            self.assertEqual(blocked.apply_status, APPLY_REFUSED)
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "DIRTY = 9\n",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            project = _prepare(app, root)
            record = create_workspace(project, root, task=_task())
            tree = Path(record.workspace_path)
            (tree / "src/app.py").write_text("CANON = 2\n", encoding="utf-8")
            (app / "src/keep.py").write_text("KEEP = 9\n", encoding="utf-8")
            applied = integrate_workspace(project, root, record.workspace_id)
            self.assertEqual(applied.apply_status, APPLY_APPLIED)
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 2\n",
            )
            self.assertEqual(
                (app / "src/keep.py").read_text(encoding="utf-8"),
                "KEEP = 9\n",
            )

    def test_stale_revision_refuses_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            project = _prepare(app, root)
            record = create_workspace(project, root, task=_task())
            tree = Path(record.workspace_path)
            (tree / "src/app.py").write_text("CANON = 2\n", encoding="utf-8")
            bump_revision(project, root, [])
            result = integrate_workspace(project, root, record.workspace_id)
            self.assertEqual(result.conflict_status, CONFLICT_STALE)
            self.assertEqual(result.apply_status, APPLY_REFUSED)
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 1\n",
            )

    def test_validation_failure_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            project = _prepare(app, root)
            record = create_workspace(project, root, task=_task())
            tree = Path(record.workspace_path)
            (tree / "src/app.py").write_text("def broken(\n", encoding="utf-8")
            result = integrate_workspace(project, root, record.workspace_id)
            self.assertEqual(result.apply_status, APPLY_ROLLED_BACK)
            self.assertEqual(result.validation_status, "failed")
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 1\n",
            )
            inspect = inspect_workspace(project, root, record.workspace_id)
            assert inspect is not None
            self.assertIn("src/app.py", inspect.changed_files)

    def test_claims_are_not_verified_by_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            project = _prepare(app, root)
            record = create_workspace(project, root, task=_task())
            tree = Path(record.workspace_path)
            (tree / "src/app.py").write_text("CANON = 2\n", encoding="utf-8")
            result = integrate_workspace(project, root, record.workspace_id)
            self.assertEqual(result.apply_status, APPLY_APPLIED)
            scores = score_claims(project, root)
            self.assertTrue(scores)
            self.assertTrue(any(not score.ok for score in scores))

    def test_strong_scope_does_not_silently_apply_out_of_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            project = _prepare(app, root)
            task = _task(affected_scope=("src/app.py",))
            record = create_workspace(project, root, task=task)
            tree = Path(record.workspace_path)
            (tree / "src/app.py").write_text("CANON = 2\n", encoding="utf-8")
            _write(tree / "src/keep.py", "KEEP = 2\n")
            _write(tree / "tests/test_app.py", "def test_ok():\n    assert True\n")
            result = integrate_workspace(
                project, root, record.workspace_id, task=task
            )
            self.assertEqual(result.scope_confidence, SCOPE_STRONG)
            self.assertIn("src/app.py", result.allowed_changes)
            self.assertIn("src/keep.py", result.rejected_changes)
            self.assertEqual(
                result.rejected_reasons.get("src/keep.py"), "out_of_scope"
            )
            self.assertEqual(result.apply_status, APPLY_APPLIED)
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 2\n",
            )
            self.assertEqual(
                (app / "src/keep.py").read_text(encoding="utf-8"),
                "KEEP = 1\n",
            )
            self.assertFalse((app / "tests/test_app.py").exists())

    def test_runtime_json_is_not_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            project = _prepare(app, root)
            record = create_workspace(project, root, task=_task())
            tree = Path(record.workspace_path)
            (tree / "src/app.py").write_text("CANON = 2\n", encoding="utf-8")
            _write(tree / "data/habits.json", '{"n": 1}\n')
            result = integrate_workspace(project, root, record.workspace_id)
            self.assertEqual(result.scope_confidence, SCOPE_POLICY)
            self.assertEqual(
                result.rejected_reasons.get("data/habits.json"),
                "runtime_artifact",
            )
            self.assertEqual(result.apply_status, APPLY_APPLIED)
            self.assertFalse((app / "data/habits.json").exists())

    def test_legacy_executor_path_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            _write(app / "docs/seed.md", "Goal: calendar\n")
            _write(app / "src/app.py", "X = 1\n")
            assignment = compile_assignment(_project(app), root, OBJ)
            self.assertEqual(assignment.task_id, "")
            self.assertFalse(assignment.stale)
            advance_src = (ROOT / "scripts/factory_advance.py").read_text(
                encoding="utf-8"
            )
            executor_src = (ROOT / "scripts/agent_executor.py").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("integrate_workspace", advance_src)
            self.assertNotIn("task_integration", executor_src)
            self.assertNotIn("create_workspace", advance_src)


class WorktreeApplyTests(unittest.TestCase):
    def test_worktree_result_applies_to_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            project = _prepare(app, root)
            sha = _git_init(app)
            record = create_workspace(project, root, task=_task())
            self.assertEqual(record.isolation_kind, KIND_WORKTREE)
            self.assertEqual(record.base_revision, sha)
            tree = Path(record.workspace_path)
            (tree / "src/app.py").write_text("CANON = 2\n", encoding="utf-8")
            _write(tree / "src/new.py", "NEW = 1\n")
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 1\n",
            )
            result = integrate_workspace(project, root, record.workspace_id)
            self.assertEqual(result.apply_status, APPLY_APPLIED)
            self.assertEqual(result.source_base_revision, sha)
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 2\n",
            )
            self.assertTrue((app / "src/new.py").is_file())
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=app,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("src/app.py", status.stdout)
            log = subprocess.run(
                ["git", "log", "--oneline"],
                cwd=app,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(log.stdout.strip().splitlines()[-1].split(" ", 1)[-1], "base")
            self.assertEqual(len(log.stdout.strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
