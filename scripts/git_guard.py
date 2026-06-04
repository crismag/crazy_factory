#!/usr/bin/env python3
"""Expose read-only Git inspection helpers for Crazy Factory bootstrap.

The bootstrap engine needs repository awareness without gaining permission to
change history or publish work. This module intentionally exposes only status,
diff-stat, and recent-log helpers. Write operations remain disabled.

Example:
    Show the current repository status from the repository root::

        python3 scripts/git_guard.py
"""

from __future__ import annotations

import subprocess

import factory_messaging as msg
from repo_tools import find_repo_root


ALLOWED_OPERATIONS = ("status", "diff", "log")
DISABLED_OPERATIONS = ("add", "commit", "push", "merge", "branch deletion")
FORBIDDEN_OPERATIONS = ("force push", "history rewrite", "destructive cleanup")


def _run_read_only_git(*args: str) -> str:
    """Run an approved read-only Git command inside the repository.

    Args:
        *args: Git subcommand and arguments. Callers in this module provide
            only inspection commands.

    Returns:
        Standard output with trailing whitespace removed.

    Raises:
        RuntimeError: If Git exits with a non-zero status.
    """
    root = find_repo_root()
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.rstrip()


def status() -> str:
    """Return the short branch and working-tree status.

    Returns:
        Output from ``git status --short --branch``.
    """
    return _run_read_only_git("status", "--short", "--branch")


def diff_stat() -> str:
    """Return a compact summary of unstaged repository changes.

    Returns:
        Output from ``git diff --stat``.
    """
    return _run_read_only_git("diff", "--stat")


def recent_log(limit: int = 5) -> str:
    """Return recent commits in compact one-line format.

    Args:
        limit: Maximum number of commits to return.

    Returns:
        Output from ``git log --oneline`` for the requested number of commits.
    """
    return _run_read_only_git("log", f"--max-count={limit}", "--oneline")


def main() -> int:
    """Print a read-only repository status summary.

    Returns:
        Process exit code ``0`` after the summary is printed.
    """
    msg.section_print("Crazy Factory repository status (read-only)")
    msg.cprint(status())
    msg.nprint(
        "Bootstrap policy: this command inspects git only — the factory never "
        "commits or pushes on its own. Commit/push is the owner's to run."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
