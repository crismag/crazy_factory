#!/usr/bin/env python3
"""Persistent mission-state handling for a Crazy Factory advance.

This module loads, validates, transitions, and persists the three durable
state snapshots in ``state/``. It encodes the recovery semantics: how a advance
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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from remediation import RemediationPlan

from checkpoint_commit import CheckpointResult, checkpoint_status_label
from coder_proposal import ProposalResult, coder_status_label
from contract_stage import ContractResult
from planning_roles import RoleResult
from proposal_applier import ApplicationResult, application_status_label
from repo_tools import resolve_repo_path, safe_load_json, safe_write_json
from test_builder import TestPlanResult, test_plan_status_label
from validation_runner import ValidationResult, validation_status_label

_VALIDATION_PASS_PRESERVES_BLOCKERS: frozenset[str] = frozenset(
    {
        "application_rejected",
        "coder_proposal_rejected",
        "planning_contract_rejected",
        "test_plan_rejected",
        "self_rejection",
        "needs_owner_decision",
        "recovery_exhausted",
    }
)


def initial_state(project_id: str) -> dict[str, dict[str, Any]]:
    """Return the three bootstrap state snapshots for a new project.

    Used by ``startproject`` and ``promote`` to seed a project's own
    ``<app>/state/`` so its first advance passes ``validate_state_project``.

    Args:
        project_id: The project the state belongs to.

    Returns:
        Mapping of state filename to its initial JSON object.
    """
    return {
        "factory_state.json": {
            "mode": "dry_run",
            "status": "bootstrap",
            "active_project": project_id,
            "pause_requested": False,
            "stop_requested": False,
            "continuous_operation_enabled": False,
            "automatic_commit_enabled": False,
            "automatic_merge_enabled": False,
            "scheduled_operation_enabled": False,
            "last_successful_run": None,
            "last_failed_run": None,
            "failure_count": 0,
            "recovery_instructions": "Review the planned task and authorize it.",
        },
        "project_state.json": {
            "project": project_id,
            "status": "planning",
            "satisfaction_status": "not_satisfied",
            "current_milestone": f"{project_id}-M1",
            "last_completed_milestone": None,
            "current_task": f"{project_id}-001",
            "current_checkpoint": None,
            "last_completed_checkpoint": None,
            "current_blocker": None,
            "failure_count": 0,
            "recovery_instructions": "Run a advance to produce a planned task.",
        },
        "active_run.json": {
            "run_status": "idle",
            "run_id": None,
            "started_at": None,
            "active_project": project_id,
            "current_phase": "WAIT",
            "current_task": f"{project_id}-001",
            "current_checkpoint": None,
            "last_completed_checkpoint": None,
            "current_blocker": None,
            "last_role_completed": None,
            "task_id": f"{project_id}-001",
            "resume_from": "Run a advance to begin planning.",
        },
    }


def load_state(
    root: Path, state_dir: str, project_name: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load global, active-run, and project state snapshots.

    A project owns its run-state inside its own workbench. Any snapshot that
    does not exist yet is bootstrapped from :func:`initial_state` for this
    project — so a project self-initializes on its first advance and needs no
    separate "activate" step (there is no global active project).

    Args:
        root: Absolute repository root.
        state_dir: Repository-relative state directory.
        project_name: Project id used to seed missing snapshots.

    Returns:
        Factory state, active-run state, and project state mappings.
    """
    bootstrap = initial_state(project_name)

    def _load(name: str) -> dict[str, Any]:
        rel = f"{str(state_dir).rstrip('/')}/{name}"
        if resolve_repo_path(rel, root).is_file():
            return safe_load_json(rel, root)
        return bootstrap[name]

    return (
        _load("factory_state.json"),
        _load("active_run.json"),
        _load("project_state.json"),
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
    coder_result: ProposalResult | None = None,
    application_result: ApplicationResult | None = None,
    test_plan_result: TestPlanResult | None = None,
    validation_result: ValidationResult | None = None,
    checkpoint_result: CheckpointResult | None = None,
    remediation: "RemediationPlan | None" = None,
) -> str:
    """Update in-memory state after a planning (and optional coder) dry run.

    The advance itself always completes (records, validates, reports), so the run
    is recorded as successful. A *rejected* contract or an *activated but
    rejected* coder proposal is a normal outcome, not a crash: it bumps the
    failure counters and sets a blocker so the Watcher can detect repeated
    failures, while the run still exits cleanly. The factory never authorizes
    a contract or applies a proposal here.

    Args:
        factory_state: Global mutable state snapshot.
        active_run: Mutable active-run state snapshot.
        project_state: Mutable project state snapshot.
        architect_result: Completed Architect result.
        planner_result: Completed Planner result.
        contract_result: Validated structured contract outcome, if produced.
        coder_result: Coder proposal outcome, if the coder stage ran.
        application_result: Proposal application outcome, if that stage ran.

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
    if coder_result is not None:
        _apply_coder_state(
            factory_state,
            active_run,
            project_state,
            coder_result,
            completed_at,
        )
    if application_result is not None:
        _apply_application_state(
            factory_state,
            active_run,
            project_state,
            application_result,
            completed_at,
        )
    if test_plan_result is not None:
        _apply_test_plan_state(
            factory_state,
            active_run,
            project_state,
            test_plan_result,
            completed_at,
        )
    if validation_result is not None:
        _apply_validation_state(
            factory_state,
            active_run,
            project_state,
            validation_result,
            completed_at,
            remediation,
        )
    if checkpoint_result is not None:
        _apply_checkpoint_state(
            factory_state, active_run, project_state, checkpoint_result
        )
    return completed_at


def _apply_checkpoint_state(
    factory_state: dict[str, Any],
    active_run: dict[str, Any],
    project_state: dict[str, Any],
    checkpoint_result: CheckpointResult,
) -> None:
    """Record the checkpoint outcome into state snapshots.

    A committed checkpoint advances the last-completed-checkpoint marker. An
    eligible-but-not-committed or not-eligible checkpoint is benign (the
    earlier stages already governed failure state).

    Args:
        factory_state: Global mutable state snapshot.
        active_run: Mutable active-run state snapshot.
        project_state: Mutable project state snapshot.
        checkpoint_result: Checkpoint outcome.
    """
    status = checkpoint_status_label(checkpoint_result)
    factory_state["last_checkpoint_status"] = status
    project_state["last_checkpoint_status"] = status
    if checkpoint_result.committed and checkpoint_result.checkpoint_id:
        project_state["last_completed_checkpoint"] = (
            checkpoint_result.checkpoint_id
        )
        active_run["current_checkpoint"] = checkpoint_result.checkpoint_id
        active_run["resume_from"] = (
            "Checkpoint committed; select the next task. "
            "resume_from=select_next_task."
        )


def _apply_test_plan_state(
    factory_state: dict[str, Any],
    active_run: dict[str, Any],
    project_state: dict[str, Any],
    test_plan_result: TestPlanResult,
    completed_at: str,
) -> None:
    """Record the test-plan outcome into state snapshots.

    A skipped test builder is healthy. An activated-but-rejected plan is a
    recoverable failure.

    Args:
        factory_state: Global mutable state snapshot.
        active_run: Mutable active-run state snapshot.
        project_state: Mutable project state snapshot.
        test_plan_result: Test-plan outcome.
        completed_at: UTC completion timestamp for the current advance.
    """
    status = test_plan_status_label(test_plan_result)
    plan = test_plan_result.plan
    factory_state["last_test_plan_status"] = status
    project_state["last_test_plan_status"] = status
    project_state["last_test_plan_id"] = plan.test_plan_id if plan else None

    if not test_plan_result.activated or test_plan_result.verdict.valid:
        return

    factory_state["last_failed_run"] = completed_at
    factory_state["failure_count"] = (
        int(factory_state.get("failure_count", 0)) + 1
    )
    project_state["failure_count"] = (
        int(project_state.get("failure_count", 0)) + 1
    )
    active_run["current_blocker"] = "test_plan_rejected"
    project_state["current_blocker"] = "test_plan_rejected"


def _apply_validation_state(
    factory_state: dict[str, Any],
    active_run: dict[str, Any],
    project_state: dict[str, Any],
    validation_result: ValidationResult,
    completed_at: str,
    remediation: "RemediationPlan | None" = None,
) -> None:
    """Record the validation outcome into state snapshots.

    A passed or skipped validation is healthy. A failed or blocked validation
    is a recoverable failure that must block any future checkpoint.

    When this advance was an owner-enabled remediation attempt, the persisted
    ``remediation_attempt`` counter advances: a pass resets it (and clears the
    blocker), a failure with budget remaining keeps ``validation_failed`` so the
    next advance retries, and a failure on the last attempt sets the terminal
    ``remediation_exhausted`` blocker for owner review.

    Args:
        factory_state: Global mutable state snapshot.
        active_run: Mutable active-run state snapshot.
        project_state: Mutable project state snapshot.
        validation_result: Validation outcome.
        completed_at: UTC completion timestamp for the current advance.
        remediation: The remediation plan for this advance, if any.
    """
    status = validation_status_label(validation_result)
    checks_run = [
        check.command
        for check in validation_result.checks
        if check.status in {"passed", "failed", "error"}
    ]
    factory_state["last_validation_status"] = status
    project_state["last_validation_status"] = status
    project_state["checks_run"] = checks_run
    active_run["last_validation_status"] = status

    if status in {"failed", "blocked"}:
        # Root-cause precedence: an upstream rejection recorded earlier this
        # beat (application_rejected, coder/contract/test-plan rejection,
        # self_rejection, …) outranks a downstream validation failure. When the
        # patch was rejected nothing new was applied, so a failing/empty
        # validation is a *symptom* of that rejection, not an independent fault.
        # Preserve the upstream blocker so recovery handles the real cause,
        # instead of flipping to validation_failed and luring remediation into
        # chasing a phantom. (A genuinely applied patch clears the blocker to
        # None in _apply_application_state, so this never masks real test/lint
        # failures of applied code.) Remediation attempts keep their own
        # accounting below.
        upstream = project_state.get("current_blocker")
        if upstream in _VALIDATION_PASS_PRESERVES_BLOCKERS and not (
            remediation is not None and remediation.active
        ):
            active_run["current_blocker"] = upstream
            return
        factory_state["last_failed_run"] = completed_at
        factory_state["failure_count"] = (
            int(factory_state.get("failure_count", 0)) + 1
        )
        project_state["failure_count"] = (
            int(project_state.get("failure_count", 0)) + 1
        )
        if remediation is not None and remediation.active:
            project_state["remediation_attempt"] = remediation.attempt
            if remediation.is_last_attempt:
                blocker = "remediation_exhausted"
                resume = (
                    f"Remediation exhausted after {remediation.attempt} "
                    "attempt(s); validation still failing. Owner review "
                    "required; see VALIDATION_REPORT.md."
                )
            else:
                blocker = "validation_failed"
                resume = (
                    f"Remediation attempt {remediation.attempt} did not pass; "
                    "another attempt will run on the next advance."
                )
        else:
            blocker = "validation_failed"
            resume = (
                "Validation failed or blocked; see VALIDATION_REPORT.md. "
                "resume_from=validation."
            )
        active_run["current_blocker"] = blocker
        project_state["current_blocker"] = blocker
        active_run["resume_from"] = resume
    elif status == "passed":
        project_state["remediation_attempt"] = 0
        current_blocker = project_state.get("current_blocker")
        if current_blocker in _VALIDATION_PASS_PRESERVES_BLOCKERS:
            active_run["current_blocker"] = current_blocker
            return
        active_run["current_blocker"] = None
        project_state["current_blocker"] = None
        active_run["resume_from"] = (
            "Validation passed; ready for owner review. "
            "resume_from=validation."
        )


def _apply_application_state(
    factory_state: dict[str, Any],
    active_run: dict[str, Any],
    project_state: dict[str, Any],
    application_result: ApplicationResult,
    completed_at: str,
) -> None:
    """Record the proposal application outcome into state snapshots.

    A not-approved application is the normal healthy state and is not a
    failure. An activated-but-rejected patch plan is a recoverable failure. A
    valid preview or a successful apply points the resume marker at the
    application artifacts.

    Args:
        factory_state: Global mutable state snapshot.
        active_run: Mutable active-run state snapshot.
        project_state: Mutable project state snapshot.
        application_result: Proposal application outcome.
        completed_at: UTC completion timestamp for the current advance.
    """
    status = application_status_label(application_result)
    plan = application_result.plan
    plan_id = plan.plan_id if plan else None
    factory_state["last_application_status"] = status
    project_state["last_application_status"] = status
    project_state["last_patch_plan_id"] = plan_id
    project_state["application_applied"] = application_result.applied
    active_run["last_application_status"] = status

    if not application_result.activated:
        return

    if application_result.verdict.valid:
        active_run["current_blocker"] = None
        project_state["current_blocker"] = None
        project_state["last_application_reasons"] = []
        verb = "applied" if application_result.applied else "previewed"
        active_run["resume_from"] = (
            f"Patch plan {verb}; review PATCH_PLAN.md and "
            "APPLICATION_REPORT.md. resume_from=application."
        )
        return

    factory_state["last_failed_run"] = completed_at
    factory_state["failure_count"] = (
        int(factory_state.get("failure_count", 0)) + 1
    )
    project_state["failure_count"] = (
        int(project_state.get("failure_count", 0)) + 1
    )
    # 9E EVID-1: persist the rejection reasons to STATE so the DiagnosisPacket
    # can carry them to the next beat even after recovery retires patch_plan.json.
    project_state["last_application_reasons"] = list(
        application_result.verdict.reasons
    )
    active_run["current_blocker"] = "application_rejected"
    project_state["current_blocker"] = "application_rejected"
    active_run["resume_from"] = (
        "Patch plan rejected; see PATCH_PLAN.md reasons. No files were "
        "applied. resume_from=application."
    )


def _apply_coder_state(
    factory_state: dict[str, Any],
    active_run: dict[str, Any],
    project_state: dict[str, Any],
    coder_result: ProposalResult,
    completed_at: str,
) -> None:
    """Record the coder proposal outcome into persistent state snapshots.

    A skipped coder (no authorized contract) is the normal healthy state and
    is not a failure. An activated-but-rejected proposal is a recoverable
    failure: it bumps the failure counters and sets a blocker. A valid
    proposal points the resume marker at owner review of the proposal.

    Args:
        factory_state: Global mutable state snapshot.
        active_run: Mutable active-run state snapshot.
        project_state: Mutable project state snapshot.
        coder_result: Coder proposal outcome.
        completed_at: UTC completion timestamp for the current advance.
    """
    status = coder_status_label(coder_result)
    proposal = coder_result.proposal
    proposal_id = proposal.proposal_id if proposal else None
    factory_state["last_coder_status"] = status
    project_state["last_coder_status"] = status
    project_state["last_proposal_id"] = proposal_id
    active_run["last_coder_status"] = status

    if not coder_result.activated:
        # Coder did not run; the contract-stage resume marker still governs.
        project_state["last_proposal_verdict"] = "skipped"
        return

    if coder_result.verdict.valid:
        project_state["last_proposal_verdict"] = "accepted"
        active_run["current_blocker"] = None
        project_state["current_blocker"] = None
        active_run["resume_from"] = (
            "Coder proposal generated and valid; review CODER_PROPOSAL.md. "
            "No files were written. resume_from=coder_proposal."
        )
        return

    project_state["last_proposal_verdict"] = "rejected"
    factory_state["last_failed_run"] = completed_at
    factory_state["failure_count"] = (
        int(factory_state.get("failure_count", 0)) + 1
    )
    project_state["failure_count"] = (
        int(project_state.get("failure_count", 0)) + 1
    )
    active_run["current_blocker"] = "coder_proposal_rejected"
    project_state["current_blocker"] = "coder_proposal_rejected"
    active_run["resume_from"] = (
        "Coder proposal rejected; see CODER_PROPOSAL.md reasons. No files "
        "were written. resume_from=coder_proposal."
    )


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
        completed_at: UTC completion timestamp for the current advance.
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

    if contract_result.verdict.valid:
        status = "valid"
    elif contract_result.decision in (
        "needs_owner_review",
        "needs_clarification",
    ):
        status = "needs_owner_review"
    else:
        status = "rejected"
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

    if status == "needs_owner_review":
        # A reviewed-but-incomplete contract is a WAITING checkpoint for the
        # owner, not a failure. Do not bump failure counters or set a
        # persistent blocker (which would drive a false stall -> blocked); the
        # owner resolves the CONTRACT_REVIEW.md checklist, then re-advances.
        _clear_failure_state(factory_state, active_run, project_state)
        active_run["resume_from"] = (
            "Contract needs owner review: resolve the CONTRACT_REVIEW.md "
            "checklist (edit the goal/context), then run another advance. "
            "Application writes remain disabled."
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
