#!/usr/bin/env python3
"""AI-reviewed task-contract decisions for Crazy Factory.

The contract decision is no longer a blunt binary reject. A deterministic
SAFETY FLOOR (in :mod:`task_contract`) is enforced first and can never be
relaxed by the model — that is the "model proposes, Python validates" trust
anchor. Above the floor, an AI reviewer interprets the situation and either
accepts, repairs safe completeness gaps, or escalates to the owner.

Decision ladder (owner-approved):

1. Floor first — :func:`task_contract.contract_safety_reasons`. Any hit →
   ``reject_unsafe`` (the AI is never consulted to override it).
2. Already complete + safe → ``valid``.
3. Exhaust AI — the ``reviewer`` model assesses the contract and may return
   repairs (filled into EMPTY fields only) or escalate to owner review.
4. Deterministic repair fallback — when the AI is unavailable/inconclusive,
   synthesize safe completeness fixes (never fake content, never self-approve).
5. Still indeterminate → emit an owner-review checklist and escalate.

A repaired contract is re-checked against the floor and must genuinely satisfy
completeness before it is called ``valid`` — the AI can never produce a fake
``valid``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from json_parsing import coerce_str, strip_code_fence
from ollama_client import OllamaClient, OllamaConnectionError
from task_contract import (
    PlannedTask,
    apply_repairs,
    contract_completeness_reasons,
    contract_safety_reasons,
    synthesize_repairs,
)

# Decision vocabulary (shares intent with the coder governance layer).
DECISION_VALID = "valid"
DECISION_REPAIR = "repair"
DECISION_NEEDS_OWNER_REVIEW = "needs_owner_review"
DECISION_NEEDS_CLARIFICATION = "needs_clarification"
DECISION_REJECT_UNSAFE = "reject_unsafe"

# Persisted validation.status per decision (authorize-task accepts only valid).
_STATUS_BY_DECISION = {
    DECISION_VALID: "valid",
    DECISION_REPAIR: "valid",
    DECISION_NEEDS_OWNER_REVIEW: "needs_owner_review",
    DECISION_NEEDS_CLARIFICATION: "needs_owner_review",
    DECISION_REJECT_UNSAFE: "rejected",
}


@dataclass(frozen=True)
class ReviewVerdict:
    """Outcome of reviewing a task contract.

    Attributes:
        decision: One of the ``DECISION_*`` values.
        status: Persisted ``validation.status`` (valid/rejected/
            needs_owner_review). Only ``valid`` lets the owner authorize.
        task: The contract after any repairs (unchanged when none applied).
        reasons: Human-readable explanation of the decision.
        checklist: Owner-facing items to resolve (for the review checkpoint).
        repairs_applied: Names of fields repaired.
        source: ``"floor"``, ``"ollama"``, or ``"deterministic"``.
    """

    decision: str
    status: str
    task: PlannedTask
    reasons: list[str] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    repairs_applied: list[str] = field(default_factory=list)
    source: str = "deterministic"

    @property
    def valid(self) -> bool:
        """Whether the contract is owner-authorizable (apply-gate signal)."""
        return self.status == "valid"


def _request_ai_review(
    task: PlannedTask,
    completeness: list[str],
    context: str,
    *,
    models_config: dict[str, Any],
    factory_config: dict[str, Any],
    retries: int,
) -> dict[str, Any] | None:
    """Ask the reviewer model to assess the contract; ``None`` if unavailable.

    Bounded retries "exhaust" the AI before any deterministic fallback. A
    malformed or empty response (after retries) returns ``None`` rather than a
    guessed verdict.
    """
    models = models_config.get("models", {})
    model = str(models.get("reviewer") or models.get("planner") or "")
    ollama = factory_config.get("ollama", {})
    if not model or not ollama:
        return None
    client = OllamaClient(
        base_url=str(ollama.get("base_url", "http://localhost:11434")),
        timeout_seconds=int(ollama.get("timeout_seconds", 120)),
        stream=bool(ollama.get("stream", False)),
    )
    contract_json = json.dumps(
        {
            "task_id": task.task_id,
            "title": task.title,
            "objective": task.objective,
            "scope": task.scope,
            "exclusions": task.exclusions,
            "acceptance_criteria": task.acceptance_criteria,
            "validation_plan": task.validation_plan,
            "risks": task.risks,
        },
        indent=2,
    )
    instruction = (
        "You review a software task contract for completeness and clarity (a "
        "separate deterministic check already handles safety, so do NOT judge "
        "safety). Decide if it is ready to act on. Return ONLY a JSON object "
        "with keys: decision (one of valid, repair, needs_owner_review, "
        "needs_clarification), reasons (array), repairs (object that may set "
        "validation_plan (string) and/or exclusions/acceptance_criteria/scope "
        "(arrays) ONLY to fill MISSING fields), clarification_questions "
        "(array), owner_review_reasons (array). Use 'repair' when the gaps are "
        "objective and you can fill them from the contract's own intent; use "
        "'needs_clarification' or 'needs_owner_review' when judgment or owner "
        "input is required. Never invent scope the contract does not imply."
    )
    messages = [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": (
                f"## Contract\n\n{contract_json}\n\n"
                f"## Deterministic completeness gaps\n\n"
                + ("\n".join(f"- {r}" for r in completeness) or "- none")
                + f"\n\n## Project context\n\n{context.strip() or '(none)'}\n"
            ),
        },
    ]
    for _ in range(max(1, retries)):
        try:
            response = client.chat(model, messages, response_format="json")
            content = str(response["message"]["content"]).strip()
            data = json.loads(strip_code_fence(content))
            if isinstance(data, dict) and data.get("decision"):
                return data
        except (
            KeyError,
            TypeError,
            ValueError,
            OllamaConnectionError,
            json.JSONDecodeError,
        ):
            continue
    return None


def review_contract(
    task: PlannedTask,
    *,
    context: str = "",
    models_config: dict[str, Any] | None = None,
    factory_config: dict[str, Any] | None = None,
    retries: int = 2,
) -> ReviewVerdict:
    """Run the safety-floor-first, AI-then-deterministic decision ladder.

    Args:
        task: The freshly generated contract to review.
        context: Short project context (goal + planning summary) for the AI.
        models_config: Parsed models config (for the reviewer model).
        factory_config: Parsed factory config (for the Ollama client).
        retries: How many times to "exhaust" the AI before falling back.

    Returns:
        A :class:`ReviewVerdict`.
    """
    # 1. Deterministic safety floor — non-negotiable, AI can never override.
    floor = contract_safety_reasons(task)
    if floor:
        return ReviewVerdict(
            decision=DECISION_REJECT_UNSAFE,
            status=_STATUS_BY_DECISION[DECISION_REJECT_UNSAFE],
            task=task,
            reasons=floor,
            checklist=floor,
            source="floor",
        )

    # 2. Already complete + safe → valid (no AI needed).
    completeness = contract_completeness_reasons(task)
    if not completeness:
        return ReviewVerdict(
            decision=DECISION_VALID,
            status="valid",
            task=task,
            reasons=["Contract is complete and within safety bounds."],
            source="deterministic",
        )

    # 3. Exhaust AI analysis.
    ai = (
        _request_ai_review(
            task,
            completeness,
            context,
            models_config=models_config or {},
            factory_config=factory_config or {},
            retries=retries,
        )
        if models_config and factory_config
        else None
    )
    repairs: dict[str, Any] = {}
    ai_reasons: list[str] = []
    source = "deterministic"
    if ai is not None:
        source = "ollama"
        ai_reasons = [coerce_str(r) for r in (ai.get("reasons") or []) if r]
        decision = str(ai.get("decision") or "")
        if decision in (
            DECISION_NEEDS_OWNER_REVIEW,
            DECISION_NEEDS_CLARIFICATION,
        ):
            checklist = [
                coerce_str(r)
                for r in (
                    (ai.get("owner_review_reasons") or [])
                    + (ai.get("clarification_questions") or [])
                )
                if r
            ] or completeness
            return ReviewVerdict(
                decision=decision,
                status=_STATUS_BY_DECISION[decision],
                task=task,
                reasons=ai_reasons or completeness,
                checklist=checklist,
                source="ollama",
            )
        if isinstance(ai.get("repairs"), dict):
            repairs = ai["repairs"]

    # 4. Repair: AI-proposed fills first, then deterministic top-up for any
    #    remaining safe gaps. Re-check the floor on the repaired contract.
    repaired = apply_repairs(task, repairs)
    if contract_completeness_reasons(repaired):
        repaired = apply_repairs(repaired, synthesize_repairs(repaired))
    repaired_floor = contract_safety_reasons(repaired)
    if repaired_floor:
        return ReviewVerdict(
            decision=DECISION_REJECT_UNSAFE,
            status="rejected",
            task=repaired,
            reasons=repaired_floor,
            checklist=repaired_floor,
            source=source,
        )
    remaining = contract_completeness_reasons(repaired)
    repaired_fields = [
        name
        for name in (
            "title",
            "objective",
            "validation_plan",
            "scope",
            "exclusions",
            "acceptance_criteria",
            "inputs",
            "risks",
        )
        if getattr(repaired, name) != getattr(task, name)
    ]
    if not remaining:
        return ReviewVerdict(
            decision=DECISION_REPAIR,
            status="valid",
            task=repaired,
            reasons=(ai_reasons or [])
            + [f"Repaired completeness gaps: {', '.join(repaired_fields)}."],
            repairs_applied=repaired_fields,
            source=source,
        )

    # 5. Still indeterminate → owner-review checklist checkpoint.
    return ReviewVerdict(
        decision=DECISION_NEEDS_OWNER_REVIEW,
        status="needs_owner_review",
        task=repaired,
        reasons=ai_reasons
        or ["Could not complete the contract automatically."],
        checklist=remaining,
        repairs_applied=repaired_fields,
        source=source,
    )


def render_contract_review_md(verdict: ReviewVerdict) -> str:
    """Render the owner-facing contract review checklist/checkpoint."""
    lines = [
        "# Contract Review",
        "",
        f"- Decision: `{verdict.decision}`",
        f"- Status: `{verdict.status}`",
        f"- Source: `{verdict.source}`",
        f"- Repairs applied: `{', '.join(verdict.repairs_applied) or 'none'}`",
        "",
        "## Reasons",
        "",
        *([f"- {r}" for r in verdict.reasons] or ["_None._"]),
        "",
        "## Owner checklist",
        "",
        *([f"- [ ] {c}" for c in verdict.checklist] or ["_None._"]),
        "",
    ]
    return "\n".join(lines)
