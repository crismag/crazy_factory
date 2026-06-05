#!/usr/bin/env python3
"""Deterministic-first recovery routing for Crazy Factory.

This module is the Phase 9D recovery entry point for known, model-free failure
patterns. It returns structured decisions, validates a small action enum, and
applies only factory-runtime artifact transitions inside the project workbench.
LLM recovery can sit above this later as an escalation layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from adjudicator import (
    ACCEPT,
    ESCALATE,
    FIXIT,
    REDIRECT,
    REJECT_UNSAFE,
    REVISE,
    SCOPE_DOWN,
    Adjudication,
    adjudicate,
)
from ollama_client import OllamaClient
from owner_controls import revoke_proposal
from repo_tools import (
    resolve_repo_path,
    safe_load_json,
    safe_write_json,
    safe_write_text,
)

APPLICATION_REJECTED = "application_rejected"
RECOVERY_EXHAUSTED = "recovery_exhausted"
NEEDS_OWNER_DECISION = "needs_owner_decision"

DECISIONS: frozenset[str] = frozenset(
    {"regenerate_patch", "revise_proposal", "replan_task", "park"}
)
ACTION_TYPES: frozenset[str] = frozenset(
    {
        "clear_approval",
        "retire_artifact",
        "request_new_proposal",
        "request_new_contract",
        "update_focus",
        "record_owner_question",
    }
)

RECOVERY_JSON = "recovery_decision.json"
RECOVERY_MD = "RECOVERY_DECISION.md"


@dataclass(frozen=True)
class RecoveryAction:
    """One validated runtime transition requested by recovery."""

    type: str
    path: str = ""
    detail: str = ""


@dataclass(frozen=True)
class RecoveryDecision:
    """Structured recovery decision."""

    recovery_id: str
    trigger: str
    trigger_stage: str
    trigger_reasons: list[str]
    decision: str
    reason: str
    target_stage: str
    actions: list[RecoveryAction] = field(default_factory=list)
    attempt: int = 1
    max_attempts: int = 3
    source: str = "deterministic"
    valid: bool = True
    validation_reasons: list[str] = field(default_factory=list)
    failure_class: str = ""
    disposition: str = ""


def _task_path(project: dict[str, Any], name: str) -> str:
    """Return a path under factory_tasks."""
    return f"{str(project['task_root']).rstrip('/')}/{name}"


def _read_task_json(
    root: Path, project: dict[str, Any], name: str
) -> dict[str, Any] | None:
    """Read a factory task JSON artifact when present."""
    rel = _task_path(project, name)
    if not resolve_repo_path(rel, root).is_file():
        return None
    data = safe_load_json(rel, root)
    return data if isinstance(data, dict) else None


def _latest_application_reasons(
    root: Path, project: dict[str, Any], project_state: dict[str, Any]
) -> list[str]:
    """Collect latest application rejection reasons."""
    patch_plan = _read_task_json(root, project, "patch_plan.json")
    if isinstance(patch_plan, dict):
        validation = patch_plan.get("validation")
        if isinstance(validation, dict):
            reasons = validation.get("reasons")
            if isinstance(reasons, list):
                return [str(reason) for reason in reasons]
    reasons = project_state.get("last_application_reasons")
    if isinstance(reasons, list):
        return [str(reason) for reason in reasons]
    return []


def _attempt(project_state: dict[str, Any], trigger: str) -> int:
    """Return the next per-trigger recovery attempt."""
    attempts = project_state.get("recovery_attempts")
    if not isinstance(attempts, dict):
        return 1
    try:
        return int(attempts.get(trigger, 0) or 0) + 1
    except (TypeError, ValueError):
        return 1


def _action(type_: str, path: str = "", detail: str = "") -> RecoveryAction:
    return RecoveryAction(type=type_, path=path, detail=detail)


# Issue #37: same failure class this many times in a row → stop blind-retrying
# and escalate to a classified park (recovery is unlikely to succeed by repeat).
ESCALATE_AFTER = 3
_HISTORY_CAP = 8

# Failure taxonomy (most-specific markers first). One class drives the recovery
# strategy and the diagnosis, instead of ad-hoc per-reason string matches.
CLASS_NO_CONTENT = "NO_CONTENT"
CLASS_PROPOSAL_DESYNC = "PROPOSAL_DESYNC"
CLASS_SYNTAX = "SYNTAX"
CLASS_INCOMPLETE = "INCOMPLETE"
CLASS_LINT = "LINT"
CLASS_CONTRACT = "CONTRACT"
CLASS_UNKNOWN = "UNKNOWN"

# Per-class mitigation shown on an escalation/budget park, so the owner sees a
# diagnosis + next step instead of a bare "budget exhausted".
_MITIGATION: dict[str, str] = {
    CLASS_NO_CONTENT: (
        "the model keeps returning empty file content — constrain it to emit "
        "full file bodies, or switch the coder model"
    ),
    CLASS_PROPOSAL_DESYNC: (
        "proposal/approval id desync persists — clear approval and re-propose "
        "from a clean state"
    ),
    CLASS_SYNTAX: (
        "the model repeatedly emits invalid Python — tighten the coder output "
        "format (no prose/fences) or switch to a stronger coder model"
    ),
    CLASS_INCOMPLETE: (
        "the implementation keeps missing required behaviors/tests — reduce the "
        "task scope or split the checklist item"
    ),
    CLASS_LINT: (
        "the patch keeps failing lint quality — consider a deterministic "
        "lint-autofix pass before apply"
    ),
    CLASS_CONTRACT: (
        "proposed work violates the architecture contract — revise the plan "
        "within the contract, or adjust the contract"
    ),
    CLASS_UNKNOWN: "owner review required — see the rejection reasons",
}


def classify_failure(reasons: list[str]) -> str:
    """Classify application rejection reasons into a single failure class.

    Most-specific markers win, so a patch that is both incomplete and lint-dirty
    is treated as INCOMPLETE (re-propose) rather than LINT (regenerate).
    """
    blob = "\n".join(reasons).lower()
    if "no content provided" in blob:
        return CLASS_NO_CONTENT
    if "does not match the approved proposal" in blob:
        return CLASS_PROPOSAL_DESYNC
    if "syntax error" in blob:
        return CLASS_SYNTAX
    if any(
        marker in blob
        for marker in (
            "does not include or declare validation tests",
            "missing behavior",
            "missing test",
            "completeness",
            "acceptance criteria require tests",
            "placeholder function body",
        )
    ):
        return CLASS_INCOMPLETE
    if "unused import" in blob or re.search(r"\b[ef]\d{3}\b", blob):
        return CLASS_LINT
    if any(
        m in blob for m in ("forbidden", "outside the project", "contract")
    ):
        return CLASS_CONTRACT
    return CLASS_UNKNOWN


def _trailing_repeats(history: object, cls: str) -> int:
    """Count how many of the most-recent history entries equal ``cls``."""
    if not isinstance(history, list):
        return 0
    count = 0
    for entry in reversed(history):
        if entry == cls:
            count += 1
        else:
            break
    return count


_REGEN_ARTIFACTS = (
    "patch_plan.json",
    "PATCH_PLAN.md",
    "APPLICATION_REPORT.md",
)
_REVISE_ARTIFACTS = (
    "coder_proposal.json",
    "CODER_PROPOSAL.md",
    *_REGEN_ARTIFACTS,
)


def _regenerate_actions() -> list[RecoveryAction]:
    return [_action("retire_artifact", name) for name in _REGEN_ARTIFACTS]


def _revise_actions(detail: str) -> list[RecoveryAction]:
    return [
        _action(
            "clear_approval",
            "approved_proposal.json",
            "stale approval targets a proposal that cannot pass application",
        ),
        *[_action("retire_artifact", name) for name in _REVISE_ARTIFACTS],
        _action("request_new_proposal", detail=detail),
    ]


def plan_recovery(
    *,
    root: Path,
    project: dict[str, Any],
    project_state: dict[str, Any],
    max_attempts: int = 3,
    client: Any | None = None,
    model: str | None = None,
) -> RecoveryDecision:
    """Plan recovery for the latest project blocker.

    The decision is **adjudicator-led** when a reviewer model is available
    (``client``/``model``): the adjudicator (9E.S2) judges the rejection
    reasons and Python maps its graded disposition onto the bounded recovery
    decision vocabulary. With no model — or when the adjudicator cannot judge an
    ambiguous block — recovery **degrades to the deterministic rail** below
    (the #37 ``classify_failure`` router), never to a fake pass. The
    deterministic ``classify_failure`` is also kept purely for the
    ``failure_class`` observability tag.
    """
    trigger = str(project_state.get("current_blocker") or "")
    if (
        not trigger
        and project_state.get("last_application_status") == "rejected"
    ):
        trigger = APPLICATION_REJECTED
    attempt = _attempt(project_state, trigger)
    reasons = _latest_application_reasons(root, project, project_state)
    recovery_id = f"REC-{attempt:03d}"
    cls = classify_failure(reasons)
    # How many times this exact failure class has already repeated in a row.
    repeats = _trailing_repeats(
        project_state.get("recovery_class_history"), cls
    )

    def _park(reason: str, *, disposition: str = "") -> RecoveryDecision:
        return RecoveryDecision(
            recovery_id=recovery_id,
            trigger=trigger or "unknown",
            trigger_stage="recovery",
            trigger_reasons=reasons,
            decision="park",
            reason=reason,
            target_stage="owner",
            actions=[_action("record_owner_question", detail=reason)],
            attempt=attempt,
            max_attempts=max_attempts,
            failure_class=cls,
            disposition=disposition,
        )

    def _regenerate(reason: str, *, source: str, disposition: str = "") -> (
        RecoveryDecision
    ):
        return RecoveryDecision(
            recovery_id=recovery_id,
            trigger=trigger,
            trigger_stage="application",
            trigger_reasons=reasons,
            decision="regenerate_patch",
            reason=reason,
            target_stage="application",
            actions=_regenerate_actions(),
            attempt=attempt,
            max_attempts=max_attempts,
            failure_class=cls,
            source=source,
            disposition=disposition,
        )

    def _revise(reason: str, detail: str, *, source: str, disposition: str = "") -> (
        RecoveryDecision
    ):
        return RecoveryDecision(
            recovery_id=recovery_id,
            trigger=trigger,
            trigger_stage="application",
            trigger_reasons=reasons,
            decision="revise_proposal",
            reason=reason,
            target_stage="coder",
            actions=_revise_actions(detail),
            attempt=attempt,
            max_attempts=max_attempts,
            failure_class=cls,
            source=source,
            disposition=disposition,
        )

    # Escalate instead of blind-retrying: budget spent, OR the same failure class
    # has already repeated enough that another identical retry is unlikely to
    # help. Park with a CLASSIFIED diagnosis + mitigation, never a bare message.
    # This is a safety rail (not a decision heuristic) so it fires before any
    # adjudication.
    if attempt > max_attempts or repeats >= ESCALATE_AFTER:
        why = (
            f"recovery budget exhausted after {attempt - 1} attempt(s)"
            if attempt > max_attempts
            else f"repeated {cls} failures ({repeats + 1}x) — retrying is "
            "unlikely to help"
        )
        return _park(f"Escalated ({cls}): {why}. {_MITIGATION.get(cls, '')}")

    # Adjudicator-led decision (the brain). Only honoured when the adjudicator
    # actually resolved the case — its deterministic fast-paths (``source ==
    # "deterministic"``: floor/all-fixable/advisory) or a real model judgement
    # (``source == "ollama"``). A ``"fallback"`` source means it could not judge
    # the ambiguous block, so we drop through to the deterministic rail.
    if client is not None and model and reasons:
        adj = adjudicate(
            reasons, client=client, model=model, context=f"Failure class: {cls}"
        )
        if adj.source in ("deterministic", "ollama"):
            return _decision_from_disposition(
                adj, regenerate=_regenerate, revise=_revise, park=_park
            )

    # Deterministic rail. regenerate_patch keeps the authorized proposal and
    # rebuilds the patch; revise_proposal clears the approval and re-proposes.
    if cls in (CLASS_SYNTAX, CLASS_LINT, CLASS_NO_CONTENT):
        return _regenerate(
            f"Application rejected ({cls}); regenerate the patch plan.",
            source="deterministic",
        )

    if cls in (CLASS_INCOMPLETE, CLASS_PROPOSAL_DESYNC):
        detail = (
            "New proposal must implement every acceptance criterion and add a "
            "test for each behavior."
            if cls == CLASS_INCOMPLETE
            else "Re-propose cleanly so the patch and approval ids match."
        )
        return _revise(
            f"Application rejected ({cls}); request a fresh proposal.",
            detail,
            source="deterministic",
        )

    # CONTRACT / UNKNOWN: no safe deterministic auto-fix — park with diagnosis.
    return _park(
        f"No deterministic recovery for {cls}. {_MITIGATION.get(cls, '')}"
    )


def _decision_from_disposition(
    adj: Adjudication,
    *,
    regenerate: Any,
    revise: Any,
    park: Any,
) -> RecoveryDecision:
    """Map an adjudicator disposition onto the bounded recovery vocabulary.

    The judgement already happened in the adjudicator; this is a flat, total
    mapping (no per-class heuristics), staying within the validated
    ``DECISIONS`` allow-list. ``fix``/``accept`` rebuild the patch (the
    apply-path autofix handles fixables on regeneration); ``scope_down``/
    ``revise``/``redirect`` request a fresh, narrower/realigned proposal;
    ``escalate``/``reject_unsafe`` park for the owner.
    """
    note = adj.rationale or "adjudicator decision"
    if adj.disposition in (FIXIT, ACCEPT):
        return regenerate(
            f"Adjudicated '{adj.disposition}': {note}. Regenerate the patch.",
            source="adjudicator",
            disposition=adj.disposition,
        )
    if adj.disposition == SCOPE_DOWN:
        return revise(
            f"Adjudicated 'scope_down': {note}. Re-propose only the in-focus "
            "deliverable.",
            "Re-propose a narrower patch: keep only the in-focus deliverable "
            "and defer the extra modules.",
            source="adjudicator",
            disposition=adj.disposition,
        )
    if adj.disposition in (REVISE, REDIRECT):
        detail = (
            "Re-propose so the patch realigns with the project goal/seed."
            if adj.disposition == REDIRECT
            else "Re-propose a complete, correct patch that satisfies the "
            "acceptance criteria."
        )
        return revise(
            f"Adjudicated '{adj.disposition}': {note}. Request a fresh proposal.",
            detail,
            source="adjudicator",
            disposition=adj.disposition,
        )
    # ESCALATE / REJECT_UNSAFE (and any unmapped disposition) → owner.
    safety = " (safety floor)" if adj.disposition == REJECT_UNSAFE else ""
    return park(
        f"Adjudicated '{adj.disposition or 'escalate'}'{safety}: {note}.",
        disposition=adj.disposition or ESCALATE,
    )


def validate_decision(decision: RecoveryDecision) -> list[str]:
    """Return validation reasons for an invalid recovery decision."""
    reasons: list[str] = []
    if decision.decision not in DECISIONS:
        reasons.append(f"Unknown recovery decision: {decision.decision}")
    for action in decision.actions:
        if action.type not in ACTION_TYPES:
            reasons.append(f"Unknown recovery action: {action.type}")
        if action.path and (
            action.path.startswith("/")
            or ".." in Path(action.path).parts
            or "/" in action.path
        ):
            reasons.append(
                f"Recovery action path must be a factory_tasks file name: {action.path}"
            )
    return reasons


def recovery_to_dict(decision: RecoveryDecision) -> dict[str, Any]:
    """Serialize a recovery decision."""
    return {
        "recovery_id": decision.recovery_id,
        "trigger": decision.trigger,
        "failure_class": decision.failure_class,
        "trigger_stage": decision.trigger_stage,
        "trigger_reasons": list(decision.trigger_reasons),
        "decision": decision.decision,
        "reason": decision.reason,
        "target_stage": decision.target_stage,
        "actions": [
            {"type": a.type, "path": a.path, "detail": a.detail}
            for a in decision.actions
        ],
        "attempt": decision.attempt,
        "max_attempts": decision.max_attempts,
        "source": decision.source,
        "disposition": decision.disposition,
        "validation": {
            "status": "valid" if decision.valid else "rejected",
            "reasons": list(decision.validation_reasons),
        },
    }


def render_recovery_md(decision: RecoveryDecision) -> str:
    """Render a Markdown recovery decision."""
    lines = [
        "# Recovery Decision",
        "",
        f"- Recovery ID: `{decision.recovery_id}`",
        f"- Source: `{decision.source}`",
        f"- Disposition: `{decision.disposition or 'n/a'}`",
        f"- Trigger: `{decision.trigger}`",
        f"- Trigger stage: `{decision.trigger_stage}`",
        f"- Decision: `{decision.decision}`",
        f"- Target stage: `{decision.target_stage}`",
        f"- Attempt: `{decision.attempt}/{decision.max_attempts}`",
        f"- Valid: `{str(decision.valid).lower()}`",
        "",
        "## Reason",
        "",
        decision.reason or "_None._",
        "",
        "## Trigger Reasons",
        "",
        *([f"- {r}" for r in decision.trigger_reasons] or ["_None._"]),
        "",
        "## Actions",
        "",
    ]
    if decision.actions:
        for action in decision.actions:
            suffix = f" `{action.path}`" if action.path else ""
            detail = f" - {action.detail}" if action.detail else ""
            lines.append(f"- `{action.type}`{suffix}{detail}")
    else:
        lines.append("_None._")
    if decision.validation_reasons:
        lines.extend(["", "## Validation Reasons", ""])
        lines.extend(f"- {r}" for r in decision.validation_reasons)
    lines.append("")
    return "\n".join(lines)


def _retire_task_artifact(
    root: Path, project: dict[str, Any], name: str
) -> bool:
    """Delete one factory_tasks artifact by file name."""
    rel = _task_path(project, name)
    target = resolve_repo_path(rel, root)
    task_root = resolve_repo_path(str(project["task_root"]), root)
    if target != task_root and task_root not in target.parents:
        raise RuntimeError(f"Recovery artifact path escapes task root: {name}")
    if target.is_file():
        target.unlink()
        return True
    return False


def _record_attempt(
    project_state: dict[str, Any], decision: RecoveryDecision
) -> None:
    attempts = project_state.get("recovery_attempts")
    if not isinstance(attempts, dict):
        attempts = {}
        project_state["recovery_attempts"] = attempts
    attempts[decision.trigger] = decision.attempt
    project_state["last_recovery_decision"] = decision.decision
    project_state["last_recovery_id"] = decision.recovery_id
    # Track the failure-class trail so repeated identical failures can escalate
    # instead of blind-retrying (issue #37 §2).
    if decision.failure_class:
        history = project_state.get("recovery_class_history")
        if not isinstance(history, list):
            history = []
        history.append(decision.failure_class)
        project_state["recovery_class_history"] = history[-_HISTORY_CAP:]


def apply_recovery(
    *,
    root: Path,
    project: dict[str, Any],
    project_state: dict[str, Any],
    active_run: dict[str, Any],
    decision: RecoveryDecision,
) -> list[str]:
    """Apply allowed recovery runtime/artifact actions."""
    validation_reasons = validate_decision(decision)
    if validation_reasons:
        object.__setattr__(decision, "valid", False)
        object.__setattr__(decision, "validation_reasons", validation_reasons)
    changed: list[str] = []
    if decision.valid:
        for action in decision.actions:
            if action.type == "clear_approval":
                revoke_proposal(project, root)
                changed.append("approved_proposal.json")
            elif action.type == "retire_artifact" and action.path:
                if _retire_task_artifact(root, project, action.path):
                    changed.append(action.path)

    _record_attempt(project_state, decision)
    if decision.decision in {
        "revise_proposal",
        "regenerate_patch",
        "replan_task",
    }:
        project_state["current_blocker"] = None
        active_run["current_blocker"] = None
        active_run["resume_from"] = (
            f"Recovery {decision.decision}; run advance to resume at "
            f"{decision.target_stage}."
        )
    elif decision.decision == "park":
        blocker = (
            RECOVERY_EXHAUSTED
            if decision.attempt > decision.max_attempts
            else NEEDS_OWNER_DECISION
        )
        project_state["current_blocker"] = blocker
        active_run["current_blocker"] = blocker
        active_run["resume_from"] = (
            "Recovery parked for owner review; see RECOVERY_DECISION.md."
        )

    task_root = str(project["task_root"])
    safe_write_json(
        _task_path(project, RECOVERY_JSON),
        recovery_to_dict(decision),
        repo_root=root,
        allowed_roots=[task_root],
    )
    safe_write_text(
        _task_path(project, RECOVERY_MD),
        render_recovery_md(decision),
        repo_root=root,
        allowed_roots=[task_root],
    )
    return changed


def _build_reviewer_client(
    factory_config: dict[str, Any] | None,
    models_config: dict[str, Any] | None,
) -> tuple[Any | None, str | None]:
    """Build the adjudicator (reviewer) LLM client from config, if available.

    Returns ``(None, None)`` when config is absent or malformed so recovery
    degrades to the deterministic rail rather than failing — never a fake pass.
    """
    if not factory_config or not models_config:
        return None, None
    try:
        ollama = factory_config["ollama"]
        model = str(models_config["models"]["reviewer"])
        client = OllamaClient(
            base_url=str(ollama["base_url"]),
            timeout_seconds=int(ollama["timeout_seconds"]),
            stream=bool(ollama["stream"]),
        )
    except (KeyError, TypeError, ValueError):
        return None, None
    return client, model


def run_recovery_router(
    *,
    root: Path,
    project: dict[str, Any],
    project_state: dict[str, Any],
    active_run: dict[str, Any],
    max_attempts: int = 3,
    factory_config: dict[str, Any] | None = None,
    models_config: dict[str, Any] | None = None,
) -> tuple[RecoveryDecision, list[str]]:
    """Plan and apply recovery (adjudicator-led when a reviewer model is set)."""
    client, model = _build_reviewer_client(factory_config, models_config)
    decision = plan_recovery(
        root=root,
        project=project,
        project_state=project_state,
        max_attempts=max_attempts,
        client=client,
        model=model,
    )
    changed = apply_recovery(
        root=root,
        project=project,
        project_state=project_state,
        active_run=active_run,
        decision=decision,
    )
    return decision, changed
