#!/usr/bin/env python3
"""Architect and Planner planning roles for a Crazy Factory tick.

This module owns the planning-only worker roles: requesting an Architect task
expansion and a Planner next action from local Ollama models, deterministic
fallbacks when Ollama is unavailable, rendering those results as Markdown
records, and resolving the two fixed planning file paths. It generates no
application code and writes nothing itself.

Example:
    Request a planning-only Architect expansion::

        result = request_architect_result(
            project_name="demo_app",
            project=project,
            project_state=project_state,
            factory_config=factory_config,
            models_config=models_config,
            max_lines=300,
            tasks=tasks,
        )
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ollama_client import OllamaClient, OllamaConnectionError
from prompt_builder import build_prompt_package
from repo_tools import resolve_repo_path


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
