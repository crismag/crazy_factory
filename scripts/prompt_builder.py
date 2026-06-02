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
    sections: list[tuple[str, str]] = []

    # Keep global context first so role-specific reasoning starts from factory
    # boundaries before reading application details.
    for path, text in read_markdown_directory(
        "contexts", repo_root=root, max_lines_per_file=max_lines_per_file
    ).items():
        sections.append((path, text))
    for path, text in read_markdown_directory(
        project_context_root,
        repo_root=root,
        max_lines_per_file=max_lines_per_file,
    ).items():
        sections.append((path, text))

    role_path = ROLE_INSTRUCTIONS[role]
    role_text = safe_read_text(role_path, root, max_lines_per_file)
    sections.append((role_path, role_text))
    prompt = "\n\n".join(
        f"## Source: {path}\n\n{text.rstrip()}" for path, text in sections
    )
    source_files = [path for path, _ in sections]
    return PromptPackage(role, project_name, prompt, source_files)
