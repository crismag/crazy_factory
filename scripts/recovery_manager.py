#!/usr/bin/env python3
"""Phase 8 recovery manager for Crazy Factory.

When the factory stalls, the recovery manager records what happened and a
concrete recovery plan, and blocks the factory so it stops retrying blindly
and waits for owner attention. It writes reports and a recovery plan, and sets
the ``blocked`` flag; it never edits application code or runs phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flags import set_flag
from repo_tools import safe_write_text
from stall_detector import StallSignal


@dataclass(frozen=True)
class RecoveryPlan:
    """A recommended recovery for a stalled factory.

    Attributes:
        actions: Ordered recovery actions for the owner or next run.
        set_blocked: Whether the factory should be blocked pending review.
    """

    actions: list[str] = field(default_factory=list)
    set_blocked: bool = True


def build_recovery_plan(
    stall_signal: StallSignal, project_state: dict[str, Any]
) -> RecoveryPlan:
    """Derive a recovery plan from a stall signal.

    Args:
        stall_signal: The detected stall.
        project_state: Active project state snapshot.

    Returns:
        A recovery plan. Blocking is recommended for any real stall.
    """
    blocker = str(project_state.get("current_blocker") or "")
    actions: list[str] = [
        "Stop automatic retries; the factory is blocked for owner review.",
    ]
    if "contract" in blocker:
        actions.append(
            "Review the latest TASK_EXPANSION/NEXT_ACTION and re-plan a "
            "smaller, bounded contract."
        )
    if "proposal" in blocker:
        actions.append(
            "Review CODER_PROPOSAL.md; tighten the contract scope before "
            "re-proposing."
        )
    if "application" in blocker:
        actions.append(
            "Review PATCH_PLAN.md; confirm targets and re-approve before any "
            "apply."
        )
    if "validation" in blocker:
        actions.append(
            "Review VALIDATION_REPORT.md; fix failing checks before promotion."
        )
    if any("model unavailable" in r.lower() for r in stall_signal.reasons):
        actions.append(
            "Check that the local Ollama service is running and reachable."
        )
    actions.append(
        "Clear state/blocked.flag once the underlying issue is resolved."
    )
    return RecoveryPlan(
        actions=actions, set_blocked=bool(stall_signal.stalled)
    )


def render_stall_report_md(
    stall_signal: StallSignal, project_state: dict[str, Any]
) -> str:
    """Render the project's ``STALL_REPORT.md`` body.

    Args:
        stall_signal: The detected stall.
        project_state: Active project state snapshot.

    Returns:
        Markdown stall report.
    """
    lines = [
        "# Stall Report",
        "",
        f"- Stalled: `{str(stall_signal.stalled).lower()}`",
        f"- Task: `{project_state.get('current_task')}`",
        f"- Failure count: `{project_state.get('failure_count')}`",
        f"- Current blocker: `{project_state.get('current_blocker')}`",
        "",
        "## Conditions",
        "",
        *([f"- {r}" for r in stall_signal.reasons] or ["_None._"]),
        "",
    ]
    return "\n".join(lines)


def render_recovery_plan_md(plan: RecoveryPlan) -> str:
    """Render ``RECOVERY_PLAN.md``.

    Args:
        plan: The recovery plan.

    Returns:
        Markdown recovery plan.
    """
    lines = [
        "# Recovery Plan",
        "",
        f"- Block for owner review: `{str(plan.set_blocked).lower()}`",
        "",
        "## Recommended Actions",
        "",
        *[f"- {a}" for a in plan.actions],
        "",
    ]
    return "\n".join(lines)


def run_recovery(
    *,
    root: Path,
    project: dict[str, Any],
    stall_signal: StallSignal,
    project_state: dict[str, Any],
    state_dir: str = "state",
) -> RecoveryPlan:
    """Record stall and recovery artifacts and block the factory.

    Args:
        root: Absolute repository root.
        project: Active project configuration mapping.
        stall_signal: The detected stall.
        project_state: Active project state snapshot.
        state_dir: Repository-relative state directory.

    Returns:
        The recovery plan that was recorded.
    """
    plan = build_recovery_plan(stall_signal, project_state)
    # Stall/recovery reports belong to the active project — write them inside
    # its report folder, never the engine root.
    report_root = str(project["report_root"])
    safe_write_text(
        str(Path(report_root) / "STALL_REPORT.md"),
        render_stall_report_md(stall_signal, project_state),
        repo_root=root,
        allowed_roots=[report_root],
    )
    safe_write_text(
        str(Path(report_root) / "RECOVERY_REPORT.md"),
        render_recovery_plan_md(plan),
        repo_root=root,
        allowed_roots=[report_root],
    )
    task_root = str(project["task_root"])
    safe_write_text(
        str(Path(task_root) / "RECOVERY_PLAN.md"),
        render_recovery_plan_md(plan),
        repo_root=root,
        allowed_roots=[task_root],
    )
    if plan.set_blocked:
        set_flag(
            "blocked",
            root,
            state_dir=state_dir,
            note="Set by recovery manager after a detected stall.",
        )
    return plan
