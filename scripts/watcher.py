#!/usr/bin/env python3
"""Produce a read-only summary of factory activity and possible stalls.

The Watcher is intentionally separate from implementation work. It reads
reports, persistent state, and Git status to show the owner where the current
mission should resume. It does not modify application code or state.

Example:
    Print the current watcher summary from the repository root::

        python3 scripts/watcher.py
"""

from __future__ import annotations

from datetime import datetime, timezone

from git_guard import status
from repo_tools import (
    find_repo_root,
    resolve_repo_path,
    safe_load_json,
    safe_read_text,
)


def activity_summary() -> str:
    """Build a read-only activity, stall, and mission-recovery summary.

    Returns:
        Human-readable summary containing report sizes, stall signal, durable
        resume state, and repository status.

    Raises:
        RepoSafetyError: If an expected report or state path is unsafe.
        ValueError: If persistent JSON state is invalid.
    """
    root = find_repo_root()
    activity_path = resolve_repo_path("reports/ACTIVITY_BLOG.md", root)
    stall_path = resolve_repo_path("reports/STALL_REPORT.md", root)
    activity = safe_read_text(activity_path, root)
    stall = safe_read_text(stall_path, root)
    factory_state = safe_load_json("state/factory_state.json", root)
    active_run = safe_load_json("state/active_run.json", root)
    project_state = safe_load_json("state/project_state.json", root)
    age_seconds = (
        datetime.now(timezone.utc).timestamp() - activity_path.stat().st_mtime
    )
    # A stale activity report or repeated failures is enough to ask for human
    # attention. The bootstrap watcher reports the signal but does not recover
    # or mutate state by itself.
    stale_activity = age_seconds > 86400
    repeated_failures = int(project_state["failure_count"]) > 1
    has_stall_signal = stale_activity or repeated_failures
    stall_signal = "possible" if has_stall_signal else "none"
    return (
        "Crazy Factory watcher summary\n"
        "=============================\n"
        f"Activity report bytes: {len(activity.encode('utf-8'))}\n"
        f"Stall report bytes: {len(stall.encode('utf-8'))}\n"
        f"Stall signal: {stall_signal}\n\n"
        "Mission recovery\n"
        "----------------\n"
        f"Factory mode: {factory_state['mode']}\n"
        f"Project: {project_state['project']}\n"
        f"Milestone: {project_state['current_milestone']}\n"
        f"Task: {project_state['current_task']}\n"
        f"Last checkpoint: {project_state['last_completed_checkpoint']}\n"
        f"Current blocker: {project_state['current_blocker']}\n"
        f"Resume from: {active_run['resume_from']}\n\n"
        "Repository status\n"
        "-----------------\n"
        f"{status()}\n"
    )


def main() -> int:
    """Print the read-only watcher summary.

    Returns:
        Process exit code ``0`` after the summary is printed.
    """
    print(activity_summary().rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
