#!/usr/bin/env python3
"""Parse and validate structured planning contracts for Crazy Factory.

A planning contract is the machine-checkable boundary between "a local model
suggested work" and "the factory is authorized to act". The Planner emits a
single JSON object; this module parses it into a :class:`PlannedTask`,
validates it against the bounded-task rules implied by
``factory/templates/PLANNED_TASK_TEMPLATE.md``, and renders a human-readable
record for owner review.

Two invariants are enforced here and must not be weakened:

- A malformed or overly broad contract is *rejected*, never trusted.
- A contract can never authorize itself. ``authorized`` is always written as
  ``False`` on creation; only the owner may flip it later. The validator
  rejects any contract that arrives pre-authorized or self-approved.

Example:
    Parse and validate one planner contract::

        task = parse_planned_task(raw_json)
        verdict = validate_planned_task(task)
        if verdict.valid:
            ...  # still requires owner authorization before any Coder phase
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Substrings that signal a task is reaching beyond bounded planning authority.
# Matched case-insensitively against the title, objective, and scope text.
FORBIDDEN_SCOPE_KEYWORDS: tuple[str, ...] = (
    "force push",
    "force-push",
    "git push",
    "push to",
    "merge into",
    "merge to",
    "rebase",
    "rewrite history",
    "reset --hard",
    "secret",
    "credential",
    "password",
    "private key",
    "rm -rf",
    "sudo",
    "deploy to production",
    "production deploy",
)

REQUIRED_TEXT_FIELDS: tuple[str, ...] = (
    "task_id",
    "title",
    "objective",
    "validation_plan",
)
REQUIRED_LIST_FIELDS: tuple[str, ...] = (
    "scope",
    "exclusions",
    "acceptance_criteria",
)

# Approval values a model is allowed to propose. Anything resembling an
# already-granted approval is treated as an attempt to self-authorize.
ALLOWED_APPROVAL_STATUSES: frozenset[str] = frozenset(
    {"pending", "proposed", "draft", "unapproved", ""}
)


class ContractParseError(ValueError):
    """Raised when planner output cannot be parsed into a planned task."""


@dataclass(frozen=True)
class PlannedTask:
    """A structured, owner-reviewable task contract.

    Mirrors the fields of ``factory/templates/PLANNED_TASK_TEMPLATE.md``.

    Attributes:
        task_id: Stable identifier for the task.
        title: Short human-readable title.
        objective: One smallest useful outcome.
        scope: Work included in this task.
        exclusions: Work intentionally left out of this task.
        inputs: Files, decisions, and context required before work begins.
        acceptance_criteria: Conditions that define completion.
        validation_plan: Evidence required to consider the task complete.
        risks: Relevant risks and stop conditions.
        approval_status: Proposed approval state. Never an approved value.
        authorized: Whether a downstream worker may act. Always ``False`` on
            creation; only the owner may flip it.
    """

    task_id: str
    title: str
    objective: str
    validation_plan: str
    scope: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    approval_status: str = "pending"
    authorized: bool = False


@dataclass(frozen=True)
class ValidationVerdict:
    """Outcome of validating a :class:`PlannedTask`.

    Attributes:
        valid: Whether the contract satisfies every bounded-task rule.
        reasons: Human-readable rejection reasons. Empty when ``valid``.
    """

    valid: bool
    reasons: list[str] = field(default_factory=list)


def _coerce_str(value: Any) -> str:
    """Coerce a JSON scalar to a trimmed string.

    Only genuine scalars (str, int, float, bool) become text. Objects and
    arrays are discarded to an empty string rather than ``repr``-ed, so a
    nested structure in a text field surfaces as missing content and is
    rejected by the validator instead of passing as garbage.

    Args:
        value: Arbitrary parsed JSON value.

    Returns:
        Stripped string, or an empty string for ``None`` or non-scalar values.
    """
    # ``bool`` is intentionally covered here via its ``int`` subclass.
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _coerce_str_list(value: Any) -> list[str]:
    """Coerce a JSON value into a list of non-empty scalar strings.

    A single string is wrapped as a one-item list so loosely structured model
    output still parses. Empty entries and non-scalar elements (nested objects
    or arrays) are dropped, so validation can rely on list length to mean "has
    real, usable content".

    Args:
        value: Arbitrary parsed JSON value.

    Returns:
        List of trimmed, non-empty strings.
    """
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        items = [_coerce_str(item) for item in value]
        return [item for item in items if item]
    # A lone scalar (number/bool) becomes a single descriptive entry; objects
    # and null coerce to an empty string and yield an empty list.
    text = _coerce_str(value)
    return [text] if text else []


def _strip_code_fence(raw: str) -> str:
    """Remove a surrounding Markdown code fence if present.

    Local models frequently wrap JSON in ```` ```json ```` fences. Stripping a
    single outer fence keeps the parser tolerant without interpreting content.

    Args:
        raw: Raw model output.

    Returns:
        Text with one outer code fence removed when detected.
    """
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    # Drop the opening fence line (e.g. "```" or "```json").
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_planned_task(raw: str) -> PlannedTask:
    """Parse a planner JSON contract into a :class:`PlannedTask`.

    Args:
        raw: Raw planner output expected to contain a single JSON object.

    Returns:
        Parsed planned task. ``authorized`` reflects what the model proposed so
        the validator can reject self-authorization; callers must still force
        it to ``False`` before persisting.

    Raises:
        ContractParseError: If the text is not a JSON object.
    """
    text = _strip_code_fence(raw)
    if not text:
        raise ContractParseError("Planner returned empty contract content")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractParseError(f"Contract is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractParseError("Contract JSON must be an object")

    authorized_raw = data.get("authorized", False)
    authorized = authorized_raw is True or _coerce_str(
        authorized_raw
    ).lower() in {"true", "yes", "1"}
    return PlannedTask(
        task_id=_coerce_str(data.get("task_id")),
        title=_coerce_str(data.get("title")),
        objective=_coerce_str(data.get("objective")),
        validation_plan=_coerce_str(data.get("validation_plan")),
        scope=_coerce_str_list(data.get("scope")),
        exclusions=_coerce_str_list(data.get("exclusions")),
        inputs=_coerce_str_list(data.get("inputs")),
        acceptance_criteria=_coerce_str_list(data.get("acceptance_criteria")),
        risks=_coerce_str_list(data.get("risks")),
        approval_status=_coerce_str(data.get("approval_status")) or "pending",
        authorized=authorized,
    )


def _forbidden_keyword_hits(task: PlannedTask) -> list[str]:
    """Return forbidden-operation keywords found in scope-bearing text.

    Args:
        task: Parsed planned task to inspect.

    Returns:
        Sorted list of matched forbidden keywords.
    """
    haystack = " ".join([task.title, task.objective, *task.scope]).lower()
    hits = {kw for kw in FORBIDDEN_SCOPE_KEYWORDS if kw in haystack}
    return sorted(hits)


def validate_planned_task(task: PlannedTask) -> ValidationVerdict:
    """Validate a planned task against the bounded-task contract rules.

    The validator is intentionally opinionated. A task is rejected when it is
    incomplete, unbounded, references forbidden operations, or attempts to
    authorize itself.

    Args:
        task: Parsed planned task to validate.

    Returns:
        Validation verdict. ``valid`` is ``True`` only when no rule is broken.
    """
    reasons: list[str] = []

    for name in REQUIRED_TEXT_FIELDS:
        if not _coerce_str(getattr(task, name)):
            reasons.append(f"Missing or empty required field: {name}")
    for name in REQUIRED_LIST_FIELDS:
        if not getattr(task, name):
            reasons.append(f"Missing or empty required list: {name}")

    # A bounded task must state at least one acceptance criterion and at least
    # one explicit exclusion; otherwise scope is effectively unbounded.
    if not task.acceptance_criteria:
        reasons.append("No acceptance criteria define completion")
    if not task.exclusions:
        reasons.append("No explicit exclusions to bound scope")

    hits = _forbidden_keyword_hits(task)
    if hits:
        reasons.append(
            "Scope references forbidden operations: " + ", ".join(hits)
        )

    # The factory may never self-authorize. Only the owner flips authorization.
    if task.authorized:
        reasons.append("Contract may not set authorized=true; owner-only")
    if task.approval_status.lower() not in ALLOWED_APPROVAL_STATUSES:
        reasons.append(
            "Contract may not propose an approved status; owner-only"
        )

    return ValidationVerdict(valid=not reasons, reasons=reasons)


def contract_to_dict(
    task: PlannedTask | None, verdict: ValidationVerdict, source: str
) -> dict[str, Any]:
    """Build the machine-readable ``planned_task.json`` record.

    The persisted record is the single source of truth a future Coder phase
    keys off. ``authorized`` is always ``False`` here; a valid verdict only
    means the contract is well-formed and awaiting owner authorization.

    Args:
        task: Parsed planned task, or ``None`` when no contract was produced.
        verdict: Validation verdict for the contract.
        source: Planning source, ``"ollama"`` or ``"fallback"``.

    Returns:
        JSON-serializable contract record.
    """
    status = "valid" if verdict.valid else "rejected"
    body: dict[str, Any] = {
        "task_id": task.task_id if task else None,
        "title": task.title if task else None,
        "objective": task.objective if task else None,
        "scope": task.scope if task else [],
        "exclusions": task.exclusions if task else [],
        "inputs": task.inputs if task else [],
        "acceptance_criteria": task.acceptance_criteria if task else [],
        "validation_plan": task.validation_plan if task else None,
        "risks": task.risks if task else [],
        "approval_status": "pending",
        # Authorization is owner-only and is never granted by the factory.
        "authorized": False,
        "validation": {
            "status": status,
            "source": source,
            "reasons": list(verdict.reasons),
        },
    }
    return body


def is_contract_actionable(record: dict[str, Any]) -> bool:
    """Report whether a persisted contract may be acted on by a worker.

    This is the single gate a future Coder phase must use. Owner authorization
    alone is not sufficient: a contract is actionable only when the owner has
    set ``authorized: true`` *and* the engine validated it as ``valid``. A
    contract that was rejected by validation can never become actionable just
    by flipping ``authorized``.

    Args:
        record: A parsed ``planned_task.json`` mapping.

    Returns:
        ``True`` only when the contract is both owner-authorized and valid.
    """
    if record.get("authorized") is not True:
        return False
    validation = record.get("validation")
    if not isinstance(validation, dict):
        return False
    return validation.get("status") == "valid"


def render_planned_task_md(
    task: PlannedTask | None,
    verdict: ValidationVerdict,
    *,
    source: str,
    detail: str,
) -> str:
    """Render a human-readable ``PLANNED_TASK.md`` record.

    Args:
        task: Parsed planned task, or ``None`` when no contract was produced.
        verdict: Validation verdict for the contract.
        source: Planning source, ``"ollama"`` or ``"fallback"``.
        detail: Human-readable explanation of the planning source.

    Returns:
        Markdown document describing the contract and its verdict.
    """
    status = "valid" if verdict.valid else "rejected"
    lines = [
        "# Planned Task Contract",
        "",
        "## Contract Source",
        "",
        f"- Source: `{source}`",
        f"- Detail: {detail}",
        f"- Validation status: `{status}`",
        "- Authorized: `false` (owner approval required before any Coder "
        "phase)",
        "",
    ]
    if verdict.reasons:
        lines.append("## Rejection Reasons")
        lines.append("")
        lines.extend(f"- {reason}" for reason in verdict.reasons)
        lines.append("")
    if task is None:
        lines.append("## Task")
        lines.append("")
        lines.append("No structured contract was produced this run.")
        lines.append("")
        return "\n".join(lines)

    lines.extend(
        [
            "## Task",
            "",
            f"- Task ID: `{task.task_id}`",
            f"- Title: {task.title}",
            f"- Approval status: `{task.approval_status}`",
            "",
            "## Objective",
            "",
            task.objective or "_None provided._",
            "",
            "## Scope",
            "",
        ]
    )
    lines.extend(_bullets(task.scope))
    lines.extend(["", "## Explicit Exclusions", ""])
    lines.extend(_bullets(task.exclusions))
    lines.extend(["", "## Inputs", ""])
    lines.extend(_bullets(task.inputs))
    lines.extend(["", "## Acceptance Criteria", ""])
    lines.extend(_checkboxes(task.acceptance_criteria))
    lines.extend(["", "## Validation Plan", ""])
    lines.append(task.validation_plan or "_None provided._")
    lines.extend(["", "## Risks And Stop Conditions", ""])
    lines.extend(_bullets(task.risks))
    lines.append("")
    return "\n".join(lines)


def _bullets(items: list[str]) -> list[str]:
    """Render a list as Markdown bullets, or a placeholder when empty.

    Args:
        items: Strings to render.

    Returns:
        Markdown bullet lines.
    """
    if not items:
        return ["_None provided._"]
    return [f"- {item}" for item in items]


def _checkboxes(items: list[str]) -> list[str]:
    """Render a list as unchecked Markdown checkboxes.

    Args:
        items: Strings to render.

    Returns:
        Markdown checkbox lines.
    """
    if not items:
        return ["_None provided._"]
    return [f"- [ ] {item}" for item in items]
