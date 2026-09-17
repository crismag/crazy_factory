"""Task-graph primitive: deps, claims, context refs; no scheduler change."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from objective_generator import (
    KIND_CODE_BIRTH,
    KIND_IMPLEMENT,
    KIND_REPAIR_RUNTIME,
    next_execute_objective,
)
from product_intent import (
    fallback_capabilities,
    persist_intent,
)
from task_graph import (
    GRAPH_FILE,
    KIND_BIRTH,
    KIND_REPAIR,
    KIND_VERIFY,
    STATUS_BLOCKED,
    STATUS_PENDING,
    STATUS_READY,
    STATUS_VERIFIED,
    TaskGraph,
    TaskNode,
    derive_task_graph,
    detect_cycles,
    is_parallelizable,
    load_task_graph,
    ready_tasks,
    repo_fingerprint,
    scopes_overlap,
    stale_revision,
    sync_task_graph,
)
from task_graph import KIND_IMPLEMENT as GRAPH_IMPLEMENT


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


def _intent(app: Path, *, revision: int = 1) -> None:
    persist_intent(
        _project(app),
        app.parent,
        prompt="build a habit tracker",
        capabilities=fallback_capabilities("build a habit tracker"),
        source="compile",
        revision=revision,
    )


def _by_id(graph: TaskGraph) -> dict[str, TaskNode]:
    return {node.task_id: node for node in graph.nodes}


class DeriveTests(unittest.TestCase):
    def test_one_node_per_claim_without_invented_deps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(app / "docs/seed.md", "Goal:\nHabits.\n")
            _intent(app)
            graph = derive_task_graph(_project(app), Path(tmp))
            claims = [
                node
                for node in graph.nodes
                if node.kind == GRAPH_IMPLEMENT
            ]
            self.assertGreaterEqual(len(claims), 4)
            for node in claims:
                self.assertEqual(node.status, STATUS_READY)
                self.assertEqual(node.dependencies, ())
                self.assertEqual(len(node.claim_ids), 1)
                self.assertTrue(
                    any(
                        ref.startswith("claim:") for ref in node.context_refs
                    )
                )
                self.assertTrue(
                    any(
                        ref.startswith("product_intent@revision-")
                        for ref in node.context_refs
                    )
                )
            verify = _by_id(graph)["TASK-VERIFY-PRODUCT"]
            self.assertEqual(verify.kind, KIND_VERIFY)
            self.assertEqual(verify.status, STATUS_PENDING)
            self.assertEqual(
                set(verify.dependencies),
                {node.task_id for node in claims},
            )

    def test_persisted_evidence_marks_claim_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _intent(app)
            _write(
                app / "factory_tasks/product_acceptance.json",
                json.dumps(
                    {
                        "intent_revision": 1,
                        "evidence": [
                            {
                                "id": "define_habits",
                                "ok": True,
                                "kind": "runtime",
                                "detail": "created",
                            }
                        ],
                    }
                ),
            )
            graph = derive_task_graph(_project(app), Path(tmp))
            node = _by_id(graph)["TASK-CLAIM-define_habits"]
            self.assertEqual(node.status, STATUS_VERIFIED)
            self.assertIn("runtime", node.evidence_targets)

    def test_runtime_repair_blocks_claim_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _intent(app)
            _write(
                app / "factory_tasks/runtime_result.json",
                json.dumps(
                    {
                        "required": True,
                        "ok": False,
                        "safe": True,
                        "reason": "did not start",
                    }
                ),
            )
            graph = derive_task_graph(_project(app), Path(tmp))
            repair = _by_id(graph)["TASK-RUNTIME"]
            self.assertEqual(repair.kind, KIND_REPAIR)
            self.assertEqual(repair.status, STATUS_READY)
            claim = _by_id(graph)["TASK-CLAIM-define_habits"]
            self.assertEqual(claim.status, STATUS_BLOCKED)
            self.assertIn("TASK-RUNTIME", claim.blocked_by)
            self.assertEqual(ready_tasks(graph)[0].task_id, "TASK-RUNTIME")

    def test_owner_delta_node_and_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _intent(app, revision=2)
            _write(
                app / "factory_tasks/deltas.json",
                json.dumps(
                    [
                        {
                            "id": "delta-1",
                            "prompt": "add a streak counter",
                            "status": "PENDING",
                            "intent_revision": 2,
                            "capabilities": [
                                {"id": "habit_streaks", "claim": "streaks"}
                            ],
                        }
                    ]
                ),
            )
            graph = derive_task_graph(_project(app), Path(tmp))
            self.assertEqual(graph.intent_revision, 2)
            delta = _by_id(graph)["TASK-DELTA-delta-1"]
            self.assertEqual(delta.status, STATUS_READY)
            self.assertIn("owner_delta:delta-1", delta.context_refs)
            self.assertIn("habit_streaks", delta.claim_ids)

    def test_greenfield_birth_without_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(app / "docs/seed.md", "Goal:\nTodo.\n")
            graph = derive_task_graph(
                _project(app),
                Path(tmp),
                objective=type(
                    "O",
                    (),
                    {"id": "OBJ-BIRTH", "kind": "code_birth"},
                )(),
            )
            birth = _by_id(graph)["TASK-BIRTH"]
            self.assertEqual(birth.kind, KIND_BIRTH)
            self.assertEqual(birth.status, STATUS_READY)

    def test_context_refs_are_pointers_not_blobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _intent(app)
            _write(
                app / "architecture.json",
                json.dumps(
                    {
                        "stack": "stdlib-web",
                        "required_files": ["src/app.py"],
                    }
                ),
            )
            graph = derive_task_graph(_project(app), Path(tmp))
            blob = json.dumps([asdict_safe(node) for node in graph.nodes])
            self.assertNotIn("stdlib-web", blob)
            self.assertIn("architecture:architecture.json", blob)
            for node in graph.nodes:
                for ref in node.context_refs:
                    self.assertLess(len(ref), 80)


def asdict_safe(node: TaskNode) -> dict[str, object]:
    return {
        "task_id": node.task_id,
        "context_refs": list(node.context_refs),
        "title": node.title,
        "purpose": node.purpose,
    }


class GraphAlgebraTests(unittest.TestCase):
    def test_ready_tasks_wait_on_unverified_deps(self) -> None:
        nodes = [
            TaskNode(
                task_id="A",
                parent_objective_id="OBJ",
                intent_revision=1,
                title="a",
                purpose="a",
                status=STATUS_READY,
                kind=GRAPH_IMPLEMENT,
            ),
            TaskNode(
                task_id="B",
                parent_objective_id="OBJ",
                intent_revision=1,
                title="b",
                purpose="b",
                status=STATUS_READY,
                kind=GRAPH_IMPLEMENT,
                dependencies=("A",),
            ),
        ]
        graph = TaskGraph(
            intent_revision=1, parent_objective_id="OBJ", nodes=nodes
        )
        ids = {node.task_id for node in ready_tasks(graph)}
        self.assertEqual(ids, {"A"})

    def test_detect_cycles(self) -> None:
        nodes = [
            TaskNode(
                task_id="A",
                parent_objective_id="OBJ",
                intent_revision=1,
                title="a",
                purpose="a",
                status=STATUS_PENDING,
                kind=GRAPH_IMPLEMENT,
                dependencies=("B",),
            ),
            TaskNode(
                task_id="B",
                parent_objective_id="OBJ",
                intent_revision=1,
                title="b",
                purpose="b",
                status=STATUS_PENDING,
                kind=GRAPH_IMPLEMENT,
                dependencies=("A",),
            ),
        ]
        self.assertEqual(detect_cycles(nodes), ["A", "B"])

    def test_module_overlap_not_whole_src_tree(self) -> None:
        self.assertTrue(
            scopes_overlap(("src/events/a.py",), ("src/events/b.py",))
        )
        self.assertFalse(
            scopes_overlap(("src/events/a.py",), ("src/tasks/b.py",))
        )
        self.assertTrue(
            scopes_overlap(("data/habits.json",), ("data/habits.json",))
        )
        self.assertTrue(
            scopes_overlap(
                ("requirements.txt",),
                ("src/x.py", "requirements.txt"),
            )
        )

    def test_unknown_write_scope_is_not_parallelizable(self) -> None:
        nodes = [
            TaskNode(
                task_id="A",
                parent_objective_id="OBJ",
                intent_revision=1,
                title="a",
                purpose="a",
                status=STATUS_READY,
                kind=GRAPH_IMPLEMENT,
                affected_scope=(),
            ),
            TaskNode(
                task_id="B",
                parent_objective_id="OBJ",
                intent_revision=1,
                title="b",
                purpose="b",
                status=STATUS_READY,
                kind=GRAPH_IMPLEMENT,
                affected_scope=("src/tasks/model.py",),
            ),
        ]
        graph = TaskGraph(
            intent_revision=1, parent_objective_id="OBJ", nodes=nodes
        )
        self.assertFalse(is_parallelizable(nodes[0], graph))
        self.assertFalse(is_parallelizable(nodes[1], graph))

    def test_disjoint_ready_writers_are_parallelizable(self) -> None:
        nodes = [
            TaskNode(
                task_id="A",
                parent_objective_id="OBJ",
                intent_revision=1,
                title="a",
                purpose="a",
                status=STATUS_READY,
                kind=GRAPH_IMPLEMENT,
                affected_scope=("src/events/model.py",),
            ),
            TaskNode(
                task_id="B",
                parent_objective_id="OBJ",
                intent_revision=1,
                title="b",
                purpose="b",
                status=STATUS_READY,
                kind=GRAPH_IMPLEMENT,
                affected_scope=("src/tasks/model.py",),
            ),
        ]
        graph = TaskGraph(
            intent_revision=1, parent_objective_id="OBJ", nodes=nodes
        )
        self.assertTrue(is_parallelizable(nodes[0], graph))
        self.assertTrue(is_parallelizable(nodes[1], graph))

    def test_stale_revision(self) -> None:
        graph = TaskGraph(intent_revision=1, parent_objective_id="OBJ")
        self.assertTrue(stale_revision(graph, 2))
        self.assertFalse(stale_revision(graph, 1))


class PersistAndScheduleTests(unittest.TestCase):
    def test_roundtrip_and_churn_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _intent(app)
            first = sync_task_graph(_project(app), Path(tmp))
            loaded = load_task_graph(app / "factory_tasks")
            assert loaded is not None
            self.assertEqual(loaded.fingerprint, first.fingerprint)
            _write(app / "src/app.py", "print('hi')\n")
            second = sync_task_graph(_project(app), Path(tmp))
            self.assertTrue(second.churn_without_progress)
            self.assertEqual(second.prior_fingerprint, first.fingerprint)
            self.assertNotEqual(second.repo_fingerprint, first.repo_fingerprint)

    def test_objective_selection_unchanged_when_graph_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(app / "docs/seed.md", "Goal:\nBuild a todo tracker.\n")
            obj = next_execute_objective(_project(app), Path(tmp))
            self.assertEqual(obj.kind, KIND_CODE_BIRTH)
            self.assertIn("ZERO_CODE", obj.gap)
            graph_path = app / "factory_tasks" / GRAPH_FILE
            self.assertTrue(graph_path.is_file())
            graph = load_task_graph(app / "factory_tasks")
            assert graph is not None
            self.assertEqual(graph.parent_objective_id, obj.id)
            self.assertIn("TASK-BIRTH", _by_id(graph))

    def test_runtime_still_outranks_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _intent(app)
            _write(
                app / "factory_tasks/runtime_result.json",
                json.dumps(
                    {
                        "required": True,
                        "ok": False,
                        "safe": True,
                        "reason": "module missing",
                        "status": "missing",
                    }
                ),
            )
            obj = next_execute_objective(_project(app), Path(tmp))
            self.assertEqual(obj.kind, KIND_REPAIR_RUNTIME)
            self.assertNotEqual(obj.kind, KIND_IMPLEMENT)
            graph = load_task_graph(app / "factory_tasks")
            assert graph is not None
            self.assertEqual(_by_id(graph)["TASK-RUNTIME"].status, STATUS_READY)
            self.assertEqual(
                _by_id(graph)["TASK-CLAIM-define_habits"].status,
                STATUS_BLOCKED,
            )


class FingerprintTests(unittest.TestCase):
    def test_repo_fingerprint_ignores_factory_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _write(app / "src/a.py", "x=1\n")
            _write(app / "factory_tasks/noise.json", "{}\n")
            first = repo_fingerprint(app)
            _write(app / "factory_tasks/more.json", "{}\n")
            self.assertEqual(first, repo_fingerprint(app))
            _write(app / "src/b.py", "y=2\n")
            self.assertNotEqual(first, repo_fingerprint(app))


if __name__ == "__main__":
    unittest.main()
