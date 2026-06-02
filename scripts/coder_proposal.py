#!/usr/bin/env python3
"""Phase 4A authorized Coder proposal engine for Crazy Factory.

This module introduces the first Coder role. The Coder may *think* and
*propose*; it may not execute. Given an owner-authorized, valid task contract,
it asks the local coder model for a structured implementation proposal, parses
and validates that proposal against strict safety rules, and writes proposal
artifacts and reports. It never writes application code, applies patches, runs
tests, or touches git.

Hard boundaries (Phase 3 invariants preserved):

- The Coder activates only when ``planned_task.json`` is owner-authorized and
  revalidates as ``valid`` (see :func:`task_contract.is_contract_actionable`).
- Proposals may only target ``apps/<project>/app|docs|tests``.
- Dangerous paths, secret-like material, destructive commands, empty
  proposals, and proposals over the file limit are rejected.
- When the model is unavailable or output is malformed, the result is a
  *rejected* proposal, never a fake-valid one. The run still exits cleanly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from contract_stage import load_existing_contract
from json_parsing import coerce_str, coerce_str_list, strip_code_fence
from ollama_client import OllamaClient, OllamaConnectionError
from prompt_builder import build_prompt_package
from repo_tools import resolve_repo_path, safe_write_json, safe_write_text
from task_contract import is_contract_actionable

# Top-level directories a proposal may never target. The allow-list of
# app/docs/tests targets already excludes these, but they are named explicitly
# so a violation produces a clear, auditable reason.
FORBIDDEN_PATH_PREFIXES: tuple[str, ...] = (
    "factory/",
    ".git/",
    ".github/",
    "config/",
    "cron/",
    "bin/",
    "logs/",
    "reports/",
    "contexts/",
    "state/",
    "checkpoints/",
)

# Secret-like markers; any appearance in a path or instruction rejects the
# proposal. Substring matching is intentionally aggressive for this
# trust-building phase.
SECRET_MARKERS: tuple[str, ...] = (
    ".env",
    "secret",
    "credential",
    "token",
    "password",
    "private key",
    "api key",
)

# Destructive or out-of-bounds operations a proposal may never describe.
DANGEROUS_COMMANDS: tuple[str, ...] = (
    "rm -rf",
    "rewrite history",
    "history rewrite",
    "force push",
    "force-push",
    "force merge",
    "git reset",
    "reset --hard",
    "git push",
    "git merge",
    "sudo",
)

RISK_LEVELS: frozenset[str] = frozenset({"low", "medium", "high"})


class ProposalParseError(ValueError):
    """Raised when coder output cannot be parsed into a proposal."""


@dataclass(frozen=True)
class CoderProposal:
    """A structured, owner-reviewable implementation proposal.

    Attributes:
        proposal_id: Stable identifier for the proposal.
        task_id: Identifier of the authorized contract this proposal serves.
        summary: One-line description of the proposed work.
        objective: The outcome the proposal aims to achieve.
        files_to_create: Repository-relative files the work would create.
        files_to_modify: Repository-relative files the work would modify.
        files_to_delete: Repository-relative files the work would delete.
        proposed_tests: Tests the work would add or run.
        implementation_steps: Ordered description of the proposed work.
        estimated_risk: Coarse risk estimate (low/medium/high).
        notes: Free-form notes for the owner.
    """

    proposal_id: str
    task_id: str
    summary: str
    objective: str
    files_to_create: list[str] = field(default_factory=list)
    files_to_modify: list[str] = field(default_factory=list)
    files_to_delete: list[str] = field(default_factory=list)
    proposed_tests: list[str] = field(default_factory=list)
    implementation_steps: list[str] = field(default_factory=list)
    estimated_risk: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ProposalVerdict:
    """Outcome of validating a :class:`CoderProposal`.

    Attributes:
        valid: Whether the proposal satisfies every safety rule.
        reasons: Human-readable rejection reasons. Empty when ``valid``.
        blocked_paths: Specific paths that violated the target boundary.
        warnings: Non-fatal concerns worth surfacing to the owner.
    """

    valid: bool
    reasons: list[str] = field(default_factory=list)
    blocked_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProposalResult:
    """Outcome of requesting and validating a coder proposal.

    Attributes:
        proposal: Parsed proposal, or ``None`` when none was produced.
        verdict: Validation verdict for the proposal.
        source: ``"ollama"``, ``"fallback"``, or ``"skipped"``.
        detail: Human-readable explanation for reports.
        activated: ``True`` when an authorized contract activated the Coder.
    """

    proposal: CoderProposal | None
    verdict: ProposalVerdict
    source: str
    detail: str
    activated: bool = False


def parse_coder_proposal(raw: str) -> CoderProposal:
    """Parse a coder JSON proposal into a :class:`CoderProposal`.

    Args:
        raw: Raw coder output expected to contain a single JSON object.

    Returns:
        Parsed proposal.

    Raises:
        ProposalParseError: If the text is not a JSON object.
    """
    text = strip_code_fence(raw)
    if not text:
        raise ProposalParseError("Coder returned empty proposal content")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProposalParseError(f"Proposal is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProposalParseError("Proposal JSON must be an object")
    return CoderProposal(
        proposal_id=coerce_str(data.get("proposal_id")),
        task_id=coerce_str(data.get("task_id")),
        summary=coerce_str(data.get("summary")),
        objective=coerce_str(data.get("objective")),
        files_to_create=coerce_str_list(data.get("files_to_create")),
        files_to_modify=coerce_str_list(data.get("files_to_modify")),
        files_to_delete=coerce_str_list(data.get("files_to_delete")),
        proposed_tests=coerce_str_list(data.get("proposed_tests")),
        implementation_steps=coerce_str_list(data.get("implementation_steps")),
        estimated_risk=coerce_str(data.get("estimated_risk")),
        notes=coerce_str(data.get("notes")),
    )


def allowed_target_prefixes(project_name: str) -> tuple[str, ...]:
    """Return the only repository prefixes a proposal may target.

    Args:
        project_name: Active application workbench name.

    Returns:
        Allowed ``app``, ``docs``, and ``tests`` path prefixes.
    """
    base = f"apps/{project_name}"
    return (f"{base}/app/", f"{base}/docs/", f"{base}/tests/")


def _proposal_paths(proposal: CoderProposal) -> list[str]:
    """Return every file path a proposal would create, modify, or delete.

    Args:
        proposal: Proposal to inspect.

    Returns:
        Combined list of proposed file paths.
    """
    return [
        *proposal.files_to_create,
        *proposal.files_to_modify,
        *proposal.files_to_delete,
    ]


def _is_allowed_path(path: str, allowed_prefixes: tuple[str, ...]) -> bool:
    """Report whether one proposed path is inside an allowed target.

    Absolute paths and parent-traversal are rejected outright; otherwise the
    normalized path must sit beneath an allowed prefix and name a file.

    Args:
        path: Repository-relative path proposed by the model.
        allowed_prefixes: Allowed target prefixes for the active project.

    Returns:
        ``True`` only when the path is a safe, in-bounds file target.
    """
    if not path or path.startswith("/"):
        return False
    normalized = PurePosixPath(path)
    if ".." in normalized.parts:
        return False
    as_text = normalized.as_posix()
    if as_text.endswith("/"):
        return False
    return any(as_text.startswith(prefix) for prefix in allowed_prefixes)


def _scan_markers(haystack: str, markers: tuple[str, ...]) -> list[str]:
    """Return the markers that appear in lowercased text.

    Args:
        haystack: Combined text to scan.
        markers: Substrings to look for.

    Returns:
        Sorted list of matched markers.
    """
    lowered = haystack.lower()
    return sorted({m for m in markers if m in lowered})


def validate_proposal(
    proposal: CoderProposal | None,
    *,
    project_name: str,
    contract_actionable: bool,
    max_files: int,
    contract_task_id: str = "",
) -> ProposalVerdict:
    """Validate a coder proposal against the Phase 4 safety rules.

    Args:
        proposal: Parsed proposal, or ``None`` when none was produced.
        project_name: Active application workbench name.
        contract_actionable: Whether the backing contract is authorized+valid.
        max_files: Maximum number of files a proposal may touch.
        contract_task_id: ``task_id`` of the backing contract, for matching.

    Returns:
        Validation verdict over all safety rules.
    """
    reasons: list[str] = []
    blocked: list[str] = []
    warnings: list[str] = []

    # Rules 1-3: the backing contract must be authorized and valid.
    if not contract_actionable:
        reasons.append(
            "Backing contract is not authorized and valid; Coder may not act"
        )
    if proposal is None:
        reasons.append("No proposal was produced")
        return ProposalVerdict(False, reasons, blocked, warnings)

    paths = _proposal_paths(proposal)

    # Rule 7: an empty proposal proposes no work.
    if not paths:
        reasons.append("Proposal targets no files (empty proposal)")

    # Rule 4 + allowed targets: every path must sit under app/docs/tests and
    # never under a protected top-level directory.
    allowed = allowed_target_prefixes(project_name)
    protected: list[str] = []
    for path in paths:
        normalized = path.lstrip("./").lower()
        if any(normalized.startswith(p) for p in FORBIDDEN_PATH_PREFIXES):
            protected.append(path)
            blocked.append(path)
        elif not _is_allowed_path(path, allowed):
            blocked.append(path)
    if protected:
        reasons.append(
            "Proposal targets protected directories: " + ", ".join(protected)
        )
    out_of_bounds = [p for p in blocked if p not in protected]
    if out_of_bounds:
        reasons.append(
            "Proposal targets paths outside "
            f"apps/{project_name}/(app|docs|tests): "
            + ", ".join(out_of_bounds)
        )

    # Rule 5: no secret-like material in paths or instructions.
    text_blob = " ".join(
        [
            proposal.summary,
            proposal.objective,
            proposal.notes,
            *paths,
            *proposal.proposed_tests,
            *proposal.implementation_steps,
        ]
    )
    secret_hits = _scan_markers(text_blob, SECRET_MARKERS)
    if secret_hits:
        reasons.append(
            "Proposal references secret-like material: "
            + ", ".join(secret_hits)
        )

    # Rule 6: no destructive or out-of-bounds operations.
    command_hits = _scan_markers(text_blob, DANGEROUS_COMMANDS)
    if command_hits:
        reasons.append(
            "Proposal references forbidden operations: "
            + ", ".join(command_hits)
        )

    # Rule 8: stay within the configured per-run file budget.
    if len(paths) > max_files:
        reasons.append(
            f"Proposal touches {len(paths)} files, over the limit of "
            f"{max_files}"
        )

    risk = proposal.estimated_risk.lower()
    if risk not in RISK_LEVELS:
        warnings.append(
            f"Unrecognized estimated_risk: {proposal.estimated_risk!r}"
        )
    elif risk == "high":
        warnings.append("Estimated risk is high; close owner review advised")
    if (
        contract_task_id
        and proposal.task_id
        and proposal.task_id != contract_task_id
    ):
        warnings.append(
            f"Proposal task_id {proposal.task_id!r} does not match contract "
            f"task_id {contract_task_id!r}"
        )

    return ProposalVerdict(
        valid=not reasons,
        reasons=reasons,
        blocked_paths=blocked,
        warnings=warnings,
    )


def coder_to_dict(result: ProposalResult) -> dict[str, Any]:
    """Build the machine-readable ``coder_proposal.json`` record.

    The record is informational only. No downstream worker may act on it in
    Phase 4; application of proposals is deferred to a later, separately
    approved phase.

    Args:
        result: Proposal result to serialize.

    Returns:
        JSON-serializable proposal record.
    """
    proposal = result.proposal
    status = coder_status_label(result)
    return {
        "proposal_id": proposal.proposal_id if proposal else None,
        "task_id": proposal.task_id if proposal else None,
        "summary": proposal.summary if proposal else None,
        "objective": proposal.objective if proposal else None,
        "files_to_create": proposal.files_to_create if proposal else [],
        "files_to_modify": proposal.files_to_modify if proposal else [],
        "files_to_delete": proposal.files_to_delete if proposal else [],
        "proposed_tests": proposal.proposed_tests if proposal else [],
        "implementation_steps": (
            proposal.implementation_steps if proposal else []
        ),
        "estimated_risk": proposal.estimated_risk if proposal else None,
        "notes": proposal.notes if proposal else None,
        "activated": result.activated,
        # The Coder never applies or authorizes anything in Phase 4.
        "applied": False,
        "validation": {
            "status": status,
            "source": result.source,
            "reasons": list(result.verdict.reasons),
            "blocked_paths": list(result.verdict.blocked_paths),
            "warnings": list(result.verdict.warnings),
        },
    }


def coder_status_label(result: ProposalResult) -> str:
    """Return the reporting label for a proposal outcome.

    Args:
        result: Proposal result for the current tick.

    Returns:
        ``"not_activated"``, ``"valid"``, or ``"rejected"``.
    """
    if not result.activated:
        return "not_activated"
    return "valid" if result.verdict.valid else "rejected"


def _bullets(items: list[str]) -> list[str]:
    """Render a list as Markdown bullets, or a placeholder when empty."""
    return [f"- {item}" for item in items] if items else ["_None._"]


def render_coder_proposal_md(result: ProposalResult) -> str:
    """Render a human-readable ``CODER_PROPOSAL.md`` record.

    Args:
        result: Proposal result to render.

    Returns:
        Markdown document describing the proposal and its verdict.
    """
    status = coder_status_label(result)
    proposal = result.proposal
    verdict = result.verdict
    lines = [
        "# Coder Proposal",
        "",
        "## Status",
        "",
        f"- Source: `{result.source}`",
        f"- Detail: {result.detail}",
        f"- Activated: `{str(result.activated).lower()}`",
        f"- Verdict: `{status}`",
        "- Applied: `false` (Phase 4 proposes only; no files are written)",
        "",
    ]
    if proposal is None:
        lines.extend(
            ["## Proposal", "", "No proposal was produced this run.", ""]
        )
    else:
        lines.extend(
            [
                "## Proposal Summary",
                "",
                f"- Proposal ID: `{proposal.proposal_id}`",
                f"- Task ID: `{proposal.task_id}`",
                f"- Estimated risk: `{proposal.estimated_risk}`",
                "",
                "## Objective",
                "",
                proposal.objective or "_None provided._",
                "",
                "## Summary",
                "",
                proposal.summary or "_None provided._",
                "",
                "## Files To Create",
                "",
                *_bullets(proposal.files_to_create),
                "",
                "## Files To Modify",
                "",
                *_bullets(proposal.files_to_modify),
                "",
                "## Files To Delete",
                "",
                *_bullets(proposal.files_to_delete),
                "",
                "## Implementation Steps",
                "",
                *_bullets(proposal.implementation_steps),
                "",
                "## Proposed Tests",
                "",
                *_bullets(proposal.proposed_tests),
                "",
            ]
        )
    lines.extend(["## Validation Verdict", "", f"- Valid: `{verdict.valid}`"])
    lines.append("")
    lines.append("### Reasons")
    lines.append("")
    lines.extend(_bullets(verdict.reasons))
    lines.extend(["", "### Warnings", ""])
    lines.extend(_bullets(verdict.warnings))
    lines.extend(["", "### Blocked Paths", ""])
    lines.extend(_bullets(verdict.blocked_paths))
    lines.append("")
    return "\n".join(lines)


def coder_proposal_paths(
    root: Path, project: dict[str, Any]
) -> tuple[str, str]:
    """Return the two fixed proposal files writable in Phase 4.

    Args:
        root: Absolute repository root.
        project: Active project configuration mapping.

    Returns:
        Repository-relative ``coder_proposal.json`` and ``CODER_PROPOSAL.md``
        paths.

    Raises:
        RuntimeError: If the task directory escapes the project workbench.
    """
    project_root = resolve_repo_path(str(project["root"]), root)
    task_root = resolve_repo_path(str(project["task_root"]), root)
    if task_root != project_root and project_root not in task_root.parents:
        raise RuntimeError("Task root must stay inside the project workbench")
    return (
        str(Path(str(project["task_root"])) / "coder_proposal.json"),
        str(Path(str(project["task_root"])) / "CODER_PROPOSAL.md"),
    )


def request_coder_proposal(
    *,
    project_name: str,
    project: dict[str, Any],
    contract_record: dict[str, Any],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
    max_lines: int,
    max_files: int,
) -> ProposalResult:
    """Ask the coder model for a proposal and validate it.

    The coder model is asked to emit a single JSON proposal. When Ollama is
    unavailable, the response is empty, or the proposal cannot be parsed, the
    result is a *rejected* proposal rather than a trusted one. No files are
    written, no code is generated, and nothing is executed.

    Args:
        project_name: Active application workbench name.
        project: Active project configuration mapping.
        contract_record: The authorized, valid contract record.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        models_config: Parsed ``config/models.yaml`` mapping.
        max_lines: Maximum context lines loaded from each file.
        max_files: Maximum number of files a proposal may touch.

    Returns:
        Proposal result. ``activated`` is always ``True`` here.
    """
    prompt_package = build_prompt_package(
        role="coder",
        project_name=project_name,
        project_context_root=str(project["context_root"]),
        max_lines_per_file=max_lines,
    )
    model = str(models_config["models"]["coder"])
    ollama = factory_config["ollama"]
    client = OllamaClient(
        base_url=str(ollama["base_url"]),
        timeout_seconds=int(ollama["timeout_seconds"]),
        stream=bool(ollama["stream"]),
    )
    contract_task_id = coerce_str(contract_record.get("task_id"))
    allowed = ", ".join(allowed_target_prefixes(project_name))
    instruction = (
        "Return ONLY a single JSON object describing an implementation "
        "proposal. Do NOT write code; describe the plan. Use these keys: "
        "proposal_id, task_id, summary, objective, files_to_create (array), "
        "files_to_modify (array), files_to_delete (array), proposed_tests "
        "(array), implementation_steps (array), estimated_risk "
        "(low|medium|high), notes. Every file path must be under one of: "
        f"{allowed}. Touch at most {max_files} files. Never reference "
        "secrets, credentials, tokens, or destructive/git operations "
        "(push, merge, reset, rm -rf, sudo). Do not propose changes outside "
        "the application workbench."
    )
    contract_summary = json.dumps(
        {
            "task_id": contract_task_id,
            "objective": contract_record.get("objective"),
            "scope": contract_record.get("scope"),
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
                f"## Authorized Contract\n\n{contract_summary}\n"
            ),
        },
    ]
    try:
        response = client.chat(model, messages, response_format="json")
    except OllamaConnectionError as exc:
        reason = f"Ollama unavailable; no validated proposal produced: {exc}"
        return ProposalResult(
            None,
            ProposalVerdict(False, [reason], [], []),
            "fallback",
            reason,
            activated=True,
        )
    try:
        content = str(response["message"]["content"]).strip()
        if not content:
            raise ValueError("Ollama returned empty proposal content")
        proposal = parse_coder_proposal(content)
    except (KeyError, TypeError, ValueError, ProposalParseError) as exc:
        reason = f"Proposal parse failed: {exc}"
        return ProposalResult(
            None,
            ProposalVerdict(False, [reason], [], []),
            "ollama",
            f"Coder model `{model}` (unparseable proposal)",
            activated=True,
        )
    verdict = validate_proposal(
        proposal,
        project_name=project_name,
        contract_actionable=True,
        max_files=max_files,
        contract_task_id=contract_task_id,
    )
    return ProposalResult(
        proposal, verdict, "ollama", f"Coder model `{model}`", activated=True
    )


def run_coder_stage(
    *,
    project_name: str,
    root: Path,
    project: dict[str, Any],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
    max_lines: int,
    max_files: int,
    contract_json_path: str,
) -> tuple[ProposalResult, str, str]:
    """Activate the Coder only for an authorized, valid contract.

    When the backing contract is not authorized and valid, the Coder is not
    activated: no model is called and no proposal artifacts are written. When
    it is, a proposal is requested, validated, and written to the two fixed
    proposal files. No application code is ever written.

    Args:
        project_name: Active application workbench name.
        root: Absolute repository root.
        project: Active project configuration mapping.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        models_config: Parsed ``config/models.yaml`` mapping.
        max_lines: Maximum context lines loaded from each file.
        max_files: Maximum number of files a proposal may touch.
        contract_json_path: Repository-relative authorized contract path.

    Returns:
        Proposal result and the two repository-relative proposal paths.
    """
    task_root = str(project["task_root"])
    proposal_json_path, proposal_md_path = coder_proposal_paths(root, project)

    contract_record = load_existing_contract(contract_json_path, root)
    if contract_record is None or not is_contract_actionable(contract_record):
        result = ProposalResult(
            None,
            ProposalVerdict(
                False,
                ["Coder not activated: no authorized valid contract"],
                [],
                [],
            ),
            "skipped",
            "Contract is not authorized and valid; Coder did not run.",
            activated=False,
        )
        return result, proposal_json_path, proposal_md_path

    result = request_coder_proposal(
        project_name=project_name,
        project=project,
        contract_record=contract_record,
        factory_config=factory_config,
        models_config=models_config,
        max_lines=max_lines,
        max_files=max_files,
    )
    safe_write_json(
        proposal_json_path,
        coder_to_dict(result),
        repo_root=root,
        allowed_roots=[task_root],
    )
    safe_write_text(
        proposal_md_path,
        render_coder_proposal_md(result),
        repo_root=root,
        allowed_roots=[task_root],
    )
    return result, proposal_json_path, proposal_md_path
