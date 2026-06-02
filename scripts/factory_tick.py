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
    validate_dry_run_settings,
)


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
    project_name, project = load_active_project(factory, projects_config)
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

    update_success_state(
        factory_state,
        active_run,
        project_state,
        architect_result,
        planner_result,
        contract_result=contract_result,
        coder_result=coder_result,
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
        repo_root=root,
    )

    authorized_text = (
        "true (owner-authorized)"
        if contract_authorized
        else ("false (owner approval required)")
    )
    print("Crazy Factory Phase 4 planning + coder-proposal dry run complete")
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
    print("Last role completed: reporter")
    print(f"Report written: {report_path.relative_to(root)}")
    print(
        "Safety: planning + proposal only; no app code, commit, or push "
        "attempted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
