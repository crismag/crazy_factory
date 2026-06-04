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
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from context_ledger import (  # noqa: E402
    append_artifact,
    load_ledger,
    next_artifact_id,
    save_ledger,
)
import factory_messaging as msg  # noqa: E402
from json_parsing import coerce_str, strip_code_fence  # noqa: E402
from ollama_client import OllamaClient, OllamaConnectionError  # noqa: E402
from mission_state import initial_state  # noqa: E402
from project_paths import (  # noqa: E402
    assert_project_local,
    resolve_paths,
)
from settings import load_engine_settings  # noqa: E402
from project_registry import (  # noqa: E402
    load_registry,
    register_project,
    save_registry,
    state_path_for,
)
from repo_tools import (  # noqa: E402
    find_repo_root,
    load_simple_yaml,
    resolve_repo_path,
    safe_load_json,
    safe_read_text,
    safe_write_json,
    safe_write_text,
)
from seed_context import (  # noqa: E402
    contexts_dir,
    init_project,
    load_seed,
    project_root,
    recent_artifacts,
    staging_base,
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
    path = f"{contexts_dir(project_id, root)}/{artifact_id}_task_proposal.json"
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
        path, record, repo_root=root, allowed_roots=[staging_base(root)]
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
            f"{contexts_dir(project_id, root)}/"
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
            path,
            document,
            repo_root=root,
            allowed_roots=[staging_base(root)],
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


class PromoteError(RuntimeError):
    """Raised when a project cannot be promoted to the build pipeline."""


# Subdirectories of an application workbench (mirrors the demo_app layout).
_WORKBENCH_SUBDIRS: tuple[str, ...] = (
    "app",
    "docs",
    "tests",
    "factory_context",
    "factory_tasks",
    "factory_reports",
    "factory_prompts",
    "factory_scripts",
)


def find_latest_valid_task_proposal(
    ledger: dict[str, Any], root: Path
) -> dict[str, Any] | None:
    """Return the most recent grown task proposal that validated as valid.

    Args:
        ledger: The project ledger.
        root: Absolute repository root.

    Returns:
        The latest valid task-proposal contract record, or ``None``.
    """
    for entry in reversed(ledger.get("artifacts", [])):
        if entry.get("type") != "task_proposal":
            continue
        try:
            record = safe_load_json(str(entry.get("path", "")), root)
        except (ValueError, OSError):
            continue
        validation = record.get("validation")
        if (
            isinstance(validation, dict)
            and validation.get("status") == "valid"
        ):
            return record
    return None


def _register_project(project_id: str, root: Path) -> bool:
    """Register the project in the registry and make it the active project.

    Writes a registry entry in the App Builder schema (``app_path`` /
    ``state_path`` / ``repo_mode`` / ``seed_file``) so the advance can resolve the
    workbench, and sets ``active_project``. Promoted apps are embedded under
    ``apps/<id>``.

    Args:
        project_id: Validated project identifier.
        root: Absolute repository root.

    Returns:
        ``True`` if the project was already registered, else ``False``.
    """
    registry = load_registry(root)
    already = project_id in registry["projects"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    register_project(
        registry,
        project_id=project_id,
        app_path=f"apps/{project_id}",
        state_path=state_path_for(project_id, root),
        repo_mode="embedded",
        seed_file="docs/seed.md",
        now=now,
    )
    save_registry(registry, root)
    return already


def _ensure_workbench(project_id: str, root: Path, seed_text: str) -> None:
    """Create the app workbench directories without clobbering existing code.

    Args:
        project_id: Validated project identifier.
        root: Absolute repository root.
        seed_text: The project seed, materialized as the project goal.
    """
    base = f"apps/{project_id}"
    for sub in _WORKBENCH_SUBDIRS:
        keep = f"{base}/{sub}/.gitkeep"
        if not resolve_repo_path(keep, root).exists():
            safe_write_text(keep, "", repo_root=root, allowed_roots=["apps"])
    goal = f"{base}/factory_context/PROJECT_GOAL.md"
    if not resolve_repo_path(goal, root).is_file():
        safe_write_text(
            goal,
            "# Project Goal\n\n"
            "Materialized from the seed-grown context.\n\n"
            f"{seed_text.strip()}\n",
            repo_root=root,
            allowed_roots=["apps"],
        )
    # Project-local runtime: config copied from the root default template, plus
    # the run-state and factory-memory folders. Engine root stays clean.
    cfg = f"{base}/config/factory.yaml"
    if not resolve_repo_path(cfg, root).is_file():
        template = load_engine_settings(root)["factory_config_template"]
        safe_write_text(
            cfg,
            safe_read_text(template, root),
            repo_root=root,
            allowed_roots=["apps"],
        )
    keep = f"{base}/factory_state/.gitkeep"
    if not resolve_repo_path(keep, root).exists():
        safe_write_text(keep, "", repo_root=root, allowed_roots=["apps"])


def _write_pipeline_contract(
    project_id: str, record: dict[str, Any], root: Path
) -> str:
    """Write the promoted contract into the build pipeline, unauthorized.

    Args:
        project_id: Validated project identifier.
        record: The grown task-proposal contract record.
        root: Absolute repository root.

    Returns:
        Repository-relative path of the written planned-task contract.
    """
    contract = dict(record)
    # The promote bridge never authorizes; the owner must do so to build.
    contract["authorized"] = False
    contract["promoted_from"] = "context_growth"
    path = f"apps/{project_id}/factory_tasks/planned_task.json"
    safe_write_json(path, contract, repo_root=root, allowed_roots=["apps"])
    return path


def _point_state_at_project(project_id: str, task_id: str, root: Path) -> None:
    """Write the project's own ``<app>/state/`` pointed at the promoted task.

    The promoted project owns its run-state; nothing is written to a root-level
    ``state/`` folder.

    Args:
        project_id: Validated project identifier.
        task_id: Task id of the promoted contract.
        root: Absolute repository root.
    """
    state_dir = f"apps/{project_id}/state"
    bootstrap = initial_state(project_id)
    bootstrap["project_state.json"].update(
        {
            "current_task": task_id,
            "task_id": task_id,
            "recovery_instructions": (
                "Review the promoted planned_task.json and authorize it."
            ),
        }
    )
    bootstrap["active_run.json"].update(
        {
            "current_task": task_id,
            "task_id": task_id,
            "resume_from": (
                f"Authorize apps/{project_id}/factory_tasks/"
                "planned_task.json to begin building."
            ),
        }
    )
    for fname, body in bootstrap.items():
        safe_write_json(
            f"{state_dir}/{fname}",
            body,
            repo_root=root,
            allowed_roots=[state_dir],
        )


def _relocate_seed_state(project_id: str, root: Path) -> bool:
    """Move pre-promote seed-grown state into the project workbench.

    The seed phase stages context under the engine root
    (``factory_state/projects/<id>/``) because no workbench exists yet. At
    promote the workbench does exist, so the whole staging tree moves into
    ``apps/<id>/factory_state/`` — after this, the project owns its grown
    context and nothing for it lives at the root.

    Non-destructive and idempotent: a missing source is a clean no-op (the
    project may have been started without seed-growth), and a destination file
    that already exists is left untouched. The moved ledger's artifact paths
    are rewritten from the old root prefix to the workbench prefix so post-
    promote inspection still resolves.

    Args:
        project_id: Validated project identifier.
        root: Absolute repository root.

    Returns:
        ``True`` if any file was relocated, else ``False``.
    """
    source_rel = project_root(project_id, root)
    dest_rel = resolve_paths(f"apps/{project_id}").factory_state_dir
    source_abs = resolve_repo_path(source_rel, root)
    if not source_abs.is_dir():
        return False

    for item in sorted(source_abs.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(source_abs).as_posix()
        dest = f"{dest_rel}/{rel}"
        assert_project_local(dest, f"apps/{project_id}", root)
        # Non-destructive: a project file already in the workbench wins.
        if not resolve_repo_path(dest, root).exists():
            safe_write_text(
                dest,
                safe_read_text(item, root),
                repo_root=root,
                allowed_roots=["apps"],
            )

    # Rewrite the relocated ledger's artifact paths to the new prefix.
    dest_ledger = f"{dest_rel}/context_ledger.json"
    if resolve_repo_path(dest_ledger, root).is_file():
        ledger = safe_load_json(dest_ledger, root)
        for artifact in ledger.get("artifacts", []) or []:
            old = str(artifact.get("path") or "")
            if old.startswith(f"{source_rel}/"):
                artifact["path"] = f"{dest_rel}/{old[len(source_rel) + 1 :]}"
        safe_write_json(
            dest_ledger, ledger, repo_root=root, allowed_roots=["apps"]
        )

    # Move semantics: the workbench now owns the grown context — drop the
    # engine-root staging tree (gitignored runtime).
    shutil.rmtree(source_abs)
    return True


def promote(project_id: str, root: Path) -> dict[str, Any]:
    """Promote a grown project into the build pipeline (owner-driven).

    Registers the app workbench, makes it the active project, repoints durable
    state, and copies the latest valid grown task proposal into the build
    pipeline as a planned-task contract with ``authorized: false``. It never
    activates the coder, applies, commits, pushes, or merges.

    Args:
        project_id: Project identifier to promote.
        root: Absolute repository root.

    Returns:
        A summary mapping for reporting.

    Raises:
        PromoteError: If there is no valid task proposal to promote.
    """
    validate_project_id(project_id)
    ledger = load_ledger(project_id, root)
    record = find_latest_valid_task_proposal(ledger, root)
    if record is None:
        raise PromoteError(
            f"No valid task proposal to promote for project '{project_id}'. "
            "Run `grow` until a valid task_proposal artifact exists."
        )
    task_id = coerce_str(record.get("task_id")) or f"{project_id}-001"
    seed = load_seed(project_id, root)

    already_registered = _register_project(project_id, root)
    _ensure_workbench(project_id, root, seed)
    # The workbench now exists — move the pre-promote seed staging into it so
    # the project owns its grown context and nothing remains at the root.
    relocated = _relocate_seed_state(project_id, root)
    contract_path = _write_pipeline_contract(project_id, record, root)
    _point_state_at_project(project_id, task_id, root)
    return {
        "project_id": project_id,
        "task_id": task_id,
        "contract_path": contract_path,
        "already_registered": already_registered,
        "seed_state_relocated": relocated,
    }


def _load_configs(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load factory and model configuration from the configured locations."""
    engine = load_engine_settings(root)
    return (
        load_simple_yaml(engine["factory_config_template"], root),
        load_simple_yaml(engine["models_config"], root),
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
    promote_p = sub.add_parser(
        "promote",
        help="Promote a grown task proposal into the build pipeline.",
    )
    promote_p.add_argument("--project-id", required=True)

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
            msg.sprint(
                f"Seeded project '{args.project_id}' with "
                f"{len(ledger['artifacts'])} artifact(s) (000_seed). Grow its "
                f"context with `context-growth grow {args.project_id}`."
            )
            return 0
        if args.command == "promote":
            summary = promote(args.project_id, root)
            pid = summary["project_id"]
            msg.sprint(
                f"Promoted '{pid}' to the build pipeline — its first contract "
                f"is staged (task {summary['task_id']}, authorized: false). No "
                f"coder/apply/commit was triggered."
            )
            msg.nprint(
                f"Next: review the contract at {summary['contract_path']}, "
                f"then `crazy-admin authorize-task {pid}` and "
                f"`crazy-admin advance {pid}` to build it."
            )
            return 0
        artifact_type, path, ledger = grow(
            project_id=args.project_id,
            root=root,
            factory_config=factory_config,
            models_config=models_config,
        )
        msg.sprint(
            f"Grew '{args.project_id}' context (cycle "
            f"#{ledger['current_cycle']}): added {artifact_type} -> {path}. "
            f"Safety: context only — no application write, apply, commit, or "
            f"push."
        )
        return 0
    except (RuntimeError, ValueError) as exc:
        msg.eprint(f"context-growth {args.command} failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
