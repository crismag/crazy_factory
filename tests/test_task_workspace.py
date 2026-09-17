"""Isolated task workspace lifecycle — no merge, no parallel workers."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_executor import (
    ExecutorResult,
    apply_executor_result,
    build_request,
)
from execution_assignment import compile_assignment
from product_intent import bump_revision, persist_intent
from task_graph import STATUS_READY, TaskNode
from task_workspace import (
    KIND_COPY,
    KIND_WORKTREE,
    STATUS_COMPLETED,
    STATUS_CREATED,
    STATUS_FAILED,
    STATUS_STALE,
    bind_project_to_workspace,
    cleanup_workspace,
    collect_workspace_result,
    create_workspace,
    inspect_workspace,
    list_workspace_ids,
    load_workspace,
    mark_workspace,
    reusable_workspace,
    workbench_is_git_repo,
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
        "affected_scope": ("src/habits.py",),
    }
    data.update(overrides)
    return TaskNode(**data)  # type: ignore[arg-type]


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
    subprocess.run(
        ["git", "commit", "-qm", "base"], cwd=app, check=True
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=app,
        check=True,
        capture_output=True,
        text=True,
    )
    return sha.stdout.strip()


class CopyIsolationTests(unittest.TestCase):
    def test_copy_when_workbench_is_not_a_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            _write(app / "src/app.py", "CANON = 1\n")
            persist_intent(
                _project(app),
                root,
                prompt="x",
                capabilities=[],
                source="compile",
                revision=1,
            )
            record = create_workspace(
                _project(app),
                root,
                task=_task(),
                created_at="2026-09-17T00:00:00Z",
            )
            self.assertEqual(record.isolation_kind, KIND_COPY)
            self.assertFalse(record.git_base_available)
            self.assertIn("not its own git", record.git_base_reason)
            self.assertEqual(record.task_id, "TASK-CLAIM-define_habits")
            self.assertEqual(record.intent_revision, 1)
            self.assertEqual(record.status, STATUS_CREATED)
            self.assertFalse(workbench_is_git_repo(app))
            tree = Path(record.workspace_path)
            self.assertTrue((tree / "src/app.py").is_file())
            (tree / "src/app.py").write_text("ISOLATED = 2\n", encoding="utf-8")
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 1\n",
            )
            updated = collect_workspace_result(_project(app), root, record)
            self.assertIn("src/app.py", updated.changed_files)

    def test_cleanup_removes_only_intended_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            _write(app / "src/app.py", "CANON = 1\n")
            persist_intent(
                _project(app),
                root,
                prompt="x",
                capabilities=[],
                source="compile",
                revision=1,
            )
            first = create_workspace(_project(app), root, task=_task())
            second = create_workspace(_project(app), root, task=_task())
            self.assertNotEqual(first.workspace_id, second.workspace_id)
            self.assertEqual(len(list_workspace_ids(_project(app), root)), 2)
            cleanup_workspace(_project(app), root, first.workspace_id)
            self.assertIsNone(
                load_workspace(_project(app), root, first.workspace_id)
            )
            leftover = load_workspace(_project(app), root, second.workspace_id)
            assert leftover is not None
            self.assertTrue(Path(leftover.workspace_path).is_dir())
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 1\n",
            )
            self.assertEqual(
                list_workspace_ids(_project(app), root),
                [second.workspace_id],
            )


class WorktreeIsolationTests(unittest.TestCase):
    def test_worktree_records_base_revision_and_git_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            _write(app / "src/app.py", "CANON = 1\n")
            sha = _git_init(app)
            persist_intent(
                _project(app),
                root,
                prompt="x",
                capabilities=[],
                source="compile",
                revision=1,
            )
            record = create_workspace(_project(app), root, task=_task())
            self.assertEqual(record.isolation_kind, KIND_WORKTREE)
            self.assertTrue(record.git_base_available)
            self.assertEqual(record.base_revision, sha)
            self.assertTrue(record.git_diff_available)
            tree = Path(record.workspace_path)
            (tree / "src/app.py").write_text("ISOLATED = 2\n", encoding="utf-8")
            _write(tree / "src/new.py", "N = 1\n")
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 1\n",
            )
            self.assertFalse((app / "src/new.py").exists())
            updated = collect_workspace_result(_project(app), root, record)
            self.assertIn("src/app.py", updated.changed_files)
            self.assertIn("src/new.py", updated.added_files)
            mark_workspace(
                _project(app), root, record, STATUS_COMPLETED
            )
            cleanup_workspace(_project(app), root, record.workspace_id)
            listed = subprocess.run(
                ["git", "worktree", "list"],
                cwd=app,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertNotIn(record.workspace_id, listed.stdout)
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 1\n",
            )


class StaleAndBindTests(unittest.TestCase):
    def test_stale_revision_is_not_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            _write(app / "src/app.py", "CANON = 1\n")
            persist_intent(
                _project(app),
                root,
                prompt="x",
                capabilities=[],
                source="compile",
                revision=1,
            )
            created = create_workspace(_project(app), root, task=_task())
            live = reusable_workspace(
                _project(app),
                root,
                task_id=created.task_id,
                intent_revision_value=1,
            )
            assert live is not None
            self.assertEqual(live.workspace_id, created.workspace_id)
            bump_revision(_project(app), root, [])
            with self.assertRaises(Exception) as ctx:
                create_workspace(
                    _project(app), root, task=_task(intent_revision=1)
                )
            self.assertIn("stale", str(ctx.exception).lower())
            none = reusable_workspace(
                _project(app),
                root,
                task_id=created.task_id,
                intent_revision_value=1,
            )
            self.assertIsNone(none)
            stale = load_workspace(_project(app), root, created.workspace_id)
            assert stale is not None
            self.assertEqual(stale.status, STATUS_STALE)
            Path(stale.workspace_path).joinpath("src/app.py").write_text(
                "STALE_EDIT = 1\n", encoding="utf-8"
            )
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 1\n",
            )

    def test_bind_project_writes_only_in_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            _write(app / "src/app.py", "CANON = 1\n")
            persist_intent(
                _project(app),
                root,
                prompt="x",
                capabilities=[],
                source="compile",
                revision=1,
            )
            record = create_workspace(_project(app), root, task=_task())
            bound = bind_project_to_workspace(_project(app), record)
            written, err = apply_executor_result(
                ExecutorResult(
                    ok=True,
                    provider="test",
                    summary="isolated",
                    files={"src/hello.py": "HELLO = 1\n"},
                ),
                bound,
                root,
            )
            self.assertIsNone(err)
            self.assertEqual(written, ["src/hello.py"])
            self.assertTrue(
                (Path(record.workspace_path) / "src/hello.py").is_file()
            )
            self.assertFalse((app / "src/hello.py").exists())
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "CANON = 1\n",
            )

    def test_legacy_assignment_and_executor_request_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            _write(app / "docs/seed.md", "Goal: calendar\n")
            _write(app / "src/app.py", "X = 1\n")
            assignment = compile_assignment(_project(app), root, OBJ)
            self.assertEqual(assignment.task_id, "")
            self.assertFalse(assignment.stale)
            req = build_request(_project(app), root, objective=OBJ)
            self.assertEqual(req.app_path, str(app))
            self.assertIn("Engineering assignment", req.assignment_text)
            advance_src = (ROOT / "scripts/factory_advance.py").read_text(
                encoding="utf-8"
            )
            executor_src = (ROOT / "scripts/agent_executor.py").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("create_workspace", advance_src)
            self.assertNotIn("task_workspace", executor_src)

    def test_mark_completed_and_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            _write(app / "src/app.py", "CANON = 1\n")
            persist_intent(
                _project(app),
                root,
                prompt="x",
                capabilities=[],
                source="compile",
                revision=1,
            )
            record = create_workspace(_project(app), root, task=_task())
            mark_workspace(_project(app), root, record, STATUS_FAILED)
            loaded = inspect_workspace(
                _project(app), root, record.workspace_id
            )
            assert loaded is not None
            self.assertEqual(loaded.status, STATUS_FAILED)
            mark_workspace(_project(app), root, record, STATUS_COMPLETED)
            self.assertEqual(record.status, STATUS_COMPLETED)


if __name__ == "__main__":
    unittest.main()
