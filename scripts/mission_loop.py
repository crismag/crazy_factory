#!/usr/bin/env python3
"""Phase 8 mission loop for Crazy Factory.

One invocation is one guarded mission iteration, intended to be driven by cron.
It reads owner control flags and the stall signal, writes a mission-status
report, and then either runs one planning tick, records a recovery plan, or
stays idle. It never loops internally and never forces work past a stop, pause,
blocked, or satisfied state.

Example:
    Run one guarded mission iteration from the repository root::

        python3 scripts/mission_loop.py
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import factory_tick  # noqa: E402
from flags import active_flags, control_decision  # noqa: E402
from mission_state import load_state  # noqa: E402
from recovery_manager import run_recovery  # noqa: E402
from repo_tools import (  # noqa: E402
    RepoSafetyError,
    find_repo_root,
    safe_read_text,
    safe_write_text,
)
from satisfaction_checker import run_satisfaction  # noqa: E402
from stall_detector import detect_stall  # noqa: E402
from tick_config import load_active_project, load_configuration  # noqa: E402


def decide_action(
    *,
    root: Path,
    factory_state: dict[str, Any],
    project_state: dict[str, Any],
    state_dir: str,
) -> str:
    """Decide what the mission loop should do this iteration.

    Owner control signals win first (stop/pause/blocked/satisfied), then a
    detected stall, otherwise the loop may run a tick.

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
    factory_config, projects_config = load_configuration(root)
    factory = factory_config["factory"]
    state_dir = str(factory["state_dir"])
    project_name, project = load_active_project(factory, projects_config)
    factory_state, _active_run, project_state = load_state(root, state_dir)

    action = decide_action(
        root=root,
        factory_state=factory_state,
        project_state=project_state,
        state_dir=state_dir,
    )
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

    if action == "run":
        factory_tick.main()
        _f, _a, refreshed = load_state(root, state_dir)
        checklist = _read_checklist(root, project)
        run_satisfaction(
            root=root,
            project=project,
            checklist_text=checklist,
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

    print(f"Crazy Factory mission iteration: action={action}")
    print(f"Active project: {project_name}")
    print(
        f"Active flags: {', '.join(active_flags(root, state_dir)) or 'none'}"
    )
    print("Mission status written: reports/MISSION_STATUS.md")
    return 0


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
