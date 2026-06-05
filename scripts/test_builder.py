#!/usr/bin/env python3
"""Phase 6 Test Builder for Crazy Factory.

The Test Builder is the validation-planning worker. Given an owner-authorized,
valid contract and a valid coder proposal, it asks the local model for a
structured test plan: the checks that should prove the work, the expected
outcome, and risk notes. It validates that plan — in particular that every
``required_check`` is an allowlisted command (see :mod:`validation_runner`) —
so the validation runner is never asked to execute something unsafe.

The Test Builder proposes checks; it does not run them. Execution belongs to
:mod:`validation_runner`, gated by owner policy. A malformed or unavailable
model response yields a *rejected* plan, never a fake-valid one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from contract_stage import load_existing_contract
from json_parsing import coerce_str, coerce_str_list, strip_code_fence
from ollama_client import OllamaClient, OllamaConnectionError
from prompt_builder import build_prompt_package
from proposal_applier import is_proposal_valid
from repo_tools import resolve_repo_path, safe_write_json, safe_write_text
from task_contract import is_contract_actionable
from validation_runner import is_command_allowed


class TestPlanParseError(ValueError):
    """Raised when test-builder output cannot be parsed into a test plan."""

    __test__ = False  # not a pytest test class despite the TestPlan* name


@dataclass(frozen=True)
class TestPlan:
    """A structured, owner-reviewable validation plan.

    Attributes:
        test_plan_id: Stable identifier for the test plan.
        task_id: Backing contract task identifier.
        required_checks: Commands that should be run to prove the work.
        manual_checks: Checks the owner must perform by hand.
        expected_outcome: What success looks like.
        risk_notes: Relevant risk notes for the change.
    """

    test_plan_id: str
    task_id: str
    required_checks: list[str] = field(default_factory=list)
    manual_checks: list[str] = field(default_factory=list)
    expected_outcome: str = ""
    risk_notes: str = ""


@dataclass(frozen=True)
class TestPlanVerdict:
    """Outcome of validating a :class:`TestPlan`.

    Attributes:
        valid: Whether the plan satisfies every rule.
        reasons: Human-readable rejection reasons. Empty when ``valid``.
        warnings: Non-fatal concerns worth surfacing to the owner.
    """

    __test__ = False  # not a pytest test class despite the TestPlan* name
    valid: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TestPlanResult:
    """Outcome of requesting and validating a test plan.

    Attributes:
        plan: Parsed test plan, or ``None`` when none was produced.
        verdict: Validation verdict for the plan.
        source: ``"ollama"``, ``"fallback"``, or ``"skipped"``.
        detail: Human-readable explanation for reports.
        activated: ``True`` when the contract+proposal gate passed.
    """

    __test__ = False  # not a pytest test class despite the TestPlan* name
    plan: TestPlan | None
    verdict: TestPlanVerdict
    source: str
    detail: str
    activated: bool = False


def parse_test_plan(raw: str) -> TestPlan:
    """Parse a test-builder JSON plan into a :class:`TestPlan`.

    Args:
        raw: Raw model output expected to contain a single JSON object.

    Returns:
        Parsed test plan.

    Raises:
        TestPlanParseError: If the text is not a JSON object.
    """
    text = strip_code_fence(raw)
    if not text:
        raise TestPlanParseError("Test builder returned empty content")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TestPlanParseError(
            f"Test plan is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise TestPlanParseError("Test plan JSON must be an object")
    return TestPlan(
        test_plan_id=coerce_str(data.get("test_plan_id")),
        task_id=coerce_str(data.get("task_id")),
        required_checks=coerce_str_list(data.get("required_checks")),
        manual_checks=coerce_str_list(data.get("manual_checks")),
        expected_outcome=coerce_str(data.get("expected_outcome")),
        risk_notes=coerce_str(data.get("risk_notes")),
    )


def validate_test_plan(
    plan: TestPlan | None,
    *,
    contract_actionable: bool,
    proposal_valid: bool,
) -> TestPlanVerdict:
    """Validate a test plan against the Phase 6 rules.

    Args:
        plan: Parsed test plan, or ``None`` when none was produced.
        contract_actionable: Whether the backing contract is authorized+valid.
        proposal_valid: Whether the backing coder proposal is valid.

    Returns:
        Validation verdict over all rules.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    if not contract_actionable:
        reasons.append("Backing contract is not authorized and valid")
    if not proposal_valid:
        reasons.append("Backing coder proposal is not valid")
    if plan is None:
        reasons.append("No test plan was produced")
        return TestPlanVerdict(False, reasons, warnings)

    for name in ("test_plan_id", "task_id"):
        if not coerce_str(getattr(plan, name)):
            reasons.append(f"Missing or empty required field: {name}")

    if not plan.required_checks and not plan.manual_checks:
        reasons.append("Test plan defines no checks")

    # Every automated check must be an allowlisted command so the validation
    # runner is never handed something unsafe.
    blocked = [c for c in plan.required_checks if not is_command_allowed(c)]
    if blocked:
        reasons.append(
            "Test plan lists non-allowlisted commands: " + ", ".join(blocked)
        )

    if not plan.expected_outcome:
        warnings.append("Test plan has no expected_outcome")

    return TestPlanVerdict(
        valid=not reasons, reasons=reasons, warnings=warnings
    )


def test_plan_status_label(result: TestPlanResult) -> str:
    """Return the reporting label for a test-plan outcome.

    Args:
        result: Test-plan result for the current advance.

    Returns:
        ``"not_activated"``, ``"valid"``, or ``"rejected"``.
    """
    if not result.activated:
        return "not_activated"
    return "valid" if result.verdict.valid else "rejected"


def test_plan_to_dict(result: TestPlanResult) -> dict[str, Any]:
    """Build the machine-readable ``test_plan.json`` record.

    Args:
        result: Test-plan result to serialize.

    Returns:
        JSON-serializable test-plan record.
    """
    plan = result.plan
    return {
        "test_plan_id": plan.test_plan_id if plan else None,
        "task_id": plan.task_id if plan else None,
        "required_checks": plan.required_checks if plan else [],
        "manual_checks": plan.manual_checks if plan else [],
        "expected_outcome": plan.expected_outcome if plan else None,
        "risk_notes": plan.risk_notes if plan else None,
        "activated": result.activated,
        "validation": {
            "status": test_plan_status_label(result),
            "source": result.source,
            "reasons": list(result.verdict.reasons),
            "warnings": list(result.verdict.warnings),
        },
    }


def _bullets(items: list[str]) -> list[str]:
    """Render a list as Markdown bullets, or a placeholder when empty."""
    return [f"- {item}" for item in items] if items else ["_None._"]


def render_test_plan_md(result: TestPlanResult) -> str:
    """Render a human-readable ``TEST_PLAN.md`` record.

    Args:
        result: Test-plan result to render.

    Returns:
        Markdown document describing the test plan and its verdict.
    """
    plan = result.plan
    status = test_plan_status_label(result)
    lines = [
        "# Test Plan",
        "",
        "## Status",
        "",
        f"- Source: `{result.source}`",
        f"- Detail: {result.detail}",
        f"- Activated: `{str(result.activated).lower()}`",
        f"- Verdict: `{status}`",
        "",
    ]
    if plan is None:
        lines.extend(["## Plan", "", "No test plan was produced.", ""])
    else:
        lines.extend(
            [
                "## Plan",
                "",
                f"- Test plan ID: `{plan.test_plan_id}`",
                f"- Task ID: `{plan.task_id}`",
                f"- Expected outcome: {plan.expected_outcome or '_None._'}",
                f"- Risk notes: {plan.risk_notes or '_None._'}",
                "",
                "## Required Checks",
                "",
                *_bullets(plan.required_checks),
                "",
                "## Manual Checks",
                "",
                *_bullets(plan.manual_checks),
                "",
            ]
        )
    lines.extend(["## Validation Verdict", "", "### Reasons", ""])
    lines.extend(_bullets(result.verdict.reasons))
    lines.extend(["", "### Warnings", ""])
    lines.extend(_bullets(result.verdict.warnings))
    lines.append("")
    return "\n".join(lines)


def test_plan_paths(root: Path, project: dict[str, Any]) -> tuple[str, str]:
    """Return the two fixed test-plan files writable in Phase 6.

    Args:
        root: Absolute repository root.
        project: Active project configuration mapping.

    Returns:
        Repository-relative ``test_plan.json`` and ``TEST_PLAN.md`` paths.

    Raises:
        RuntimeError: If the task directory escapes the project workbench.
    """
    project_root = resolve_repo_path(str(project["root"]), root)
    task_root = resolve_repo_path(str(project["task_root"]), root)
    if task_root != project_root and project_root not in task_root.parents:
        raise RuntimeError("Task root must stay inside the project workbench")
    base = Path(str(project["task_root"]))
    return (str(base / "test_plan.json"), str(base / "TEST_PLAN.md"))


def request_test_plan(
    *,
    project_name: str,
    project: dict[str, Any],
    contract_record: dict[str, Any],
    proposal_record: dict[str, Any],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
    max_lines: int,
) -> TestPlanResult:
    """Ask the test-builder model for a test plan and validate it.

    Args:
        project_name: Active application workbench name.
        project: Active project configuration mapping.
        contract_record: The authorized, valid contract record.
        proposal_record: The valid coder proposal record.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        models_config: Parsed ``config/models.yaml`` mapping.
        max_lines: Maximum context lines loaded from each file.

    Returns:
        Test-plan result with ``activated=True``.
    """
    prompt_package = build_prompt_package(
        role="test_builder",
        project_name=project_name,
        project_context_root=str(project["context_root"]),
        max_lines_per_file=max_lines,
    )
    model = str(models_config["models"]["test_builder"])
    ollama = factory_config["ollama"]
    client = OllamaClient(
        base_url=str(ollama["base_url"]),
        timeout_seconds=int(ollama["timeout_seconds"]),
        stream=bool(ollama["stream"]),
    )
    instruction = (
        "Return ONLY a single JSON object describing a validation test plan "
        "for THIS ONE task. Use keys: test_plan_id, task_id, required_checks "
        "(array of shell commands), manual_checks (array of strings), "
        "expected_outcome, risk_notes. required_checks MUST be limited to "
        "safe, read-only validation commands such as 'python3 -m pytest', "
        "'pytest', 'ruff check', or 'mypy'. Never include git, network, "
        "install, or destructive commands.\n\n"
        "SCOPE every check to ONLY the files this task creates or modifies "
        "(listed under 'Work To Validate'). Run the specific test file(s) for "
        "this task (e.g. 'python3 -m pytest tests/test_x.py'), NOT the whole "
        "suite. If you lint or type-check, target only this task's files "
        "(e.g. 'ruff check src/x.py') — NEVER the whole project, so an "
        "unrelated or not-yet-written file cannot block this task. Prefer the "
        "smallest set of checks that proves THIS task's increment works. "
        "Whole-project checks belong only to an explicit final 'run all tests' "
        "task, not to an incremental one."
    )
    proposal_summary = json.dumps(
        {
            "task_id": contract_record.get("task_id"),
            "proposal_id": proposal_record.get("proposal_id"),
            "files_to_create": proposal_record.get("files_to_create"),
            "files_to_modify": proposal_record.get("files_to_modify"),
            "acceptance_criteria": contract_record.get("acceptance_criteria"),
        },
        indent=2,
    )
    messages = [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": (
                f"{prompt_package.prompt}\n\n"
                f"## Work To Validate\n\n{proposal_summary}\n"
            ),
        },
    ]
    try:
        response = client.chat(model, messages, response_format="json")
    except OllamaConnectionError as exc:
        reason = f"Ollama unavailable; no validated test plan produced: {exc}"
        return TestPlanResult(
            None,
            TestPlanVerdict(False, [reason]),
            "fallback",
            reason,
            activated=True,
        )
    try:
        content = str(response["message"]["content"]).strip()
        if not content:
            raise ValueError("Ollama returned empty test plan content")
        plan = parse_test_plan(content)
    except (KeyError, TypeError, ValueError, TestPlanParseError) as exc:
        reason = f"Test plan parse failed: {exc}"
        return TestPlanResult(
            None,
            TestPlanVerdict(False, [reason]),
            "ollama",
            f"Test builder model `{model}` (unparseable plan)",
            activated=True,
        )
    verdict = validate_test_plan(
        plan, contract_actionable=True, proposal_valid=True
    )
    return TestPlanResult(
        plan,
        verdict,
        "ollama",
        f"Test builder model `{model}`",
        activated=True,
    )


def run_test_builder_stage(
    *,
    project_name: str,
    root: Path,
    project: dict[str, Any],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
    max_lines: int,
    contract_json_path: str,
    proposal_json_path: str,
) -> tuple[TestPlanResult, str, str]:
    """Build a test plan only for an authorized contract and valid proposal.

    When the gate is not satisfied the Test Builder is skipped: no model call
    and no artifacts. Otherwise a test plan is requested, validated, and
    written to the two fixed test-plan files. It never executes checks.

    Args:
        project_name: Active application workbench name.
        root: Absolute repository root.
        project: Active project configuration mapping.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        models_config: Parsed ``config/models.yaml`` mapping.
        max_lines: Maximum context lines loaded from each file.
        contract_json_path: Repository-relative authorized contract path.
        proposal_json_path: Repository-relative coder proposal path.

    Returns:
        Test-plan result and the test-plan JSON and Markdown paths.
    """
    task_root = str(project["task_root"])
    plan_json_path, plan_md_path = test_plan_paths(root, project)

    contract_record = load_existing_contract(contract_json_path, root)
    proposal_record = load_existing_contract(proposal_json_path, root)
    contract_ok = contract_record is not None and is_contract_actionable(
        contract_record
    )
    proposal_ok = is_proposal_valid(proposal_record)

    if not (contract_ok and proposal_ok):
        result = TestPlanResult(
            None,
            TestPlanVerdict(
                False, ["Test builder not activated: gate not satisfied"]
            ),
            "skipped",
            "Contract/proposal gate not satisfied; no test plan generated.",
            activated=False,
        )
        return result, plan_json_path, plan_md_path

    assert contract_record is not None
    assert proposal_record is not None
    result = request_test_plan(
        project_name=project_name,
        project=project,
        contract_record=contract_record,
        proposal_record=proposal_record,
        factory_config=factory_config,
        models_config=models_config,
        max_lines=max_lines,
    )
    safe_write_json(
        plan_json_path,
        test_plan_to_dict(result),
        repo_root=root,
        allowed_roots=[task_root],
    )
    safe_write_text(
        plan_md_path,
        render_test_plan_md(result),
        repo_root=root,
        allowed_roots=[task_root],
    )
    return result, plan_json_path, plan_md_path
