#!/usr/bin/env python3
"""Phase 8 mission loop for Crazy Factory.

One invocation is one guarded mission iteration, intended to be driven by cron.
It reads owner control flags and the stall signal, writes a mission-status
report, and then either runs one planning advance, records a recovery plan, or
stays idle. It never loops internally and never forces work past a stop, pause,
blocked, or satisfied state.

Example:
    Run one guarded mission iteration from the repository root::

        python3 scripts/mission_loop.py
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import factory_advance  # noqa: E402
from flags import active_flags, control_decision  # noqa: E402
from mission_state import load_state  # noqa: E402
from recovery_manager import run_recovery  # noqa: E402
from repo_tools import (  # noqa: E402
    RepoSafetyError,
    find_repo_root,
    resolve_repo_path,
    safe_read_text,
    safe_write_text,
)
from project_registry import (  # noqa: E402
    RegistryError,
    active_project_id,
    app_is_external,
    load_registry,
    resolve_project,
    workbench_exists,
)
from project_paths import load_project_factory_config  # noqa: E402
from satisfaction_checker import run_satisfaction  # noqa: E402
from stall_detector import detect_stall  # noqa: E402

LOCK_NAME = "mission.lock"
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _lock_relpath(state_dir: str) -> str:
    """Return the repository-relative mission lock path."""
    return str(Path(state_dir) / LOCK_NAME)


def _lock_is_stale(
    data: dict[str, Any], now: datetime, stale_seconds: int
) -> bool:
    """Report whether an existing lock is stale and may be taken over.

    Args:
        data: Parsed lock contents.
        now: Current timezone-aware time.
        stale_seconds: Age beyond which a lock is considered abandoned.

    Returns:
        ``True`` when the lock is missing a timestamp or is older than the
        stale threshold.
    """
    stamp = data.get("acquired_at")
    if not isinstance(stamp, str):
        return True
    try:
        acquired = datetime.strptime(stamp, _TIMESTAMP_FORMAT).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return True
    return (now - acquired).total_seconds() > stale_seconds


def acquire_lock(
    root: Path,
    state_dir: str,
    *,
    pid: int,
    now: datetime,
    stale_seconds: int,
) -> bool:
    """Acquire the mission lock, taking over only a stale lock.

    Args:
        root: Absolute repository root.
        state_dir: Repository-relative state directory.
        pid: Current process id, recorded in the lock.
        now: Current timezone-aware time.
        stale_seconds: Age beyond which an existing lock may be taken over.

    Returns:
        ``True`` when the lock was acquired; ``False`` when another run holds a
        fresh lock.
    """
    relpath = _lock_relpath(state_dir)
    target = resolve_repo_path(relpath, root)
    if target.is_file():
        try:
            existing = json.loads(safe_read_text(relpath, root))
        except (ValueError, RepoSafetyError):
            existing = {}
        if not isinstance(existing, dict) or not _lock_is_stale(
            existing, now, stale_seconds
        ):
            return False
    safe_write_text(
        relpath,
        json.dumps(
            {"pid": pid, "acquired_at": now.strftime(_TIMESTAMP_FORMAT)}
        )
        + "\n",
        repo_root=root,
        allowed_roots=[state_dir],
    )
    return True


def release_lock(root: Path, state_dir: str) -> None:
    """Remove the mission lock if present.

    Args:
        root: Absolute repository root.
        state_dir: Repository-relative state directory.
    """
    target = resolve_repo_path(_lock_relpath(state_dir), root)
    if target.is_file():
        target.unlink()


def decide_action(
    *,
    root: Path,
    factory_state: dict[str, Any],
    project_state: dict[str, Any],
    state_dir: str,
) -> str:
    """Decide what the mission loop should do this iteration.

    Owner control signals win first (stop/pause/blocked/satisfied), then a
    detected stall, otherwise the loop may run a advance.

    Args:
        root: Absolute repository root.
        factory_state: Global state snapshot.
        project_state: Active project state snapshot.
        state_dir: Repository-relative state directory.

    Returns:
        ``"stopped"``, ``"paused"``, ``"blocked"``, ``"satisfied"``,
        ``"stalled"``, or ``"run"``.
    """
    control = control_decision(root, factory_state, state_dir)
    if control is not None:
        return control
    stall = detect_stall(
        factory_state=factory_state, project_state=project_state
    )
    return "stalled" if stall.stalled else "run"


def render_mission_status_md(
    *,
    action: str,
    flags: list[str],
    factory_state: dict[str, Any],
    project_state: dict[str, Any],
) -> str:
    """Render ``reports/MISSION_STATUS.md``.

    Args:
        action: The decided action for this iteration.
        flags: Currently active control flags.
        factory_state: Global state snapshot.
        project_state: Active project state snapshot.

    Returns:
        Markdown mission-status report.
    """
    lines = [
        "# Mission Status",
        "",
        f"- Action: `{action}`",
        f"- Active flags: `{', '.join(flags) or 'none'}`",
        f"- Mode: `{factory_state.get('mode')}`",
        f"- Project: `{project_state.get('project')}`",
        f"- Milestone: `{project_state.get('current_milestone')}`",
        f"- Task: `{project_state.get('current_task')}`",
        f"- Failure count: `{project_state.get('failure_count')}`",
        f"- Current blocker: `{project_state.get('current_blocker')}`",
        "- Six fundamental questions are answered in the latest session "
        "report.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    """Execute one guarded mission iteration.

    Returns:
        Process exit code ``0``.
    """
    root = find_repo_root()
    registry = load_registry(root)
    project_name = active_project_id(registry)
    if not project_name:
        print(
            "No active project selected. Choose an app to work on first "
            "(crazy-admin startproject/attachproject, then activate)."
        )
        return 0
    try:
        project = resolve_project(registry, project_name)
    except RegistryError as exc:
        print(f"Active project '{project_name}' is not usable: {exc}")
        return 0
    if not workbench_exists(project["app_path"], root):
        print(
            f"Workbench for '{project_name}' is missing "
            f"({project['app_path']}). Create or re-attach it first."
        )
        return 0
    if app_is_external(project["app_path"], root):
        print(
            f"Project '{project_name}' is external ({project['app_path']}). "
            "Building external apps is not enabled in this increment."
        )
        return 0
    # The project owns its config, run-state, lock, and flags — all under its
    # own folder, resolved from app_path.
    factory_config = load_project_factory_config(project["app_path"], root)
    state_dir = str(project["state_dir"])
    factory_state, _active_run, project_state = load_state(root, state_dir)

    stale_seconds = int(
        factory_config.get("mission", {}).get("lock_stale_seconds", 3600)
    )
    if not acquire_lock(
        root,
        state_dir,
        pid=os.getpid(),
        now=datetime.now(timezone.utc),
        stale_seconds=stale_seconds,
    ):
        # Another mission run holds a fresh lock; do not overlap.
        _write_status(root, "locked", factory_state, project_state, state_dir)
        print("Crazy Factory mission iteration: action=locked")
        print("Another mission run is in progress; skipping this beat.")
        return 0

    try:
        action = decide_action(
            root=root,
            factory_state=factory_state,
            project_state=project_state,
            state_dir=state_dir,
        )
        _write_status(root, action, factory_state, project_state, state_dir)

        if action == "run":
            factory_advance.main()
            _f, _a, refreshed = load_state(root, state_dir)
            run_satisfaction(
                root=root,
                project=project,
                checklist_text=_read_checklist(root, project),
                project_state=refreshed,
                state_dir=state_dir,
            )
        elif action == "stalled":
            stall = detect_stall(
                factory_state=factory_state, project_state=project_state
            )
            run_recovery(
                root=root,
                project=project,
                stall_signal=stall,
                project_state=project_state,
                state_dir=state_dir,
            )
    finally:
        release_lock(root, state_dir)

    print(f"Crazy Factory mission iteration: action={action}")
    print(f"Active project: {project_name}")
    print(
        f"Active flags: {', '.join(active_flags(root, state_dir)) or 'none'}"
    )
    print("Mission status written: reports/MISSION_STATUS.md")
    return 0


def _write_status(
    root: Path,
    action: str,
    factory_state: dict[str, Any],
    project_state: dict[str, Any],
    state_dir: str,
) -> None:
    """Write the mission-status report for the current iteration.

    Args:
        root: Absolute repository root.
        action: The decided action for this iteration.
        factory_state: Global state snapshot.
        project_state: Active project state snapshot.
        state_dir: Repository-relative state directory.
    """
    safe_write_text(
        "reports/MISSION_STATUS.md",
        render_mission_status_md(
            action=action,
            flags=active_flags(root, state_dir),
            factory_state=factory_state,
            project_state=project_state,
        ),
        repo_root=root,
        allowed_roots=["reports"],
    )


def _read_checklist(root: Path, project: dict[str, Any]) -> str:
    """Read the active project's master checklist, or empty when absent.

    Args:
        root: Absolute repository root.
        project: Active project configuration mapping.

    Returns:
        Checklist contents, or an empty string when it cannot be read.
    """
    path = str(Path(str(project["task_root"])) / "MASTER_CHECKLIST.md")
    try:
        return safe_read_text(path, root)
    except RepoSafetyError:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
