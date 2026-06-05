"""Tests for the Phase 4A authorized Coder proposal engine.

These tests exercise proposal parsing, the safety validator, the
activation gate, deterministic fallback, state transitions, and report
generation without writing application code or calling Ollama.
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

from coder_proposal import (  # noqa: E402
    APPLY_ELIGIBLE_DECISIONS,
    DECISION_BLOCKED,
    DECISION_INVALID,
    DECISION_NEEDS_CLARIFICATION,
    DECISION_NEEDS_OWNER_REVIEW,
    DECISION_VALID,
    CoderProposal,
    ProposalParseError,
    ProposalResult,
    ProposalVerdict,
    allowed_target_prefixes,
    coder_proposal_paths,
    coder_status_label,
    coder_to_dict,
    decision_label,
    parse_coder_proposal,
    read_workbench_source,
    render_coder_proposal_md,
    request_coder_proposal,
    run_coder_stage,
    validate_proposal,
)
from mission_state import update_success_state  # noqa: E402
from ollama_client import OllamaConnectionError  # noqa: E402
from planning_roles import RoleResult  # noqa: E402
from prompt_builder import PromptPackage  # noqa: E402
from report_writer import append_dry_run_report  # noqa: E402


def _valid_proposal_dict() -> dict[str, object]:
    """Return a well-formed, in-bounds proposal mapping for demo_app."""
    return {
        "proposal_id": "CP-001",
        "task_id": "DEMO-002",
        "summary": "Add a status note",
        "objective": "Document the demo build status",
        "files_to_create": ["apps/demo_app/app/status.py"],
        "files_to_modify": ["apps/demo_app/docs/README.md"],
        "files_to_delete": [],
        "proposed_tests": ["apps/demo_app/tests/test_status.py"],
        "implementation_steps": ["Create module", "Update docs"],
        "estimated_risk": "low",
        "notes": "",
    }


def _authorized_contract_dict() -> dict[str, object]:
    """Return a valid, owner-authorized contract record."""
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
        "authorized": True,
        "validation": {"status": "valid", "source": "ollama", "reasons": []},
    }


def _valid_proposal() -> CoderProposal:
    """Return a parsed valid proposal."""
    return parse_coder_proposal(json.dumps(_valid_proposal_dict()))


class ParseTests(unittest.TestCase):
    """Verify proposal parsing behavior."""

    def test_parse_valid_proposal(self) -> None:
        """Parse a well-formed JSON proposal."""
        proposal = _valid_proposal()
        self.assertEqual(proposal.proposal_id, "CP-001")
        self.assertEqual(
            proposal.files_to_create, ["apps/demo_app/app/status.py"]
        )

    def test_parse_strips_code_fence(self) -> None:
        """Tolerate JSON wrapped in a Markdown code fence."""
        fenced = "```json\n" + json.dumps(_valid_proposal_dict()) + "\n```"
        self.assertEqual(parse_coder_proposal(fenced).task_id, "DEMO-002")

    def test_parse_rejects_non_json(self) -> None:
        """Raise a parse error for non-object output."""
        with self.assertRaises(ProposalParseError):
            parse_coder_proposal("not a proposal")
        with self.assertRaises(ProposalParseError):
            parse_coder_proposal("[1, 2]")

    def test_parse_drops_nested_objects_in_lists(self) -> None:
        """Object elements in list fields are discarded (shared coercion)."""
        data = _valid_proposal_dict()
        data["files_to_create"] = [{"x": 1}, "apps/demo_app/app/ok.py"]
        proposal = parse_coder_proposal(json.dumps(data))
        self.assertEqual(proposal.files_to_create, ["apps/demo_app/app/ok.py"])


class ValidateTests(unittest.TestCase):
    """Verify the proposal safety validator."""

    def _validate(
        self, proposal: CoderProposal | None, **kwargs: object
    ) -> ProposalVerdict:
        params: dict[str, object] = {
            "app_path": "apps/demo_app",
            "contract_actionable": True,
            "max_files": 5,
        }
        params.update(kwargs)
        return validate_proposal(proposal, **params)  # type: ignore[arg-type]

    def test_accepts_allowed_paths(self) -> None:
        """Accept an in-bounds, complete proposal."""
        verdict = self._validate(_valid_proposal())
        self.assertTrue(verdict.valid, verdict.reasons)

    def test_rejects_unauthorized_contract(self) -> None:
        """Rule 1-3: reject when the backing contract is not actionable."""
        verdict = self._validate(_valid_proposal(), contract_actionable=False)
        self.assertFalse(verdict.valid)

    def test_rejects_none_proposal(self) -> None:
        """A missing proposal is never valid."""
        self.assertFalse(self._validate(None).valid)

    def test_rejects_empty_proposal(self) -> None:
        """Rule 7: reject a proposal that targets no files."""
        data = _valid_proposal_dict()
        data["files_to_create"] = []
        data["files_to_modify"] = []
        data["files_to_delete"] = []
        verdict = self._validate(parse_coder_proposal(json.dumps(data)))
        self.assertFalse(verdict.valid)
        self.assertTrue(any("empty" in r.lower() for r in verdict.reasons))

    def test_rejects_escape_outside_workbench(self) -> None:
        """Absolute/traversal paths that leave the workbench are blocked."""
        for bad in ["/etc/passwd", "../elsewhere.py"]:
            data = _valid_proposal_dict()
            data["files_to_create"] = [bad]
            data["files_to_modify"] = []
            verdict = self._validate(parse_coder_proposal(json.dumps(data)))
            self.assertFalse(verdict.valid, bad)
            self.assertIn(bad, verdict.blocked_paths)

    def test_rejects_factory_runtime_and_vcs(self) -> None:
        """Workbench-relative paths into factory runtime or .git are blocked."""
        for bad in [
            ".git/config",
            "state/x.json",
            "factory_tasks/planned_task.json",
            "config/factory.yaml",
        ]:
            data = _valid_proposal_dict()
            data["files_to_modify"] = [bad]
            data["files_to_create"] = []
            verdict = self._validate(parse_coder_proposal(json.dumps(data)))
            self.assertFalse(verdict.valid, bad)
            self.assertIn(bad, verdict.blocked_paths)

    def test_app_readme_is_in_project(self) -> None:
        """A bare README.md is the app's own README — in-project, allowed."""
        data = _valid_proposal_dict()
        data["files_to_modify"] = ["README.md"]
        data["files_to_create"] = []
        verdict = self._validate(parse_coder_proposal(json.dumps(data)))
        self.assertTrue(verdict.valid, verdict.reasons)

    def test_rejects_delete_escape(self) -> None:
        """A delete that escapes the workbench is blocked."""
        data = _valid_proposal_dict()
        data["files_to_create"] = []
        data["files_to_modify"] = []
        data["files_to_delete"] = ["../outside.md"]
        verdict = self._validate(parse_coder_proposal(json.dumps(data)))
        self.assertFalse(verdict.valid)
        self.assertIn("../outside.md", verdict.blocked_paths)

    def test_rejects_parent_traversal(self) -> None:
        """Reject parent-traversal paths even under an allowed prefix."""
        data = _valid_proposal_dict()
        data["files_to_create"] = ["apps/demo_app/app/../../../etc/passwd"]
        data["files_to_modify"] = []
        verdict = self._validate(parse_coder_proposal(json.dumps(data)))
        self.assertFalse(verdict.valid)

    def test_rejects_secret_markers(self) -> None:
        """Rule 5: reject secret-like material."""
        data = _valid_proposal_dict()
        data["files_to_create"] = ["apps/demo_app/app/.env"]
        data["files_to_modify"] = []
        verdict = self._validate(parse_coder_proposal(json.dumps(data)))
        self.assertFalse(verdict.valid)
        self.assertTrue(any("secret" in r.lower() for r in verdict.reasons))

    def test_rejects_dangerous_command(self) -> None:
        """Rule 6: reject destructive/git operations in steps."""
        data = _valid_proposal_dict()
        data["implementation_steps"] = ["rm -rf /", "git push --force"]
        verdict = self._validate(parse_coder_proposal(json.dumps(data)))
        self.assertFalse(verdict.valid)
        self.assertTrue(any("forbidden" in r.lower() for r in verdict.reasons))

    def test_rejects_over_file_limit(self) -> None:
        """Rule 8: reject proposals over the file budget."""
        data = _valid_proposal_dict()
        data["files_to_create"] = [
            "apps/demo_app/app/a.py",
            "apps/demo_app/app/b.py",
        ]
        data["files_to_modify"] = ["apps/demo_app/docs/README.md"]
        verdict = self._validate(
            parse_coder_proposal(json.dumps(data)), max_files=2
        )
        self.assertFalse(verdict.valid)
        self.assertTrue(any("limit" in r.lower() for r in verdict.reasons))

    def test_warns_on_high_risk(self) -> None:
        """High estimated risk is a warning, not a rejection."""
        data = _valid_proposal_dict()
        data["estimated_risk"] = "high"
        verdict = self._validate(parse_coder_proposal(json.dumps(data)))
        self.assertTrue(verdict.valid)
        self.assertTrue(any("risk" in w.lower() for w in verdict.warnings))

    def test_warns_on_task_id_mismatch(self) -> None:
        """A proposal task_id unlike the contract's warns but may pass."""
        verdict = self._validate(
            _valid_proposal(), contract_task_id="OTHER-999"
        )
        self.assertTrue(verdict.valid)
        self.assertTrue(any("task_id" in w.lower() for w in verdict.warnings))


class DecisionTests(unittest.TestCase):
    """Verify the Stage 1 governance decision layer.

    ``decision`` is additive; ``valid`` (the apply-gate signal) must stay
    exactly equivalent to the old ``not reasons`` behavior, i.e.
    ``valid == decision in APPLY_ELIGIBLE_DECISIONS``.
    """

    def _v(
        self, proposal: CoderProposal | None, **kw: object
    ) -> ProposalVerdict:
        params: dict[str, object] = {
            "app_path": "apps/demo_app",
            "contract_actionable": True,
            "max_files": 5,
        }
        params.update(kw)
        return validate_proposal(proposal, **params)  # type: ignore[arg-type]

    def test_clean_proposal_is_valid(self) -> None:
        v = self._v(_valid_proposal())
        self.assertEqual(v.decision, DECISION_VALID)
        self.assertTrue(v.valid)

    def test_high_risk_is_needs_owner_review_but_apply_eligible(self) -> None:
        data = _valid_proposal_dict()
        data["estimated_risk"] = "high"
        v = self._v(parse_coder_proposal(json.dumps(data)))
        self.assertEqual(v.decision, DECISION_NEEDS_OWNER_REVIEW)
        self.assertTrue(v.valid)  # eligible *through* the owner-approval gate
        self.assertTrue(v.review_reasons)

    def test_factory_runtime_path_is_blocked(self) -> None:
        # A workbench-relative path into the factory runtime is blocked.
        data = _valid_proposal_dict()
        data["files_to_modify"] = ["factory_tasks/planned_task.json"]
        data["files_to_create"] = []
        v = self._v(parse_coder_proposal(json.dumps(data)))
        self.assertEqual(v.decision, DECISION_BLOCKED)
        self.assertFalse(v.valid)

    def test_escape_path_is_blocked(self) -> None:
        data = _valid_proposal_dict()
        data["files_to_create"] = ["/etc/passwd"]
        data["files_to_modify"] = []
        v = self._v(parse_coder_proposal(json.dumps(data)))
        self.assertEqual(v.decision, DECISION_BLOCKED)
        self.assertFalse(v.valid)

    def test_workbench_relative_src_is_valid(self) -> None:
        # The model's natural "src/x.py" resolves into the workbench → valid.
        data = _valid_proposal_dict()
        data["files_to_create"] = ["src/elsewhere.py"]
        data["files_to_modify"] = []
        v = self._v(parse_coder_proposal(json.dumps(data)))
        self.assertEqual(v.decision, DECISION_VALID)
        self.assertTrue(v.valid)

    def test_empty_proposal_is_needs_clarification(self) -> None:
        data = _valid_proposal_dict()
        data["files_to_create"] = []
        data["files_to_modify"] = []
        data["files_to_delete"] = []
        data["proposed_tests"] = []
        v = self._v(parse_coder_proposal(json.dumps(data)))
        self.assertEqual(v.decision, DECISION_NEEDS_CLARIFICATION)
        self.assertFalse(v.valid)
        self.assertTrue(v.clarification_questions)

    def test_none_proposal_is_invalid(self) -> None:
        v = self._v(None)
        self.assertEqual(v.decision, DECISION_INVALID)
        self.assertFalse(v.valid)

    def test_valid_iff_apply_eligible(self) -> None:
        # The core invariant the apply gate depends on.
        for proposal in (
            _valid_proposal(),
            parse_coder_proposal(
                json.dumps(
                    {**_valid_proposal_dict(), "estimated_risk": "high"}
                )
            ),
            parse_coder_proposal(
                json.dumps(
                    {
                        **_valid_proposal_dict(),
                        "files_to_create": ["factory/x.py"],
                        "files_to_modify": [],
                    }
                )
            ),
            None,
        ):
            v = self._v(proposal)
            self.assertEqual(
                v.valid, v.decision in APPLY_ELIGIBLE_DECISIONS, v.decision
            )

    def test_decision_label_not_activated(self) -> None:
        skipped = ProposalResult(
            None, ProposalVerdict(False, [], [], []), "skipped", "d"
        )
        self.assertEqual(decision_label(skipped), "not_activated")

    def _decision_for(self, **path_fields: object) -> str:
        data = _valid_proposal_dict()
        data["files_to_create"] = []
        data["files_to_modify"] = []
        data["files_to_delete"] = []
        data["proposed_tests"] = []
        data.update(path_fields)
        return self._v(parse_coder_proposal(json.dumps(data))).decision

    def test_scripts_dir_is_needs_owner_review(self) -> None:
        # Stage 3: in-bounds but higher-impact -> review, not blocked.
        d = self._decision_for(files_to_create=["apps/demo_app/scripts/x.py"])
        self.assertEqual(d, DECISION_NEEDS_OWNER_REVIEW)

    def test_migrations_dir_is_needs_owner_review(self) -> None:
        d = self._decision_for(
            files_to_create=["apps/demo_app/migrations/001.sql"]
        )
        self.assertEqual(d, DECISION_NEEDS_OWNER_REVIEW)

    def test_in_bounds_delete_is_needs_owner_review(self) -> None:
        d = self._decision_for(files_to_delete=["apps/demo_app/app/old.py"])
        self.assertEqual(d, DECISION_NEEDS_OWNER_REVIEW)

    def test_novel_app_dir_is_valid(self) -> None:
        # Stage 2: the whole workbench is in-bounds (not just app/docs/tests).
        d = self._decision_for(files_to_create=["apps/demo_app/src/main.py"])
        self.assertEqual(d, DECISION_VALID)

    def test_factory_runtime_inside_workbench_is_blocked(self) -> None:
        for runtime in [
            "apps/demo_app/factory_tasks/planned_task.json",
            "apps/demo_app/config/factory.yaml",
            "apps/demo_app/state/factory_state.json",
            "apps/demo_app/crazy_project.yaml",
        ]:
            d = self._decision_for(files_to_modify=[runtime])
            self.assertEqual(d, DECISION_BLOCKED, runtime)

    def test_env_example_is_not_blocked(self) -> None:
        # Stage 4: placeholder env files are documentation, not secrets.
        d = self._decision_for(
            files_to_create=["apps/demo_app/docs/.env.example"]
        )
        self.assertEqual(d, DECISION_VALID)

    def test_bare_env_is_blocked_as_secret(self) -> None:
        data = _valid_proposal_dict()
        data["files_to_create"] = ["apps/demo_app/app/.env"]
        data["files_to_modify"] = []
        v = self._v(parse_coder_proposal(json.dumps(data)))
        self.assertEqual(v.decision, DECISION_BLOCKED)
        self.assertTrue(any("secret" in r.lower() for r in v.reasons))

    def test_coder_to_dict_carries_decision(self) -> None:
        data = _valid_proposal_dict()
        data["estimated_risk"] = "high"
        proposal = parse_coder_proposal(json.dumps(data))
        verdict = self._v(proposal)
        record = coder_to_dict(
            ProposalResult(proposal, verdict, "ollama", "d", activated=True)
        )
        # status stays the apply-gate signal; decision is additive.
        self.assertEqual(record["validation"]["status"], "valid")
        self.assertEqual(
            record["validation"]["decision"], DECISION_NEEDS_OWNER_REVIEW
        )
        self.assertIn("review_reasons", record["validation"])
        self.assertIn("clarification_questions", record["validation"])


class RequestTests(unittest.TestCase):
    """Verify the model request path with Ollama mocked."""

    def _project(self) -> dict[str, object]:
        return {
            "root": "apps/demo_app",
            "task_root": "apps/demo_app/factory_tasks",
            "context_root": "apps/demo_app/factory_context",
        }

    def _factory_config(self) -> dict[str, object]:
        return {
            "ollama": {
                "base_url": "http://localhost:11434",
                "timeout_seconds": 1,
                "stream": False,
            }
        }

    def _call(
        self,
        *,
        side_effect: object = None,
        return_value: object = None,
    ) -> ProposalResult:
        with (
            patch(
                "coder_proposal.build_prompt_package",
                return_value=PromptPackage("coder", "demo_app", "P", []),
            ),
            patch(
                "coder_proposal.OllamaClient.chat",
                side_effect=side_effect,
                return_value=return_value,
            ),
        ):
            return request_coder_proposal(
                app_path="apps/demo_app",
                project=self._project(),
                contract_record=_authorized_contract_dict(),
                factory_config=self._factory_config(),
                models_config={"models": {"coder": "qwen2.5-coder:14b"}},
                max_lines=20,
                max_files=5,
            )

    def test_falls_back_when_ollama_unavailable(self) -> None:
        """Ollama down yields a rejected proposal, never a fake-valid one."""
        result = self._call(side_effect=OllamaConnectionError("offline"))
        self.assertEqual(result.source, "fallback")
        self.assertIsNone(result.proposal)
        self.assertFalse(result.verdict.valid)
        self.assertTrue(result.activated)

    def test_rejects_unparseable_response(self) -> None:
        """A non-JSON model response is rejected."""
        result = self._call(return_value={"message": {"content": "not json"}})
        self.assertEqual(result.source, "ollama")
        self.assertIsNone(result.proposal)
        self.assertFalse(result.verdict.valid)

    def test_validates_ollama_proposal(self) -> None:
        """A well-formed in-bounds proposal validates."""
        content = json.dumps(_valid_proposal_dict())
        result = self._call(return_value={"message": {"content": content}})
        self.assertEqual(result.source, "ollama")
        self.assertIsNotNone(result.proposal)
        self.assertTrue(result.verdict.valid, result.verdict.reasons)

    def test_coder_prompt_carries_quality_bar(self) -> None:
        """9D.0.2: the coder instruction includes the anti-stub quality bar."""
        captured: dict[str, object] = {}

        def _chat(model: object, messages: object, **_: object) -> dict:
            captured["messages"] = messages
            raise OllamaConnectionError("captured")

        with (
            patch(
                "coder_proposal.build_prompt_package",
                return_value=PromptPackage("coder", "demo_app", "P", []),
            ),
            patch("coder_proposal.OllamaClient.chat", side_effect=_chat),
        ):
            request_coder_proposal(
                app_path="apps/demo_app",
                project=self._project(),
                contract_record=_authorized_contract_dict(),
                factory_config=self._factory_config(),
                models_config={"models": {"coder": "qwen2.5-coder:14b"}},
                max_lines=20,
                max_files=5,
            )
        system = captured["messages"][0]["content"]  # type: ignore[index]
        self.assertIn("QUALITY BAR", system)
        self.assertIn("NotImplementedError", system)

    def test_situational_ground_truth_reaches_coder_prompt(self) -> None:
        """9D.2: the curated packet slice is injected into the coder prompt."""
        captured: dict[str, object] = {}

        def _chat(model: object, messages: object, **_: object) -> dict:
            captured["messages"] = messages
            raise OllamaConnectionError("captured")

        with (
            patch(
                "coder_proposal.build_prompt_package",
                return_value=PromptPackage("coder", "demo_app", "P", []),
            ),
            patch("coder_proposal.OllamaClient.chat", side_effect=_chat),
        ):
            request_coder_proposal(
                app_path="apps/demo_app",
                project=self._project(),
                contract_record=_authorized_contract_dict(),
                factory_config=self._factory_config(),
                models_config={"models": {"coder": "qwen2.5-coder:14b"}},
                max_lines=20,
                max_files=5,
                situational="GROUNDTRUTH-MARK: prior proposal rejected",
            )
        user = captured["messages"][1]["content"]  # type: ignore[index]
        self.assertIn("GROUNDTRUTH-MARK", user)
        self.assertIn("What Happened Last Time", user)


class StageTests(unittest.TestCase):
    """Verify the activation gate and artifact writing."""

    def _project(self, root: Path) -> dict[str, object]:
        (root / "apps/demo/factory_tasks").mkdir(parents=True)
        return {
            "root": "apps/demo",
            "task_root": "apps/demo/factory_tasks",
            "context_root": "apps/demo/factory_context",
        }

    def test_coder_proposal_paths_inside_project(self) -> None:
        """Proposal paths stay inside the project workbench."""
        project = {
            "root": "apps/demo_app",
            "task_root": "apps/demo_app/factory_tasks",
        }
        repo_root = Path(__file__).resolve().parents[1]
        json_path, md_path = coder_proposal_paths(repo_root, project)
        self.assertTrue(json_path.endswith("coder_proposal.json"))
        self.assertTrue(md_path.endswith("CODER_PROPOSAL.md"))
        with self.assertRaises(RuntimeError):
            coder_proposal_paths(
                repo_root,
                {"root": "apps/demo_app", "task_root": "reports"},
            )

    def test_preserves_valid_proposal_without_regenerating(self) -> None:
        """A valid proposal for the same task is preserved, not regenerated."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._project(root)
            task_root = root / "apps/demo/factory_tasks"
            (task_root / "planned_task.json").write_text(
                json.dumps(_authorized_contract_dict()), encoding="utf-8"
            )
            # A previously generated, owner-reviewed valid proposal on disk,
            # in-bounds for project "demo".
            existing = {
                "proposal_id": "CP-001",
                "task_id": "DEMO-002",
                "summary": "s",
                "objective": "o",
                "files_to_create": [],
                "files_to_modify": ["apps/demo/docs/README.md"],
                "files_to_delete": [],
                "proposed_tests": [],
                "implementation_steps": ["append a note"],
                "estimated_risk": "low",
                "notes": "",
                "validation": {"status": "valid", "reasons": []},
            }
            (task_root / "coder_proposal.json").write_text(
                json.dumps(existing), encoding="utf-8"
            )
            with patch(
                "coder_proposal.OllamaClient.chat",
                side_effect=AssertionError("must not regenerate proposal"),
            ):
                result, _, _ = run_coder_stage(
                    app_path="apps/demo",
                    root=root,
                    project=project,
                    factory_config={"ollama": {}},
                    models_config={"models": {"coder": "x"}},
                    max_lines=20,
                    max_files=5,
                    contract_json_path="apps/demo/factory_tasks/"
                    "planned_task.json",
                )
            self.assertEqual(result.source, "preserved")
            self.assertTrue(result.activated)
            assert result.proposal is not None
            self.assertEqual(result.proposal.proposal_id, "CP-001")

    def test_stale_proposal_for_other_task_is_not_preserved(self) -> None:
        """A valid proposal for a different task is regenerated, not kept."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._project(root)
            task_root = root / "apps/demo/factory_tasks"
            (task_root / "planned_task.json").write_text(
                json.dumps(_authorized_contract_dict()), encoding="utf-8"
            )
            stale = {
                "proposal_id": "CP-OLD",
                "task_id": "OTHER-999",
                "summary": "s",
                "objective": "o",
                "files_to_create": [],
                "files_to_modify": ["apps/demo/docs/README.md"],
                "files_to_delete": [],
                "proposed_tests": [],
                "implementation_steps": ["x"],
                "estimated_risk": "low",
                "notes": "",
                "validation": {"status": "valid", "reasons": []},
            }
            (task_root / "coder_proposal.json").write_text(
                json.dumps(stale), encoding="utf-8"
            )
            fake = ProposalResult(
                None,
                ProposalVerdict(False, ["regenerated"], [], []),
                "ollama",
                "m",
                activated=True,
            )
            with patch(
                "coder_proposal.request_coder_proposal", return_value=fake
            ):
                result, _, _ = run_coder_stage(
                    app_path="apps/demo",
                    root=root,
                    project=project,
                    factory_config={"ollama": {}},
                    models_config={"models": {"coder": "x"}},
                    max_lines=20,
                    max_files=5,
                    contract_json_path="apps/demo/factory_tasks/"
                    "planned_task.json",
                )
            # Regeneration path was taken (stale proposal not preserved).
            self.assertEqual(result.source, "ollama")

    def test_skips_without_authorized_contract(self) -> None:
        """No authorized contract -> Coder skipped, no artifacts, no call."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._project(root)
            task_root = root / "apps/demo/factory_tasks"
            # A rejected/unauthorized contract on disk.
            (task_root / "planned_task.json").write_text(
                json.dumps(
                    {"authorized": False, "validation": {"status": "valid"}}
                ),
                encoding="utf-8",
            )
            with patch(
                "coder_proposal.OllamaClient.chat",
                side_effect=AssertionError("must not call model"),
            ):
                result, json_path, _ = run_coder_stage(
                    app_path="apps/demo",
                    root=root,
                    project=project,
                    factory_config={"ollama": {}},
                    models_config={"models": {"coder": "x"}},
                    max_lines=20,
                    max_files=5,
                    contract_json_path="apps/demo/factory_tasks/"
                    "planned_task.json",
                )
            self.assertFalse(result.activated)
            self.assertEqual(result.source, "skipped")
            # No proposal artifacts written when skipped.
            self.assertFalse((root / json_path).exists())

    def test_activates_and_writes_artifacts(self) -> None:
        """Authorized contract -> Coder runs and writes both artifacts."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._project(root)
            task_root = root / "apps/demo/factory_tasks"
            (task_root / "planned_task.json").write_text(
                json.dumps(_authorized_contract_dict()), encoding="utf-8"
            )
            fake = ProposalResult(
                _valid_proposal(),
                ProposalVerdict(True, [], [], []),
                "ollama",
                "model",
                activated=True,
            )
            with patch(
                "coder_proposal.request_coder_proposal", return_value=fake
            ):
                result, json_path, md_path = run_coder_stage(
                    app_path="apps/demo",
                    root=root,
                    project=project,
                    factory_config={"ollama": {}},
                    models_config={"models": {"coder": "x"}},
                    max_lines=20,
                    max_files=5,
                    contract_json_path="apps/demo/factory_tasks/"
                    "planned_task.json",
                )
            self.assertTrue(result.activated)
            self.assertTrue((root / json_path).is_file())
            self.assertTrue((root / md_path).is_file())
            record = json.loads((root / json_path).read_text())
            self.assertFalse(record["applied"])


class StateAndReportTests(unittest.TestCase):
    """Verify coder state transitions and report rendering."""

    def _states(self) -> tuple[dict, dict, dict]:
        return (
            {"failure_count": 0},
            {},
            {"current_task": "DEMO-002", "failure_count": 0},
        )

    def _update(self, coder_result: ProposalResult) -> tuple[dict, dict]:
        factory_state, active_run, project_state = self._states()
        update_success_state(
            factory_state,
            active_run,
            project_state,
            RoleResult("a", "x", "ollama", "m"),
            RoleResult("p", "y", "ollama", "m"),
            coder_result=coder_result,
        )
        return active_run, project_state

    def test_state_skipped_is_not_a_failure(self) -> None:
        """A skipped coder records status without bumping failures."""
        result = ProposalResult(
            None, ProposalVerdict(False, ["skip"], [], []), "skipped", "d"
        )
        active_run, project_state = self._update(result)
        self.assertEqual(project_state["last_coder_status"], "not_activated")
        self.assertEqual(project_state["last_proposal_verdict"], "skipped")
        self.assertEqual(project_state["failure_count"], 0)

    def test_state_valid_proposal_points_to_review(self) -> None:
        """A valid proposal sets accepted verdict and review resume."""
        result = ProposalResult(
            _valid_proposal(),
            ProposalVerdict(True, [], [], []),
            "ollama",
            "d",
            activated=True,
        )
        active_run, project_state = self._update(result)
        self.assertEqual(project_state["last_coder_status"], "valid")
        self.assertEqual(project_state["last_proposal_verdict"], "accepted")
        self.assertEqual(project_state["last_proposal_id"], "CP-001")
        self.assertIn("coder_proposal", str(active_run["resume_from"]))
        self.assertEqual(project_state["failure_count"], 0)

    def test_state_rejected_proposal_increments_failure(self) -> None:
        """An activated rejected proposal is a recoverable failure."""
        result = ProposalResult(
            None,
            ProposalVerdict(False, ["bad"], [], []),
            "ollama",
            "d",
            activated=True,
        )
        active_run, project_state = self._update(result)
        self.assertEqual(project_state["last_coder_status"], "rejected")
        self.assertEqual(project_state["failure_count"], 1)
        self.assertEqual(
            project_state["current_blocker"], "coder_proposal_rejected"
        )

    def test_coder_to_dict_marks_applied_false(self) -> None:
        """The machine record always reports applied=false."""
        result = ProposalResult(
            _valid_proposal(),
            ProposalVerdict(True, [], [], []),
            "ollama",
            "d",
            activated=True,
        )
        record = coder_to_dict(result)
        self.assertFalse(record["applied"])
        self.assertEqual(record["validation"]["status"], "valid")

    def test_render_md_includes_sections(self) -> None:
        """The Markdown report contains the required sections."""
        result = ProposalResult(
            _valid_proposal(),
            ProposalVerdict(True, [], [], []),
            "ollama",
            "d",
            activated=True,
        )
        text = render_coder_proposal_md(result)
        for heading in [
            "Coder Proposal",
            "Files To Create",
            "Files To Modify",
            "Implementation Steps",
            "Proposed Tests",
            "Validation Verdict",
            "Owner Review Reasons",
            "Clarifications Needed",
        ]:
            self.assertIn(heading, text)
        self.assertIn("Applied: `false`", text)
        self.assertIn("Decision:", text)

    def test_status_label(self) -> None:
        """Status labels reflect activation and validity."""
        skipped = ProposalResult(
            None, ProposalVerdict(False, [], [], []), "skipped", "d"
        )
        self.assertEqual(coder_status_label(skipped), "not_activated")
        valid = ProposalResult(
            _valid_proposal(),
            ProposalVerdict(True, [], [], []),
            "ollama",
            "d",
            activated=True,
        )
        self.assertEqual(coder_status_label(valid), "valid")

    def test_allowed_target_prefixes(self) -> None:
        """Allowed prefixes cover only app/docs/tests."""
        prefixes = allowed_target_prefixes("apps/demo_app")
        self.assertEqual(
            prefixes,
            (
                "apps/demo_app/app/",
                "apps/demo_app/docs/",
                "apps/demo_app/tests/",
            ),
        )

    def test_report_includes_coder_section(self) -> None:
        """The session report renders a Coder Proposal section."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "reports").mkdir()
            (root / "apps/demo/factory_reports").mkdir(parents=True)
            (root / "reports/ACTIVITY_BLOG.md").write_text(
                "# Activity Blog\n", encoding="utf-8"
            )
            (root / "reports/DAILY_REPORT.md").write_text(
                "# Daily Report\n", encoding="utf-8"
            )
            report_path = append_dry_run_report(
                project_name="demo",
                project_report_root="apps/demo/factory_reports",
                mode="dry_run",
                context_files=["c.md"],
                task_files=["t.md"],
                git_status="clean",
                factory_state={"last_failed_run": None},
                active_run={"resume_from": "review"},
                project_state={
                    "current_task": "DEMO",
                    "current_milestone": "M",
                    "last_completed_checkpoint": None,
                    "failure_count": 0,
                    "current_blocker": None,
                },
                architect_source="ollama",
                architect_detail="m",
                planner_source="ollama",
                planner_detail="m",
                last_role_completed="reporter",
                planning_files=["TASK_EXPANSION.md", "NEXT_ACTION.md"],
                coder_status="rejected",
                coder_proposal_id="CP-001",
                coder_task_id="DEMO-002",
                coder_activated=True,
                coder_warnings=["high risk"],
                coder_blocked_paths=["factory/x.py"],
                coder_files=["coder_proposal.json", "CODER_PROPOSAL.md"],
                repo_root=root,
            )
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("Coder Proposal", report)
            self.assertIn("CP-001", report)
            self.assertIn("factory/x.py", report)
            self.assertIn("Applied: `false`", report)


class WorkbenchSourceTests(unittest.TestCase):
    """The coder sees current app source, never factory-managed/secret files."""

    def test_includes_source_excludes_factory_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "src").mkdir()
            (base / "src" / "game.py").write_text(
                "def apply_move():\n    return True\n", encoding="utf-8"
            )
            (base / "tests").mkdir()
            (base / "tests" / "test_game.py").write_text(
                "from src.game import apply_move\n", encoding="utf-8"
            )
            # Factory-managed + secret + binary files must be excluded.
            (base / "factory_tasks").mkdir()
            (base / "factory_tasks" / "planned_task.json").write_text(
                '{"secret_plan": true}', encoding="utf-8"
            )
            (base / "config").mkdir()
            (base / "config" / "factory.yaml").write_text(
                "mode: apply\n", encoding="utf-8"
            )
            (base / ".env").write_text("TOKEN=supersecret\n", encoding="utf-8")
            (base / "crazy_project.yaml").write_text(
                "id: x\n", encoding="utf-8"
            )

            out = read_workbench_source(str(base))

            self.assertIn("src/game.py", out)
            self.assertIn("def apply_move", out)
            self.assertIn("tests/test_game.py", out)
            self.assertNotIn("planned_task.json", out)
            self.assertNotIn("supersecret", out)
            self.assertNotIn("crazy_project.yaml", out)

    def test_empty_workbench_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(read_workbench_source(tmp), "")

    def test_total_byte_budget_bounds_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "src").mkdir()
            for i in range(50):
                (base / "src" / f"m{i}.py").write_text(
                    "x = 1\n" * 200, encoding="utf-8"
                )
            out = read_workbench_source(
                str(base), max_total_bytes=4000, max_file_bytes=1000
            )
            self.assertLessEqual(len(out), 8000)


if __name__ == "__main__":
    unittest.main()
