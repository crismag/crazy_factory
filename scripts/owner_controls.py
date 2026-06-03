#!/usr/bin/env python3
"""Owner-control operations for Crazy Factory.

These functions implement the owner decisions that gate the pipeline —
authorizing a planned task, approving a coder proposal, toggling per-project
capabilities — and the read-only ``next`` / ``status`` summaries. They are the
programmatic core behind the ``crazy-admin`` owner-control subcommands.

Nothing here weakens the safety model. Authorization is refused for any contract
that is not currently valid; approval is refused for a missing or rejected
proposal; capability toggles only ever set the project-local switch. The runtime
still re-validates and still applies only within ``app/`` / ``docs/`` /
``tests/``. The CLI simply replaces hand-editing generated JSON.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_control import (
    CAPABILITY_BRIDGE,
    ControlError,
    capability_keys,
    effective_capability,
    load_or_init_control,
    read_control,
    save_control,
)
from repo_tools import resolve_repo_path, safe_load_json, safe_write_json

PLANNED_TASK_FILE = "planned_task.json"
CODER_PROPOSAL_FILE = "coder_proposal.json"
PATCH_PLAN_FILE = "patch_plan.json"
APPROVED_PROPOSAL_FILE = "approved_proposal.json"


def _task_path(project: dict[str, Any], name: str) -> str:
    """Return the repo-relative path of a factory_tasks artifact."""
    return f"{str(project['task_root']).rstrip('/')}/{name}"


def _read_json_or_none(
    project: dict[str, Any], name: str, root: Path
) -> dict[str, Any] | None:
    """Read a factory_tasks JSON artifact, or ``None`` when absent."""
    rel = _task_path(project, name)
    if not resolve_repo_path(rel, root).is_file():
        return None
    return safe_load_json(rel, root)


def _write_task_json(
    project: dict[str, Any], name: str, data: dict[str, Any], root: Path
) -> None:
    """Write a factory_tasks JSON artifact, confined to the task root."""
    safe_write_json(
        _task_path(project, name),
        data,
        repo_root=root,
        allowed_roots=[str(project["task_root"])],
    )


def _contract_validation(task: dict[str, Any]) -> tuple[str, list[str]]:
    """Return ``(status, reasons)`` from a planned-task record."""
    validation = task.get("validation")
    if not isinstance(validation, dict):
        return "unknown", []
    reasons = validation.get("reasons")
    return (
        str(validation.get("status") or "unknown"),
        [str(r) for r in reasons] if isinstance(reasons, list) else [],
    )


# --- task authorization -----------------------------------------------------


def authorize_task(project: dict[str, Any], root: Path) -> dict[str, Any]:
    """Authorize the current planned task after revalidating its verdict.

    Raises:
        ControlError: If the contract is missing, not valid, has reasons, or is
            already authorized.
    """
    task = _read_json_or_none(project, PLANNED_TASK_FILE, root)
    if task is None:
        raise ControlError(
            "No planned task yet. Run `crazy-admin tick` to produce one."
        )
    status, reasons = _contract_validation(task)
    if status != "valid":
        detail = "\n".join(f"  - {r}" for r in reasons) or "  (no detail)"
        raise ControlError(
            f"Contract validation status is {status}.\n"
            f"Validation errors:\n{detail}"
        )
    if reasons:
        raise ControlError(
            "Contract has unresolved validation reasons:\n"
            + "\n".join(f"  - {r}" for r in reasons)
        )
    if task.get("authorized") is True:
        raise ControlError("Task is already authorized.")

    control = load_or_init_control(
        str(project["app_path"]), root, project=project
    )
    control["owner_controls"]["task_authorized"] = True
    save_control(control, str(project["app_path"]), root)

    task["authorized"] = True
    _write_task_json(project, PLANNED_TASK_FILE, task, root)
    return {"task_id": task.get("task_id")}


def revoke_task(project: dict[str, Any], root: Path) -> None:
    """Reverse owner task authorization without deleting artifacts."""
    control = load_or_init_control(
        str(project["app_path"]), root, project=project
    )
    control["owner_controls"]["task_authorized"] = False
    save_control(control, str(project["app_path"]), root)

    task = _read_json_or_none(project, PLANNED_TASK_FILE, root)
    if task is not None:
        task["authorized"] = False
        _write_task_json(project, PLANNED_TASK_FILE, task, root)


# --- proposal approval ------------------------------------------------------


def approve_proposal(project: dict[str, Any], root: Path) -> dict[str, Any]:
    """Approve the current coder proposal for application.

    Raises:
        ControlError: If the proposal is missing, lacks an id, or was rejected.
    """
    proposal = _read_json_or_none(project, CODER_PROPOSAL_FILE, root)
    if proposal is None:
        raise ControlError(
            "No coder proposal yet. Authorize the task and run a tick first."
        )
    proposal_id = proposal.get("proposal_id")
    if not proposal_id:
        raise ControlError("Coder proposal has no proposal_id to approve.")
    validation = proposal.get("validation")
    if isinstance(validation, dict) and validation.get("status") == "rejected":
        raise ControlError(
            f"Coder proposal {proposal_id} was rejected; cannot approve it."
        )

    control = load_or_init_control(
        str(project["app_path"]), root, project=project
    )
    control["owner_controls"]["proposal_approved"] = True
    control["owner_controls"]["approved_proposal_id"] = str(proposal_id)
    save_control(control, str(project["app_path"]), root)

    _write_task_json(
        project,
        APPROVED_PROPOSAL_FILE,
        {"application_approved": True, "proposal_id": str(proposal_id)},
        root,
    )
    return {"proposal_id": str(proposal_id)}


def revoke_proposal(project: dict[str, Any], root: Path) -> None:
    """Clear proposal approval and invalidate the approval artifact."""
    control = load_or_init_control(
        str(project["app_path"]), root, project=project
    )
    control["owner_controls"]["proposal_approved"] = False
    control["owner_controls"]["approved_proposal_id"] = None
    save_control(control, str(project["app_path"]), root)

    if _read_json_or_none(project, APPROVED_PROPOSAL_FILE, root) is not None:
        # Invalidate rather than delete: the evidence stays, but it no longer
        # approves anything.
        _write_task_json(
            project,
            APPROVED_PROPOSAL_FILE,
            {"application_approved": False, "proposal_id": None},
            root,
        )


# --- capability toggles -----------------------------------------------------


def set_capability(
    project: dict[str, Any], root: Path, cap_key: str, value: bool
) -> None:
    """Set a per-project capability switch.

    Raises:
        ControlError: If ``cap_key`` is not a recognized capability.
    """
    if cap_key not in capability_keys():
        raise ControlError(f"Unknown capability: {cap_key}")
    control = load_or_init_control(
        str(project["app_path"]), root, project=project
    )
    control["capabilities"][cap_key] = bool(value)
    save_control(control, str(project["app_path"]), root)


# --- summaries --------------------------------------------------------------


def _is_authorized(
    task: dict[str, Any] | None, raw_control: dict[str, Any] | None
) -> bool:
    """Report whether the task is authorized per the contract or control."""
    if task is not None and task.get("authorized") is True:
        return True
    controls = (raw_control or {}).get("owner_controls")
    return (
        isinstance(controls, dict) and controls.get("task_authorized") is True
    )


def _is_approved(
    proposal: dict[str, Any] | None,
    approval: dict[str, Any] | None,
) -> bool:
    """Report whether the current proposal is approved (matching id)."""
    if proposal is None or approval is None:
        return False
    if approval.get("application_approved") is not True:
        return False
    return bool(approval.get("proposal_id")) and approval.get(
        "proposal_id"
    ) == proposal.get("proposal_id")


def gather_status(
    project: dict[str, Any], root: Path, factory_config: dict[str, Any]
) -> dict[str, Any]:
    """Collect a structured owner-facing status for a project."""
    raw_control = read_control(str(project["app_path"]), root)
    task = _read_json_or_none(project, PLANNED_TASK_FILE, root)
    proposal = _read_json_or_none(project, CODER_PROPOSAL_FILE, root)
    approval = _read_json_or_none(project, APPROVED_PROPOSAL_FILE, root)
    project_state = safe_load_json("state/project_state.json", root)

    status, reasons = _contract_validation(task) if task else ("absent", [])
    caps = {
        cap: effective_capability(raw_control, factory_config, cap)
        for cap in CAPABILITY_BRIDGE
    }
    return {
        "project_id": project["name"],
        "app_path": project["app_path"],
        "state_path": project["state_path"],
        "contract_exists": task is not None,
        "contract_status": status,
        "contract_authorized": bool(task and task.get("authorized") is True),
        "contract_reasons": reasons,
        "proposal_exists": proposal is not None,
        "proposal_id": (proposal or {}).get("proposal_id"),
        "proposal_approved": _is_approved(proposal, approval),
        "capabilities": caps,
        "current_blocker": project_state.get("current_blocker"),
    }


def describe_next(
    project: dict[str, Any], root: Path, factory_config: dict[str, Any]
) -> str:
    """Return a human-readable "what to do next" summary for a project."""
    pid = str(project["name"])
    raw_control = read_control(str(project["app_path"]), root)
    task = _read_json_or_none(project, PLANNED_TASK_FILE, root)
    proposal = _read_json_or_none(project, CODER_PROPOSAL_FILE, root)
    approval = _read_json_or_none(project, APPROVED_PROPOSAL_FILE, root)
    planned_md = f"{str(project['task_root'])}/PLANNED_TASK.md"
    proposal_json = _task_path(project, CODER_PROPOSAL_FILE)
    patch_json = _task_path(project, PATCH_PLAN_FILE)

    if task is None:
        return (
            "Current state: no_planned_task\n\n"
            "No planning contract yet.\n\n"
            "Recommended action:\n"
            "  bin/crazy-admin tick"
        )

    status, reasons = _contract_validation(task)
    if status != "valid":
        reason_lines = "\n".join(f"  {r}" for r in reasons) or "  (no detail)"
        return (
            "Current blocker: planning_contract_rejected\n\n"
            "Do not authorize yet.\n\n"
            f"Reason:\n{reason_lines}\n\n"
            f"Review:\n  {planned_md}\n\n"
            "Recommended action:\n"
            "  Run another tick to re-plan, or fix the planning contract "
            "source so the rejected field is populated.\n"
            "  bin/crazy-admin tick"
        )

    if not _is_authorized(task, raw_control):
        return (
            "Current state: contract_valid_waiting_for_owner\n\n"
            f"Review:\n  {planned_md}\n\n"
            "To authorize:\n"
            f"  bin/crazy-admin authorize-task {pid}"
        )

    if proposal is None:
        return (
            "Current state: authorized_waiting_for_tick\n\n"
            "The task is authorized but no coder proposal exists yet.\n\n"
            "Recommended action:\n"
            "  bin/crazy-admin tick"
        )

    pverdict = proposal.get("validation")
    if isinstance(pverdict, dict) and pverdict.get("status") == "rejected":
        return (
            "Current state: proposal_rejected\n\n"
            f"Review:\n  {proposal_json}\n\n"
            "Recommended action:\n"
            "  Run another tick to regenerate the proposal.\n"
            "  bin/crazy-admin tick"
        )

    if not _is_approved(proposal, approval):
        return (
            "Current state: proposal_waiting_for_owner\n\n"
            f"Review:\n  {proposal_json}\n  {patch_json}\n\n"
            "To approve:\n"
            f"  bin/crazy-admin approve-proposal {pid}"
        )

    if not effective_capability(raw_control, factory_config, "allow_apply"):
        return (
            "Current state: apply_disabled\n\n"
            "Proposal is approved but application is disabled.\n\n"
            "To enable:\n"
            f"  bin/crazy-admin enable-apply {pid}"
        )

    return (
        "Current state: ready_to_apply\n\n"
        "Task authorized, proposal approved, apply enabled.\n\n"
        "Recommended action:\n"
        "  bin/crazy-admin tick"
    )
