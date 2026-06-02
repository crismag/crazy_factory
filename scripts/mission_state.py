#!/usr/bin/env python3
"""Persistent mission-state handling for a Crazy Factory tick.

This module loads, validates, transitions, and persists the three durable
state snapshots in ``state/``. It encodes the recovery semantics: how a tick
records success, how a rejected contract becomes a recoverable failure, and how
a healthy run clears prior failures. It performs no model calls.

Example:
    Load state, advance it, and persist::

        factory_state, active_run, project_state = load_state(root, "state")
        update_success_state(
            factory_state,
            active_run,
            project_state,
            architect_result,
            planner_result,
            contract_result=contract_result,
        )
        persist_state(
            root=root,
            state_dir="state",
            factory_state=factory_state,
            active_run=active_run,
            project_state=project_state,
        )
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contract_stage import ContractResult
from planning_roles import RoleResult
from repo_tools import safe_load_json, safe_write_json


def load_state(
    root: Path, state_dir: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load global, active-run, and project state snapshots.

    Args:
        root: Absolute repository root.
        state_dir: Repository-relative state directory.

    Returns:
        Factory state, active-run state, and project state mappings.
    """
    return (
        safe_load_json(Path(state_dir) / "factory_state.json", root),
        safe_load_json(Path(state_dir) / "active_run.json", root),
        safe_load_json(Path(state_dir) / "project_state.json", root),
    )


def validate_state_project(
    project_name: str,
    factory_state: dict[str, Any],
    project_state: dict[str, Any],
) -> None:
    """Ensure persistent state points at the configured project.

    Args:
        project_name: Active project selected from configuration.
        factory_state: Global state snapshot.
        project_state: Active project state snapshot.

    Raises:
        RuntimeError: If configuration and persistent state disagree.
    """
    if factory_state["active_project"] != project_name:
        raise RuntimeError(
            "Factory state active project does not match configuration"
        )
    if project_state["project"] != project_name:
        raise RuntimeError(
            "Project state does not match configured active project"
        )


def requested_control_action(factory_state: dict[str, Any]) -> str | None:
    """Return a requested pause or stop action.

    Stop takes precedence over pause so an owner can halt a previously paused
    worker without clearing the pause flag first.

    Args:
        factory_state: Global state snapshot.

    Returns:
        ``"stopped"``, ``"paused"``, or ``None``.
    """
    if factory_state.get("stop_requested"):
        return "stopped"
    if factory_state.get("pause_requested"):
        return "paused"
    return None


def update_success_state(
    factory_state: dict[str, Any],
    active_run: dict[str, Any],
    project_state: dict[str, Any],
    architect_result: RoleResult,
    planner_result: RoleResult,
    *,
    contract_result: ContractResult | None = None,
) -> str:
    """Update in-memory state after a Phase 3 planning dry run.

    The tick itself always completes (records, validates, reports), so the run
    is recorded as successful. A *rejected* contract is a normal planning
    outcome, not a crash: it bumps the failure counters and sets a blocker so
    the Watcher can detect repeated planning failures, while the run still
    exits cleanly. ``authorized`` is never set here; only the owner may flip
    it.

    Args:
        factory_state: Global mutable state snapshot.
        active_run: Mutable active-run state snapshot.
        project_state: Mutable project state snapshot.
        architect_result: Completed Architect result.
        planner_result: Completed Planner result.
        contract_result: Validated structured contract outcome, if produced.

    Returns:
        UTC completion timestamp written into state.
    """
    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    factory_state["last_successful_run"] = completed_at
    factory_state["last_architect_source"] = architect_result.source
    factory_state["last_planner_source"] = planner_result.source
    factory_state["last_role_completed"] = "reporter"
    active_run["run_status"] = "idle"
    active_run["current_phase"] = "WAIT"
    active_run["last_role_completed"] = "reporter"
    active_run["task_id"] = project_state["current_task"]
    active_run["resume_from"] = (
        "Resume from the Planner recommendation in NEXT_ACTION.md. "
        "Keep application writes disabled until owner approval."
    )
    project_state["last_architect_source"] = architect_result.source
    project_state["last_planner_source"] = planner_result.source
    project_state["last_role_completed"] = "reporter"
    project_state["task_id"] = project_state["current_task"]

    if contract_result is not None:
        _apply_contract_state(
            factory_state,
            active_run,
            project_state,
            contract_result,
            completed_at,
        )
    return completed_at


def _apply_contract_state(
    factory_state: dict[str, Any],
    active_run: dict[str, Any],
    project_state: dict[str, Any],
    contract_result: ContractResult,
    completed_at: str,
) -> None:
    """Record contract verdict into persistent state snapshots.

    Args:
        factory_state: Global mutable state snapshot.
        active_run: Mutable active-run state snapshot.
        project_state: Mutable project state snapshot.
        contract_result: Validated structured contract outcome.
        completed_at: UTC completion timestamp for the current tick.
    """
    # A preserved contract is one the owner already authorized; it is healthy
    # and is held for a future Coder phase rather than regenerated.
    if contract_result.preserved:
        _record_contract_status(
            factory_state, active_run, project_state, "authorized", []
        )
        project_state["contract_authorized"] = True
        _clear_failure_state(factory_state, active_run, project_state)
        active_run["resume_from"] = (
            "An owner-authorized valid contract exists in planned_task.json. "
            "Holding for the Coder phase (not yet implemented); no new "
            "contract was generated. Application writes remain disabled."
        )
        return

    status = "valid" if contract_result.verdict.valid else "rejected"
    _record_contract_status(
        factory_state,
        active_run,
        project_state,
        status,
        list(contract_result.verdict.reasons),
    )
    # Authorization is owner-only and is never granted by the factory.
    project_state["contract_authorized"] = False

    if contract_result.verdict.valid:
        # A clean valid contract is a recovery point: clear prior failures so
        # the Watcher does not report a stall after planning recovers.
        _clear_failure_state(factory_state, active_run, project_state)
        active_run["resume_from"] = (
            "Owner review required: PLANNED_TASK.md is valid but "
            "authorized=false. Set planned_task.json authorized=true to "
            "approve before any Coder phase. Application writes remain "
            "disabled."
        )
        return

    factory_state["last_failed_run"] = completed_at
    factory_state["failure_count"] = (
        int(factory_state.get("failure_count", 0)) + 1
    )
    project_state["failure_count"] = (
        int(project_state.get("failure_count", 0)) + 1
    )
    active_run["current_blocker"] = "planning_contract_rejected"
    project_state["current_blocker"] = "planning_contract_rejected"
    active_run["resume_from"] = (
        "Planning contract rejected; see PLANNED_TASK.md validation reasons. "
        "Re-plan the current task. Application writes remain disabled."
    )


def _record_contract_status(
    factory_state: dict[str, Any],
    active_run: dict[str, Any],
    project_state: dict[str, Any],
    status: str,
    reasons: list[str],
) -> None:
    """Record the contract status string across state snapshots.

    Args:
        factory_state: Global mutable state snapshot.
        active_run: Mutable active-run state snapshot.
        project_state: Mutable project state snapshot.
        status: Contract status (``"valid"``, ``"rejected"``, ``"authorized"``).
        reasons: Validation rejection reasons, if any.
    """
    factory_state["last_contract_status"] = status
    active_run["last_contract_status"] = status
    project_state["last_contract_status"] = status
    project_state["last_contract_reasons"] = reasons


def _clear_failure_state(
    factory_state: dict[str, Any],
    active_run: dict[str, Any],
    project_state: dict[str, Any],
) -> None:
    """Clear failure counters and blockers after a healthy planning run.

    Args:
        factory_state: Global mutable state snapshot.
        active_run: Mutable active-run state snapshot.
        project_state: Mutable project state snapshot.
    """
    factory_state["failure_count"] = 0
    project_state["failure_count"] = 0
    active_run["current_blocker"] = None
    project_state["current_blocker"] = None


def persist_state(
    *,
    root: Path,
    state_dir: str,
    factory_state: dict[str, Any],
    active_run: dict[str, Any],
    project_state: dict[str, Any],
) -> None:
    """Write approved JSON state snapshots.

    Args:
        root: Absolute repository root.
        state_dir: Repository-relative approved state directory.
        factory_state: Global state snapshot.
        active_run: Active-run state snapshot.
        project_state: Project state snapshot.
    """
    safe_write_json(
        Path(state_dir) / "factory_state.json",
        factory_state,
        repo_root=root,
        allowed_roots=[state_dir],
    )
    safe_write_json(
        Path(state_dir) / "active_run.json",
        active_run,
        repo_root=root,
        allowed_roots=[state_dir],
    )
    safe_write_json(
        Path(state_dir) / "project_state.json",
        project_state,
        repo_root=root,
        allowed_roots=[state_dir],
    )
