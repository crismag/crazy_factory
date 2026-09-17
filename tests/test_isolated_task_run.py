"""Opt-in isolated TaskNode pipeline — default AgentExecutor unchanged."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_executor import ExecutorResult, build_request, default_executor
from execution_assignment import compile_assignment
from isolated_task_run import (
    ENV_ISOLATED,
    ENV_TASK_ID,
    IsolatedTaskError,
    isolated_task_requested,
    run_isolated_task,
)
from product_intent import Capability, persist_intent, score_claims
from task_workspace import list_workspace_ids, load_workspace


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(app: Path) -> dict[str, str]:
    return {
        "name": "probe",
        "app_path": str(app),
        "task_root": str(app / "factory_tasks"),
        "seed_file": "docs/seed.md",
    }


def _intent(project: dict[str, str], root: Path) -> None:
    persist_intent(
        project,
        root,
        prompt="greet a person by name",
        capabilities=[
            Capability(
                id="greet_name",
                claim="The application can greet a person by name.",
                symbols=("greet",),
                files=("src/app.py",),
                evidence=("static",),
            )
        ],
        source="compile",
        revision=1,
    )


class FakeExecutor:
    name = "fake"

    def __init__(self, files: dict[str, str] | None = None, ok: bool = True) -> None:
        self.files = files if files is not None else {
            "src/app.py": (
                "def ping() -> str:\n    return \"pong\"\n\n"
                "def greet(name: str) -> str:\n    return f\"hello, {name}\"\n"
            )
        }
        self.ok = ok
        self.seen_app = ""

    def can_implement(self) -> bool:
        return True

    def execute(self, request: object) -> ExecutorResult:
        self.seen_app = str(getattr(request, "app_path", "") or "")
        return ExecutorResult(
            ok=self.ok,
            provider=self.name,
            summary="fake files" if self.ok else "fake skip",
            files=dict(self.files) if self.ok else {},
            reason="" if self.ok else "fake_skip",
        )


class IsolatedTaskRunTests(unittest.TestCase):
    def test_isolated_pipeline_applies_only_via_factory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "probe"
            _write(app / "src/app.py", "def ping() -> str:\n    return \"pong\"\n")
            _write(app / "docs/seed.md", "Goal: greet by name\n")
            project = _project(app)
            _intent(project, root)
            before = (app / "src/app.py").read_text(encoding="utf-8")
            fake = FakeExecutor()
            result = run_isolated_task(
                project, root, executor=fake, cleanup_on_success=False
            )
            self.assertTrue(result.ok)
            self.assertTrue(result.canonical_untouched_until_apply)
            self.assertEqual(result.apply_status, "applied")
            self.assertEqual(result.validation_status, "passed")
            self.assertIn("src/app.py", result.allowed_changes)
            self.assertIn("src/app.py", result.workspace_changed)
            self.assertTrue(fake.seen_app)
            self.assertNotEqual(Path(fake.seen_app).resolve(), app.resolve())
            self.assertIn("greet", (app / "src/app.py").read_text(encoding="utf-8"))
            self.assertNotEqual(
                before, (app / "src/app.py").read_text(encoding="utf-8")
            )
            after = score_claims(project, root)
            self.assertTrue(any(row.cap.id == "greet_name" and row.ok for row in after))
            self.assertFalse(result.cleaned)
            self.assertIsNotNone(
                load_workspace(project, root, result.workspace_id)
            )

    def test_cleanup_after_success_preserves_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "probe"
            _write(app / "src/app.py", "def ping() -> str:\n    return \"pong\"\n")
            _write(app / "docs/seed.md", "Goal: greet\n")
            project = _project(app)
            _intent(project, root)
            ok = run_isolated_task(
                project, root, executor=FakeExecutor(), cleanup_on_success=True
            )
            self.assertTrue(ok.ok)
            self.assertTrue(ok.cleaned)
            self.assertEqual(list_workspace_ids(project, root), [])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "probe"
            _write(app / "src/app.py", "def ping() -> str:\n    return \"pong\"\n")
            _write(app / "docs/seed.md", "Goal: greet\n")
            project = _project(app)
            _intent(project, root)
            failed = run_isolated_task(
                project,
                root,
                executor=FakeExecutor(ok=False),
                cleanup_on_success=True,
            )
            self.assertFalse(failed.ok)
            self.assertFalse(failed.cleaned)
            self.assertEqual(
                (app / "src/app.py").read_text(encoding="utf-8"),
                "def ping() -> str:\n    return \"pong\"\n",
            )
            leftover = load_workspace(project, root, failed.workspace_id)
            assert leftover is not None
            self.assertEqual(leftover.status, "failed")

    def test_integration_does_not_verify_unrelated_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "probe"
            _write(app / "src/app.py", "def ping() -> str:\n    return \"pong\"\n")
            _write(app / "docs/seed.md", "Goal: greet\n")
            project = _project(app)
            _intent(project, root)
            result = run_isolated_task(
                project,
                root,
                executor=FakeExecutor(
                    files={"src/app.py": "def ping() -> str:\n    return \"pong\"\n# note\n"}
                ),
                cleanup_on_success=True,
            )
            self.assertTrue(result.ok)
            self.assertTrue(any(not row["ok"] for row in result.claims_after))
            scores = score_claims(project, root)
            greet = next(row for row in scores if row.cap.id == "greet_name")
            self.assertFalse(greet.ok)

    def test_unknown_task_id_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "probe"
            _write(app / "src/app.py", "X = 1\n")
            _write(app / "docs/seed.md", "Goal: greet\n")
            project = _project(app)
            _intent(project, root)
            with self.assertRaises(IsolatedTaskError):
                run_isolated_task(
                    project, root, task_id="TASK-MISSING", executor=FakeExecutor()
                )

    def test_default_live_path_unchanged(self) -> None:
        self.assertFalse(isolated_task_requested())
        with patch.dict(os.environ, {ENV_ISOLATED: "1", ENV_TASK_ID: "TASK-X"}):
            self.assertTrue(isolated_task_requested())
        advance_src = (ROOT / "scripts/factory_advance.py").read_text(
            encoding="utf-8"
        )
        executor_src = (ROOT / "scripts/agent_executor.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("isolated_task_run", advance_src)
        self.assertNotIn("create_workspace", advance_src)
        self.assertNotIn("integrate_workspace", advance_src)
        self.assertNotIn("isolated_task_run", executor_src)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "probe"
            _write(app / "docs/seed.md", "Goal: calendar\n")
            _write(app / "src/app.py", "X = 1\n")
            from types import SimpleNamespace

            obj = SimpleNamespace(
                id="OBJ-PRODUCT",
                kind="implement",
                title="Implement",
                gap="gap",
                why="why",
                focus="focus",
            )
            assignment = compile_assignment(_project(app), root, obj)
            self.assertEqual(assignment.task_id, "")
            req = build_request(_project(app), root, objective=obj)
            self.assertEqual(req.app_path, str(app))
        with patch.dict(os.environ, {ENV_ISOLATED: "1"}):
            # Env opt-in does not rewrite default_executor selection.
            os.environ.pop("CRAZY_FACTORY_EXECUTOR", None)
            name = default_executor().name
            self.assertIn(name, {"chain", "cloud_coding", "stdlib_web", "codex"})


class ReadyTaskSelectionTests(unittest.TestCase):
    def test_selects_ready_graph_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "probe"
            _write(app / "src/app.py", "def ping() -> str:\n    return \"pong\"\n")
            _write(app / "docs/seed.md", "Goal: greet\n")
            project = _project(app)
            _intent(project, root)
            result = run_isolated_task(
                project, root, executor=FakeExecutor(), cleanup_on_success=True
            )
            self.assertTrue(result.task_id)
            self.assertTrue(result.task_id.startswith("TASK-"))
            self.assertEqual(result.executor_provider, "fake")


if __name__ == "__main__":
    unittest.main()
