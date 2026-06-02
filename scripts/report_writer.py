#!/usr/bin/env python3
"""Write and inspect human-readable Crazy Factory activity reports."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from repo_tools import find_repo_root, safe_read_text, safe_write_text


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _filename_timestamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def append_dry_run_report(
    *,
    project_name: str,
    project_report_root: str,
    mode: str,
    context_files: list[str],
    task_files: list[str],
    git_status: str,
) -> Path:
    """Append top-level summaries and create one app-specific session report."""
    root = find_repo_root()
    now = utc_now()
    stamp = _timestamp(now)
    report_name = f"session-{_filename_timestamp(now)}.md"
    app_report_path = str(Path(project_report_root) / report_name)
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
        + "\n## Repository Status\n\n```text\n"
        + (git_status or "clean")
        + "\n```\n\n"
        + "## Safety Record\n\n"
        + "- No Ollama request was made.\n"
        + "- No application code was modified.\n"
        + "- No git commit or push was attempted.\n"
    )
    entry = (
        f"\n## {stamp} - Dry-run tick\n\n"
        f"- Active project: `{project_name}`\n"
        f"- Result: created `{app_report_path}`\n"
        "- Safety: no model call, application edit, commit, or push attempted.\n"
    )
    daily_entry = (
        f"\n## {stamp}\n\n"
        f"Dry-run tick completed for `{project_name}`. "
        f"Detailed report: `{app_report_path}`.\n"
    )
    safe_write_text(
        app_report_path,
        body,
        repo_root=root,
        allowed_roots=[project_report_root],
    )
    safe_write_text(
        "reports/ACTIVITY_BLOG.md",
        entry,
        repo_root=root,
        allowed_roots=["reports"],
        append=True,
    )
    safe_write_text(
        "reports/DAILY_REPORT.md",
        daily_entry,
        repo_root=root,
        allowed_roots=["reports"],
        append=True,
    )
    return root / app_report_path


def main() -> int:
    root = find_repo_root()
    print(safe_read_text("reports/ACTIVITY_BLOG.md", root).rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
