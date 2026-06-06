#!/usr/bin/env python3
"""Phase 8 satisfaction checker for Crazy Factory.

The factory may declare a project ``satisfied`` only when the milestone
checklist is complete, there are no critical blockers, validation has passed,
and the work is recorded. This module evaluates those criteria, writes a
satisfaction report and criteria record, and sets the ``satisfied`` flag —
which itself pauses further automatic work pending owner review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flags import set_flag
from repo_tools import safe_write_text
from workbench_growth import workbench_metrics


@dataclass(frozen=True)
class SatisfactionVerdict:
    """Whether a project may be declared satisfied.

    Attributes:
        satisfied: ``True`` when every satisfaction criterion is met.
        reasons: Criteria that are NOT yet met. Empty when satisfied.
    """

    satisfied: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_satisfaction(
    *,
    checklist_text: str,
    project_state: dict[str, Any],
    source_file_count: int | None = None,
    test_file_count: int | None = None,
) -> SatisfactionVerdict:
    """Evaluate satisfaction criteria from the checklist and state.

    Args:
        checklist_text: Contents of the project ``MASTER_CHECKLIST.md``.
        project_state: Active project state snapshot.
        source_file_count: Real source files in the workbench. When provided
            (Issue #38 #6/#7), a project with no source — or no test — is NOT
            satisfied: a software factory that produced no software has not
            finished, however clean the checklist looks. ``None`` skips the
            check (kept for callers without workbench access).
        test_file_count: Real test files in the workbench (Minimum Viable Code
            Birth requires at least one).

    Returns:
        The satisfaction verdict; ``reasons`` lists unmet criteria.
    """
    reasons: list[str] = []

    if "- [ ]" in checklist_text:
        reasons.append("Open checklist items remain")
    if not checklist_text.strip():
        reasons.append("Checklist is empty")
    if project_state.get("current_blocker"):
        reasons.append(
            f"Active blocker: {project_state.get('current_blocker')}"
        )
    if project_state.get("last_validation_status") != "passed":
        reasons.append("Validation has not passed")
    if source_file_count is not None and source_file_count == 0:
        reasons.append("Application has no source code (empty project)")
    if test_file_count is not None and test_file_count == 0:
        reasons.append("Application has no tests (code birth requires a test)")

    return SatisfactionVerdict(satisfied=not reasons, reasons=reasons)


def render_satisfaction_report_md(
    verdict: SatisfactionVerdict, project_state: dict[str, Any]
) -> str:
    """Render ``SATISFACTION_REPORT.md``.

    Args:
        verdict: The satisfaction verdict.
        project_state: Active project state snapshot.

    Returns:
        Markdown satisfaction report.
    """
    heading = (
        "Project satisfied"
        if verdict.satisfied
        else "Project not yet satisfied"
    )
    lines = [
        "# Satisfaction Report",
        "",
        f"- Status: `{'satisfied' if verdict.satisfied else 'not_satisfied'}`",
        f"- Project: `{project_state.get('project')}`",
        f"- Milestone: `{project_state.get('current_milestone')}`",
        "",
        f"## {heading}",
        "",
        "## Unmet Criteria",
        "",
        *(
            [f"- {r}" for r in verdict.reasons]
            or ["_None — all criteria met._"]
        ),
        "",
        "## Owner Review",
        "",
        "- Owner review is recommended before acting on a satisfied state.",
        "",
    ]
    return "\n".join(lines)


def render_satisfaction_criteria_md() -> str:
    """Render the static ``SATISFACTION_CRITERIA.md`` reference.

    Returns:
        Markdown describing the satisfaction criteria.
    """
    return (
        "# Satisfaction Criteria\n\n"
        "A project may be declared satisfied only when ALL hold:\n\n"
        "- The milestone checklist has no open items.\n"
        "- There are no critical blockers.\n"
        "- Validation has passed.\n"
        "- Reports and known risks are recorded.\n"
        "- Owner review is recommended before relying on the result.\n"
    )


def run_satisfaction(
    *,
    root: Path,
    project: dict[str, Any],
    checklist_text: str,
    project_state: dict[str, Any],
    state_dir: str = "state",
) -> SatisfactionVerdict:
    """Evaluate satisfaction, record artifacts, and flag when satisfied.

    Args:
        root: Absolute repository root.
        project: Active project configuration mapping.
        checklist_text: Contents of the project ``MASTER_CHECKLIST.md``.
        project_state: Active project state snapshot.
        state_dir: Repository-relative state directory.

    Returns:
        The satisfaction verdict.
    """
    # Issue #38 #6/#7: a project is not "satisfied" while the workbench is empty
    # or has no test. Resolve the workbench against root (CWD-independent).
    app_path = str(project["app_path"])
    wb = app_path if Path(app_path).is_absolute() else str(root / app_path)
    metrics = workbench_metrics(wb)
    verdict = evaluate_satisfaction(
        checklist_text=checklist_text,
        project_state=project_state,
        source_file_count=metrics.source_files,
        test_file_count=metrics.test_files,
    )
    report_root = str(project["report_root"])
    task_root = str(project["task_root"])
    safe_write_text(
        str(Path(report_root) / "SATISFACTION_REPORT.md"),
        render_satisfaction_report_md(verdict, project_state),
        repo_root=root,
        allowed_roots=[report_root],
    )
    safe_write_text(
        str(Path(task_root) / "SATISFACTION_CRITERIA.md"),
        render_satisfaction_criteria_md(),
        repo_root=root,
        allowed_roots=[task_root],
    )
    if verdict.satisfied:
        set_flag(
            "satisfied",
            root,
            state_dir=state_dir,
            note="Set by satisfaction checker; owner review recommended.",
        )
    return verdict
