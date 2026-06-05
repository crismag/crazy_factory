#!/usr/bin/env python3
"""Phase 9D Layer 1 — seed-derived per-file requirement expansion.

Deterministic decomposition (``completion.items_from_required_files``) fixes the
checklist's order and count — which is what makes the build converge — but each
item is generic ("Implement src/storage.py with the functionality the project
goal assigns to it"). That genericness starves every downstream prompt of the
file's actual behaviors.

This module keeps the deterministic skeleton and enriches the *content*: for the
file the build is currently focused on, an LLM reads the seed and produces a
concrete behavior + test contract, which is **frozen** to disk and folded into
the planning focus so it flows to planner → contract → coder → patch-plan.

Two safety rules:

- **Freeze once.** A file's contract is expanded the first time it becomes the
  focus and reused thereafter. Regenerating every beat would reintroduce the
  run-to-run variance the deterministic decomposition removed.
- **Degrade, never regress.** If the model is unavailable or returns malformed
  output, fall back to a generic spec (today's behavior) flagged
  ``source="fallback"`` — the flow is never worse than before.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from json_parsing import coerce_str, coerce_str_list, strip_code_fence
from ollama_client import OllamaClient, OllamaConnectionError
from repo_tools import safe_write_json

_CONTRACTS_DIR = "file_contracts"
_MAX_BEHAVIORS = 12


@dataclass(frozen=True)
class FocusRequirementSpec:
    """A concrete, frozen behavior/test contract for one focus file."""

    file: str
    purpose: str
    required_behaviors: list[str]
    required_tests: list[str]
    interfaces: list[str]
    dependencies: list[str]
    done_definition: list[str]
    source: str = "fallback"  # "ollama" | "fallback"


def fallback_spec(focus_file: str) -> FocusRequirementSpec:
    """Generic spec used when expansion is unavailable (no worse than today)."""
    return FocusRequirementSpec(
        file=focus_file,
        purpose=(
            f"Implement {focus_file} per the project goal, keeping the whole "
            "project compiling, lint-clean, and passing all tests."
        ),
        required_behaviors=[],
        required_tests=[],
        interfaces=[],
        dependencies=[],
        done_definition=[
            "compileall passes",
            "pytest passes",
            "ruff passes",
        ],
        source="fallback",
    )


def spec_to_dict(spec: FocusRequirementSpec) -> dict[str, Any]:
    """Return a JSON-serializable mapping of the spec."""
    return {
        "file": spec.file,
        "purpose": spec.purpose,
        "required_behaviors": spec.required_behaviors,
        "required_tests": spec.required_tests,
        "interfaces": spec.interfaces,
        "dependencies": spec.dependencies,
        "done_definition": spec.done_definition,
        "source": spec.source,
    }


def spec_from_dict(data: dict[str, Any]) -> FocusRequirementSpec:
    """Reconstruct a spec from a persisted mapping (tolerant of gaps)."""
    return FocusRequirementSpec(
        file=coerce_str(data.get("file")),
        purpose=coerce_str(data.get("purpose")),
        required_behaviors=coerce_str_list(data.get("required_behaviors")),
        required_tests=coerce_str_list(data.get("required_tests")),
        interfaces=coerce_str_list(data.get("interfaces")),
        dependencies=coerce_str_list(data.get("dependencies")),
        done_definition=coerce_str_list(data.get("done_definition"))
        or ["compileall passes", "pytest passes", "ruff passes"],
        source=coerce_str(data.get("source")) or "fallback",
    )


def _slug(focus_file: str) -> str:
    """Filesystem-safe slug for a focus file path."""
    return re.sub(r"[^A-Za-z0-9]+", "_", focus_file).strip("_") or "file"


def _request_spec(
    *,
    seed_context: str,
    focus_file: str,
    architecture_brief: str,
    models_config: dict[str, Any],
    factory_config: dict[str, Any],
    retries: int,
) -> FocusRequirementSpec | None:
    """Ask a model for the file's behavior/test contract; ``None`` if down."""
    models = models_config.get("models", {})
    model = str(models.get("planner") or models.get("architect") or "")
    ollama = factory_config.get("ollama", {})
    if not model or not ollama:
        return None
    client = OllamaClient(
        base_url=str(ollama.get("base_url", "http://localhost:11434")),
        timeout_seconds=int(ollama.get("timeout_seconds", 120)),
        stream=bool(ollama.get("stream", False)),
    )
    instruction = (
        "You translate a software project goal into a CONCRETE build contract "
        f"for ONE file: {focus_file}. Return ONLY a JSON object with keys: "
        "purpose (string), required_behaviors (array of observable behaviors "
        "this file must implement, including the unhappy paths the goal "
        "implies), required_tests (array of test names, one per behavior), "
        "interfaces (array of function/class signatures), dependencies (array "
        "of other project files it relies on), done_definition (array). Derive "
        "behaviors ONLY from the goal below; do not invent scope. At most "
        f"{_MAX_BEHAVIORS} behaviors. No prose outside the JSON."
    )
    messages = [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": (
                f"## Project goal / context\n\n{seed_context}\n\n"
                f"## Architecture constraints\n\n{architecture_brief}\n\n"
                f"## Target file\n\n{focus_file}"
            ),
        },
    ]
    for _ in range(max(1, retries)):
        try:
            response = client.chat(model, messages, response_format="json")
            content = str(response["message"]["content"]).strip()
            data = json.loads(strip_code_fence(content))
            if not isinstance(data, dict):
                continue
            behaviors = coerce_str_list(data.get("required_behaviors"))[
                :_MAX_BEHAVIORS
            ]
            if not behaviors:
                continue  # a contract with no behaviors is not useful
            return FocusRequirementSpec(
                file=focus_file,
                purpose=coerce_str(data.get("purpose")),
                required_behaviors=behaviors,
                required_tests=coerce_str_list(data.get("required_tests")),
                interfaces=coerce_str_list(data.get("interfaces")),
                dependencies=coerce_str_list(data.get("dependencies")),
                done_definition=coerce_str_list(data.get("done_definition"))
                or ["compileall passes", "pytest passes", "ruff passes"],
                source="ollama",
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            OllamaConnectionError,
            json.JSONDecodeError,
        ):
            continue
    return None


def expand_focus_requirements(
    *,
    seed_context: str,
    focus_file: str,
    architecture_brief: str = "",
    models_config: dict[str, Any] | None = None,
    factory_config: dict[str, Any] | None = None,
    retries: int = 2,
) -> FocusRequirementSpec:
    """Expand a focus file into a behavior/test contract (AI, else fallback)."""
    if models_config and factory_config:
        spec = _request_spec(
            seed_context=seed_context,
            focus_file=focus_file,
            architecture_brief=architecture_brief,
            models_config=models_config,
            factory_config=factory_config,
            retries=retries,
        )
        if spec is not None:
            return spec
    return fallback_spec(focus_file)


def _contract_path(
    project: dict[str, Any], focus_file: str
) -> tuple[str, Path]:
    """Return (repo-relative path, absolute path) for a file's frozen contract."""
    context_root = str(project["context_root"])
    rel = f"{context_root}/{_CONTRACTS_DIR}/{_slug(focus_file)}.json"
    return rel, Path(rel)


def load_or_expand(
    *,
    focus_file: str,
    seed_context: str,
    architecture_brief: str,
    project: dict[str, Any],
    root: Path,
    models_config: dict[str, Any] | None,
    factory_config: dict[str, Any] | None,
) -> FocusRequirementSpec:
    """Load a file's frozen contract, or expand once and freeze it.

    Freezing preserves convergence: a file is expanded the first time it is the
    focus and reused on every later beat.
    """
    context_root = str(project["context_root"])
    rel, abs_path = _contract_path(project, focus_file)
    try:
        existing = json.loads(abs_path.read_text(encoding="utf-8"))
        if isinstance(existing, dict) and existing.get("required_behaviors"):
            return spec_from_dict(existing)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    spec = expand_focus_requirements(
        seed_context=seed_context,
        focus_file=focus_file,
        architecture_brief=architecture_brief,
        models_config=models_config,
        factory_config=factory_config,
    )
    # Freeze only a real (AI) contract; a fallback is re-tried next beat in case
    # the model comes back, but never blocks the flow.
    if spec.source == "ollama":
        try:
            safe_write_json(
                rel,
                spec_to_dict(spec),
                repo_root=root,
                allowed_roots=[context_root],
            )
        except Exception:  # pragma: no cover - freezing is best-effort
            pass
    return spec


def render_focus_with_spec(focus_md: str, spec: FocusRequirementSpec) -> str:
    """Fold a file contract into the planning focus text.

    A fallback spec (no behaviors) returns the original focus unchanged, so the
    planner sees today's generic instruction rather than empty sections.
    """
    if not spec.required_behaviors:
        return focus_md
    lines = [focus_md.strip(), "", f"### File contract for {spec.file}"]
    if spec.purpose:
        lines += ["", f"Purpose: {spec.purpose}"]
    lines += ["", "Required behaviors (each must be implemented and tested):"]
    lines += [f"- {b}" for b in spec.required_behaviors]
    if spec.required_tests:
        lines += ["", "Required tests:"]
        lines += [f"- {t}" for t in spec.required_tests]
    if spec.interfaces:
        lines += ["", "Interfaces:"]
        lines += [f"- {i}" for i in spec.interfaces]
    if spec.dependencies:
        lines += ["", "Depends on: " + ", ".join(spec.dependencies)]
    return "\n".join(lines)
