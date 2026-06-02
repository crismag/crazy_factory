#!/usr/bin/env python3
"""Build local prompt packages from factory and application context."""

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
    """Assemble context without sending it to any model."""
    if role not in ROLE_INSTRUCTIONS:
        raise ValueError(f"Unsupported worker role: {role}")
    root = find_repo_root()
    sections: list[tuple[str, str]] = []

    for path, text in read_markdown_directory(
        "contexts", repo_root=root, max_lines_per_file=max_lines_per_file
    ).items():
        sections.append((path, text))
    for path, text in read_markdown_directory(
        project_context_root, repo_root=root, max_lines_per_file=max_lines_per_file
    ).items():
        sections.append((path, text))

    role_path = ROLE_INSTRUCTIONS[role]
    sections.append((role_path, safe_read_text(role_path, root, max_lines_per_file)))
    prompt = "\n\n".join(f"## Source: {path}\n\n{text.rstrip()}" for path, text in sections)
    return PromptPackage(role, project_name, prompt, [path for path, _ in sections])
