#!/usr/bin/env python3
"""Run one conservative Crazy Factory planning tick.

This module is the orchestrator. It wires together the cohesive helper modules
and owns no domain logic of its own:

- :mod:`tick_config` loads and validates configuration and the active project.
- :mod:`mission_state` loads, transitions, and persists durable state.
- :mod:`planning_roles` runs the Architect and Planner planning roles.
- :mod:`contract_stage` produces or preserves the structured task contract.
- :mod:`report_writer` records observable, recoverable reports.

The loop reads context, asks the Architect for an expansion and the Planner for
a next action, derives a validated task contract, updates resume state, and
writes reports. If Ollama is unavailable, deterministic fallbacks keep the tick
useful and recoverable. It may update fixed planning and contract files,
approved report files, and JSON state snapshots only. It cannot modify
application source code, choose arbitrary write paths, commit, push, or
activate scheduling.

Example:
    Run one local dry-run validation tick from the repository root::

        python3 scripts/factory_tick.py
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from coder_proposal import (  # noqa: E402
    coder_status_label,
    run_coder_stage,
)
from contract_stage import (  # noqa: E402
    contract_status_label,
    run_contract_stage,
)
from checkpoint_commit import (  # noqa: E402
    checkpoint_status_label,
    run_checkpoint_stage,
)
from proposal_applier import (  # noqa: E402
    application_status_label,
    run_application_stage,
)
from test_builder import (  # noqa: E402
    run_test_builder_stage,
    test_plan_status_label,
)
from validation_runner import (  # noqa: E402
    run_validation_stage,
    validation_status_label,
)
from git_guard import status  # noqa: E402
from mission_state import (  # noqa: E402
    load_state,
    persist_state,
    requested_control_action,
    update_success_state,
    validate_state_project,
)
from planning_roles import (  # noqa: E402
    planning_paths,
    render_next_action,
    render_task_expansion,
    request_architect_result,
    request_planner_result,
)
from report_writer import (  # noqa: E402
    append_control_event,
    append_dry_run_report,
)
from repo_tools import (  # noqa: E402
    find_repo_root,
    load_simple_yaml,
    read_markdown_directory,
    safe_write_text,
)
from tick_config import (  # noqa: E402
    load_active_project,
    load_configuration,
    selected_active_project,
    validate_dry_run_settings,
    workbench_ready,
)


def _no_active_project_notice() -> int:
    """Print guidance when no app to work on is selected, and exit cleanly."""
    print("No active project selected. Choose an app to work on first:")
    print(
        "  - grow a seed and promote it: "
        "python3 scripts/context_growth.py promote --project-id <id>"
    )
    print(
        "  - or set factory.active_project to a registered workbench in "
        "config/."
    )
    return 0


def main() -> int:
    """Execute one planning-only Architect, Planner, and contract tick.

    Returns:
        Process exit code ``0`` after completion, pause, or stop.
    """
    root = find_repo_root()
    factory_config, projects_config = load_configuration(root)
    models_config = load_simple_yaml("config/models.yaml", root)
    factory = factory_config["factory"]
    validate_dry_run_settings(factory)
    if not selected_active_project(factory, projects_config):
        return _no_active_project_notice()
    project_name, project = load_active_project(factory, projects_config)
    if not workbench_ready(project, root):
        print(
            f"Workbench for '{project_name}' is missing. Promote or create it "
            "before running a tick."
        )
        return 0
    state_dir = str(factory["state_dir"])
    factory_state, active_run, project_state = load_state(root, state_dir)
    validate_state_project(project_name, factory_state, project_state)

    control_action = requested_control_action(factory_state)
    if control_action:
        factory_state["status"] = control_action
        active_run["run_status"] = control_action
        active_run["current_phase"] = "WAIT"
        persist_state(
            root=root,
            state_dir=state_dir,
            factory_state=factory_state,
            active_run=active_run,
            project_state=project_state,
        )
        detail = f"Owner {control_action} flag is active."
        append_control_event(
            project_name=project_name,
            outcome=control_action,
            detail=detail,
            repo_root=root,
        )
        print(f"Crazy Factory tick {control_action}: {detail}")
        return 0

    max_lines = int(factory["max_lines_per_file"])
    contexts = read_markdown_directory(
        str(project["context_root"]),
        repo_root=root,
        max_lines_per_file=max_lines,
    )
    tasks = read_markdown_directory(
        str(project["task_root"]),
        repo_root=root,
        max_lines_per_file=max_lines,
    )
    architect_result = request_architect_result(
        project_name=project_name,
        project=project,
        project_state=project_state,
        factory_config=factory_config,
        models_config=models_config,
        max_lines=max_lines,
        tasks=tasks,
    )

    task_root = str(project["task_root"])
    task_expansion_path, next_action_path = planning_paths(root, project)
    safe_write_text(
        task_expansion_path,
        render_task_expansion(architect_result),
        repo_root=root,
        allowed_roots=[task_root],
    )
    planner_result = request_planner_result(
        project_name=project_name,
        project=project,
        project_state=project_state,
        factory_config=factory_config,
        models_config=models_config,
        max_lines=max_lines,
        tasks=tasks,
        architect_result=architect_result,
    )
    safe_write_text(
        next_action_path,
        render_next_action(planner_result),
        repo_root=root,
        allowed_roots=[task_root],
    )

    contract_result, contract_json_path, planned_task_path = (
        run_contract_stage(
            project_name=project_name,
            root=root,
            project=project,
            factory_config=factory_config,
            models_config=models_config,
            max_lines=max_lines,
            tasks=tasks,
            architect_result=architect_result,
            planner_result=planner_result,
        )
    )

    max_files = int(factory["max_files_per_run"])
    coder_result, proposal_json_path, proposal_md_path = run_coder_stage(
        project_name=project_name,
        root=root,
        project=project,
        factory_config=factory_config,
        models_config=models_config,
        max_lines=max_lines,
        max_files=max_files,
        contract_json_path=contract_json_path,
    )

    application_result, patch_plan_json, patch_plan_md, application_report = (
        run_application_stage(
            project_name=project_name,
            root=root,
            project=project,
            factory_config=factory_config,
            models_config=models_config,
            max_lines=max_lines,
            max_files=max_files,
            contract_json_path=contract_json_path,
            proposal_json_path=proposal_json_path,
        )
    )

    test_plan_result, test_plan_json, test_plan_md = run_test_builder_stage(
        project_name=project_name,
        root=root,
        project=project,
        factory_config=factory_config,
        models_config=models_config,
        max_lines=max_lines,
        contract_json_path=contract_json_path,
        proposal_json_path=proposal_json_path,
    )
    validation_config = factory_config.get("validation", {})
    test_plan = test_plan_result.plan
    validation_result, validation_json, validation_md = run_validation_stage(
        test_plan_id=test_plan.test_plan_id if test_plan else "",
        required_checks=test_plan.required_checks if test_plan else [],
        plan_valid=test_plan is not None and test_plan_result.verdict.valid,
        root=root,
        project=project,
        allow_run=bool(validation_config.get("allow_run", False)),
        timeout_seconds=int(validation_config.get("timeout_seconds", 60)),
    )

    coder_summary = (
        coder_result.proposal.summary if coder_result.proposal else ""
    )
    checkpoint_result, checkpoint_report = run_checkpoint_stage(
        project_name=project_name,
        root=root,
        project=project,
        factory_config=factory_config,
        contract_json_path=contract_json_path,
        proposal_json_path=proposal_json_path,
        application_json_path=patch_plan_json,
        validation_json_path=validation_json,
        summary=coder_summary,
    )

    update_success_state(
        factory_state,
        active_run,
        project_state,
        architect_result,
        planner_result,
        contract_result=contract_result,
        coder_result=coder_result,
        application_result=application_result,
        test_plan_result=test_plan_result,
        validation_result=validation_result,
        checkpoint_result=checkpoint_result,
    )
    persist_state(
        root=root,
        state_dir=state_dir,
        factory_state=factory_state,
        active_run=active_run,
        project_state=project_state,
    )
    planning_files = [task_expansion_path, next_action_path]
    contract_status = contract_status_label(contract_result)
    contract_authorized = contract_result.preserved
    coder_status = coder_status_label(coder_result)
    coder_proposal = coder_result.proposal
    coder_files = (
        [proposal_json_path, proposal_md_path]
        if coder_result.activated
        else []
    )
    report_path = append_dry_run_report(
        project_name=project_name,
        project_report_root=str(project["report_root"]),
        mode=str(factory["mode"]),
        context_files=list(contexts),
        task_files=list(tasks),
        git_status=status(),
        factory_state=factory_state,
        active_run=active_run,
        project_state=project_state,
        architect_source=architect_result.source,
        architect_detail=architect_result.detail,
        planner_source=planner_result.source,
        planner_detail=planner_result.detail,
        last_role_completed="reporter",
        planning_files=planning_files,
        contract_status=contract_status,
        contract_source=contract_result.source,
        contract_detail=contract_result.detail,
        contract_reasons=list(contract_result.verdict.reasons),
        contract_files=[contract_json_path, planned_task_path],
        contract_authorized=contract_authorized,
        coder_status=coder_status,
        coder_proposal_id=(
            coder_proposal.proposal_id if coder_proposal else None
        ),
        coder_task_id=coder_proposal.task_id if coder_proposal else None,
        coder_activated=coder_result.activated,
        coder_warnings=list(coder_result.verdict.warnings),
        coder_blocked_paths=list(coder_result.verdict.blocked_paths),
        coder_files=coder_files,
        application_status=application_status_label(application_result),
        application_mode=application_result.mode,
        application_applied=application_result.applied,
        application_reasons=list(application_result.verdict.reasons),
        application_blocked_paths=list(
            application_result.verdict.blocked_paths
        ),
        application_files=(
            [patch_plan_json, patch_plan_md, application_report]
            if application_result.activated
            else []
        ),
        test_plan_status=test_plan_status_label(test_plan_result),
        test_plan_id=test_plan.test_plan_id if test_plan else None,
        validation_status=validation_status_label(validation_result),
        validation_executed=validation_result.executed,
        validation_checks=[
            f"`{c.status}` {c.command}" for c in validation_result.checks
        ],
        validation_files=(
            [validation_json, validation_md]
            if (test_plan is not None and test_plan_result.verdict.valid)
            else []
        ),
        checkpoint_status=checkpoint_status_label(checkpoint_result),
        checkpoint_id=checkpoint_result.checkpoint_id,
        checkpoint_commit=checkpoint_result.commit_sha,
        checkpoint_committed=checkpoint_result.committed,
        checkpoint_excluded=list(checkpoint_result.excluded_files),
        repo_root=root,
    )

    authorized_text = (
        "true (owner-authorized)"
        if contract_authorized
        else ("false (owner approval required)")
    )
    application_status = application_status_label(application_result)
    print(
        "Crazy Factory Phase 7 planning + proposal + application + "
        "validation + checkpoint dry run complete"
    )
    print(f"Active project: {project_name}")
    print(f"Context files read: {len(contexts)}")
    print(f"Task files read: {len(tasks)}")
    print(f"Architect planning source: {architect_result.source}")
    print(f"Planner planning source: {planner_result.source}")
    print(f"Contract source: {contract_result.source}")
    print(f"Contract validation: {contract_status}")
    print(f"Contract authorized: {authorized_text}")
    print(f"Coder activated: {str(coder_result.activated).lower()}")
    print(f"Coder proposal verdict: {coder_status}")
    print(f"Application mode: {application_result.mode}")
    print(f"Application status: {application_status}")
    print(f"Application applied: {str(application_result.applied).lower()}")
    print(
        f"Test plan: {test_plan_status_label(test_plan_result)} | "
        f"Validation: {validation_status_label(validation_result)} "
        f"(executed: {str(validation_result.executed).lower()})"
    )
    print(
        f"Checkpoint: {checkpoint_status_label(checkpoint_result)} "
        f"(committed: {str(checkpoint_result.committed).lower()})"
    )
    print("Last role completed: reporter")
    print(f"Report written: {report_path.relative_to(root)}")
    print(
        "Safety: planning + proposal + preview only; no commit/push/merge "
        "attempted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
