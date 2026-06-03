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
from dataclasses import dataclass, field, replace
from typing import Any

from json_parsing import coerce_str, coerce_str_list, strip_code_fence

# Substrings that signal a task is reaching beyond bounded planning authority.
# Matched case-insensitively against every instruction-bearing field (see
# _forbidden_keyword_hits): title, objective, validation plan, scope, and
# acceptance criteria. Exclusions and risks are intentionally not scanned.
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


def _planned_task_from_mapping(data: dict[str, Any]) -> PlannedTask:
    """Build a :class:`PlannedTask` from a parsed contract mapping.

    Shared by :func:`parse_planned_task` (fresh model output) and
    :func:`planned_task_from_record` (a persisted ``planned_task.json``).
    ``authorized`` reflects what the mapping claims so callers can decide what
    to do with it; the validator and persistence layer enforce policy.

    Args:
        data: Parsed contract mapping.

    Returns:
        Planned task populated from the mapping.
    """
    authorized_raw = data.get("authorized", False)
    authorized = authorized_raw is True or coerce_str(
        authorized_raw
    ).lower() in {"true", "yes", "1"}
    return PlannedTask(
        task_id=coerce_str(data.get("task_id")),
        title=coerce_str(data.get("title")),
        objective=coerce_str(data.get("objective")),
        validation_plan=coerce_str(data.get("validation_plan")),
        scope=coerce_str_list(data.get("scope")),
        exclusions=coerce_str_list(data.get("exclusions")),
        inputs=coerce_str_list(data.get("inputs")),
        acceptance_criteria=coerce_str_list(data.get("acceptance_criteria")),
        risks=coerce_str_list(data.get("risks")),
        approval_status=coerce_str(data.get("approval_status")) or "pending",
        authorized=authorized,
    )


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
    text = strip_code_fence(raw)
    if not text:
        raise ContractParseError("Planner returned empty contract content")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractParseError(f"Contract is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractParseError("Contract JSON must be an object")
    return _planned_task_from_mapping(data)


def planned_task_from_record(record: dict[str, Any]) -> PlannedTask:
    """Rebuild a :class:`PlannedTask` from a persisted contract record.

    Args:
        record: A parsed ``planned_task.json`` mapping.

    Returns:
        Planned task populated from the record's current fields.
    """
    return _planned_task_from_mapping(record)


def _forbidden_keyword_hits(task: PlannedTask) -> list[str]:
    """Return forbidden-operation keywords found in instruction-bearing text.

    Every field that could direct a future worker is scanned: title,
    objective, scope, acceptance criteria, and validation plan. ``exclusions``
    is intentionally exempt because it is the safe harbor for negative
    statements ("do not push", "do not touch secrets"); ``risks`` is exempt as
    descriptive rather than directive. This prevents bypassing the safety
    boundary by relocating an instruction into another field.

    Args:
        task: Parsed planned task to inspect.

    Returns:
        Sorted list of matched forbidden keywords.
    """
    haystack = " ".join(
        [
            task.title,
            task.objective,
            task.validation_plan,
            *task.scope,
            *task.acceptance_criteria,
        ]
    ).lower()
    hits = {kw for kw in FORBIDDEN_SCOPE_KEYWORDS if kw in haystack}
    return sorted(hits)


def _content_reasons(task: PlannedTask) -> list[str]:
    """Return content-rule violations, independent of authorization.

    These checks define a well-formed, bounded task: required fields are
    present, completion is defined, scope is bounded, and no instruction-
    bearing field references a forbidden operation. They deliberately exclude
    the self-authorization checks so the same rules can revalidate an
    owner-authorized contract.

    Args:
        task: Planned task to inspect.

    Returns:
        List of human-readable content violations; empty when well-formed.
    """
    reasons = contract_completeness_reasons(task)
    hits = _forbidden_keyword_hits(task)
    if hits:
        reasons.append(
            "Contract references forbidden operations: " + ", ".join(hits)
        )
    return reasons


def contract_completeness_reasons(task: PlannedTask) -> list[str]:
    """Return ONLY the completeness gaps — the repairable, non-safety rules.

    Missing required fields, an empty scope/exclusions/acceptance: these make a
    contract incomplete, not unsafe. They are candidates for repair (AI or
    deterministic), never a hard safety rejection.
    """
    reasons: list[str] = []
    for name in REQUIRED_TEXT_FIELDS:
        if not coerce_str(getattr(task, name)):
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
    return reasons


def contract_safety_reasons(task: PlannedTask) -> list[str]:
    """Return the NON-NEGOTIABLE safety-floor violations (Python-enforced).

    This is the deterministic floor an AI reviewer may never relax: forbidden
    destructive/out-of-bounds operations in instruction-bearing fields, and any
    attempt to self-authorize or self-approve. A non-empty result means the
    contract is genuinely unsafe and must be rejected outright.
    """
    reasons: list[str] = []
    hits = _forbidden_keyword_hits(task)
    if hits:
        reasons.append(
            "Contract references forbidden operations: " + ", ".join(hits)
        )
    if task.authorized:
        reasons.append("Contract may not set authorized=true; owner-only")
    if task.approval_status.lower() not in ALLOWED_APPROVAL_STATUSES:
        reasons.append(
            "Contract may not propose an approved status; owner-only"
        )
    return reasons


def synthesize_repairs(task: PlannedTask) -> dict[str, Any]:
    """Deterministically fill safe completeness gaps (AI-down fallback).

    Only fills EMPTY fields, and only descriptive ones — never touches
    authorization, approval, scope intent, or anything safety-bearing.
    """
    repairs: dict[str, Any] = {}
    if not coerce_str(task.validation_plan):
        if task.acceptance_criteria:
            repairs["validation_plan"] = (
                "Verify each acceptance criterion is met: "
                + "; ".join(task.acceptance_criteria)
            )
        else:
            repairs["validation_plan"] = (
                "Run the project's tests and confirm the stated objective is "
                "met before considering the task complete."
            )
    if not task.exclusions:
        repairs["exclusions"] = [
            "No changes beyond the stated scope.",
            "No destructive or git operations.",
        ]
    return repairs


def apply_repairs(task: PlannedTask, repairs: dict[str, Any]) -> PlannedTask:
    """Return a copy of ``task`` with repairs applied to EMPTY fields only.

    Repairs may fill descriptive/completeness fields (validation_plan, scope,
    exclusions, acceptance_criteria, inputs, risks, title, objective) when they
    are currently empty. ``authorized`` and ``approval_status`` are never
    repairable — the safety floor owns those.
    """
    fields: dict[str, Any] = {}
    for name in ("title", "objective", "validation_plan"):
        text_value = coerce_str(repairs.get(name))
        if text_value and not coerce_str(getattr(task, name)):
            fields[name] = text_value
    for name in (
        "scope",
        "exclusions",
        "acceptance_criteria",
        "inputs",
        "risks",
    ):
        list_value = coerce_str_list(repairs.get(name))
        if list_value and not getattr(task, name):
            fields[name] = list_value
    return replace(task, **fields) if fields else task


def validate_contract_content(task: PlannedTask) -> ValidationVerdict:
    """Validate only the bounded-task content rules.

    Excludes the self-authorization checks, so this can revalidate the current
    fields of an owner-authorized contract (where ``authorized`` is
    legitimately ``True``).

    Args:
        task: Planned task to validate.

    Returns:
        Verdict over the content rules alone.
    """
    reasons = _content_reasons(task)
    return ValidationVerdict(valid=not reasons, reasons=reasons)


def validate_planned_task(task: PlannedTask) -> ValidationVerdict:
    """Validate a freshly generated planned task against all contract rules.

    The validator is intentionally opinionated. A task is rejected when it is
    incomplete, unbounded, references forbidden operations, or attempts to
    authorize itself. This is the gate for *fresh* model output; revalidating
    an owner-authorized contract uses :func:`validate_contract_content`.

    Args:
        task: Parsed planned task to validate.

    Returns:
        Validation verdict. ``valid`` is ``True`` only when no rule is broken.
    """
    reasons = _content_reasons(task)

    # The factory may never self-authorize. Only the owner flips authorization.
    if task.authorized:
        reasons.append("Contract may not set authorized=true; owner-only")
    if task.approval_status.lower() not in ALLOWED_APPROVAL_STATUSES:
        reasons.append(
            "Contract may not propose an approved status; owner-only"
        )

    return ValidationVerdict(valid=not reasons, reasons=reasons)


def contract_to_dict(
    task: PlannedTask | None,
    verdict: ValidationVerdict,
    source: str,
    *,
    status: str | None = None,
    decision: str = "",
    checklist: list[str] | None = None,
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
    status = status or ("valid" if verdict.valid else "rejected")
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
            "decision": decision,
            "source": source,
            "reasons": list(verdict.reasons),
            "checklist": list(checklist or []),
        },
    }
    return body


def is_contract_actionable(record: object) -> bool:
    """Report whether a persisted contract may be acted on by a worker.

    This is the single gate a future Coder phase must use. Two conditions must
    hold:

    - the owner has set ``authorized: true``, and
    - the contract's *current* fields still pass the bounded-task content
      rules.

    The cached ``validation.status`` is deliberately ignored and the record is
    revalidated, so an owner who flips ``authorized`` while also editing the
    body (emptying scope, slipping in a forbidden operation) does not leave a
    stale ``valid`` verdict standing. A non-mapping record is never actionable.

    Args:
        record: A parsed ``planned_task.json`` value; expected to be a mapping.

    Returns:
        ``True`` only when the contract is owner-authorized and its current
        content revalidates as well-formed and bounded.
    """
    if not isinstance(record, dict):
        return False
    if record.get("authorized") is not True:
        return False
    task = planned_task_from_record(record)
    return validate_contract_content(task).valid


def render_planned_task_md(
    task: PlannedTask | None,
    verdict: ValidationVerdict,
    *,
    source: str,
    detail: str,
    authorized: bool = False,
) -> str:
    """Render a human-readable ``PLANNED_TASK.md`` record.

    Args:
        task: Parsed planned task, or ``None`` when no contract was produced.
        verdict: Validation verdict for the contract.
        source: Planning source, ``"ollama"``, ``"fallback"``, or
            ``"preserved"``.
        detail: Human-readable explanation of the planning source.
        authorized: Whether the contract is owner-authorized. The factory never
            sets this; it is only ``True`` when rendering a preserved,
            owner-authorized contract.

    Returns:
        Markdown document describing the contract and its verdict.
    """
    status = (
        "authorized"
        if authorized
        else ("valid" if verdict.valid else "rejected")
    )
    authorized_line = (
        "- Authorized: `true` (owner-authorized; preserved)"
        if authorized
        else "- Authorized: `false` (owner approval required before any "
        "Coder phase)"
    )
    lines = [
        "# Planned Task Contract",
        "",
        "## Contract Source",
        "",
        f"- Source: `{source}`",
        f"- Detail: {detail}",
        f"- Validation status: `{status}`",
        authorized_line,
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
