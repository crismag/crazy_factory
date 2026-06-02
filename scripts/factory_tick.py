#!/usr/bin/env python3
"""Perform one conservative Crazy Factory dry-run tick."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from git_guard import status
from report_writer import append_dry_run_report
from repo_tools import find_repo_root, load_simple_yaml, read_markdown_directory


def main() -> int:
    root = find_repo_root()
    factory_config = load_simple_yaml("config/factory.yaml", root)
    projects_config = load_simple_yaml("config/projects.yaml", root)
    factory = factory_config["factory"]
    mode = str(factory["mode"])
    if mode != "dry_run":
        raise RuntimeError(f"Bootstrap tick refuses non-dry-run mode: {mode}")
    if factory.get("allow_commit") or factory.get("allow_push"):
        raise RuntimeError("Bootstrap tick refuses enabled commit or push settings")

    project_name = str(factory.get("active_project") or projects_config["active_project"])
    projects = projects_config["projects"]
    if project_name not in projects:
        raise RuntimeError(f"Unknown active project: {project_name}")
    project = projects[project_name]
    max_lines = int(factory["max_lines_per_file"])

    contexts = read_markdown_directory(
        project["context_root"], repo_root=root, max_lines_per_file=max_lines
    )
    tasks = read_markdown_directory(
        project["task_root"], repo_root=root, max_lines_per_file=max_lines
    )
    report_path = append_dry_run_report(
        project_name=project_name,
        project_report_root=project["report_root"],
        mode=mode,
        context_files=list(contexts),
        task_files=list(tasks),
        git_status=status(),
    )

    print("Crazy Factory dry-run tick complete")
    print(f"Active project: {project_name}")
    print(f"Context files read: {len(contexts)}")
    print(f"Task files read: {len(tasks)}")
    print(f"Report written: {report_path.relative_to(root)}")
    print("Safety: no model call, application edit, commit, or push attempted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
