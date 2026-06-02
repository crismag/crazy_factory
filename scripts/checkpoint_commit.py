#!/usr/bin/env python3
"""Phase 7 checkpoint commit engine for Crazy Factory.

This is the first stage that may preserve work through git automatically — and
only under a hard gate. A checkpoint commit is created only when the contract,
proposal, application, and validation all passed, auto-commit is explicitly
enabled, and there are stage-able changes inside the approved commit paths.

Only ``git status``, ``git add <path>``, ``git commit``, and ``git rev-parse``
are ever invoked, always with ``shell=False`` and fixed arguments. The engine
never pushes, merges, resets, rebases, cleans, or rewrites history, and it
stages only files under the configured allowed paths — engine, config, and VCS
files are never staged. Auto-commit defaults to off.
"""

from __future__ import annotations

import json
import subprocess  # noqa: S404 - fixed git argv, shell-free, no user input
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contract_stage import load_existing_contract
from proposal_applier import is_proposal_valid
from repo_tools import safe_write_text
from task_contract import is_contract_actionable

# git subcommands this engine is ever allowed to run. Anything that could push,
# merge, or destroy history is intentionally absent.
ALLOWED_GIT_SUBCOMMANDS: frozenset[str] = frozenset(
    {"status", "add", "commit", "rev-parse"}
)


@dataclass(frozen=True)
class CheckpointResult:
    """Outcome of the checkpoint stage.

    Attributes:
        eligible: Whether the contract/proposal/application/validation gate
            passed.
        committed: Whether a checkpoint commit was actually created.
        reasons: Why a commit was or was not made.
        staged_files: Allowed changed files that were (or would be) staged.
        excluded_files: Changed files outside the allowed commit paths.
        commit_sha: The new commit hash, when committed.
        checkpoint_id: The checkpoint identifier, when committed.
        commit_message: The commit message, when committed.
    """

    eligible: bool
    committed: bool = False
    reasons: list[str] = field(default_factory=list)
    staged_files: list[str] = field(default_factory=list)
    excluded_files: list[str] = field(default_factory=list)
    commit_sha: str | None = None
    checkpoint_id: str | None = None
    commit_message: str | None = None


def _git(args: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    """Run one allowlisted git subcommand with the shell disabled.

    Args:
        args: git arguments beginning with an allowlisted subcommand.
        root: Repository working directory.

    Returns:
        The completed process.

    Raises:
        ValueError: If the subcommand is not allowlisted.
    """
    if not args or args[0] not in ALLOWED_GIT_SUBCOMMANDS:
        raise ValueError(f"Refusing non-allowlisted git subcommand: {args}")
    return subprocess.run(  # noqa: S603 - fixed argv, shell-free
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
        check=False,
    )


def allowed_commit_prefixes(
    factory_config: dict[str, Any], project_name: str
) -> list[str]:
    """Resolve the configured allowed commit-path prefixes.

    Args:
        factory_config: Parsed ``config/factory.yaml`` mapping.
        project_name: Active application workbench name.

    Returns:
        Repository-relative path prefixes that may be staged.
    """
    git_config = factory_config.get("git", {})
    configured = git_config.get("allowed_auto_commit_paths", [])
    if not isinstance(configured, list):
        return []
    return [
        str(item).replace("<active_project>", project_name)
        for item in configured
    ]


def _porcelain_paths(root: Path) -> list[str]:
    """Return repository-relative paths with working-tree changes.

    Args:
        root: Repository working directory.

    Returns:
        Changed paths reported by ``git status --porcelain``.
    """
    # --untracked-files=all lists individual new files instead of collapsing
    # untracked directories to their top-level name.
    completed = _git(["status", "--porcelain", "--untracked-files=all"], root)
    paths: list[str] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        # Porcelain format: XY <path>; renames use "old -> new".
        entry = line[3:].strip()
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        paths.append(entry.strip('"'))
    return paths


def classify_changes(
    paths: list[str], allowed_prefixes: list[str]
) -> tuple[list[str], list[str]]:
    """Split changed paths into allowed and excluded sets.

    Args:
        paths: Changed repository-relative paths.
        allowed_prefixes: Path prefixes that may be staged.

    Returns:
        Allowed paths and excluded paths.
    """
    allowed: list[str] = []
    excluded: list[str] = []
    for path in paths:
        if any(
            path == prefix or path.startswith(prefix.rstrip("/") + "/")
            for prefix in allowed_prefixes
        ):
            allowed.append(path)
        else:
            excluded.append(path)
    return allowed, excluded


def checkpoint_gate(
    *,
    contract_record: object,
    proposal_record: object,
    application_record: object,
    validation_record: object,
) -> tuple[bool, list[str]]:
    """Evaluate whether a checkpoint is eligible.

    A checkpoint requires the full chain to have passed: an authorized, valid
    contract; a valid proposal; a successful (non-rejected) application; and a
    passed validation.

    Args:
        contract_record: Parsed ``planned_task.json``.
        proposal_record: Parsed ``coder_proposal.json``.
        application_record: Parsed ``patch_plan.json``.
        validation_record: Parsed ``validation_result.json``.

    Returns:
        Eligibility and the reasons it is or is not eligible.
    """
    reasons: list[str] = []
    if not (
        isinstance(contract_record, dict)
        and is_contract_actionable(contract_record)
    ):
        reasons.append("Contract is not authorized and valid")
    if not is_proposal_valid(proposal_record):
        reasons.append("Coder proposal is not valid")
    app_status = ""
    if isinstance(application_record, dict):
        validation = application_record.get("validation")
        if isinstance(validation, dict):
            app_status = str(validation.get("status"))
    if app_status not in {"preview", "applied"}:
        reasons.append("Proposal application was not successful")
    val_status = ""
    if isinstance(validation_record, dict):
        val_status = str(validation_record.get("status"))
    if val_status != "passed":
        reasons.append("Validation did not pass")
    return (not reasons, reasons)


def build_commit_message(*, prefix: str, task_id: str, summary: str) -> str:
    """Build a checkpoint commit message from the contract.

    Args:
        prefix: Commit prefix from config (e.g. ``"factory:"``).
        task_id: Backing contract task identifier.
        summary: Short human-readable summary.

    Returns:
        The commit message ``<prefix> checkpoint <task_id> <summary>``.
    """
    clean_prefix = prefix.rstrip(": ").strip() or "factory"
    short = (summary or "workbench update").strip().splitlines()[0][:72]
    return f"{clean_prefix}: checkpoint {task_id or 'UNKNOWN'} {short}".strip()


def _utc_stamp() -> str:
    """Return a compact UTC timestamp for checkpoint identifiers."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def checkpoint_to_dict(
    result: CheckpointResult, *, task_id: str, timestamp: str
) -> dict[str, Any]:
    """Build the machine-readable checkpoint log record.

    Args:
        result: Checkpoint result to serialize.
        task_id: Backing contract task identifier.
        timestamp: UTC timestamp string.

    Returns:
        JSON-serializable checkpoint record.
    """
    return {
        "checkpoint_id": result.checkpoint_id,
        "task_id": task_id,
        "timestamp": timestamp,
        "commit_sha": result.commit_sha,
        "commit_message": result.commit_message,
        "staged_files": list(result.staged_files),
        "excluded_files": list(result.excluded_files),
    }


def render_checkpoint_report_md(
    result: CheckpointResult, *, task_id: str
) -> str:
    """Render a human-readable ``CHECKPOINT_REPORT.md``.

    Args:
        result: Checkpoint result to render.
        task_id: Backing contract task identifier.

    Returns:
        Markdown checkpoint report.
    """

    def bullets(items: list[str]) -> list[str]:
        return [f"- `{item}`" for item in items] if items else ["_None._"]

    lines = [
        "# Checkpoint Report",
        "",
        f"- Task: `{task_id}`",
        f"- Eligible: `{str(result.eligible).lower()}`",
        f"- Committed: `{str(result.committed).lower()}`",
        f"- Checkpoint ID: `{result.checkpoint_id}`",
        f"- Commit: `{result.commit_sha}`",
        f"- Message: {result.commit_message or '_None._'}",
        "",
        "## Reasons",
        "",
        *([f"- {r}" for r in result.reasons] or ["_None._"]),
        "",
        "## Staged Files",
        "",
        *bullets(result.staged_files),
        "",
        "## Excluded Files (outside allowed commit paths)",
        "",
        *bullets(result.excluded_files),
        "",
    ]
    return "\n".join(lines)


def run_checkpoint_stage(
    *,
    project_name: str,
    root: Path,
    project: dict[str, Any],
    factory_config: dict[str, Any],
    contract_json_path: str,
    proposal_json_path: str,
    application_json_path: str,
    validation_json_path: str,
    summary: str,
) -> tuple[CheckpointResult, str]:
    """Create a checkpoint commit only when the full gate passes.

    Stages and commits only files under the configured allowed commit paths,
    and only when the gate passed, auto-commit is enabled, and there are
    changes to stage. Otherwise it writes a preview report and commits nothing.

    Args:
        project_name: Active application workbench name.
        root: Absolute repository root.
        project: Active project configuration mapping.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        contract_json_path: Repository-relative contract path.
        proposal_json_path: Repository-relative coder proposal path.
        application_json_path: Repository-relative patch-plan path.
        validation_json_path: Repository-relative validation-result path.
        summary: Short summary for the commit message.

    Returns:
        Checkpoint result and the checkpoint report path.
    """
    git_config = factory_config.get("git", {})
    allow_auto_commit = bool(git_config.get("allow_auto_commit", False))
    prefix = str(git_config.get("commit_prefix", "factory:"))
    allowed_prefixes = allowed_commit_prefixes(factory_config, project_name)

    contract_record = load_existing_contract(contract_json_path, root)
    proposal_record = load_existing_contract(proposal_json_path, root)
    application_record = load_existing_contract(application_json_path, root)
    validation_record = load_existing_contract(validation_json_path, root)
    task_id = ""
    if isinstance(contract_record, dict):
        task_id = str(contract_record.get("task_id") or "")

    eligible, reasons = checkpoint_gate(
        contract_record=contract_record,
        proposal_record=proposal_record,
        application_record=application_record,
        validation_record=validation_record,
    )
    changed = _porcelain_paths(root)
    staged, excluded = classify_changes(changed, allowed_prefixes)

    result = CheckpointResult(
        eligible=eligible,
        reasons=list(reasons),
        staged_files=staged,
        excluded_files=excluded,
    )

    report_path = str(
        Path(str(project["report_root"])) / "CHECKPOINT_REPORT.md"
    )

    if eligible and allow_auto_commit and staged:
        result = _commit_checkpoint(
            root=root,
            staged=staged,
            excluded=excluded,
            prefix=prefix,
            task_id=task_id,
            summary=summary,
        )
    elif eligible and not allow_auto_commit:
        result = CheckpointResult(
            eligible=True,
            reasons=[*reasons, "auto_commit is disabled (preview only)"],
            staged_files=staged,
            excluded_files=excluded,
        )
    elif eligible and not staged:
        result = CheckpointResult(
            eligible=True,
            reasons=[*reasons, "No changes within allowed commit paths"],
            staged_files=staged,
            excluded_files=excluded,
        )

    safe_write_text(
        report_path,
        render_checkpoint_report_md(result, task_id=task_id),
        repo_root=root,
        allowed_roots=[str(project["report_root"])],
    )
    return result, report_path


def _commit_checkpoint(
    *,
    root: Path,
    staged: list[str],
    excluded: list[str],
    prefix: str,
    task_id: str,
    summary: str,
) -> CheckpointResult:
    """Stage allowed paths, create the commit, and record the checkpoint.

    Args:
        root: Absolute repository root.
        staged: Allowed changed paths to stage.
        excluded: Changed paths outside the allowed commit paths.
        prefix: Commit prefix from config.
        task_id: Backing contract task identifier.
        summary: Short summary for the commit message.

    Returns:
        The committed checkpoint result.
    """
    for path in staged:
        _git(["add", "--", path], root)
    message = build_commit_message(
        prefix=prefix, task_id=task_id, summary=summary
    )
    commit = _git(["commit", "-m", message], root)
    if commit.returncode != 0:
        return CheckpointResult(
            eligible=True,
            committed=False,
            reasons=[f"git commit failed: {commit.stderr.strip()}"],
            staged_files=staged,
            excluded_files=excluded,
        )
    sha = _git(["rev-parse", "HEAD"], root).stdout.strip()
    timestamp = _utc_stamp()
    checkpoint_id = f"CKPT-{timestamp}"
    result = CheckpointResult(
        eligible=True,
        committed=True,
        reasons=["Checkpoint committed"],
        staged_files=staged,
        excluded_files=excluded,
        commit_sha=sha,
        checkpoint_id=checkpoint_id,
        commit_message=message,
    )
    _append_checkpoint_log(
        root=root, result=result, task_id=task_id, timestamp=timestamp
    )
    return result


def _append_checkpoint_log(
    *, root: Path, result: CheckpointResult, task_id: str, timestamp: str
) -> None:
    """Append the checkpoint to the top-level checkpoint log and index.

    Args:
        root: Absolute repository root.
        result: Committed checkpoint result.
        task_id: Backing contract task identifier.
        timestamp: UTC timestamp string.
    """
    record = checkpoint_to_dict(result, task_id=task_id, timestamp=timestamp)
    safe_write_text(
        "checkpoints/checkpoint_log.jsonl",
        json.dumps(record) + "\n",
        repo_root=root,
        allowed_roots=["checkpoints"],
        append=True,
    )
    safe_write_text(
        "checkpoints/CHECKPOINTS.md",
        f"- `{result.checkpoint_id}` `{result.commit_sha}` "
        f"{result.commit_message}\n",
        repo_root=root,
        allowed_roots=["checkpoints"],
        append=True,
    )


def checkpoint_status_label(result: CheckpointResult) -> str:
    """Return the reporting label for a checkpoint outcome.

    Args:
        result: Checkpoint result for the current tick.

    Returns:
        ``"committed"``, ``"eligible"``, or ``"not_eligible"``.
    """
    if result.committed:
        return "committed"
    return "eligible" if result.eligible else "not_eligible"
