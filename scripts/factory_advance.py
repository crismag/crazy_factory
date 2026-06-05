#!/usr/bin/env python3
"""Run one conservative Crazy Factory planning advance.

This module is the orchestrator. It wires together the cohesive helper modules
and owns no domain logic of its own:

- :mod:`advance_config` loads and validates configuration and the active project.
- :mod:`mission_state` loads, transitions, and persists durable state.
- :mod:`planning_roles` runs the Architect and Planner planning roles.
- :mod:`contract_stage` produces or preserves the structured task contract.
- :mod:`report_writer` records observable, recoverable reports.

The loop reads context, asks the Architect for an expansion and the Planner for
a next action, derives a validated task contract, updates resume state, and
writes reports. If Ollama is unavailable, deterministic fallbacks keep the advance
useful and recoverable. It may update fixed planning and contract files,
approved report files, and JSON state snapshots only. It cannot modify
application source code, choose arbitrary write paths, commit, push, or
activate scheduling.

Example:
    Run one local dry-run validation advance from the repository root::

        python3 scripts/factory_advance.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

import factory_messaging as msg  # noqa: E402
from diagnosis_packet import (  # noqa: E402
    build_packet,
    coder_slice,
    patch_plan_slice,
    write_packet,
)
from requirement_expander import (  # noqa: E402
    load_or_expand,
    render_focus_with_spec,
)
from coder_proposal import (  # noqa: E402
    coder_status_label,
    run_coder_stage,
)
from context_loader import (  # noqa: E402
    load_context_bundle,
    summarize_drops,
)
from project_control import (  # noqa: E402
    ControlError,
    apply_project_controls,
    read_control,
)
from owner_controls import (  # noqa: E402
    approve_proposal,
    authorize_task,
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
    application_paths,
    application_status_label,
    run_application_stage,
)
from remediation import (  # noqa: E402
    fix_approval_record,
    plan_remediation,
)
from recovery_router import run_recovery_router  # noqa: E402
from completion import (  # noqa: E402
    CHECKLIST_FILENAME,
    checklist_focus,
    initial_checklist_markdown,
    mark_first_open_done,
    open_items,
    parse_checklist,
)
from test_builder import (  # noqa: E402
    run_test_builder_stage,
    test_plan_status_label,
)
from validation_runner import (  # noqa: E402
    CheckResult,
    ValidationResult,
    run_validation_stage,
    validation_status_label,
)
from architecture import (  # noqa: E402
    coherence_commands,
    existing_violations,
    is_contract_conflict,
    load_contract,
    missing_required,
    render_contract_brief,
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
    safe_write_json,
    safe_write_text,
)
from project_paths import (  # noqa: E402
    assert_project_local,
    load_project_factory_config,
)
from project_registry import (  # noqa: E402
    RegistryError,
    app_is_buildable,
    load_registry,
    resolve_target,
    workbench_exists,
)
from advance_config import validate_dry_run_settings  # noqa: E402
from settings import load_engine_settings  # noqa: E402


def _read_text_or_empty(rel_path: str, root: Path) -> str:
    """Read a workbench file directly (handles external paths + missing).

    Unlike safe_read_text, this does not enforce repo-root confinement, so it
    works for an external app's absolute paths; a missing file yields "".
    """
    try:
        return Path(rel_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _retire_task_artifacts(task_root: str) -> None:
    """Remove a completed task's contract/proposal artifacts.

    Forces the next advance to plan the next open checklist item instead of
    preserving the finished (authorized) contract. The owner re-authorizes each
    fresh task unless autonomous mode pre-authorizes it.
    """
    for name in (
        "planned_task.json",
        "PLANNED_TASK.md",
        "coder_proposal.json",
        "CODER_PROPOSAL.md",
        "approved_proposal.json",
        "patch_plan.json",
        "PATCH_PLAN.md",
        "CONTRACT_REVIEW.md",
    ):
        try:
            (Path(task_root) / name).unlink()
        except OSError:
            pass


def _focus_file_token(checklist_md: str) -> str | None:
    """Extract the target file path from the first open checklist item.

    Items derived from ``required_files`` read "Implement <path> …" / "Write
    <path> …", so the first path-like token names the file the item delivers.
    Returns ``None`` when there is no open item or no path token.
    """
    items = open_items(parse_checklist(checklist_md))
    if not items:
        return None
    for token in items[0].text.split():
        if "/" in token:
            return token.strip(".,;:`")
    return None


def _no_target_notice(detail: str) -> int:
    """Print guidance when no project could be targeted, and exit cleanly."""
    msg.wprint(f"No project to advance: {detail}. Nothing was built.")
    msg.nprint(
        "Target a project one of these ways:\n"
        "  - name one:   crazy-admin advance <id>\n"
        "  - by path:    crazy-admin advance --path <dir>\n"
        "  - from inside the project workbench (cwd), or use --all"
    )
    return 0


def main(project: dict[str, Any] | None = None) -> int:
    """Execute one planning-only Architect, Planner, and contract advance.

    Args:
        project: Pre-resolved project mapping to act on. When ``None`` (e.g.
            the module is run directly), the project is discovered from the
            current working directory — there is no global active project.

    Returns:
        Process exit code ``0`` after completion, pause, or stop.
    """
    root = find_repo_root()
    models_config = load_simple_yaml(
        load_engine_settings(root)["models_config"], root
    )
    if project is None:
        try:
            project = resolve_target(load_registry(root), root, cwd=Path.cwd())
        except RegistryError as exc:
            return _no_target_notice(str(exc))
    project_name = str(project["name"])
    if not workbench_exists(project["app_path"], root):
        msg.eprint(
            f"Cannot advance '{project_name}': its workbench is missing at "
            f"{project['app_path']}. Nothing was built. Create or re-attach it "
            f"with `crazy-admin attachproject {project_name} <path>`."
        )
        return 0
    if not app_is_buildable(project["app_path"], root):
        # An app may live under the repo (embedded) or under the owner-
        # configured external apps base. Anywhere else is not an approved build
        # location, so the factory refuses rather than writing there.
        msg.eprint(
            f"TARGET_PATH_UNSUPPORTED: refusing to advance '{project_name}' at "
            f"the unapproved location {project['app_path']}. The factory only "
            f"writes inside approved roots. Fix: set paths.engine.apps_base "
            f"(or CRAZY_FACTORY_APPS_BASE) to cover it, or move the app under "
            f"apps/."
        )
        return 0
    # Fail loudly if any runtime path is not inside the project folder — the
    # engine root is never a destination for project runtime data.
    for runtime in (
        project["state_dir"],
        project["report_root"],
        project["task_root"],
        project["context_root"],
        project["factory_state_dir"],
    ):
        assert_project_local(str(runtime), project["app_path"], root)
    # The project's own config is authoritative; the engine root holds only the
    # default template. Validate it, then overlay the owner-control capabilities
    # (apply/validation/commit) — project-local switches win when set, else the
    # project config default (OFF). All runtime paths come from the resolver.
    factory_config = load_project_factory_config(project["app_path"], root)
    validate_dry_run_settings(factory_config["factory"])
    factory_config = apply_project_controls(
        factory_config, read_control(project["app_path"], root)
    )
    factory = factory_config["factory"]
    state_dir = str(project["state_dir"])
    factory_state, active_run, project_state = load_state(
        root, state_dir, project_name
    )
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
            project_report_root=str(project["report_root"]),
            outcome=control_action,
            detail=detail,
            repo_root=root,
        )
        msg.info(f"Crazy Factory advance {control_action}: {detail}")
        return 0

    # Park on a terminal blocker rather than churning: a spent remediation
    # budget, or a SELF_REJECTION (the factory's own gate rejected work it
    # produced — a governance contradiction needing upstream repair, not more
    # coding). The owner reviews and runs `revoke-task` to reset and resume.
    parked_blocker = project_state.get("current_blocker")
    if parked_blocker in ("remediation_exhausted", "self_rejection"):
        reason = (
            "remediation_exhausted (fix budget spent on the current task)"
            if parked_blocker == "remediation_exhausted"
            else "self_rejection (work violated the project's own architecture "
            "contract — regenerate the task plan within the contract)"
        )
        msg.warn(
            f"advance parked: '{project_name}' is blocked by {reason}. See the "
            f"latest report; run `crazy-admin revoke-task {project_name}` to "
            "reset and resume."
        )
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
    # Phase 9A: aggregate imported project context and inject it into planning
    # so plans reflect supplied knowledge. The guard bounds prompt growth.
    context_bundle = load_context_bundle(
        root, project, max_lines_per_file=max_lines
    )
    drop_note = summarize_drops(context_bundle)
    if drop_note:
        msg.info(drop_note)
    if context_bundle.included:
        msg.info(
            f"Loaded {len(context_bundle.included)} context file(s) "
            f"({context_bundle.total_bytes} bytes) into planning."
        )

    # Completion engine: a project needs a definition of done. Decompose the
    # goal/context into MASTER_CHECKLIST.md once (when missing/empty), then
    # surface the next OPEN item so planning targets it instead of "some small
    # task". The checklist lives where satisfaction reads it.
    task_root = str(project["task_root"])
    app_path = str(project["app_path"])
    checklist_rel = f"{task_root}/{CHECKLIST_FILENAME}"
    # The architecture contract is the single source of truth for legal work.
    # It is injected UPSTREAM — into decomposition AND planning — so the
    # checklist and tasks only ever propose legal work, instead of the gate
    # rejecting work the factory itself produced (SELF_REJECTION).
    arch_contract = load_contract(app_path)
    arch_brief = render_contract_brief(arch_contract) if arch_contract else ""
    goal_text = "\n\n".join(
        [*contexts.values(), context_bundle.text, arch_brief]
    )
    checklist_md = _read_text_or_empty(checklist_rel, root)
    if not parse_checklist(checklist_md):
        required_files = (
            arch_contract.get("required_files") if arch_contract else None
        )
        checklist_md = initial_checklist_markdown(
            goal_text,
            models_config=models_config,
            factory_config=factory_config,
            required_files=required_files
            if isinstance(required_files, list)
            else None,
        )
        safe_write_text(
            checklist_rel,
            checklist_md,
            repo_root=root,
            allowed_roots=[task_root],
        )
        msg.info(
            f"Decomposed goal into {len(parse_checklist(checklist_md))} "
            f"checklist item(s) -> {CHECKLIST_FILENAME}"
        )
    focus = checklist_focus(checklist_md)
    # 9D Layer 1: enrich the focus with a seed-derived, frozen per-file behavior
    # contract so planner/contract/coder/patch-plan all see concrete behaviors
    # instead of a generic "implement <file>". The deterministic checklist
    # (order/count) is unchanged; only this beat's focus gets richer. Best-
    # effort: any failure degrades to the generic focus.
    focus_file = _focus_file_token(checklist_md)
    if focus_file:
        try:
            spec = load_or_expand(
                focus_file=focus_file,
                seed_context=goal_text,
                architecture_brief=arch_brief,
                project=project,
                root=root,
                models_config=models_config,
                factory_config=factory_config,
            )
            focus = render_focus_with_spec(focus, spec)
            if spec.source == "ollama":
                msg.detail(
                    f"expanded file contract for {focus_file} "
                    f"({len(spec.required_behaviors)} behaviors)"
                )
        except Exception as exc:  # pragma: no cover - expansion is best-effort
            msg.warn(
                f"requirement expansion unavailable for {focus_file}: {exc}"
            )
    planning_context = "\n\n".join(
        part for part in (context_bundle.text, arch_brief, focus) if part
    )

    architect_result = request_architect_result(
        project_name=project_name,
        project=project,
        project_state=project_state,
        factory_config=factory_config,
        models_config=models_config,
        max_lines=max_lines,
        tasks=tasks,
        context_bundle=planning_context,
    )

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
        context_bundle=planning_context,
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
    msg.phase(
        f"Contract — planning and reviewing the next task for '{project_name}'"
    )
    msg.decision(
        "contract.review",
        contract_status_label(contract_result),
        reasons=contract_result.verdict.reasons,
    )
    if not contract_result.verdict.valid:
        msg.rejection("contract", contract_result.verdict.reasons)

    # Autonomous mode (owner-enabled, default OFF): the owner pre-delegates
    # authorization for this checklist-driven build so the loop can march
    # through items unattended. The deterministic safety floor still gates every
    # contract; this only removes the per-item authorize/approve typing.
    autonomous = bool(factory_config.get("autonomy", {}).get("enabled", False))
    if (
        autonomous
        and contract_result.task is not None
        and contract_result.verdict.valid
        and not contract_result.preserved
    ):
        try:
            authorize_task(project, root)
            msg.info(
                "Autonomous: auto-authorized the planned task (owner-enabled)."
            )
        except ControlError:
            pass

    # Remediation: if the prior advance left a validation_failed blocker and
    # the owner enabled remediation, re-engage the coder with the failing
    # report as context and auto-approve the fix (within budget). Every
    # deterministic floor still applies; this only removes per-iteration typing.
    # Read directly (not safe_read_text): task_root is absolute for an external
    # app and would fail repo-root confinement. The path is inside the
    # workbench, and a missing report (first run) just yields empty context.
    report_path = Path(f"{task_root}/VALIDATION_REPORT.md")
    try:
        prior_validation_report = report_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        prior_validation_report = ""
    remediation_plan = plan_remediation(
        factory_config, project_state, prior_validation_report
    )
    if remediation_plan.active:
        msg.decision(
            "remediation",
            f"attempt {remediation_plan.attempt}/"
            f"{remediation_plan.max_attempts}",
            reasons=["re-engaging the coder to fix the failed validation"],
        )

    # 9D: build the situational packet from the PRIOR beat's artifacts (exact
    # failures, rejections, acceptance criteria, workbench reality) and feed
    # each generator its role slice, so a retry targets the real gap instead of
    # repeating a thin/rejected attempt. Best-effort: a build failure must not
    # break the advance.
    coder_situational = ""
    patch_situational = ""
    try:
        packet = build_packet(
            project=project,
            root=root,
            project_state=project_state,
            now=datetime.now(timezone.utc).isoformat(),
        )
        coder_situational = coder_slice(packet)
        patch_situational = patch_plan_slice(packet)
        write_packet(packet, root, project)
    except Exception as exc:  # pragma: no cover - evidence is best-effort
        msg.warn(f"situational packet unavailable this beat: {exc}")

    max_files = int(factory["max_files_per_run"])
    coder_result, proposal_json_path, proposal_md_path = run_coder_stage(
        app_path=str(project["app_path"]),
        root=root,
        project=project,
        factory_config=factory_config,
        models_config=models_config,
        max_lines=max_lines,
        max_files=max_files,
        contract_json_path=contract_json_path,
        remediation_context=remediation_plan.context,
        situational=coder_situational,
    )
    if coder_result.activated:
        msg.phase(f"Coder — proposing a code patch for '{project_name}'")
        msg.decision(
            "coder.proposal",
            coder_status_label(coder_result),
            reasons=coder_result.verdict.reasons,
        )
        if not coder_result.verdict.valid:
            msg.rejection("coder proposal", coder_result.verdict.reasons)

    # Owner-enabled remediation pre-approves the fix proposal for THIS task so
    # the same advance can apply + re-validate it. Gated by remediation_plan
    # (allow_remediation + budget) and only for a freshly valid proposal.
    if (
        remediation_plan.active
        and coder_result.proposal is not None
        and coder_result.verdict.valid
    ):
        approved_path = application_paths(root, project)[0]
        safe_write_json(
            approved_path,
            fix_approval_record(coder_result.proposal.proposal_id),
            repo_root=root,
            allowed_roots=[task_root],
        )
        msg.info(
            "Remediation: auto-approved fix proposal "
            f"{coder_result.proposal.proposal_id} (owner-enabled)."
        )

    # Autonomous mode: pre-approve a freshly valid proposal for the current task
    # (the non-remediation path) so the same advance can apply + validate it.
    if (
        autonomous
        and not remediation_plan.active
        and coder_result.proposal is not None
        and coder_result.verdict.valid
    ):
        try:
            approve_proposal(project, root)
            msg.info("Autonomous: auto-approved the proposal (owner-enabled).")
        except ControlError:
            pass

    application_result, patch_plan_json, patch_plan_md, application_report = (
        run_application_stage(
            app_path=str(project["app_path"]),
            root=root,
            project=project,
            factory_config=factory_config,
            models_config=models_config,
            max_lines=max_lines,
            max_files=max_files,
            contract_json_path=contract_json_path,
            proposal_json_path=proposal_json_path,
            situational=patch_situational,
        )
    )
    if application_result.activated:
        msg.phase(
            f"Application — writing the approved patch into '{project_name}'"
        )
        msg.stage(
            "application",
            application_status_label(application_result),
            detail=application_result.detail,
        )
        if (
            not application_result.applied
            and application_result.verdict.reasons
        ):
            # WHAT was rejected, not just that it was — the rejection checklist.
            msg.rejection("application", application_result.verdict.reasons)

    # SELF_REJECTION: the factory produced work (activated) that its OWN gate
    # rejected for violating the architecture contract. That is a governance
    # contradiction, not a coder failure — do not loop the coder; pause for
    # upstream correction (regenerate the task plan / adjust the contract).
    self_rejection = bool(
        arch_contract
        and application_result.activated
        and not application_result.applied
        and is_contract_conflict(application_result.verdict.reasons)
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
    # When the project declares an architecture contract, validation is the
    # deterministic WHOLE-PROJECT coherence gate (compile + tests + lint over the
    # canonical dirs), never the model's narrow per-file checks. A tick is only
    # earned when the whole project still validates together. (arch_contract +
    # app_path were resolved upstream with the planning context.)
    if arch_contract:
        checks = coherence_commands(app_path, arch_contract)
        plan_valid = bool(checks)
        plan_id = "coherence-gate"
    else:
        checks = test_plan.required_checks if test_plan else []
        plan_valid = test_plan is not None and test_plan_result.verdict.valid
        plan_id = test_plan.test_plan_id if test_plan else ""
    validation_result, validation_json, validation_md = run_validation_stage(
        test_plan_id=plan_id,
        required_checks=checks,
        plan_valid=plan_valid,
        root=root,
        project=project,
        allow_run=bool(validation_config.get("allow_run", False)),
        timeout_seconds=int(validation_config.get("timeout_seconds", 60)),
    )
    # Contract scan: any forbidden file/import already on disk fails the gate
    # outright, regardless of test results (defence in depth behind the patch
    # gate, which should prevent these from landing in the first place).
    if arch_contract:
        violations = existing_violations(app_path, arch_contract)
        if violations:
            validation_result = ValidationResult(
                test_plan_id=plan_id,
                checks=[
                    CheckResult(
                        "architecture-contract",
                        "failed",
                        None,
                        "; ".join(violations)[:400],
                    )
                ],
                status="failed",
                executed=True,
            )
            msg.detail(
                "coherence gate: contract violations on disk",
                items=violations,
            )

    # Surface validation outcome + WHICH checks failed and why (the error
    # checklist), so a failure is diagnosable, not just "validation failed".
    _val_status = validation_status_label(validation_result)
    msg.phase(
        f"Validation — checking the whole '{project_name}' project is "
        f"coherent (compile, tests, lint)"
    )
    msg.stage("validation", _val_status)
    if _val_status in ("failed", "blocked"):
        msg.error(
            "validation did not pass",
            checklist=[
                f"{c.command}: {c.status} — {c.detail}"
                for c in validation_result.checks
                if c.status in ("failed", "error", "blocked")
            ],
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
        remediation=remediation_plan,
    )
    if self_rejection:
        # Override any generic blocker with the named governance failure and
        # park (see the start-of-advance park check). This is the safety net;
        # the upstream contract injection should make it rare.
        project_state["current_blocker"] = "self_rejection"
        active_run["current_blocker"] = "self_rejection"
        msg.error(
            "SYSTEM_CONTRACT_CONFLICT (self_rejection): the factory proposed "
            "work that violates its own architecture contract. Not a coder "
            "failure — regenerate the task plan within the contract (or adjust "
            f"the contract), then `crazy-admin revoke-task {project_name}`.",
            checklist=application_result.verdict.reasons,
        )
    persist_state(
        root=root,
        state_dir=state_dir,
        factory_state=factory_state,
        active_run=active_run,
        project_state=project_state,
    )

    # Completion tick: a FRESH build (new code applied, not a preserved no-op)
    # that validates green completes the item it was working — mark it done so
    # the next beat targets the next open item and the project converges. A
    # preserved/green re-validation does no new work and must not over-tick.
    if (
        application_result.applied
        and application_result.source != "preserved"
        and validation_status_label(validation_result) == "passed"
    ):
        # 9D.5: do not retire an item whose declared required file still does
        # not exist. Whole-project coherence can pass without the item's file
        # having been created (the project was already coherent), which would
        # tick "done" while the deliverable is missing. Gate only on declared
        # required files so AI/synth checklists are unaffected.
        checklist_now = _read_text_or_empty(checklist_rel, root)
        focus_file = _focus_file_token(checklist_now)
        still_missing = set(
            missing_required(app_path, arch_contract) if arch_contract else []
        )
        if focus_file is not None and focus_file in still_missing:
            msg.warn(
                f"Not retiring the current item: its required file "
                f"'{focus_file}' does not exist yet, even though whole-project "
                f"validation passed. The applied patch did not create it; the "
                f"item stays open."
            )
            updated_checklist, completed_item = checklist_now, None
        else:
            updated_checklist, completed_item = mark_first_open_done(
                checklist_now
            )
        if completed_item is not None:
            safe_write_text(
                checklist_rel,
                updated_checklist,
                repo_root=root,
                allowed_roots=[task_root],
            )
            msg.info(f"checklist: completed item -> {completed_item}")
            # Retire the finished task so the next advance plans the NEXT open
            # item. Without this the authorized contract is preserved and the
            # loop never moves past the completed item. If nothing remains open,
            # leave artifacts in place — the project is satisfied.
            if open_items(parse_checklist(updated_checklist)):
                _retire_task_artifacts(task_root)
                msg.info(
                    "retired completed task; next advance plans the next item."
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
        application_written_files=list(application_result.applied_files),
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
    # Verbatim run summary, gated by verbosity (silent at 0) and teed to the
    # log file. Exact text is preserved for downstream tooling.
    msg.report(
        "Crazy Factory Phase 7 planning + proposal + application + "
        "validation + checkpoint dry run complete"
    )
    msg.report(f"Active project: {project_name}")
    msg.report(f"Context files read: {len(contexts)}")
    msg.report(f"Task files read: {len(tasks)}")
    msg.report(f"Architect planning source: {architect_result.source}")
    msg.report(f"Planner planning source: {planner_result.source}")
    msg.report(f"Contract source: {contract_result.source}")
    msg.report(f"Contract validation: {contract_status}")
    msg.report(f"Contract authorized: {authorized_text}")
    msg.report(f"Coder activated: {str(coder_result.activated).lower()}")
    msg.report(f"Coder proposal verdict: {coder_status}")
    msg.report(f"Application mode: {application_result.mode}")
    msg.report(f"Application status: {application_status}")
    msg.report(
        f"Application applied: {str(application_result.applied).lower()}"
    )
    msg.report(
        f"Test plan: {test_plan_status_label(test_plan_result)} | "
        f"Validation: {validation_status_label(validation_result)} "
        f"(executed: {str(validation_result.executed).lower()})"
    )
    msg.report(
        f"Checkpoint: {checkpoint_status_label(checkpoint_result)} "
        f"(committed: {str(checkpoint_result.committed).lower()})"
    )
    msg.report("Last role completed: reporter")
    # report_path may live outside the repo (external app workbench).
    try:
        report_display = report_path.relative_to(root)
    except ValueError:
        report_display = report_path
    msg.report(f"Report written: {report_display}")
    if application_result.applied:
        msg.report(
            "Safety: application writes stayed inside the approved workbench; "
            "no commit/push/merge attempted"
        )
    else:
        msg.report(
            "Safety: no application edit, commit, push, or merge attempted"
        )
    if project_state.get("current_blocker") == "application_rejected" and bool(
        factory_config.get("validation", {}).get("allow_remediation", False)
    ):
        decision, changed = run_recovery_router(
            root=root,
            project=project,
            project_state=project_state,
            active_run=active_run,
        )
        persist_state(
            root=root,
            state_dir=state_dir,
            factory_state=factory_state,
            active_run=active_run,
            project_state=project_state,
        )
        msg.decision(
            "recovery",
            decision.decision,
            reasons=[decision.reason],
        )
        if changed:
            msg.detail("recovery changed artifacts", items=changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
