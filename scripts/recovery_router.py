#!/usr/bin/env python3
"""Deterministic-first recovery routing for Crazy Factory.

This module is the Phase 9D recovery entry point for known, model-free failure
patterns. It returns structured decisions, validates a small action enum, and
applies only factory-runtime artifact transitions inside the project workbench.
LLM recovery can sit above this later as an escalation layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


def plan_recovery(
    *,
    root: Path,
    project: dict[str, Any],
    project_state: dict[str, Any],
    max_attempts: int = 3,
) -> RecoveryDecision:
    """Plan deterministic recovery for the latest project blocker."""
    trigger = str(project_state.get("current_blocker") or "")
    if (
        not trigger
        and project_state.get("last_application_status") == "rejected"
    ):
        trigger = APPLICATION_REJECTED
    attempt = _attempt(project_state, trigger)
    reasons = _latest_application_reasons(root, project, project_state)
    reason_blob = "\n".join(reasons).lower()
    recovery_id = f"REC-{attempt:03d}"

    if attempt > max_attempts:
        return RecoveryDecision(
            recovery_id=recovery_id,
            trigger=trigger,
            trigger_stage="recovery",
            trigger_reasons=reasons,
            decision="park",
            reason="Recovery attempt budget exhausted.",
            target_stage="owner",
            actions=[
                _action(
                    "record_owner_question",
                    detail="Recovery exhausted; owner review is required.",
                )
            ],
            attempt=attempt,
            max_attempts=max_attempts,
        )

    if trigger == APPLICATION_REJECTED and (
        "does not include or declare validation tests" in reason_blob
    ):
        return RecoveryDecision(
            recovery_id=recovery_id,
            trigger=trigger,
            trigger_stage="application",
            trigger_reasons=reasons,
            decision="revise_proposal",
            reason=(
                "Application rejected a source-only implementation; request a "
                "fresh proposal that includes validation tests."
            ),
            target_stage="coder",
            actions=[
                _action(
                    "clear_approval",
                    "approved_proposal.json",
                    "stale approval targets a proposal that cannot pass application",
                ),
                _action("retire_artifact", "coder_proposal.json"),
                _action("retire_artifact", "CODER_PROPOSAL.md"),
                _action("retire_artifact", "patch_plan.json"),
                _action("retire_artifact", "PATCH_PLAN.md"),
                _action("retire_artifact", "APPLICATION_REPORT.md"),
                _action(
                    "request_new_proposal",
                    detail="New proposal must include source and tests.",
                ),
            ],
            attempt=attempt,
            max_attempts=max_attempts,
        )

    if (
        trigger == APPLICATION_REJECTED
        and "python syntax error" in reason_blob
    ):
        return RecoveryDecision(
            recovery_id=recovery_id,
            trigger=trigger,
            trigger_stage="application",
            trigger_reasons=reasons,
            decision="regenerate_patch",
            reason="Application rejected a syntactically invalid patch plan.",
            target_stage="application",
            actions=[
                _action("retire_artifact", "patch_plan.json"),
                _action("retire_artifact", "PATCH_PLAN.md"),
                _action("retire_artifact", "APPLICATION_REPORT.md"),
            ],
            attempt=attempt,
            max_attempts=max_attempts,
        )

    if trigger == APPLICATION_REJECTED and "unused import" in reason_blob:
        return RecoveryDecision(
            recovery_id=recovery_id,
            trigger=trigger,
            trigger_stage="application",
            trigger_reasons=reasons,
            decision="regenerate_patch",
            reason=(
                "Application rejected a patch with deterministic lint-quality "
                "violations; regenerate the patch plan without changing the "
                "authorized proposal."
            ),
            target_stage="application",
            actions=[
                _action("retire_artifact", "patch_plan.json"),
                _action("retire_artifact", "PATCH_PLAN.md"),
                _action("retire_artifact", "APPLICATION_REPORT.md"),
            ],
            attempt=attempt,
            max_attempts=max_attempts,
        )

    return RecoveryDecision(
        recovery_id=recovery_id,
        trigger=trigger or "unknown",
        trigger_stage="unknown",
        trigger_reasons=reasons,
        decision="park",
        reason="No deterministic recovery rule matched.",
        target_stage="owner",
        actions=[
            _action(
                "record_owner_question",
                detail="No deterministic recovery rule matched; owner review required.",
            )
        ],
        attempt=attempt,
        max_attempts=max_attempts,
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


def run_recovery_router(
    *,
    root: Path,
    project: dict[str, Any],
    project_state: dict[str, Any],
    active_run: dict[str, Any],
    max_attempts: int = 3,
) -> tuple[RecoveryDecision, list[str]]:
    """Plan and apply deterministic recovery."""
    decision = plan_recovery(
        root=root,
        project=project,
        project_state=project_state,
        max_attempts=max_attempts,
    )
    changed = apply_recovery(
        root=root,
        project=project,
        project_state=project_state,
        active_run=active_run,
        decision=decision,
    )
    return decision, changed
