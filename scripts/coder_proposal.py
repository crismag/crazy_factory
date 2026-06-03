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
- Proposals may target anywhere inside the active project workbench EXCEPT the
  factory-managed runtime folders (config/state/factory_state/reports/tasks/
  context, from the path resolver) and the owner-control file; anything outside
  the workbench is blocked.
- Dangerous paths, secret-like material, destructive commands, empty
  proposals, and proposals over the file limit are rejected.
- When the model is unavailable or output is malformed, the result is a
  *rejected* proposal, never a fake-valid one. The run still exits cleanly.

Stage 1 governance layer: alongside the binary ``valid`` (the apply-gate
signal, unchanged), each verdict carries a ``decision`` — one of
``invalid``/``blocked``/``needs_clarification``/``needs_owner_review``/``valid``.
``valid == decision in APPLY_ELIGIBLE_DECISIONS`` by construction, so the
classifier is purely additive: it explains *why* a proposal is or isn't
apply-eligible without changing which proposals are. The rejection engine is
wrapped, not replaced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from contract_stage import load_existing_contract
from json_parsing import coerce_str, coerce_str_list, strip_code_fence
from ollama_client import OllamaClient, OllamaConnectionError
from project_paths import resolve_paths
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

# Governance decision model (Stage 1: classify, do not replace the rejection
# engine). Ordered most-to-least severe. ``valid`` (apply-eligibility) is
# derived as ``decision in APPLY_ELIGIBLE_DECISIONS`` — so a proposal flagged
# for owner review is still eligible *through the existing owner-approval gate*,
# while blocked/invalid/needs_clarification are not actionable.
DECISION_INVALID = "invalid"
DECISION_BLOCKED = "blocked"
DECISION_NEEDS_CLARIFICATION = "needs_clarification"
DECISION_NEEDS_OWNER_REVIEW = "needs_owner_review"
DECISION_VALID = "valid"
DECISION_VALUES: tuple[str, ...] = (
    DECISION_INVALID,
    DECISION_BLOCKED,
    DECISION_NEEDS_CLARIFICATION,
    DECISION_NEEDS_OWNER_REVIEW,
    DECISION_VALID,
)
# A proposal is apply-eligible (after the owner's existing approval) only for
# these decisions. This is the contract that keeps the apply gate unchanged.
APPLY_ELIGIBLE_DECISIONS: frozenset[str] = frozenset(
    {DECISION_VALID, DECISION_NEEDS_OWNER_REVIEW}
)

# Stage 2/3 project boundary policy. The boundary is the active project
# workbench (``app_path``): anything outside is blocked, and the factory's own
# per-project runtime folders *inside* the workbench (config/state/reports/
# tasks/context, derived from the path resolver — not a separate policy file)
# are blocked too, because they are factory-managed, not application content.
# App-content directories inside the workbench are in-bounds; a few
# higher-impact classes route to owner review rather than straight to valid.
REVIEW_DIR_CLASSES: frozenset[str] = frozenset({"scripts", "migrations"})
# Top-level workbench dirs the coder may never write to — version-control
# metadata of the project itself (an external app may be its own git repo).
WORKBENCH_FORBIDDEN_TOP: frozenset[str] = frozenset(
    {".git", ".github", ".hg", ".svn"}
)
# The owner-control file at the workbench root is factory-managed.
CONTROL_FILE_NAME = "crazy_project.yaml"
# Placeholder env files are documentation, not real secrets — they must not be
# blocked by the ``.env`` secret marker.
PLACEHOLDER_ENV_FILES: tuple[str, ...] = (
    ".env.example",
    ".env.sample",
    ".env.template",
    ".env.dist",
)


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

    ``valid`` remains the apply-eligibility signal that downstream stages
    already consume; ``decision`` is the additive governance classification
    (Stage 1). They are kept consistent by construction:
    ``valid == (decision in APPLY_ELIGIBLE_DECISIONS)``.

    Attributes:
        valid: Whether the proposal is apply-eligible (after owner approval).
        reasons: Human-readable rejection reasons. Empty when ``valid``.
        blocked_paths: Specific paths that violated the target boundary.
        warnings: Non-fatal concerns worth surfacing to the owner.
        decision: Governance decision (one of :data:`DECISION_VALUES`).
        review_reasons: Why owner review is advised (for needs_owner_review).
        clarification_questions: What the owner/model must clarify.
        risk_level: The proposal's coarse risk (low/medium/high), or "".
        policy_hits: Project-policy classes the proposal touched (reserved).
    """

    valid: bool
    reasons: list[str] = field(default_factory=list)
    blocked_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    decision: str = ""
    review_reasons: list[str] = field(default_factory=list)
    clarification_questions: list[str] = field(default_factory=list)
    risk_level: str = ""
    policy_hits: list[str] = field(default_factory=list)


def _make_verdict(
    *,
    decision: str,
    reasons: list[str],
    blocked: list[str],
    warnings: list[str],
    review_reasons: list[str] | None = None,
    clarification_questions: list[str] | None = None,
    risk_level: str = "",
    policy_hits: list[str] | None = None,
) -> ProposalVerdict:
    """Build a verdict with ``valid`` derived from ``decision``.

    Centralizes the invariant ``valid == decision in APPLY_ELIGIBLE_DECISIONS``
    so callers cannot set the two inconsistently.
    """
    return ProposalVerdict(
        valid=decision in APPLY_ELIGIBLE_DECISIONS,
        reasons=reasons,
        blocked_paths=blocked,
        warnings=warnings,
        decision=decision,
        review_reasons=review_reasons or [],
        clarification_questions=clarification_questions or [],
        risk_level=risk_level,
        policy_hits=policy_hits or [],
    )


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


def allowed_target_prefixes(app_path: str) -> tuple[str, ...]:
    """Return the primary always-valid target prefixes for the prompt.

    The boundary itself is broader (the whole workbench minus factory runtime,
    see :func:`classify_path`); these are the directories the coder is steered
    toward and that classify straight to ``valid``.

    Args:
        app_path: Active application workbench path (e.g. ``apps/<id>``).

    Returns:
        The ``app``, ``docs``, and ``tests`` prefixes under the workbench.
    """
    base = app_path.rstrip("/")
    return (f"{base}/app/", f"{base}/docs/", f"{base}/tests/")


def _default_runtime_prefixes(app_path: str) -> tuple[str, ...]:
    """Factory-managed runtime dir prefixes inside a workbench (resolver-based).

    Uses the central path resolver so the protected set tracks the configured
    workbench layout rather than a hardcoded list.
    """
    paths = resolve_paths(app_path)
    dirs = (
        paths.config_dir,
        paths.state_dir,
        paths.factory_state_dir,
        paths.reports_dir,
        paths.tasks_dir,
        paths.factory_context_dir,
        paths.context_dir,
    )
    return tuple(f"{d.rstrip('/')}/" for d in dirs)


def project_runtime_prefixes(project: dict[str, Any]) -> tuple[str, ...]:
    """Factory-managed runtime dir prefixes from a resolved project mapping.

    Honors per-project path overrides (the resolved dirs already carry them).
    """
    keys = (
        "config_dir",
        "state_dir",
        "factory_state_dir",
        "report_root",
        "task_root",
        "context_root",
        "context_store_root",
    )
    dirs = [str(project[k]).rstrip("/") for k in keys if project.get(k)]
    return tuple(f"{d}/" for d in dirs)


def resolve_workbench_path(path: str, app_path: str) -> str:
    """Interpret a proposed path against the project workbench.

    Models naturally propose workbench-relative paths (``src/x.py``,
    ``README.md``). Those are resolved to ``<app_path>/<path>``. A path that is
    already absolute or already prefixed with the workbench is returned
    unchanged (and judged by the boundary check). This makes generation robust
    for both embedded and external (absolute) workbenches.

    Args:
        path: Raw path proposed by the model.
        app_path: Active workbench path (repo-relative or absolute).

    Returns:
        The workbench-resolved path.
    """
    base = app_path.rstrip("/")
    if not path or path.startswith("/"):
        return path
    if path == base or path.startswith(f"{base}/"):
        return path
    # Strip a leading "./" only — must NOT mangle dotfiles like ".git".
    rel = path
    while rel.startswith("./"):
        rel = rel[2:]
    return f"{base}/{rel}"


def classify_path(
    path: str, app_path: str, runtime_prefixes: tuple[str, ...]
) -> str:
    """Classify one proposed path as ``blocked``, ``review``, or ``valid``.

    The boundary is the active project workbench. Outside it (or absolute /
    parent-traversal / a top-level factory directory) is ``blocked``; the
    factory-managed runtime folders and owner-control file *inside* the
    workbench are ``blocked``; app-content directories are ``valid`` except a
    few higher-impact classes which route to ``review``.

    Args:
        path: Repository-relative path proposed by the model.
        app_path: Active workbench path (e.g. ``apps/<id>``).
        runtime_prefixes: Factory-managed dir prefixes inside the workbench.

    Returns:
        ``"blocked"``, ``"review"``, or ``"valid"``.
    """
    if not path:
        return "blocked"
    base = app_path.rstrip("/")
    # Interpret a workbench-relative path (e.g. "src/x.py") against the
    # workbench, so the model need not echo the full prefix. Already-prefixed
    # or absolute paths are taken as-is and judged by the containment below.
    text = PurePosixPath(resolve_workbench_path(path, app_path)).as_posix()
    if ".." in PurePosixPath(text).parts:
        return "blocked"
    if text.endswith("/"):
        return "blocked"
    # Defense in depth: explicit top-level factory directories (repo-relative).
    lowered = text.lstrip("./").lower()
    if any(lowered.startswith(p) for p in FORBIDDEN_PATH_PREFIXES):
        return "blocked"
    if text != base and not text.startswith(f"{base}/"):
        return "blocked"  # outside the active project workbench
    if text == f"{base}/{CONTROL_FILE_NAME}":
        return "blocked"  # the owner-control file is factory-managed
    if any(text.startswith(rp) for rp in runtime_prefixes):
        return "blocked"  # factory-managed runtime inside the workbench
    top = text[len(base) + 1 :].split("/", 1)[0]
    if top in WORKBENCH_FORBIDDEN_TOP:
        return "blocked"  # the project's own VCS metadata is off-limits
    return "review" if top in REVIEW_DIR_CLASSES else "valid"


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
    app_path: str,
    contract_actionable: bool,
    max_files: int,
    contract_task_id: str = "",
    runtime_prefixes: tuple[str, ...] = (),
) -> ProposalVerdict:
    """Validate a coder proposal against the safety + governance rules.

    Args:
        proposal: Parsed proposal, or ``None`` when none was produced.
        app_path: Active application workbench path (e.g. `apps/<id>`).
        contract_actionable: Whether the backing contract is authorized+valid.
        max_files: Maximum number of files a proposal may touch.
        contract_task_id: ``task_id`` of the backing contract, for matching.
        runtime_prefixes: Factory-managed runtime dir prefixes inside the
            workbench to block. Defaults to the resolver's layout for
            ``app_path`` when not supplied.

    Returns:
        Validation verdict over all safety rules.
    """
    reasons: list[str] = []
    blocked: list[str] = []
    warnings: list[str] = []
    review_reasons: list[str] = []
    runtime = runtime_prefixes or _default_runtime_prefixes(app_path)

    # Rules 1-3: the backing contract must be authorized and valid.
    if not contract_actionable:
        reasons.append(
            "Backing contract is not authorized and valid; Coder may not act"
        )
    if proposal is None:
        reasons.append("No proposal was produced")
        return _make_verdict(
            decision=DECISION_INVALID,
            reasons=reasons,
            blocked=blocked,
            warnings=warnings,
        )

    paths = _proposal_paths(proposal)
    clarification_questions: list[str] = []

    # Rule 7: an empty proposal proposes no work — not unsafe, just not yet
    # actionable, so it routes to clarification rather than a hard block.
    empty_proposal = not paths
    if empty_proposal:
        reasons.append("Proposal targets no files (empty proposal)")
        clarification_questions.append(
            "Which files under the workbench should this proposal "
            "create, modify, or delete? It currently targets none."
        )

    # Boundary + project policy: outside the workbench (or a factory-managed
    # runtime folder inside it) is blocked; higher-impact in-bounds classes
    # (scripts/, migrations/) route to owner review.
    review_paths: list[str] = []
    for path in paths:
        cls = classify_path(path, app_path, runtime)
        if cls == "blocked":
            blocked.append(path)
        elif cls == "review":
            review_paths.append(path)
    if blocked:
        reasons.append(
            "Proposal targets paths outside the project workbench or its "
            "factory-managed runtime: " + ", ".join(blocked)
        )
    if review_paths:
        review_reasons.append(
            "Touches higher-impact project areas (scripts/migrations): "
            + ", ".join(review_paths)
        )
    # Deletes inside the workbench are allowed but always owner-reviewed.
    in_bounds_deletes = [
        p
        for p in proposal.files_to_delete
        if classify_path(p, app_path, runtime) != "blocked"
    ]
    if in_bounds_deletes:
        review_reasons.append(
            "Deletes files (owner review required): "
            + ", ".join(in_bounds_deletes)
        )

    # No secret-like material in paths or instructions. Placeholder env files
    # (.env.example/.sample/.template/.dist) are documentation, not secrets, so
    # they are excluded from the ``.env`` marker.
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
    scrubbed = text_blob
    for placeholder in PLACEHOLDER_ENV_FILES:
        scrubbed = scrubbed.replace(placeholder, "env-placeholder")
    secret_hits = _scan_markers(scrubbed, SECRET_MARKERS)
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
        review_reasons.append(
            "Estimated risk is high; owner review advised before approval"
        )
    if (
        contract_task_id
        and proposal.task_id
        and proposal.task_id != contract_task_id
    ):
        warnings.append(
            f"Proposal task_id {proposal.task_id!r} does not match contract "
            f"task_id {contract_task_id!r}"
        )

    # Governance classification. Fatal safety/boundary/structural reasons keep
    # ``valid`` False; an empty proposal routes to clarification; in-bounds
    # higher-impact areas, deletes, or high risk route to owner review (still
    # apply-eligible through the existing owner-approval gate); otherwise valid.
    block_reasons = [r for r in reasons if "empty proposal" not in r]
    if block_reasons:
        decision = DECISION_BLOCKED
    elif empty_proposal:
        decision = DECISION_NEEDS_CLARIFICATION
    elif review_reasons:
        decision = DECISION_NEEDS_OWNER_REVIEW
    else:
        decision = DECISION_VALID

    return _make_verdict(
        decision=decision,
        reasons=reasons,
        blocked=blocked,
        warnings=warnings,
        review_reasons=review_reasons,
        clarification_questions=clarification_questions,
        risk_level=risk,
        policy_hits=[],
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
    decision = decision_label(result)
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
            # ``status`` stays the apply-gate signal (valid/rejected/
            # not_activated); ``decision`` is the additive governance layer.
            "status": status,
            "decision": decision,
            "source": result.source,
            "reasons": list(result.verdict.reasons),
            "blocked_paths": list(result.verdict.blocked_paths),
            "warnings": list(result.verdict.warnings),
            "review_reasons": list(result.verdict.review_reasons),
            "clarification_questions": list(
                result.verdict.clarification_questions
            ),
            "risk_level": result.verdict.risk_level,
            "policy_hits": list(result.verdict.policy_hits),
        },
    }


def coder_status_label(result: ProposalResult) -> str:
    """Return the reporting label for a proposal outcome.

    Args:
        result: Proposal result for the current advance.

    Returns:
        ``"not_activated"``, ``"valid"``, or ``"rejected"``.
    """
    if not result.activated:
        return "not_activated"
    return "valid" if result.verdict.valid else "rejected"


def decision_label(result: ProposalResult) -> str:
    """Return the governance decision label for a proposal outcome.

    Distinct from :func:`coder_status_label` (the apply-gate signal). When the
    Coder is not activated there is no proposal to classify, so this reports
    ``"not_activated"``. Otherwise it returns the verdict's ``decision``,
    falling back to a value derived from ``valid`` for verdicts built outside
    :func:`validate_proposal`.

    Args:
        result: Proposal result for the current advance.

    Returns:
        One of :data:`DECISION_VALUES`, or ``"not_activated"``.
    """
    if not result.activated:
        return "not_activated"
    if result.verdict.decision:
        return result.verdict.decision
    return DECISION_VALID if result.verdict.valid else DECISION_INVALID


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
    decision = decision_label(result)
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
        f"- Decision: `{decision}`",
        f"- Owner review required: "
        f"`{str(decision == DECISION_NEEDS_OWNER_REVIEW).lower()}`",
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
    lines.extend(
        [
            "## Validation Verdict",
            "",
            f"- Decision: `{decision}`",
            f"- Valid (apply-eligible after owner approval): `{verdict.valid}`",
            "",
            "### Reasons",
            "",
            *_bullets(verdict.reasons),
            "",
            "### Owner Review Reasons",
            "",
            *_bullets(verdict.review_reasons),
            "",
            "### Clarifications Needed",
            "",
            *_bullets(verdict.clarification_questions),
            "",
            "### Warnings",
            "",
            *_bullets(verdict.warnings),
            "",
            "### Blocked Paths",
            "",
            *_bullets(verdict.blocked_paths),
            "",
        ]
    )
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
    app_path: str,
    project: dict[str, Any],
    contract_record: dict[str, Any],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
    max_lines: int,
    max_files: int,
    remediation_context: str = "",
) -> ProposalResult:
    """Ask the coder model for a proposal and validate it.

    The coder model is asked to emit a single JSON proposal. When Ollama is
    unavailable, the response is empty, or the proposal cannot be parsed, the
    result is a *rejected* proposal rather than a trusted one. No files are
    written, no code is generated, and nothing is executed.

    Args:
        app_path: Active application workbench path (e.g. `apps/<id>`).
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
        project_name=str(project.get("name") or app_path),
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
    base = app_path.rstrip("/")
    instruction = (
        "Return ONLY a single JSON object describing an implementation "
        "proposal. Do NOT write code; describe the plan. Use these keys: "
        "proposal_id, task_id, summary, objective, files_to_create (array), "
        "files_to_modify (array), files_to_delete (array), proposed_tests "
        "(array), implementation_steps (array), estimated_risk "
        "(low|medium|high), notes. Every file path MUST stay inside the "
        f"project workbench {base}/ — prefer app/, docs/, tests/. You may use "
        "scripts/ and migrations/, but those require owner review. Never "
        "target the factory-managed folders (config/, state/, factory_state/, "
        "factory_reports/, factory_tasks/, factory_context/, context/) or "
        f"{base}/crazy_project.yaml. Touch at most {max_files} files. Never "
        "reference secrets, credentials, tokens, private keys, or destructive/"
        "git operations (push, merge, reset, rm -rf, sudo); a .env.example "
        "placeholder is fine. Do not propose changes outside the workbench."
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
    remediation_block = (
        f"\n\n{remediation_context.strip()}\n" if remediation_context else ""
    )
    messages = [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": (
                f"{prompt_package.prompt}\n\n"
                f"## Authorized Contract\n\n{contract_summary}\n"
                f"{remediation_block}"
            ),
        },
    ]
    try:
        response = client.chat(model, messages, response_format="json")
    except OllamaConnectionError as exc:
        reason = f"Ollama unavailable; no validated proposal produced: {exc}"
        return ProposalResult(
            None,
            _make_verdict(
                decision=DECISION_INVALID,
                reasons=[reason],
                blocked=[],
                warnings=[],
            ),
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
            _make_verdict(
                decision=DECISION_INVALID,
                reasons=[reason],
                blocked=[],
                warnings=[],
            ),
            "ollama",
            f"Coder model `{model}` (unparseable proposal)",
            activated=True,
        )
    verdict = validate_proposal(
        proposal,
        app_path=app_path,
        contract_actionable=True,
        max_files=max_files,
        contract_task_id=contract_task_id,
        runtime_prefixes=project_runtime_prefixes(project),
    )
    return ProposalResult(
        proposal, verdict, "ollama", f"Coder model `{model}`", activated=True
    )


def _preserved_proposal_result(
    existing: dict[str, Any] | None,
    app_path: str,
    contract_task_id: str,
    max_files: int,
    runtime_prefixes: tuple[str, ...] = (),
) -> ProposalResult | None:
    """Return a preserved proposal result, or ``None`` to regenerate.

    A proposal is preserved only when it exists on disk, names the same task as
    the current authorized contract, and its *current* fields still revalidate.
    The cached verdict is not trusted.

    Args:
        existing: Parsed ``coder_proposal.json`` record, or ``None``.
        app_path: Active application workbench path (e.g. `apps/<id>`).
        contract_task_id: Task id of the authorized contract.
        max_files: Maximum number of files a proposal may touch.
        runtime_prefixes: Factory-managed runtime dir prefixes to block.

    Returns:
        A preserved :class:`ProposalResult`, or ``None`` when regeneration is
        required.
    """
    if not isinstance(existing, dict):
        return None
    proposal = parse_coder_proposal(json.dumps(existing))
    if not proposal.task_id or proposal.task_id != contract_task_id:
        return None
    verdict = validate_proposal(
        proposal,
        app_path=app_path,
        contract_actionable=True,
        max_files=max_files,
        contract_task_id=contract_task_id,
        runtime_prefixes=runtime_prefixes,
    )
    if not verdict.valid:
        return None
    return ProposalResult(
        proposal,
        verdict,
        "preserved",
        "Existing valid proposal preserved for the authorized task; no new "
        "proposal was generated.",
        activated=True,
    )


def run_coder_stage(
    *,
    app_path: str,
    root: Path,
    project: dict[str, Any],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
    max_lines: int,
    max_files: int,
    contract_json_path: str,
    remediation_context: str = "",
) -> tuple[ProposalResult, str, str]:
    """Activate the Coder only for an authorized, valid contract.

    When the backing contract is not authorized and valid, the Coder is not
    activated: no model is called and no proposal artifacts are written. When
    it is, a proposal is requested, validated, and written to the two fixed
    proposal files. No application code is ever written.

    Args:
        app_path: Active application workbench path (e.g. `apps/<id>`).
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

    # Preserve an existing valid proposal for this same authorized task
    # instead of regenerating it. The proposal id a model picks is not stable
    # across runs, so regenerating would invalidate any owner approval that
    # targets a specific proposal id. Preserving keeps owner approval usable
    # until the contract changes. The current fields are re-validated rather
    # than trusting the cached verdict.
    # During remediation the preserved proposal is exactly the one that failed
    # validation, so it must be regenerated (with the failure as context)
    # rather than preserved — otherwise we would re-apply the broken proposal.
    existing = load_existing_contract(proposal_json_path, root)
    contract_task_id = coerce_str(contract_record.get("task_id"))
    preserved = (
        None
        if remediation_context
        else _preserved_proposal_result(
            existing,
            app_path,
            contract_task_id,
            max_files,
            project_runtime_prefixes(project),
        )
    )
    if preserved is not None:
        # Re-persist so the on-disk record reflects the FRESH re-validation
        # (the cached verdict may be stale, e.g. rejected under an older rule).
        safe_write_json(
            proposal_json_path,
            coder_to_dict(preserved),
            repo_root=root,
            allowed_roots=[task_root],
        )
        safe_write_text(
            proposal_md_path,
            render_coder_proposal_md(preserved),
            repo_root=root,
            allowed_roots=[task_root],
        )
        return preserved, proposal_json_path, proposal_md_path

    result = request_coder_proposal(
        app_path=app_path,
        project=project,
        contract_record=contract_record,
        factory_config=factory_config,
        models_config=models_config,
        max_lines=max_lines,
        max_files=max_files,
        remediation_context=remediation_context,
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
