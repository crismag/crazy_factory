#!/usr/bin/env python3
"""Write and inspect human-readable Crazy Factory dry-run reports.

Reports make autonomous activity observable and recoverable. This module writes
one application-specific report per tick and appends compact summaries to the
factory-level activity and daily reports. All writes use explicit approved
directories through :mod:`repo_tools`.

Example:
    Print the accumulated activity blog from the repository root::

        python3 scripts/report_writer.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from project_registry import (
    active_project_id,
    load_registry,
    resolve_project,
)
from repo_tools import (
    find_repo_root,
    resolve_repo_path,
    safe_read_text,
    safe_write_text,
)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime.

    Returns:
        Current UTC datetime.
    """
    return datetime.now(timezone.utc)


def _timestamp(now: datetime) -> str:
    """Format a datetime for human-readable report content.

    Args:
        now: Timezone-aware datetime to format.

    Returns:
        UTC-style timestamp such as ``"2026-06-02T20:21:02Z"``.
    """
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _filename_timestamp(now: datetime) -> str:
    """Format a datetime for a filesystem-friendly report filename.

    Args:
        now: Timezone-aware datetime to format.

    Returns:
        Compact timestamp such as ``"20260602T202102Z"``.
    """
    return now.strftime("%Y%m%dT%H%M%SZ")


def _render_contract_section(
    *,
    status: str | None,
    source: str | None,
    detail: str | None,
    reasons: list[str] | None,
    files: list[str] | None,
    authorized: bool,
) -> str:
    """Render the optional Task Contract section of a session report.

    Args:
        status: Contract verdict label, or ``None`` to omit the section.
        source: Planning source of the contract.
        detail: Human-readable explanation of the source.
        reasons: Rejection reasons, rendered only for a rejected contract.
        files: Contract files written or preserved this tick.
        authorized: Whether the contract is owner-authorized (preserved).

    Returns:
        Markdown section text, or an empty string when ``status`` is ``None``.
    """
    if status is None:
        return ""
    authorized_line = (
        "- Authorized: `true` (owner-authorized; preserved)\n"
        if authorized
        else "- Authorized: `false` (owner approval required)\n"
    )
    files_label = (
        "- Contract files preserved:\n"
        if authorized
        else "- Contract files written:\n"
    )
    rejection = (
        "- Rejection reasons:\n"
        + "".join(f"  - {reason}\n" for reason in (reasons or []))
        if status == "rejected"
        else ""
    )
    return (
        "\n## Task Contract\n\n"
        f"- Source: `{source}`\n"
        f"- Detail: {detail}\n"
        f"- Validation status: `{status}`\n"
        + authorized_line
        + rejection
        + files_label
        + "".join(f"  - `{path}`\n" for path in (files or []))
    )


def _render_coder_section(
    *,
    status: str | None,
    proposal_id: str | None,
    task_id: str | None,
    activated: bool,
    warnings: list[str] | None,
    blocked_paths: list[str] | None,
    files: list[str] | None,
) -> str:
    """Render the optional Coder Proposal section of a session report.

    Args:
        status: Proposal verdict label, or ``None`` to omit the section.
        proposal_id: Proposal identifier, if any.
        task_id: Task identifier the proposal serves, if any.
        activated: Whether an authorized contract activated the Coder.
        warnings: Non-fatal proposal warnings.
        blocked_paths: Paths blocked by the target boundary.
        files: Proposal files written this tick.

    Returns:
        Markdown section text, or an empty string when ``status`` is ``None``.
    """
    if status is None:
        return ""
    return (
        "\n## Coder Proposal\n\n"
        f"- Proposal ID: `{proposal_id}`\n"
        f"- Task ID: `{task_id}`\n"
        f"- Verdict: `{status}`\n"
        f"- Activated (authorized contract): `{str(activated).lower()}`\n"
        "- Applied: `false` (proposal only; no files written)\n"
        + "- Warnings:\n"
        + "".join(f"  - {w}\n" for w in (warnings or []))
        + "- Blocked paths:\n"
        + "".join(f"  - `{p}`\n" for p in (blocked_paths or []))
        + "- Proposal files:\n"
        + "".join(f"  - `{path}`\n" for path in (files or []))
    )


def _render_application_section(
    *,
    status: str | None,
    mode: str | None,
    applied: bool,
    reasons: list[str] | None,
    blocked_paths: list[str] | None,
    files: list[str] | None,
) -> str:
    """Render the optional Proposal Application section of a session report.

    Args:
        status: Application verdict label, or ``None`` to omit the section.
        mode: ``"preview_only"`` or ``"apply"``.
        applied: Whether files were actually written.
        reasons: Patch-plan rejection reasons, rendered when rejected.
        blocked_paths: Paths blocked by the boundary.
        files: Application artifact files written this tick.

    Returns:
        Markdown section text, or an empty string when ``status`` is ``None``.
    """
    if status is None:
        return ""
    rejection = (
        "- Rejection reasons:\n"
        + "".join(f"  - {r}\n" for r in (reasons or []))
        if status == "rejected"
        else ""
    )
    return (
        "\n## Proposal Application\n\n"
        f"- Mode: `{mode}`\n"
        f"- Status: `{status}`\n"
        f"- Applied: `{str(applied).lower()}`\n"
        + rejection
        + "- Blocked paths:\n"
        + "".join(f"  - `{p}`\n" for p in (blocked_paths or []))
        + "- Application files:\n"
        + "".join(f"  - `{path}`\n" for path in (files or []))
    )


def _render_validation_section(
    *,
    test_plan_status: str | None,
    test_plan_id: str | None,
    validation_status: str | None,
    validation_executed: bool,
    validation_checks: list[str] | None,
    validation_files: list[str] | None,
) -> str:
    """Render the optional Validation section of a session report.

    Args:
        test_plan_status: Test-plan verdict, or ``None`` to omit the section.
        test_plan_id: Test-plan identifier, if any.
        validation_status: Validation verdict label.
        validation_executed: Whether any check ran.
        validation_checks: ``"status command"`` lines.
        validation_files: Validation artifact files written.

    Returns:
        Markdown section text, or empty when ``test_plan_status`` is ``None``.
    """
    if test_plan_status is None:
        return ""
    return (
        "\n## Validation\n\n"
        f"- Test plan: `{test_plan_id}` (`{test_plan_status}`)\n"
        f"- Validation status: `{validation_status}`\n"
        f"- Executed: `{str(validation_executed).lower()}`\n"
        + "- Checks:\n"
        + "".join(f"  - {c}\n" for c in (validation_checks or []))
        + "- Validation files:\n"
        + "".join(f"  - `{path}`\n" for path in (validation_files or []))
    )


def _render_checkpoint_section(
    *,
    status: str | None,
    checkpoint_id: str | None,
    commit: str | None,
    committed: bool,
    excluded: list[str] | None,
) -> str:
    """Render the optional Checkpoint section of a session report.

    Args:
        status: Checkpoint verdict, or ``None`` to omit the section.
        checkpoint_id: Checkpoint identifier, when committed.
        commit: Commit hash, when committed.
        committed: Whether a checkpoint commit was created.
        excluded: Changed files outside the allowed commit paths.

    Returns:
        Markdown section text, or empty when ``status`` is ``None``.
    """
    if status is None:
        return ""
    return (
        "\n## Checkpoint\n\n"
        f"- Status: `{status}`\n"
        f"- Committed: `{str(committed).lower()}`\n"
        f"- Checkpoint ID: `{checkpoint_id}`\n"
        f"- Commit: `{commit}`\n"
        + "- Excluded (outside allowed commit paths):\n"
        + "".join(f"  - `{p}`\n" for p in (excluded or []))
    )


def append_dry_run_report(
    *,
    project_name: str,
    project_report_root: str,
    mode: str,
    context_files: list[str],
    task_files: list[str],
    git_status: str,
    factory_state: dict[str, Any],
    active_run: dict[str, Any],
    project_state: dict[str, Any],
    architect_source: str,
    architect_detail: str,
    planner_source: str,
    planner_detail: str,
    last_role_completed: str,
    planning_files: list[str],
    contract_status: str | None = None,
    contract_source: str | None = None,
    contract_detail: str | None = None,
    contract_reasons: list[str] | None = None,
    contract_files: list[str] | None = None,
    contract_authorized: bool = False,
    coder_status: str | None = None,
    coder_proposal_id: str | None = None,
    coder_task_id: str | None = None,
    coder_activated: bool = False,
    coder_warnings: list[str] | None = None,
    coder_blocked_paths: list[str] | None = None,
    coder_files: list[str] | None = None,
    application_status: str | None = None,
    application_mode: str | None = None,
    application_applied: bool = False,
    application_reasons: list[str] | None = None,
    application_blocked_paths: list[str] | None = None,
    application_files: list[str] | None = None,
    test_plan_status: str | None = None,
    test_plan_id: str | None = None,
    validation_status: str | None = None,
    validation_executed: bool = False,
    validation_checks: list[str] | None = None,
    validation_files: list[str] | None = None,
    checkpoint_status: str | None = None,
    checkpoint_id: str | None = None,
    checkpoint_commit: str | None = None,
    checkpoint_committed: bool = False,
    checkpoint_excluded: list[str] | None = None,
    repo_root: str | Path | None = None,
) -> Path:
    """Write a dry-run report and append top-level activity summaries.

    Args:
        project_name: Active application workbench name.
        project_report_root: Approved app-specific report directory.
        mode: Current factory mode. Bootstrap expects ``"dry_run"``.
        context_files: Repository-relative context files read by the tick.
        task_files: Repository-relative task files read by the tick.
        git_status: Read-only Git status captured during the tick.
        factory_state: Global persistent state snapshot.
        active_run: Current run and resume-point snapshot.
        project_state: Active project state snapshot.
        architect_source: Whether planning came from Ollama or fallback logic.
        architect_detail: Human-readable explanation of the planning source.
        planner_source: Whether planning came from Ollama or fallback logic.
        planner_detail: Human-readable explanation of the planning source.
        last_role_completed: Last worker role completed during the run.
        planning_files: Fixed planning files updated during the tick.
        contract_status: Structured-contract verdict (``"valid"`` or
            ``"rejected"``), or ``None`` when no contract step ran.
        contract_source: Whether the contract came from Ollama or fallback.
        contract_detail: Human-readable explanation of the contract source.
        contract_reasons: Rejection reasons for the contract, if any.
        contract_files: Contract files written during the tick.
        contract_authorized: Whether the recorded contract is owner-authorized
            (a preserved contract); the factory never sets this itself.
        coder_status: Coder proposal verdict label, or ``None`` when the coder
            stage did not run this tick.
        coder_proposal_id: Proposal identifier, if a proposal was produced.
        coder_task_id: Task identifier the proposal serves, if any.
        coder_activated: Whether an authorized contract activated the Coder.
        coder_warnings: Non-fatal proposal warnings, if any.
        coder_blocked_paths: Proposal paths blocked by the target boundary.
        coder_files: Proposal files written during the tick.
        application_status: Application verdict label, or ``None`` when the
            application stage did not run this tick.
        application_mode: ``"preview_only"`` or ``"apply"``.
        application_applied: Whether files were actually written.
        application_reasons: Patch-plan rejection reasons, if any.
        application_blocked_paths: Patch paths blocked by the boundary.
        application_files: Application artifact files written this tick.
        test_plan_status: Test-plan verdict label, or ``None`` when the test
            builder did not run this tick.
        test_plan_id: Test-plan identifier, if any.
        validation_status: Validation verdict label, or ``None`` when
            validation did not run.
        validation_executed: Whether any check was actually executed.
        validation_checks: ``"status command"`` lines for each check.
        validation_files: Validation artifact files written this tick.
        checkpoint_status: Checkpoint verdict label, or ``None`` when the
            checkpoint stage did not run.
        checkpoint_id: Checkpoint identifier, when committed.
        checkpoint_commit: Commit hash, when committed.
        checkpoint_committed: Whether a checkpoint commit was created.
        checkpoint_excluded: Changed files outside the allowed commit paths.
        repo_root: Optional explicit repository root, primarily for tests.

    Returns:
        Absolute path to the newly written app-specific report.

    Raises:
        RepoSafetyError: If a report destination violates write boundaries.
    """
    root = Path(repo_root or find_repo_root()).resolve()
    now = utc_now()
    stamp = _timestamp(now)
    report_name = f"session-{_filename_timestamp(now)}.md"
    app_report_path = str(Path(project_report_root) / report_name)
    contract_section = _render_contract_section(
        status=contract_status,
        source=contract_source,
        detail=contract_detail,
        reasons=contract_reasons,
        files=contract_files,
        authorized=contract_authorized,
    )
    coder_section = _render_coder_section(
        status=coder_status,
        proposal_id=coder_proposal_id,
        task_id=coder_task_id,
        activated=coder_activated,
        warnings=coder_warnings,
        blocked_paths=coder_blocked_paths,
        files=coder_files,
    )
    application_section = _render_application_section(
        status=application_status,
        mode=application_mode,
        applied=application_applied,
        reasons=application_reasons,
        blocked_paths=application_blocked_paths,
        files=application_files,
    )
    validation_section = _render_validation_section(
        test_plan_status=test_plan_status,
        test_plan_id=test_plan_id,
        validation_status=validation_status,
        validation_executed=validation_executed,
        validation_checks=validation_checks,
        validation_files=validation_files,
    )
    checkpoint_section = _render_checkpoint_section(
        status=checkpoint_status,
        checkpoint_id=checkpoint_id,
        commit=checkpoint_commit,
        committed=checkpoint_committed,
        excluded=checkpoint_excluded,
    )
    body = (
        f"# Factory Session Report\n\n"
        f"- Timestamp: `{stamp}`\n"
        f"- Mode: `{mode}`\n"
        f"- Active project: `{project_name}`\n"
        f"- Outcome: `dry-run complete`\n\n"
        f"## Context Read\n\n"
        + "".join(f"- `{path}`\n" for path in context_files)
        + "\n## Task Records Read\n\n"
        + "".join(f"- `{path}`\n" for path in task_files)
        + "\n## Mission Recovery\n\n"
        + f"- What am I working on? `{project_state['current_task']}`\n"
        + "- Why am I working on it? Current milestone: "
        + f"`{project_state['current_milestone']}`\n"
        + "- What did I finish? Last checkpoint: "
        + f"`{project_state['last_completed_checkpoint']}`\n"
        + f"- What failed? Failure count: `{project_state['failure_count']}`; "
        + f"last failed run: `{factory_state['last_failed_run']}`\n"
        + "- What remains? Read the active project's `MASTER_CHECKLIST.md`.\n"
        + f"- Where do I resume? {active_run['resume_from']}\n"
        + f"- Current blocker: `{project_state['current_blocker']}`\n"
        + "\n## Architect Dry Run\n\n"
        + f"- Source: `{architect_source}`\n"
        + f"- Detail: {architect_detail}\n"
        + "- Planning files updated:\n"
        + "".join(f"  - `{path}`\n" for path in planning_files[:1])
        + "\n## Planner Dry Run\n\n"
        + f"- Source: `{planner_source}`\n"
        + f"- Detail: {planner_detail}\n"
        + "- Planning files updated:\n"
        + "".join(f"  - `{path}`\n" for path in planning_files[1:])
        + contract_section
        + coder_section
        + application_section
        + validation_section
        + checkpoint_section
        + "\n## Reporter Outcome\n\n"
        + f"- Last role completed: `{last_role_completed}`\n"
        + "\n## Repository Status\n\n```text\n"
        + (git_status or "clean")
        + "\n```\n\n"
        + "## Safety Record\n\n"
        + f"- Architect planning source: `{architect_source}`.\n"
        + f"- Planner planning source: `{planner_source}`.\n"
        + "- No application code was modified.\n"
        + "- Task contract authorization is owner-only; the factory never "
        + "sets `authorized` itself.\n"
        + "- No git commit or push was attempted.\n"
    )
    entry = (
        f"\n## {stamp} - Dry-run tick\n\n"
        f"- Active project: `{project_name}`\n"
        f"- Result: created `{app_report_path}`\n"
        f"- Architect planning source: `{architect_source}`\n"
        f"- Planner planning source: `{planner_source}`\n"
        f"- Last role completed: `{last_role_completed}`\n"
        "- Safety: no application edit, commit, or push attempted.\n"
    )
    daily_entry = (
        f"\n## {stamp}\n\n"
        f"Dry-run tick completed for `{project_name}`. "
        f"Detailed report: `{app_report_path}`.\n"
    )
    # Reports are the only app-workbench writes performed by the bootstrap
    # tick. Each destination is constrained to an approved report subtree.
    safe_write_text(
        app_report_path,
        body,
        repo_root=root,
        allowed_roots=[project_report_root],
    )
    # The activity blog and daily report are project-owned: they live in the
    # project's report root, never in a root-level reports/ folder.
    safe_write_text(
        str(Path(project_report_root) / "ACTIVITY_BLOG.md"),
        entry,
        repo_root=root,
        allowed_roots=[project_report_root],
        append=True,
    )
    safe_write_text(
        str(Path(project_report_root) / "DAILY_REPORT.md"),
        daily_entry,
        repo_root=root,
        allowed_roots=[project_report_root],
        append=True,
    )
    return root / app_report_path


def append_control_event(
    *,
    project_name: str,
    project_report_root: str,
    outcome: str,
    detail: str,
    repo_root: str | Path | None = None,
) -> None:
    """Append a pause or stop event without modifying application files.

    Args:
        project_name: Active application workbench name.
        project_report_root: The project's own report directory.
        outcome: Short control result, such as ``"paused"`` or ``"stopped"``.
        detail: Human-readable reason for ending the tick early.
        repo_root: Optional explicit repository root, primarily for tests.

    Raises:
        RepoSafetyError: If the activity report destination is unsafe.
    """
    root = Path(repo_root or find_repo_root()).resolve()
    stamp = _timestamp(utc_now())
    entry = (
        f"\n## {stamp} - Tick {outcome}\n\n"
        f"- Active project: `{project_name}`\n"
        f"- Result: `{outcome}`\n"
        f"- Detail: {detail}\n"
        "- Safety: no planning file, application code, commit, or push "
        "change attempted.\n"
    )
    safe_write_text(
        str(Path(project_report_root) / "ACTIVITY_BLOG.md"),
        entry,
        repo_root=root,
        allowed_roots=[project_report_root],
        append=True,
    )


def main() -> int:
    """Print the active project's accumulated factory activity blog.

    Returns:
        Process exit code ``0`` after the report is printed.
    """
    root = find_repo_root()
    registry = load_registry(root)
    project_id = active_project_id(registry)
    if not project_id:
        print(
            "No active project. Select one with `crazy-admin activate <id>`."
        )
        return 0
    report_root = resolve_project(registry, project_id)["report_root"]
    blog = f"{report_root}/ACTIVITY_BLOG.md"
    if not resolve_repo_path(blog, root).is_file():
        print(f"No activity blog yet at {blog}.")
        return 0
    print(safe_read_text(blog, root).rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
