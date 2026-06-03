#!/usr/bin/env python3
"""Structured task-contract stage for a Crazy Factory advance.

This module orchestrates the planning contract: asking the Planner model for a
JSON contract, parsing and validating it via :mod:`task_contract`, preserving
an existing owner-authorized contract instead of clobbering it, and writing the
two fixed contract files. The pure parse/validate/render rules live in
:mod:`task_contract`; this module is the I/O and decision layer around them.

Two invariants are upheld here:

- An owner-authorized valid contract is preserved, never regenerated, so owner
  authorization survives later advances until a Coder phase consumes it.
- A contract is never authorized by the factory; ``authorized`` stays ``False``
  for every freshly generated contract regardless of verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ollama_client import OllamaClient, OllamaConnectionError
from planning_roles import RoleResult
from prompt_builder import build_prompt_package
from repo_tools import (
    resolve_repo_path,
    safe_load_json,
    safe_write_json,
    safe_write_text,
)
from contract_review import (
    DECISION_VALID,
    render_contract_review_md,
    review_contract,
)
from task_contract import (
    ContractParseError,
    PlannedTask,
    ValidationVerdict,
    contract_to_dict,
    is_contract_actionable,
    parse_planned_task,
    planned_task_from_record,
    render_planned_task_md,
    validate_planned_task,
)


@dataclass(frozen=True)
class ContractResult:
    """Outcome of requesting and validating a structured task contract.

    Attributes:
        task: Parsed planned task, or ``None`` when none could be produced.
        verdict: Validation verdict for the contract.
        source: ``"ollama"``, ``"fallback"``, or ``"preserved"``.
        detail: Human-readable explanation for reports.
        preserved: ``True`` when an existing owner-authorized valid contract
            was kept and no new contract was generated this run.
    """

    task: PlannedTask | None
    verdict: ValidationVerdict
    source: str
    detail: str
    preserved: bool = False
    decision: str = ""


def request_task_contract(
    *,
    project_name: str,
    project: dict[str, Any],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
    max_lines: int,
    tasks: dict[str, str],
    architect_result: RoleResult,
    planner_result: RoleResult,
) -> ContractResult:
    """Ask Ollama for a JSON task contract and validate it.

    The Planner model is asked to emit a single structured JSON object. The
    response is parsed and validated. When Ollama is unavailable, the response
    is empty, or the contract cannot be parsed, the result is a *rejected*
    contract rather than a trusted one. The factory never authorizes a
    contract on its own; ``authorized`` stays ``False`` regardless of verdict.

    Args:
        project_name: Active application workbench name.
        project: Active project configuration mapping.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        models_config: Parsed ``config/models.yaml`` mapping.
        max_lines: Maximum context lines loaded from each file.
        tasks: Repository-relative task filenames and their content.
        architect_result: Architect expansion handed to the contract step.
        planner_result: Planner next action handed to the contract step.

    Returns:
        Contract result containing the parsed task (or ``None``) and verdict.
    """
    prompt_package = build_prompt_package(
        role="planner",
        project_name=project_name,
        project_context_root=str(project["context_root"]),
        max_lines_per_file=max_lines,
    )
    model = str(models_config["models"]["planner"])
    ollama = factory_config["ollama"]
    client = OllamaClient(
        base_url=str(ollama["base_url"]),
        timeout_seconds=int(ollama["timeout_seconds"]),
        stream=bool(ollama["stream"]),
    )
    instruction = (
        "Return ONLY a single JSON object describing one bounded task "
        "contract. Use these keys: task_id, title, objective, scope (array "
        "of strings), exclusions (array of strings), inputs (array of "
        "strings), acceptance_criteria (array of strings), validation_plan, "
        "risks (array of strings), approval_status. Set approval_status to "
        '"pending". Do not include an authorized field and do not propose an '
        "approved status; only the owner authorizes work. Keep scope small "
        "and bounded, and provide explicit exclusions. Do not reference push, "
        "merge, secrets, or production. Do not generate application code."
    )
    task_context = "\n\n".join(
        f"## Task Source: {path}\n\n{text.rstrip()}"
        for path, text in tasks.items()
    )
    messages = [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": (
                f"{prompt_package.prompt}\n\n"
                f"## Architect Expansion\n\n{architect_result.content}\n\n"
                f"## Planner Next Action\n\n{planner_result.content}\n\n"
                f"{task_context}"
            ),
        },
    ]
    try:
        response = client.chat(model, messages, response_format="json")
    except OllamaConnectionError as exc:
        reason = f"Ollama unavailable; no validated contract produced: {exc}"
        return ContractResult(
            None, ValidationVerdict(False, [reason]), "fallback", reason
        )
    try:
        content = str(response["message"]["content"]).strip()
        if not content:
            raise ValueError("Ollama returned empty contract content")
        task = parse_planned_task(content)
    except (KeyError, TypeError, ValueError, ContractParseError) as exc:
        reason = f"Contract parse failed: {exc}"
        return ContractResult(
            None,
            ValidationVerdict(False, [reason]),
            "ollama",
            f"Planner model `{model}` (unparseable contract)",
        )
    verdict = validate_planned_task(task)
    return ContractResult(task, verdict, "ollama", f"Planner model `{model}`")


def contract_paths(root: Path, project: dict[str, Any]) -> tuple[str, str]:
    """Return the two fixed contract files writable in Phase 3.

    Args:
        root: Absolute repository root.
        project: Active project configuration mapping.

    Returns:
        Repository-relative ``planned_task.json`` and ``PLANNED_TASK.md`` paths.

    Raises:
        RuntimeError: If the task directory escapes the project workbench.
    """
    project_root = resolve_repo_path(str(project["root"]), root)
    task_root = resolve_repo_path(str(project["task_root"]), root)
    if task_root != project_root and project_root not in task_root.parents:
        raise RuntimeError("Task root must stay inside the project workbench")
    return (
        str(Path(str(project["task_root"])) / "planned_task.json"),
        str(Path(str(project["task_root"])) / "PLANNED_TASK.md"),
    )


def load_existing_contract(
    contract_json_path: str, root: Path
) -> dict[str, Any] | None:
    """Load an existing ``planned_task.json`` record if one is present.

    Args:
        contract_json_path: Repository-relative contract path.
        root: Absolute repository root.

    Returns:
        Parsed contract mapping, or ``None`` when no readable contract exists.
    """
    target = resolve_repo_path(contract_json_path, root)
    if not target.is_file():
        return None
    try:
        return safe_load_json(contract_json_path, root)
    except ValueError:
        # A corrupt or non-object contract is treated as absent so the advance
        # can regenerate it rather than fail.
        return None


def run_contract_stage(
    *,
    project_name: str,
    root: Path,
    project: dict[str, Any],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
    max_lines: int,
    tasks: dict[str, str],
    architect_result: RoleResult,
    planner_result: RoleResult,
) -> tuple[ContractResult, str, str]:
    """Produce or preserve the structured task contract for this advance.

    If an owner-authorized valid contract already exists, it is preserved and
    no new contract is generated, so owner authorization survives later advances
    until a Coder phase consumes it. Otherwise a fresh contract is requested,
    validated, and written to the two fixed contract files.

    Args:
        project_name: Active application workbench name.
        root: Absolute repository root.
        project: Active project configuration mapping.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        models_config: Parsed ``config/models.yaml`` mapping.
        max_lines: Maximum context lines loaded from each file.
        tasks: Repository-relative task filenames and their content.
        architect_result: Architect expansion handed to the contract step.
        planner_result: Planner next action handed to the contract step.

    Returns:
        Contract result and the two repository-relative contract paths.
    """
    task_root = str(project["task_root"])
    contract_json_path, planned_task_path = contract_paths(root, project)

    existing = load_existing_contract(contract_json_path, root)
    if existing is not None and is_contract_actionable(existing):
        # Preserve the owner-authorized JSON untouched, but refresh the
        # owner-facing Markdown so it stops claiming approval is still
        # required and instead reflects the authorized status.
        preserved_task = planned_task_from_record(existing)
        result = ContractResult(
            task=preserved_task,
            verdict=ValidationVerdict(True, []),
            source="preserved",
            detail=(
                "Owner-authorized valid contract preserved; no new contract "
                "was generated this run."
            ),
            preserved=True,
        )
        safe_write_text(
            planned_task_path,
            render_planned_task_md(
                preserved_task,
                result.verdict,
                source=result.source,
                detail=result.detail,
                authorized=True,
            ),
            repo_root=root,
            allowed_roots=[task_root],
        )
        return result, contract_json_path, planned_task_path

    result = request_task_contract(
        project_name=project_name,
        project=project,
        factory_config=factory_config,
        models_config=models_config,
        max_lines=max_lines,
        tasks=tasks,
        architect_result=architect_result,
        planner_result=planner_result,
    )

    # AI-reviewed decision: a deterministic safety floor first (never relaxed),
    # then the reviewer interprets/repairs safe completeness gaps, then a
    # deterministic repair fallback, then an owner-review checklist. This is
    # what stops a safe-but-incomplete plan from churning to a hard reject.
    record: dict[str, Any]
    if result.task is not None:
        review = review_contract(
            result.task,
            context=f"{architect_result.content}\n\n{planner_result.content}",
            models_config=models_config,
            factory_config=factory_config,
        )
        verdict = ValidationVerdict(valid=review.valid, reasons=review.reasons)
        result = ContractResult(
            task=review.task,
            verdict=verdict,
            source=result.source,
            detail=(
                f"Contract review: {review.decision} (via {review.source}). "
                + result.detail
            ),
            decision=review.decision,
        )
        record = contract_to_dict(
            review.task,
            verdict,
            result.source,
            status=review.status,
            decision=review.decision,
            checklist=review.checklist,
        )
        # Write the owner checklist/checkpoint whenever the decision is not a
        # clean valid (repaired, escalated, or rejected) for transparency.
        if review.decision != DECISION_VALID:
            safe_write_text(
                f"{task_root}/CONTRACT_REVIEW.md",
                render_contract_review_md(review),
                repo_root=root,
                allowed_roots=[task_root],
            )
    else:
        record = contract_to_dict(result.task, result.verdict, result.source)

    safe_write_json(
        contract_json_path,
        record,
        repo_root=root,
        allowed_roots=[task_root],
    )
    safe_write_text(
        planned_task_path,
        render_planned_task_md(
            result.task,
            result.verdict,
            source=result.source,
            detail=result.detail,
        ),
        repo_root=root,
        allowed_roots=[task_root],
    )
    return result, contract_json_path, planned_task_path


def contract_status_label(contract_result: ContractResult) -> str:
    """Return the reporting label for a contract outcome.

    Args:
        contract_result: Contract result for the current advance.

    Returns:
        ``"authorized"`` when preserved, otherwise ``"valid"`` or
        ``"rejected"``.
    """
    if contract_result.preserved:
        return "authorized"
    # Prefer the reviewer's graded decision over a bare valid/rejected so the
    # report distinguishes "needs_owner_review"/"repair" from a hard reject.
    if contract_result.decision:
        return contract_result.decision
    return "valid" if contract_result.verdict.valid else "rejected"
