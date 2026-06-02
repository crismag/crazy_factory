#!/usr/bin/env python3
"""Read-only git inspection helpers for Crazy Factory bootstrap."""

from __future__ import annotations

import subprocess

from repo_tools import find_repo_root


ALLOWED_OPERATIONS = ("status", "diff", "log")
DISABLED_OPERATIONS = ("add", "commit", "push", "merge", "branch deletion")
FORBIDDEN_OPERATIONS = ("force push", "history rewrite", "destructive cleanup")


def _run_read_only_git(*args: str) -> str:
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
    return _run_read_only_git("status", "--short", "--branch")


def diff_stat() -> str:
    return _run_read_only_git("diff", "--stat")


def recent_log(limit: int = 5) -> str:
    return _run_read_only_git("log", f"--max-count={limit}", "--oneline")


def main() -> int:
    print("Crazy Factory status")
    print("====================")
    print(status())
    print()
    print("Bootstrap policy: git inspection only; commits and pushes are disabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
