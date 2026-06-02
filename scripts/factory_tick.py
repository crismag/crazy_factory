#!/usr/bin/env python3
"""Run one conservative Crazy Factory Phase 2 planning tick.

The validation loop loads configuration, resolves the active application,
loads persistent state, respects pause and stop flags, reads project planning
context. It asks the Architect model for a task expansion and then asks the
Planner model for a bounded next action. If Ollama is unavailable,
deterministic fallback planning keeps the tick useful and recoverable.

The loop may update two fixed planning files, approved report files, and JSON
state snapshots. It cannot modify application source code, choose arbitrary
write paths, commit changes, push changes, or activate scheduling.

Example:
    Run one local dry-run validation tick from the repository root::

        python3 scripts/factory_tick.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from git_guard import status  # noqa: E402
from ollama_client import OllamaClient, OllamaConnectionError  # noqa: E402
from prompt_builder import build_prompt_package  # noqa: E402
from report_writer import (  # noqa: E402
    append_control_event,
    append_dry_run_report,
)
from repo_tools import (  # noqa: E402
    find_repo_root,
    load_simple_yaml,
    read_markdown_directory,
    resolve_repo_path,
    safe_load_json,
    safe_write_json,
    safe_write_text,
)
from task_contract import (  # noqa: E402
    ContractParseError,
    PlannedTask,
    ValidationVerdict,
    contract_to_dict,
    parse_planned_task,
    render_planned_task_md,
    validate_planned_task,
)


@dataclass(frozen=True)
class RoleResult:
    """Planning text and provenance for one worker role.

    Attributes:
        role: Worker role that produced the planning text.
        content: Planning-only worker output.
        source: ``"ollama"`` or ``"fallback"``.
        detail: Human-readable explanation for reports.
    """

    role: str
    content: str
    source: str
    detail: str


@dataclass(frozen=True)
class ContractResult:
    """Outcome of requesting and validating a structured task contract.

    Attributes:
        task: Parsed planned task, or ``None`` when none could be produced.
        verdict: Validation verdict for the contract.
        source: ``"ollama"`` or ``"fallback"``.
        detail: Human-readable explanation for reports.
    """

    task: PlannedTask | None
    verdict: ValidationVerdict
    source: str
    detail: str


def load_configuration(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load factory and project configuration files.

    Args:
        root: Absolute repository root.

    Returns:
        Tuple containing factory configuration and projects configuration.
    """
    return (
        load_simple_yaml("config/factory.yaml", root),
        load_simple_yaml("config/projects.yaml", root),
    )


def validate_dry_run_settings(factory: dict[str, Any]) -> None:
    """Reject settings that exceed Phase 2 authority.

    Args:
        factory: Parsed ``factory`` configuration mapping.

    Raises:
        RuntimeError: If dry-run mode is disabled or a broad write capability
            is enabled.
    """
    mode = str(factory["mode"])
    if mode != "dry_run":
        raise RuntimeError(f"Validation tick refuses non-dry-run mode: {mode}")
    if factory.get("allow_commit") or factory.get("allow_push"):
        raise RuntimeError(
            "Validation tick refuses enabled commit or push settings"
        )
    if factory.get("allow_application_writes") or factory.get(
        "allow_factory_writes"
    ):
        raise RuntimeError(
            "Validation tick refuses broad application or factory writes"
        )


def load_active_project(
    factory: dict[str, Any], projects_config: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Resolve the configured active project.

    Args:
        factory: Parsed ``factory`` configuration mapping.
        projects_config: Parsed ``config/projects.yaml`` mapping.

    Returns:
        Active project name and its configuration mapping.

    Raises:
        RuntimeError: If the configured project is missing or malformed.
    """
    project_name = str(
        factory.get("active_project") or projects_config["active_project"]
    )
    projects = projects_config["projects"]
    if not isinstance(projects, dict) or project_name not in projects:
        raise RuntimeError(f"Unknown active project: {project_name}")
    project = projects[project_name]
    if not isinstance(project, dict):
        raise RuntimeError(f"Invalid project configuration: {project_name}")
    return project_name, project


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


def fallback_architect_result(
    project_name: str, project_state: dict[str, Any], reason: str
) -> RoleResult:
    """Create deterministic planning text when Ollama is unavailable.

    Args:
        project_name: Active application workbench name.
        project_state: Active project state snapshot.
        reason: Human-readable fallback reason.

    Returns:
        Planning-only fallback Architect result.
    """
    task = project_state["current_task"]
    milestone = project_state["current_milestone"]
    content = (
        f"## Validation Expansion For `{task}`\n\n"
        f"- Project: `{project_name}`\n"
        f"- Milestone: `{milestone}`\n"
        "- Mode: `dry_run`\n\n"
        "## Recommended Scope\n\n"
        "- Review the current context and checklist.\n"
        "- Define one small planning-only next action.\n"
        "- Keep application writes disabled until owner approval.\n\n"
        "## Exclusions\n\n"
        "- Do not generate application code.\n"
        "- Do not edit arbitrary files.\n"
        "- Do not commit, push, merge, or activate scheduling.\n"
    )
    return RoleResult("architect", content, "fallback", reason)


def request_architect_result(
    *,
    project_name: str,
    project: dict[str, Any],
    project_state: dict[str, Any],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
    max_lines: int,
    tasks: dict[str, str],
) -> RoleResult:
    """Ask Ollama for a planning-only Architect expansion when available.

    Args:
        project_name: Active application workbench name.
        project: Active project configuration mapping.
        project_state: Active project state snapshot.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        models_config: Parsed ``config/models.yaml`` mapping.
        max_lines: Maximum context lines loaded from each file.
        tasks: Repository-relative task filenames and their content.

    Returns:
        Ollama-backed result or deterministic fallback result.
    """
    prompt_package = build_prompt_package(
        role="architect",
        project_name=project_name,
        project_context_root=str(project["context_root"]),
        max_lines_per_file=max_lines,
    )
    model = str(models_config["models"]["architect"])
    ollama = factory_config["ollama"]
    client = OllamaClient(
        base_url=str(ollama["base_url"]),
        timeout_seconds=int(ollama["timeout_seconds"]),
        stream=bool(ollama["stream"]),
    )
    instruction = (
        "Create a concise planning-only task expansion. Do not generate code. "
        "Do not request arbitrary file edits. Recommend one safe next action."
    )
    task_context = "\n\n".join(
        f"## Task Source: {path}\n\n{text.rstrip()}"
        for path, text in tasks.items()
    )
    messages = [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": f"{prompt_package.prompt}\n\n{task_context}",
        },
    ]
    try:
        response = client.chat(model, messages)
        content = str(response["message"]["content"]).strip()
        if not content:
            raise ValueError("Ollama returned empty Architect content")
    except (KeyError, TypeError, ValueError, OllamaConnectionError) as exc:
        reason = f"Ollama unavailable or invalid; used fallback: {exc}"
        return fallback_architect_result(project_name, project_state, reason)
    return RoleResult(
        "architect", content, "ollama", f"Architect model `{model}`"
    )


def fallback_planner_result(
    project_state: dict[str, Any], reason: str
) -> RoleResult:
    """Create a deterministic next action when Ollama is unavailable.

    Args:
        project_state: Active project state snapshot.
        reason: Human-readable fallback reason.

    Returns:
        Planning-only fallback Planner result.
    """
    task = project_state["current_task"]
    content = (
        f"Continue planning-only review for `{task}`. "
        "Read `TASK_EXPANSION.md`, choose one bounded documentation or "
        "planning follow-up, and keep application writes disabled until "
        "owner approval."
    )
    return RoleResult("planner", content, "fallback", reason)


def request_planner_result(
    *,
    project_name: str,
    project: dict[str, Any],
    project_state: dict[str, Any],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
    max_lines: int,
    tasks: dict[str, str],
    architect_result: RoleResult,
) -> RoleResult:
    """Ask Ollama for a planning-only next action when available.

    Args:
        project_name: Active application workbench name.
        project: Active project configuration mapping.
        project_state: Active project state snapshot.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        models_config: Parsed ``config/models.yaml`` mapping.
        max_lines: Maximum context lines loaded from each file.
        tasks: Repository-relative task filenames and their content.
        architect_result: Architect expansion handed to the Planner.

    Returns:
        Ollama-backed result or deterministic fallback result.
    """
    prompt_package = build_prompt_package(
        role="planner",
        project_name=project_name,
        project_context_root=str(project["context_root"]),
        max_lines_per_file=max_lines,
    )
    model = str(models_config["models"]["planner"])
    ollama = factory_config["ollama"]
    client = OllamaClient(
        base_url=str(ollama["base_url"]),
        timeout_seconds=int(ollama["timeout_seconds"]),
        stream=bool(ollama["stream"]),
    )
    instruction = (
        "Create one concise planning-only next action based on the Architect "
        "expansion. Do not generate code. Do not request arbitrary file "
        "edits. "
        "Keep application writes disabled until owner approval."
    )
    task_context = "\n\n".join(
        f"## Task Source: {path}\n\n{text.rstrip()}"
        for path, text in tasks.items()
    )
    messages = [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": (
                f"{prompt_package.prompt}\n\n"
                f"## Architect Expansion\n\n{architect_result.content}\n\n"
                f"{task_context}"
            ),
        },
    ]
    try:
        response = client.chat(model, messages)
        content = str(response["message"]["content"]).strip()
        if not content:
            raise ValueError("Ollama returned empty Planner content")
    except (KeyError, TypeError, ValueError, OllamaConnectionError) as exc:
        reason = f"Ollama unavailable or invalid; used fallback: {exc}"
        return fallback_planner_result(project_state, reason)
    return RoleResult("planner", content, "ollama", f"Planner model `{model}`")


def request_task_contract(
    *,
    project_name: str,
    project: dict[str, Any],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
    max_lines: int,
    tasks: dict[str, str],
    architect_result: RoleResult,
    planner_result: RoleResult,
) -> ContractResult:
    """Ask Ollama for a JSON task contract and validate it.

    The Planner model is asked to emit a single structured JSON object. The
    response is parsed and validated. When Ollama is unavailable, the response
    is empty, or the contract cannot be parsed, the result is a *rejected*
    contract rather than a trusted one. The factory never authorizes a
    contract on its own; ``authorized`` stays ``False`` regardless of verdict.

    Args:
        project_name: Active application workbench name.
        project: Active project configuration mapping.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        models_config: Parsed ``config/models.yaml`` mapping.
        max_lines: Maximum context lines loaded from each file.
        tasks: Repository-relative task filenames and their content.
        architect_result: Architect expansion handed to the contract step.
        planner_result: Planner next action handed to the contract step.

    Returns:
        Contract result containing the parsed task (or ``None``) and verdict.
    """
    prompt_package = build_prompt_package(
        role="planner",
        project_name=project_name,
        project_context_root=str(project["context_root"]),
        max_lines_per_file=max_lines,
    )
    model = str(models_config["models"]["planner"])
    ollama = factory_config["ollama"]
    client = OllamaClient(
        base_url=str(ollama["base_url"]),
        timeout_seconds=int(ollama["timeout_seconds"]),
        stream=bool(ollama["stream"]),
    )
    instruction = (
        "Return ONLY a single JSON object describing one bounded task "
        "contract. Use these keys: task_id, title, objective, scope (array "
        "of strings), exclusions (array of strings), inputs (array of "
        "strings), acceptance_criteria (array of strings), validation_plan, "
        "risks (array of strings), approval_status. Set approval_status to "
        '"pending". Do not include an authorized field and do not propose an '
        "approved status; only the owner authorizes work. Keep scope small "
        "and bounded, and provide explicit exclusions. Do not reference push, "
        "merge, secrets, or production. Do not generate application code."
    )
    task_context = "\n\n".join(
        f"## Task Source: {path}\n\n{text.rstrip()}"
        for path, text in tasks.items()
    )
    messages = [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": (
                f"{prompt_package.prompt}\n\n"
                f"## Architect Expansion\n\n{architect_result.content}\n\n"
                f"## Planner Next Action\n\n{planner_result.content}\n\n"
                f"{task_context}"
            ),
        },
    ]
    try:
        response = client.chat(model, messages, response_format="json")
    except OllamaConnectionError as exc:
        reason = f"Ollama unavailable; no validated contract produced: {exc}"
        return ContractResult(
            None, ValidationVerdict(False, [reason]), "fallback", reason
        )
    try:
        content = str(response["message"]["content"]).strip()
        if not content:
            raise ValueError("Ollama returned empty contract content")
        task = parse_planned_task(content)
    except (KeyError, TypeError, ValueError, ContractParseError) as exc:
        reason = f"Contract parse failed: {exc}"
        return ContractResult(
            None,
            ValidationVerdict(False, [reason]),
            "ollama",
            f"Planner model `{model}` (unparseable contract)",
        )
    verdict = validate_planned_task(task)
    return ContractResult(task, verdict, "ollama", f"Planner model `{model}`")


def render_task_expansion(result: RoleResult) -> str:
    """Render Architect planning text as a repository task record.

    Args:
        result: Architect result to persist.

    Returns:
        Markdown task-expansion document.
    """
    return (
        "# Task Expansion\n\n"
        "## Architect Dry-Run Source\n\n"
        f"- Source: `{result.source}`\n"
        f"- Detail: {result.detail}\n\n"
        "## Expansion\n\n"
        f"{result.content.rstrip()}\n"
    )


def render_next_action(result: RoleResult) -> str:
    """Render the Planner's bounded next-action record.

    Args:
        result: Planner result used to explain provenance.

    Returns:
        Markdown next-action document.
    """
    return (
        "# Next Action\n\n"
        "## Planner Dry-Run Source\n\n"
        f"- Source: `{result.source}`\n"
        f"- Detail: {result.detail}\n\n"
        "## Recommended Next Action\n\n"
        f"{result.content.rstrip()}\n"
    )


def planning_paths(root: Path, project: dict[str, Any]) -> tuple[str, str]:
    """Return the only two application task files writable in Phase 2.

    Args:
        root: Absolute repository root.
        project: Active project configuration mapping.

    Returns:
        Repository-relative task-expansion and next-action paths.

    Raises:
        RuntimeError: If the task directory escapes the project workbench.
    """
    project_root = resolve_repo_path(str(project["root"]), root)
    task_root = resolve_repo_path(str(project["task_root"]), root)
    if task_root != project_root and project_root not in task_root.parents:
        raise RuntimeError("Task root must stay inside the project workbench")
    return (
        str(Path(str(project["task_root"])) / "TASK_EXPANSION.md"),
        str(Path(str(project["task_root"])) / "NEXT_ACTION.md"),
    )


def contract_paths(root: Path, project: dict[str, Any]) -> tuple[str, str]:
    """Return the two fixed contract files writable in Phase 3.

    Args:
        root: Absolute repository root.
        project: Active project configuration mapping.

    Returns:
        Repository-relative ``planned_task.json`` and ``PLANNED_TASK.md`` paths.

    Raises:
        RuntimeError: If the task directory escapes the project workbench.
    """
    project_root = resolve_repo_path(str(project["root"]), root)
    task_root = resolve_repo_path(str(project["task_root"]), root)
    if task_root != project_root and project_root not in task_root.parents:
        raise RuntimeError("Task root must stay inside the project workbench")
    return (
        str(Path(str(project["task_root"])) / "planned_task.json"),
        str(Path(str(project["task_root"])) / "PLANNED_TASK.md"),
    )


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
    status = "valid" if contract_result.verdict.valid else "rejected"
    reasons = list(contract_result.verdict.reasons)
    factory_state["last_contract_status"] = status
    factory_state["last_contract_source"] = contract_result.source
    project_state["last_contract_status"] = status
    project_state["last_contract_reasons"] = reasons
    # Authorization is owner-only and is never granted by the factory.
    project_state["contract_authorized"] = False
    active_run["last_contract_status"] = status

    if contract_result.verdict.valid:
        active_run["current_blocker"] = None
        project_state["current_blocker"] = None
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


def main() -> int:
    """Execute one Phase 2 Architect and Planner dry-run tick.

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

    contract_result = request_task_contract(
        project_name=project_name,
        project=project,
        factory_config=factory_config,
        models_config=models_config,
        max_lines=max_lines,
        tasks=tasks,
        architect_result=architect_result,
        planner_result=planner_result,
    )
    contract_json_path, planned_task_path = contract_paths(root, project)
    safe_write_json(
        contract_json_path,
        contract_to_dict(
            contract_result.task,
            contract_result.verdict,
            contract_result.source,
        ),
        repo_root=root,
        allowed_roots=[task_root],
    )
    safe_write_text(
        planned_task_path,
        render_planned_task_md(
            contract_result.task,
            contract_result.verdict,
            source=contract_result.source,
            detail=contract_result.detail,
        ),
        repo_root=root,
        allowed_roots=[task_root],
    )

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
        state_dir=state_dir,
        factory_state=factory_state,
        active_run=active_run,
        project_state=project_state,
    )
    planning_files = [task_expansion_path, next_action_path]
    contract_status = "valid" if contract_result.verdict.valid else "rejected"
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
        repo_root=root,
    )

    print("Crazy Factory Phase 3 planning-contract dry run complete")
    print(f"Active project: {project_name}")
    print(f"Context files read: {len(contexts)}")
    print(f"Task files read: {len(tasks)}")
    print(f"Architect planning source: {architect_result.source}")
    print(f"Planner planning source: {planner_result.source}")
    print(f"Contract source: {contract_result.source}")
    print(f"Contract validation: {contract_status}")
    print("Contract authorized: false (owner approval required)")
    print("Last role completed: reporter")
    print(f"Report written: {report_path.relative_to(root)}")
    print(
        "Safety: planning files only; no app code, commit, or push attempted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
