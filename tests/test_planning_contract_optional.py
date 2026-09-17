"""Planning-contract optionalization for AgentExecutor missions.

AgentExecutor beats must not require an Ollama planned_task.json, must not
stamp planning_contract_rejected, and must still leave the inner Coder
chain gated on is_contract_actionable. The factory never self-authorizes.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import crazy_admin as ca
from agent_executor import ExecutorResult, apply_executor_result
from checkpoint_commit import checkpoint_gate
from coder_proposal import ProposalResult, ProposalVerdict, run_coder_stage
from contract_stage import (
    DECISION_SKIPPED_AGENT_EXECUTOR,
    SOURCE_SKIPPED,
    agent_executor_path_active,
    contract_status_label,
    request_task_contract,
    run_contract_stage,
    skipped_agent_executor_contract,
)
from mission_runner import (
    COMPLETE,
    MORE_WORK,
    RUNNABLE_PREVIEW,
    evaluate_mission,
    run_mission,
)
from mission_state import load_state, update_success_state
from ollama_client import OllamaConnectionError
from planning_roles import RoleResult
from proposal_applier import run_application_stage
from task_contract import (
    ValidationVerdict,
    is_contract_actionable,
    parse_planned_task,
    validate_planned_task,
)
from test_builder import run_test_builder_stage

from contract_stage import ContractResult


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _bootstrap_repo(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "apps").mkdir(parents=True, exist_ok=True)
    (root / "config/projects.yaml").write_text("projects:\n", encoding="utf-8")
    (root / "config/factory.yaml").write_text(
        "factory:\n"
        '  mode: "dry_run"\n'
        '  state_dir: "state"\n'
        "  max_lines_per_file: 200\n"
        "  max_files_per_run: 5\n"
        "proposal_application:\n  allow_apply: false\n"
        "validation:\n  allow_run: false\n"
        "git:\n  allow_auto_commit: false\n"
        "ollama:\n"
        '  base_url: "http://localhost:11434"\n'
        "  timeout_seconds: 1\n"
        "  stream: false\n",
        encoding="utf-8",
    )
    (root / "config/models.yaml").write_text(
        "models:\n"
        "  architect: cogito:14b\n"
        "  planner: cogito:14b\n"
        "  coder: cogito:14b\n"
        "  test_builder: cogito:14b\n",
        encoding="utf-8",
    )


def _valid_contract_dict() -> dict[str, object]:
    return {
        "task_id": "DEMO-002",
        "title": "Document demo status",
        "objective": "Describe the demo status in docs",
        "validation_plan": "Owner reads the docs and confirms accuracy.",
        "scope": ["Add a status note to the demo docs"],
        "exclusions": ["No application code changes"],
        "acceptance_criteria": ["A status note exists"],
        "inputs": [],
        "risks": [],
        "approval_status": "pending",
        "authorized": False,
    }


def _authorized_contract_dict() -> dict[str, object]:
    return {
        **_valid_contract_dict(),
        "authorized": True,
        "validation": {"status": "valid", "source": "ollama", "reasons": []},
    }


def _roles() -> tuple[RoleResult, RoleResult]:
    return (
        RoleResult("architect", "expand", "fallback", "off"),
        RoleResult("planner", "next", "fallback", "off"),
    )


def _ollama_factory() -> dict[str, object]:
    return {
        "ollama": {
            "base_url": "http://localhost:11434",
            "timeout_seconds": 1,
            "stream": False,
        }
    }


def _make_accepted(app: Path) -> None:
    _write(app / "README.md", "# Todo\n")
    _write(
        app / "architecture.json",
        json.dumps({"required_files": ["src/todo.py", "tests/test_todo.py"]}),
    )
    _write(
        app / "src/todo.py",
        "def add(item, items):\n    items.append(item)\n    return items\n",
    )
    _write(
        app / "tests/test_todo.py",
        "from src.todo import add\n\n"
        "def test_add():\n    assert add('a', []) == ['a']\n",
    )
    _write(
        app / "factory_tasks/MASTER_CHECKLIST.md",
        "- [x] Implement src/todo.py\n- [x] Write tests/test_todo.py\n",
    )
    _write(
        app / "factory_tasks/validation_result.json",
        json.dumps({"status": "passed", "checks": []}),
    )


class AgentExecutorOptionalContractTests(unittest.TestCase):
    """AgentExecutor missions do not require a live Ollama task contract."""

    def test_allow_apply_is_the_agent_executor_path(self) -> None:
        self.assertTrue(
            agent_executor_path_active(
                {"proposal_application": {"allow_apply": True}}
            )
        )
        self.assertFalse(
            agent_executor_path_active(
                {"proposal_application": {"allow_apply": False}}
            )
        )
        self.assertFalse(agent_executor_path_active({}))

    def test_ollama_unavailable_does_not_set_planning_blocker(self) -> None:
        """1. AgentExecutor + Ollama down → no planning_contract_rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_root = root / "apps/demo/factory_tasks"
            task_root.mkdir(parents=True)
            project = {
                "root": "apps/demo",
                "task_root": "apps/demo/factory_tasks",
                "context_root": "apps/demo/factory_context",
            }
            architect, planner = _roles()
            factory_config = {
                **_ollama_factory(),
                "proposal_application": {"allow_apply": True},
            }
            with patch(
                "contract_stage.OllamaClient.chat",
                side_effect=OllamaConnectionError("offline"),
            ) as chat:
                result, json_path, _ = run_contract_stage(
                    project_name="demo",
                    root=root,
                    project=project,
                    factory_config=factory_config,
                    models_config={"models": {"planner": "cogito:14b"}},
                    max_lines=20,
                    tasks={"CURRENT_TASK.md": "# Current Task"},
                    architect_result=architect,
                    planner_result=planner,
                )
            chat.assert_not_called()
            self.assertEqual(result.source, SOURCE_SKIPPED)
            self.assertEqual(contract_status_label(result), "skipped")
            self.assertFalse(result.verdict.valid)
            record = json.loads((root / json_path).read_text(encoding="utf-8"))
            self.assertFalse(record["authorized"])
            self.assertEqual(record["validation"]["status"], "skipped")
            self.assertFalse(is_contract_actionable(record))

            factory_state: dict[str, object] = {"failure_count": 0}
            active_run: dict[str, object] = {
                "current_blocker": "planning_contract_rejected"
            }
            project_state: dict[str, object] = {
                "current_task": "DEMO-001",
                "failure_count": 2,
                "current_blocker": "planning_contract_rejected",
            }
            update_success_state(
                factory_state,
                active_run,
                project_state,
                architect,
                planner,
                contract_result=result,
            )
            self.assertNotEqual(
                project_state.get("current_blocker"),
                "planning_contract_rejected",
            )
            self.assertEqual(project_state["last_contract_status"], "skipped")
            self.assertFalse(project_state["contract_authorized"])
            self.assertEqual(project_state["failure_count"], 0)

    def test_agent_executor_runs_without_task_contract(self) -> None:
        """2. AgentExecutor still writes files with no planned_task body."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps/demo"
            (app / "src").mkdir(parents=True)
            (app / "factory_tasks").mkdir(parents=True)
            fake = MagicMock()
            fake.name = "fake"
            fake.can_implement.return_value = True
            fake.execute.return_value = ExecutorResult(
                ok=True,
                provider="fake",
                summary="wrote src/ok.py",
                files={"src/ok.py": "VALUE = 1\n"},
            )
            project = {
                "app_path": "apps/demo",
                "root": "apps/demo",
                "task_root": "apps/demo/factory_tasks",
            }
            written, err = apply_executor_result(
                fake.execute.return_value, project, root
            )
            self.assertIsNone(err)
            self.assertEqual(written, ["src/ok.py"])
            self.assertTrue((app / "src/ok.py").is_file())
            self.assertFalse((app / "factory_tasks/planned_task.json").exists())

            architect, planner = _roles()
            with patch(
                "contract_stage.OllamaClient.chat",
                side_effect=AssertionError("must not call Ollama"),
            ):
                result, _, _ = run_contract_stage(
                    project_name="demo",
                    root=root,
                    project=project,
                    factory_config={
                        **_ollama_factory(),
                        "proposal_application": {"allow_apply": True},
                    },
                    models_config={"models": {"planner": "cogito:14b"}},
                    max_lines=20,
                    tasks={},
                    architect_result=architect,
                    planner_result=planner,
                )
            self.assertEqual(result.source, SOURCE_SKIPPED)
            coder, _, _ = run_coder_stage(
                app_path="apps/demo",
                root=root,
                project=project,
                factory_config=_ollama_factory(),
                models_config={"models": {"coder": "x"}},
                max_lines=20,
                max_files=5,
                contract_json_path="apps/demo/factory_tasks/planned_task.json",
            )
            self.assertFalse(coder.activated)

    def test_complete_does_not_retain_stale_planning_blocker(self) -> None:
        """3. COMPLETE drops leftover planning_contract_rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("todo", "apps/todo", root=root)
            app = root / "apps/todo"
            project = ca.resolve_project(ca.load_registry(root), "todo")
            _make_accepted(app)
            state_path = app / "state/project_state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["current_blocker"] = "planning_contract_rejected"
            _write(state_path, json.dumps(state, indent=2))
            result = run_mission(
                project,
                root,
                max_beats=2,
                apply_profile=False,
                advance=lambda _p: 0,
            )
            self.assertEqual(result.outcome, COMPLETE, result.reason)
            _factory, _run, project_state = load_state(
                root, str(project["state_dir"]), "todo"
            )
            self.assertNotEqual(
                project_state.get("current_blocker"),
                "planning_contract_rejected",
            )
            self.assertNotEqual(
                result.records[-1].blocker, "planning_contract_rejected"
            )

    def test_more_work_continues_without_contract(self) -> None:
        """4. MORE_WORK AgentExecutor mission is not a contract failure."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("fresh", "apps/fresh", root=root)
            app = root / "apps/fresh"
            project = ca.resolve_project(ca.load_registry(root), "fresh")
            state_path = app / "state/project_state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["current_blocker"] = "planning_contract_rejected"
            _write(state_path, json.dumps(state, indent=2))

            def _skip_advance(_project: dict) -> int:
                architect, planner = _roles()
                result, _, _ = run_contract_stage(
                    project_name="fresh",
                    root=root,
                    project=project,
                    factory_config={
                        **_ollama_factory(),
                        "proposal_application": {"allow_apply": True},
                    },
                    models_config={"models": {"planner": "cogito:14b"}},
                    max_lines=20,
                    tasks={},
                    architect_result=architect,
                    planner_result=planner,
                )
                factory_state, active_run, project_state = load_state(
                    root, str(project["state_dir"]), "fresh"
                )
                update_success_state(
                    factory_state,
                    active_run,
                    project_state,
                    architect,
                    planner,
                    contract_result=result,
                )
                from mission_state import persist_state

                persist_state(
                    root=root,
                    state_dir=str(project["state_dir"]),
                    factory_state=factory_state,
                    active_run=active_run,
                    project_state=project_state,
                )
                return 0

            with patch(
                "contract_stage.OllamaClient.chat",
                side_effect=AssertionError("must not call Ollama"),
            ):
                result = run_mission(
                    project,
                    root,
                    max_beats=2,
                    apply_profile=True,
                    advance=_skip_advance,
                )
            self.assertEqual(result.records[0].evaluation, MORE_WORK)
            self.assertGreaterEqual(result.beats, 1)
            self.assertNotEqual(result.outcome, "RECOVERABLE_FAILURE")
            self.assertFalse(
                any(
                    rec.evaluation == "RECOVERABLE_FAILURE"
                    for rec in result.records
                )
            )
            _factory, _run, project_state = load_state(
                root, str(project["state_dir"]), "fresh"
            )
            self.assertNotEqual(
                project_state.get("current_blocker"),
                "planning_contract_rejected",
            )
            planned = app / "factory_tasks/planned_task.json"
            self.assertTrue(planned.is_file())
            record = json.loads(planned.read_text(encoding="utf-8"))
            self.assertEqual(record["validation"]["status"], "skipped")
            self.assertFalse(record["authorized"])


class InnerCoderContractGateTests(unittest.TestCase):
    """Inner Coder chain still requires is_contract_actionable."""

    def _project(self, root: Path) -> dict[str, str]:
        task_root = root / "apps/demo/factory_tasks"
        task_root.mkdir(parents=True)
        (root / "apps/demo/docs").mkdir(parents=True, exist_ok=True)
        return {
            "root": "apps/demo",
            "task_root": "apps/demo/factory_tasks",
            "context_root": "contexts",
            "app_path": "apps/demo",
        }

    def test_rejected_or_missing_contract_stays_gated(self) -> None:
        """5. Inner Coder path + rejected/missing contract remains gated."""
        architect, planner = _roles()
        factory_state: dict[str, object] = {"failure_count": 0}
        active_run: dict[str, object] = {}
        project_state: dict[str, object] = {
            "current_task": "DEMO-002",
            "failure_count": 0,
        }
        rejected = ContractResult(
            None, ValidationVerdict(False, ["bad"]), "fallback", "offline"
        )
        update_success_state(
            factory_state,
            active_run,
            project_state,
            architect,
            planner,
            contract_result=rejected,
        )
        self.assertEqual(
            project_state["current_blocker"], "planning_contract_rejected"
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self._project(root)
            with patch(
                "contract_stage.OllamaClient.chat",
                side_effect=OllamaConnectionError("offline"),
            ):
                result = request_task_contract(
                    project_name="demo",
                    project=project,
                    factory_config=_ollama_factory(),
                    models_config={"models": {"planner": "cogito:14b"}},
                    max_lines=20,
                    tasks={},
                    architect_result=architect,
                    planner_result=planner,
                )
            self.assertEqual(result.source, "fallback")
            self.assertFalse(result.verdict.valid)

            with patch(
                "coder_proposal.OllamaClient.chat",
                side_effect=AssertionError("must not call coder"),
            ):
                coder, _, _ = run_coder_stage(
                    app_path="apps/demo",
                    root=root,
                    project=project,
                    factory_config=_ollama_factory(),
                    models_config={"models": {"coder": "x"}},
                    max_lines=20,
                    max_files=5,
                    contract_json_path="apps/demo/factory_tasks/"
                    "planned_task.json",
                )
            self.assertFalse(coder.activated)

            with patch(
                "proposal_applier.OllamaClient.chat",
                side_effect=AssertionError("must not call applier"),
            ):
                application, _, _, _ = run_application_stage(
                    app_path="apps/demo",
                    root=root,
                    project=project,
                    factory_config={
                        **_ollama_factory(),
                        "proposal_application": {
                            "mode": "apply",
                            "allow_apply": False,
                        },
                    },
                    models_config={"models": {"coder": "x"}},
                    max_lines=20,
                    max_files=5,
                    contract_json_path="apps/demo/factory_tasks/"
                    "planned_task.json",
                    proposal_json_path="apps/demo/factory_tasks/"
                    "coder_proposal.json",
                )
            self.assertFalse(application.activated)

            tests, _, _ = run_test_builder_stage(
                project_name="demo",
                root=root,
                project=project,
                factory_config=_ollama_factory(),
                models_config={"models": {"test_builder": "x"}},
                max_lines=20,
                contract_json_path="apps/demo/factory_tasks/planned_task.json",
                proposal_json_path="apps/demo/factory_tasks/coder_proposal.json",
            )
            self.assertFalse(tests.activated)

            eligible, reasons = checkpoint_gate(
                contract_record=None,
                proposal_record=None,
                application_record=None,
                validation_record=None,
            )
            self.assertFalse(eligible)
            self.assertTrue(
                any("authorized" in r.lower() for r in reasons),
                reasons,
            )

    def test_valid_unauthorized_contract_stays_gated(self) -> None:
        """6. Valid but unauthorized contract does not activate inner Coder."""
        task = parse_planned_task(json.dumps(_valid_contract_dict()))
        verdict = validate_planned_task(task)
        self.assertTrue(verdict.valid)
        record = {
            **_valid_contract_dict(),
            "authorized": False,
            "validation": {"status": "valid", "reasons": []},
        }
        self.assertFalse(is_contract_actionable(record))

        architect, planner = _roles()
        factory_state: dict[str, object] = {"failure_count": 0}
        active_run: dict[str, object] = {}
        project_state: dict[str, object] = {
            "current_task": "DEMO-002",
            "failure_count": 0,
        }
        update_success_state(
            factory_state,
            active_run,
            project_state,
            architect,
            planner,
            contract_result=ContractResult(task, verdict, "ollama", "m"),
        )
        self.assertIsNone(project_state.get("current_blocker"))
        self.assertFalse(project_state["contract_authorized"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self._project(root)
            (
                root / "apps/demo/factory_tasks/planned_task.json"
            ).write_text(json.dumps(record), encoding="utf-8")
            with patch(
                "coder_proposal.OllamaClient.chat",
                side_effect=AssertionError("must not call coder"),
            ):
                coder, _, _ = run_coder_stage(
                    app_path="apps/demo",
                    root=root,
                    project=project,
                    factory_config=_ollama_factory(),
                    models_config={"models": {"coder": "x"}},
                    max_lines=20,
                    max_files=5,
                    contract_json_path="apps/demo/factory_tasks/"
                    "planned_task.json",
                )
            self.assertFalse(coder.activated)
            eligible, _reasons = checkpoint_gate(
                contract_record=record,
                proposal_record={
                    "validation": {"status": "valid", "reasons": []}
                },
                application_record={
                    "validation": {"status": "applied", "reasons": []}
                },
                validation_record={"status": "passed"},
            )
            self.assertFalse(eligible)

    def test_valid_authorized_contract_still_activates_coder(self) -> None:
        """7. Authorized valid contract still opens the inner Coder gate."""
        record = _authorized_contract_dict()
        self.assertTrue(is_contract_actionable(record))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self._project(root)
            (
                root / "apps/demo/factory_tasks/planned_task.json"
            ).write_text(json.dumps(record), encoding="utf-8")
            fake = ProposalResult(
                None,
                ProposalVerdict(False, ["parsed later"], [], []),
                "ollama",
                "model",
                activated=True,
            )
            with patch(
                "coder_proposal.request_coder_proposal", return_value=fake
            ):
                coder, _, _ = run_coder_stage(
                    app_path="apps/demo",
                    root=root,
                    project=project,
                    factory_config=_ollama_factory(),
                    models_config={"models": {"coder": "x"}},
                    max_lines=20,
                    max_files=5,
                    contract_json_path="apps/demo/factory_tasks/"
                    "planned_task.json",
                )
            self.assertTrue(coder.activated)
            self.assertEqual(coder.source, "ollama")
            eligible, reasons = checkpoint_gate(
                contract_record=record,
                proposal_record={
                    "validation": {"status": "valid", "reasons": []}
                },
                application_record={
                    "validation": {"status": "applied", "reasons": []}
                },
                validation_record={"status": "passed"},
            )
            self.assertTrue(eligible, reasons)


class SkippedContractSemanticsTests(unittest.TestCase):
    """Skipped diagnostics stay unauthorized and never look like a reject."""

    def test_skipped_result_is_not_a_rejection_label(self) -> None:
        result = skipped_agent_executor_contract()
        self.assertEqual(result.decision, DECISION_SKIPPED_AGENT_EXECUTOR)
        self.assertEqual(contract_status_label(result), "skipped")
        self.assertFalse(result.task)
        self.assertFalse(result.verdict.valid)

    def test_skipped_does_not_clobber_existing_unauthorized_contract(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_root = root / "apps/demo/factory_tasks"
            task_root.mkdir(parents=True)
            original = {
                **_valid_contract_dict(),
                "authorized": False,
                "validation": {"status": "valid", "reasons": []},
            }
            path = task_root / "planned_task.json"
            path.write_text(json.dumps(original, indent=2), encoding="utf-8")
            architect, planner = _roles()
            with patch(
                "contract_stage.OllamaClient.chat",
                side_effect=AssertionError("must not regenerate"),
            ):
                result, _, _ = run_contract_stage(
                    project_name="demo",
                    root=root,
                    project={
                        "root": "apps/demo",
                        "task_root": "apps/demo/factory_tasks",
                        "context_root": "apps/demo/factory_context",
                    },
                    factory_config={
                        **_ollama_factory(),
                        "proposal_application": {"allow_apply": True},
                    },
                    models_config={"models": {"planner": "cogito:14b"}},
                    max_lines=20,
                    tasks={},
                    architect_result=architect,
                    planner_result=planner,
                )
            self.assertEqual(result.source, SOURCE_SKIPPED)
            kept = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(kept["task_id"], "DEMO-002")
            self.assertFalse(kept["authorized"])
            self.assertEqual(kept["validation"]["status"], "valid")

    def test_inner_coder_path_still_requests_ollama(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "apps/demo/factory_tasks").mkdir(parents=True)
            architect, planner = _roles()
            with patch(
                "contract_stage.OllamaClient.chat",
                side_effect=OllamaConnectionError("offline"),
            ) as chat:
                result, _, _ = run_contract_stage(
                    project_name="demo",
                    root=root,
                    project={
                        "root": "apps/demo",
                        "task_root": "apps/demo/factory_tasks",
                        "context_root": "contexts",
                    },
                    factory_config=_ollama_factory(),
                    models_config={"models": {"planner": "cogito:14b"}},
                    max_lines=20,
                    tasks={},
                    architect_result=architect,
                    planner_result=planner,
                )
            chat.assert_called()
            self.assertEqual(result.source, "fallback")
            self.assertFalse(result.verdict.valid)


class EvaluateMissionLeftoverTests(unittest.TestCase):
    """Product stops ignore leftover planning rejects without using them."""

    def test_runnable_preview_also_drops_stale_planning_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bootstrap_repo(root)
            ca.startproject("habit", "apps/habit", root=root)
            app = root / "apps/habit"
            project = ca.resolve_project(ca.load_registry(root), "habit")
            from prompt_compiler import compile_into_workbench

            compile_into_workbench(project, root, "build a habit tracker")
            _make_accepted(app)
            state_path = app / "state/project_state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["current_blocker"] = "planning_contract_rejected"
            _write(state_path, json.dumps(state, indent=2))
            with patch(
                "mission_runner.coding_executor_available",
                return_value=False,
            ):
                status, _reason = evaluate_mission(
                    project, root, beat=0, max_beats=3
                )
            self.assertEqual(status, RUNNABLE_PREVIEW)
            _factory, _run, project_state = load_state(
                root, str(project["state_dir"]), "habit"
            )
            self.assertNotEqual(
                project_state.get("current_blocker"),
                "planning_contract_rejected",
            )


if __name__ == "__main__":
    unittest.main()
