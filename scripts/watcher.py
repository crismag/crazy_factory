#!/usr/bin/env python3
"""Produce a read-only summary of factory activity and possible stalls."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from git_guard import status
from repo_tools import find_repo_root, resolve_repo_path, safe_read_text


def activity_summary() -> str:
    root = find_repo_root()
    activity_path = resolve_repo_path("reports/ACTIVITY_BLOG.md", root)
    stall_path = resolve_repo_path("reports/STALL_REPORT.md", root)
    activity = safe_read_text(activity_path, root)
    stall = safe_read_text(stall_path, root)
    age_seconds = datetime.now(timezone.utc).timestamp() - activity_path.stat().st_mtime
    stall_signal = "possible: activity report is older than 24 hours" if age_seconds > 86400 else "none"
    return (
        "Crazy Factory watcher summary\n"
        "=============================\n"
        f"Activity report bytes: {len(activity.encode('utf-8'))}\n"
        f"Stall report bytes: {len(stall.encode('utf-8'))}\n"
        f"Stall signal: {stall_signal}\n\n"
        "Repository status\n"
        "-----------------\n"
        f"{status()}\n"
    )


def main() -> int:
    print(activity_summary().rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
