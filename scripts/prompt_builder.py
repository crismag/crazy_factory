#!/usr/bin/env python3
"""Build local prompt packages from approved Markdown context.

Prompt assembly is separate from model execution. This module loads global
context, application context, and role instructions into a single local prompt
package. It never sends that package to Ollama or any external service.

Example:
    Build an Architect prompt without making a model request::

        package = build_prompt_package(
            role="architect",
            project_name="demo_app",
            project_context_root="apps/demo_app/factory_context",
        )
"""

from __future__ import annotations

from dataclasses import dataclass

from repo_tools import find_repo_root, read_markdown_directory, safe_read_text


# App-construction constraints handed to every worker role. Deliberately about
# building THE APP, not about operating the factory — see build_prompt_package.
APP_BUILD_CONSTRAINTS = (
    "- You are building ONE application, confined entirely to its own project "
    "folder. Plan and write ONLY what advances the project goal below.\n"
    "- NEVER plan or perform factory/engine work: do not configure the "
    "factory, create or edit engine/config files (e.g. config.toml/yaml), "
    "install or select models, manage factory state, or bootstrap phases. "
    "That is the engine's concern, not this project.\n"
    "- Treat the application as a bounded construction site: prefer the "
    "smallest valuable change, and keep core logic importable and testable.\n"
    "- Do not perform git operations (commit, push, merge), read secrets or "
    "credentials, or touch files outside the project folder."
)

ROLE_INSTRUCTIONS = {
    "architect": "factory/instructions/ARCHITECT_RULES.md",
    "planner": "factory/instructions/PLANNER_RULES.md",
    "coder": "factory/instructions/CODER_RULES.md",
    "test_builder": "factory/instructions/TEST_BUILDER_RULES.md",
    "reviewer": "factory/instructions/REVIEWER_RULES.md",
}


@dataclass
class PromptPackage:
    """Collected prompt text and its source metadata.

    Attributes:
        role: Worker role that will receive the prompt.
        project_name: Application workbench associated with the prompt.
        prompt: Combined Markdown prompt text.
        source_files: Repository-relative files included in ``prompt``.
    """

    role: str
    project_name: str
    prompt: str
    source_files: list[str]


def build_prompt_package(
    *,
    role: str,
    project_name: str,
    project_context_root: str,
    max_lines_per_file: int = 300,
) -> PromptPackage:
    """Assemble an approved local context package for one worker role.

    Args:
        role: Worker role name. Must exist in ``ROLE_INSTRUCTIONS``.
        project_name: Human-readable project name for package metadata.
        project_context_root: Repository-relative application context folder.
        max_lines_per_file: Maximum number of lines read from each context
            file. This bounds prompt growth during bootstrap.

    Returns:
        Prompt package containing assembled Markdown and source-file metadata.

    Raises:
        RepoSafetyError: If a context path crosses a repository boundary.
        ValueError: If ``role`` is unsupported.
    """
    if role not in ROLE_INSTRUCTIONS:
        raise ValueError(f"Unsupported worker role: {role}")
    root = find_repo_root()

    project_sections = list(
        read_markdown_directory(
            project_context_root,
            repo_root=root,
            max_lines_per_file=max_lines_per_file,
        ).items()
    )
    role_path = ROLE_INSTRUCTIONS[role]
    role_text = safe_read_text(role_path, root, max_lines_per_file)

    # IMPORTANT: app-building roles receive app-construction CONSTRAINTS plus
    # the project goal — NOT the factory's own self-operation corpus
    # (contexts/: mission, model strategy, continuous operation, phase
    # permissions). Those docs describe the FACTORY's job, and a local model
    # reads them as the task — it would plan "configure the factory / create
    # config.toml / set up Ollama for Phase 2" instead of building the app.
    # Real safety does not depend on the model seeing that corpus: the
    # deterministic contract floor enforces forbidden-operation and
    # write-confinement rules regardless of the prompt.
    parts: list[str] = [
        "# Operating Constraints (apply to every task; NOT the work itself)",
        APP_BUILD_CONSTRAINTS,
        "# The Project To Build",
        (
            "This is the application you are working on. Any task you plan, "
            "and any code you write, MUST advance THIS project as described "
            "below."
        ),
    ]
    if project_sections:
        parts.extend(
            f"## Source: {path}\n\n{text.rstrip()}"
            for path, text in project_sections
        )
    else:
        parts.append(
            "_No project goal/context has been provided yet. Do not invent "
            "factory-setup work; request the project goal instead._"
        )
    parts.append(f"## Role Instructions: {role_path}\n\n{role_text.rstrip()}")

    prompt = "\n\n".join(parts)
    source_files = [path for path, _ in project_sections] + [role_path]
    return PromptPackage(role, project_name, prompt, source_files)
