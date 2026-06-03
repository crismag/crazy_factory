#!/usr/bin/env python3
"""Phase 9 seed-grown context engine for Crazy Factory.

A project starts from one small seed document and grows its context one
artifact at a time. Each ``grow`` cycle reads the seed and the most recent
artifacts, asks the model for the single next most useful artifact (its type,
the reason, and its content), writes exactly that one artifact, records it in
the ledger, and stops. The growth order is decided by the model, not
hardcoded.

Hard boundaries (Phase 8 invariants preserved):

- This layer writes only under ``factory_state/projects/<id>/``. It never
  writes application code, never applies a patch, never runs a command, and
  never touches git.
- When the model decides the next artifact is an implementation task, it does
  NOT modify files. It emits a *planned task contract* shaped for the existing
  Phase 3-8 pipeline with ``authorized: false`` — the owner must authorize it
  through the normal flow before anything is built.
- Model unavailable or malformed output falls back to a deterministic, safe
  artifact rather than crashing.

Example:
    python3 scripts/context_growth.py start \\
        --seed examples/seeds/sqlite_project_manager.md \\
        --project-id sqlite_project_manager
    python3 scripts/context_growth.py grow --project-id sqlite_project_manager
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from context_ledger import (  # noqa: E402
    append_artifact,
    load_ledger,
    next_artifact_id,
    save_ledger,
)
from json_parsing import coerce_str, strip_code_fence  # noqa: E402
from ollama_client import OllamaClient, OllamaConnectionError  # noqa: E402
from repo_tools import (  # noqa: E402
    find_repo_root,
    load_simple_yaml,
    safe_write_json,
    safe_write_text,
)
from seed_context import (  # noqa: E402
    contexts_dir,
    init_project,
    load_seed,
    recent_artifacts,
    validate_project_id,
)
from task_contract import (  # noqa: E402
    ContractParseError,
    contract_to_dict,
    parse_planned_task,
    validate_planned_task,
)

# Artifact types the model may choose. The set is bounded so a stray type
# cannot create arbitrary files; the ORDER is the model's decision.
ALLOWED_ARTIFACT_TYPES: tuple[str, ...] = (
    "observation",
    "questions",
    "requirements",
    "architecture",
    "task_proposal",
    "reflection",
    "validation_summary",
    "next_action",
)


@dataclass(frozen=True)
class GrowthResult:
    """One growth decision and the artifact content it produced.

    Attributes:
        artifact_type: The chosen artifact type (in ALLOWED_ARTIFACT_TYPES).
        reason: Why this is the next most useful artifact.
        requires_user_input: Whether the model wants owner input next.
        safe_to_continue: Whether the model judges it safe to keep growing.
        content: The artifact body (markdown, or JSON text for task_proposal).
        source: ``"ollama"`` or ``"fallback"``.
    """

    artifact_type: str
    reason: str
    requires_user_input: bool
    safe_to_continue: bool
    content: str
    source: str


def _fallback_growth(seed: str, recent: list[tuple[str, str]]) -> GrowthResult:
    """Produce a deterministic, safe growth artifact when the model is down.

    Args:
        seed: The project seed text.
        recent: Recent ``(type, content)`` artifacts.

    Returns:
        A deterministic growth result that never proposes an implementation.
    """
    artifact_type = "observation" if len(recent) <= 1 else "next_action"
    content = (
        f"# {artifact_type.title()} (fallback)\n\n"
        "The local model was unavailable, so this is a deterministic "
        "placeholder.\n\n"
        "## Seed Recap\n\n"
        f"{seed.strip()[:600]}\n\n"
        "## Next Useful Step\n\n"
        "- Re-run `grow` once the local model is reachable to continue "
        "growing context.\n"
    )
    return GrowthResult(
        artifact_type=artifact_type,
        reason="Local model unavailable; recorded a safe placeholder.",
        requires_user_input=False,
        safe_to_continue=True,
        content=content,
        source="fallback",
    )


def request_growth(
    *,
    seed: str,
    recent: list[tuple[str, str]],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
) -> GrowthResult:
    """Ask the model for the next useful context artifact.

    Args:
        seed: The project seed text.
        recent: Recent ``(type, content)`` artifacts, oldest first.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        models_config: Parsed ``config/models.yaml`` mapping.

    Returns:
        A growth result. Falls back deterministically on any model failure.
    """
    model = str(models_config["models"]["planner"])
    ollama = factory_config["ollama"]
    client = OllamaClient(
        base_url=str(ollama["base_url"]),
        timeout_seconds=int(ollama["timeout_seconds"]),
        stream=bool(ollama["stream"]),
    )
    types = ", ".join(ALLOWED_ARTIFACT_TYPES)
    instruction = (
        "You grow a software project's context from a seed, one artifact at a "
        "time. Read the seed and recent artifacts and decide the SINGLE next "
        "most useful artifact. Return ONLY a JSON object with keys: "
        f"next_artifact_type (one of: {types}), reason, requires_user_input "
        "(boolean), safe_to_continue (boolean), content. 'content' is the full "
        "artifact body as Markdown. For next_artifact_type 'task_proposal', "
        "'content' MUST be a JSON object string with keys task_id, title, "
        "objective, scope (array), exclusions (array), inputs (array), "
        "acceptance_criteria (array), validation_plan, risks (array), "
        "approval_status set to 'pending'. Never write or apply code; only "
        "describe. Choose the smallest useful next step based on what is "
        "missing."
    )
    recent_text = "\n\n".join(
        f"### Recent artifact: {atype}\n\n{text.rstrip()}"
        for atype, text in recent
    )
    messages = [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": (
                f"## Seed\n\n{seed.rstrip()}\n\n"
                f"## Recent Context\n\n{recent_text or '_None yet._'}\n"
            ),
        },
    ]
    try:
        response = client.chat(model, messages, response_format="json")
        content = str(response["message"]["content"]).strip()
        data = json.loads(strip_code_fence(content))
        if not isinstance(data, dict):
            raise ValueError("growth decision is not an object")
    except (
        KeyError,
        TypeError,
        ValueError,
        OllamaConnectionError,
        json.JSONDecodeError,
    ):
        return _fallback_growth(seed, recent)

    artifact_type = coerce_str(data.get("next_artifact_type")).lower()
    if artifact_type not in ALLOWED_ARTIFACT_TYPES:
        artifact_type = "observation"
    body = data.get("content")
    body_text = body if isinstance(body, str) else json.dumps(body, indent=2)
    if not body_text.strip():
        return _fallback_growth(seed, recent)
    return GrowthResult(
        artifact_type=artifact_type,
        reason=coerce_str(data.get("reason")) or "No reason provided.",
        requires_user_input=bool(data.get("requires_user_input")),
        safe_to_continue=bool(data.get("safe_to_continue", True)),
        content=body_text,
        source="ollama",
    )


def _write_task_proposal(
    content: str, *, project_id: str, artifact_id: str, root: Path
) -> str:
    """Write an implementation task as a pipeline-compatible contract record.

    The record is always ``authorized: false``: the context layer can propose
    an implementation task, but only the owner may authorize it through the
    existing Phase 3 contract flow. A malformed proposal is written as a
    rejected, unauthorized record rather than dropped.

    Args:
        content: The model's JSON contract text.
        project_id: Project identifier.
        artifact_id: Sequential artifact id.
        root: Absolute repository root.

    Returns:
        Repository-relative path of the written task-proposal record.
    """
    path = f"{contexts_dir(project_id)}/{artifact_id}_task_proposal.json"
    try:
        task = parse_planned_task(content)
        verdict = validate_planned_task(task)
        record = contract_to_dict(task, verdict, "context_growth")
    except ContractParseError as exc:
        from task_contract import ValidationVerdict

        record = contract_to_dict(
            None,
            ValidationVerdict(False, [f"Unparseable task proposal: {exc}"]),
            "context_growth",
        )
    # Defense in depth: the context layer never authorizes a contract.
    record["authorized"] = False
    record["source_layer"] = "context_growth"
    safe_write_json(
        path, record, repo_root=root, allowed_roots=["factory_state"]
    )
    return path


def grow(
    *,
    project_id: str,
    root: Path,
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Run exactly one growth cycle, producing one artifact.

    Args:
        project_id: Project identifier.
        root: Absolute repository root.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        models_config: Parsed ``config/models.yaml`` mapping.

    Returns:
        The artifact type, its repository-relative path, and the updated
        ledger.
    """
    validate_project_id(project_id)
    ledger = load_ledger(project_id, root)
    seed = load_seed(project_id, root)
    recent = recent_artifacts(ledger, root, limit=4)

    result = request_growth(
        seed=seed,
        recent=recent,
        factory_config=factory_config,
        models_config=models_config,
    )
    artifact_id = next_artifact_id(ledger)

    if result.artifact_type == "task_proposal":
        path = _write_task_proposal(
            result.content,
            project_id=project_id,
            artifact_id=artifact_id,
            root=root,
        )
    else:
        path = (
            f"{contexts_dir(project_id)}/"
            f"{artifact_id}_{result.artifact_type}.md"
        )
        document = (
            f"# {result.artifact_type.replace('_', ' ').title()}\n\n"
            f"- Source: `{result.source}`\n"
            f"- Reason: {result.reason}\n"
            f"- Requires owner input: "
            f"`{str(result.requires_user_input).lower()}`\n\n"
            f"{result.content.rstrip()}\n"
        )
        safe_write_text(
            path, document, repo_root=root, allowed_roots=["factory_state"]
        )

    append_artifact(
        ledger,
        artifact_id=artifact_id,
        artifact_type=result.artifact_type,
        path=path,
        summary=result.reason[:120],
    )
    ledger["current_cycle"] = int(ledger.get("current_cycle", 0)) + 1
    save_ledger(ledger, project_id, root)
    return result.artifact_type, path, ledger


def _load_configs(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load factory and model configuration."""
    return (
        load_simple_yaml("config/factory.yaml", root),
        load_simple_yaml("config/models.yaml", root),
    )


def main(argv: list[str] | None = None) -> int:
    """Run the context-growth CLI.

    Args:
        argv: Optional argument vector (for tests). Defaults to ``sys.argv``.

    Returns:
        Process exit code: ``0`` on success, ``2`` on a user error.
    """
    parser = argparse.ArgumentParser(description="Seed-grown context engine.")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="Initialize a project from a seed.")
    start.add_argument("--seed", required=True)
    start.add_argument("--project-id", required=True)
    grow_p = sub.add_parser("grow", help="Grow one context artifact.")
    grow_p.add_argument("--project-id", required=True)

    args = parser.parse_args(argv)
    root = find_repo_root()
    factory_config, models_config = _load_configs(root)

    try:
        if args.command == "start":
            ledger = init_project(
                seed_path=args.seed,
                project_id=args.project_id,
                root=root,
            )
            print(f"Seeded project '{args.project_id}'.")
            print(f"Artifacts: {len(ledger['artifacts'])} (000_seed)")
            return 0
        artifact_type, path, ledger = grow(
            project_id=args.project_id,
            root=root,
            factory_config=factory_config,
            models_config=models_config,
        )
        print(
            f"Grew artifact #{ledger['current_cycle']}: "
            f"{artifact_type} -> {path}"
        )
        print(
            "Safety: context only; no application write, apply, commit, or "
            "push."
        )
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"context_growth error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
