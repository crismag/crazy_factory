#!/usr/bin/env python3
"""Opt-in: one TaskNode through isolated workspace + Factory apply.

Default AgentExecutor / factory_advance still writes the canonical
workbench. This module is the explicit isolated path:

TaskNode → bounded packet → isolated workspace → executor (Codex)
  → collect workspace result → Factory integrate → validation
  → product evidence

Codex remains read-only. Its file map is applied to the isolated
tree only. Integration never trusts that map; it inspects the
workspace and applies under Factory authority.

Cleanup runs only after successful integration. Failures keep the
workspace. No merge, push, parallel workers, or claim verification
from worker prose.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent_executor import (
    apply_executor_result,
    build_request,
    default_executor,
)
from execution_assignment import (
    ALLOWED_TOPS,
    compile_assignment,
    persist_assignment,
)
from objective_generator import next_execute_objective
from product_intent import score_claims
from task_graph import (
    STATUS_READY,
    get_task,
    load_task_graph,
    sync_task_graph,
)
from task_integration import (
    APPLY_APPLIED,
    APPLY_REFUSED,
    integrate_workspace,
)
from task_workspace import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    bind_project_to_workspace,
    cleanup_workspace,
    collect_workspace_result,
    create_workspace,
    mark_workspace,
)

ENV_ISOLATED = "CRAZY_FACTORY_ISOLATED_TASK"
ENV_TASK_ID = "CRAZY_FACTORY_TASK_ID"
RUN_FILE = "isolated_task_run.json"


class IsolatedTaskError(RuntimeError):
    """Refused or failed isolated task run."""


@dataclass
class IsolatedTaskRun:
    """One opt-in isolated execution. Every field has a report consumer."""

    ok: bool
    task_id: str
    workspace_id: str
    intent_revision: int
    base_revision: str
    isolation_kind: str
    assignment_stale: bool
    executor_ok: bool
    executor_provider: str
    executor_summary: str
    executor_proposed_files: list[str]
    workspace_changed: list[str]
    workspace_added: list[str]
    workspace_deleted: list[str]
    apply_status: str
    conflict_status: str
    validation_status: str
    allowed_changes: list[str]
    rejected_changes: list[str]
    rejected_reasons: dict[str, str] = field(default_factory=dict)
    scope_confidence: str = ""
    claims_before: list[dict[str, Any]] = field(default_factory=list)
    claims_after: list[dict[str, Any]] = field(default_factory=list)
    canonical_untouched_until_apply: bool = False
    cleaned: bool = False
    reason: str = ""


def isolated_task_requested() -> bool:
    """True when the owner opted into the isolated task pipeline."""
    raw = (os.environ.get(ENV_ISOLATED) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def isolated_task_id_from_env() -> str:
    return (os.environ.get(ENV_TASK_ID) or "").strip()


def _as_path(value: object, root: Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (root / path)


def _app_dir(project: dict[str, Any], root: Path) -> Path:
    return _as_path(project["app_path"], root).resolve()


def _task_dir(project: dict[str, Any], root: Path) -> Path:
    return _as_path(project.get("task_root") or "factory_tasks", root)


def _digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_fingerprint(app: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    if not app.is_dir():
        return hashes
    for top in ALLOWED_TOPS:
        item = app / top
        if not item.exists() or item.is_symlink():
            continue
        if item.is_file():
            hashes[top] = _digest_file(item)
            continue
        if not item.is_dir():
            continue
        for path in sorted(item.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(app).as_posix()
            hashes[rel] = _digest_file(path)
    return hashes


def _claim_rows(project: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for score in score_claims(project, root):
        cap = score.cap
        rows.append(
            {
                "id": getattr(cap, "id", ""),
                "ok": bool(score.ok),
                "kind": str(score.kind),
                "detail": str(score.detail),
            }
        )
    return rows


def _select_task(graph: Any, task_id: str) -> Any:
    if task_id:
        node = get_task(graph, task_id)
        if node is None:
            raise IsolatedTaskError(f"unknown task_id: {task_id}")
        return node
    ready = [
        node
        for node in graph.nodes
        if node.status == STATUS_READY
    ]
    if not ready:
        raise IsolatedTaskError("no ready TaskNode to run in isolation")
    return ready[0]


def _persist_run(
    project: dict[str, Any],
    root: Path,
    record: IsolatedTaskRun,
    workspace_path: str,
) -> None:
    payload = asdict(record)
    if workspace_path:
        home = Path(workspace_path).resolve().parent
        try:
            home.mkdir(parents=True, exist_ok=True)
            (home / RUN_FILE).write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
        except OSError:
            pass
    task_root = _task_dir(project, root)
    try:
        task_root.mkdir(parents=True, exist_ok=True)
        (task_root / RUN_FILE).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        pass


def run_isolated_task(
    project: dict[str, Any],
    root: Path,
    *,
    task_id: str = "",
    executor: Any | None = None,
    cleanup_on_success: bool = True,
) -> IsolatedTaskRun:
    """Run one selected task through the isolated workspace pipeline."""
    wanted = (task_id or isolated_task_id_from_env()).strip()
    objective = next_execute_objective(project, root)
    task_root = _task_dir(project, root)
    graph = load_task_graph(task_root) or sync_task_graph(
        project, root, objective=objective
    )
    task = _select_task(graph, wanted)
    assignment = compile_assignment(project, root, objective, task=task)
    try:
        persist_assignment(assignment, _task_dir(project, root))
    except (OSError, ValueError):
        pass
    claims_before = _claim_rows(project, root)
    empty = IsolatedTaskRun(
        ok=False,
        task_id=task.task_id,
        workspace_id="",
        intent_revision=int(getattr(task, "intent_revision", 0) or 0),
        base_revision="",
        isolation_kind="",
        assignment_stale=bool(assignment.stale),
        executor_ok=False,
        executor_provider="",
        executor_summary="",
        executor_proposed_files=[],
        workspace_changed=[],
        workspace_added=[],
        workspace_deleted=[],
        apply_status=APPLY_REFUSED,
        conflict_status="",
        validation_status="not_run",
        allowed_changes=[],
        rejected_changes=[],
        claims_before=claims_before,
        claims_after=claims_before,
        reason="",
    )
    if assignment.stale:
        empty.reason = assignment.stale_reason or "stale assignment"
        _persist_run(project, root, empty, "")
        return empty
    app = _app_dir(project, root)
    before = _canonical_fingerprint(app)
    workspace = create_workspace(project, root, task=task, assignment=assignment)
    bound = bind_project_to_workspace(project, workspace)
    backend = executor if executor is not None else default_executor()
    request = build_request(
        bound, root, objective=objective, task=task
    )
    exec_out = backend.execute(request)
    proposed = sorted(exec_out.files.keys()) if exec_out.files else []
    apply_err: str | None = None
    if exec_out.ok and exec_out.files:
        _written, apply_err = apply_executor_result(exec_out, bound, root)
    after_worker = _canonical_fingerprint(app)
    untouched = after_worker == before
    inspected = collect_workspace_result(project, root, workspace)
    result = IsolatedTaskRun(
        ok=False,
        task_id=task.task_id,
        workspace_id=workspace.workspace_id,
        intent_revision=workspace.intent_revision,
        base_revision=workspace.base_revision,
        isolation_kind=workspace.isolation_kind,
        assignment_stale=False,
        executor_ok=bool(exec_out.ok),
        executor_provider=str(exec_out.provider or ""),
        executor_summary=str(exec_out.summary or ""),
        executor_proposed_files=proposed,
        workspace_changed=list(inspected.changed_files),
        workspace_added=list(inspected.added_files),
        workspace_deleted=list(inspected.deleted_files),
        apply_status=APPLY_REFUSED,
        conflict_status="",
        validation_status="not_run",
        allowed_changes=[],
        rejected_changes=[],
        claims_before=claims_before,
        claims_after=claims_before,
        canonical_untouched_until_apply=untouched,
        reason=apply_err or exec_out.reason or "",
    )
    if not untouched:
        result.reason = "canonical tree changed before Factory apply"
        mark_workspace(project, root, workspace, STATUS_FAILED)
        _persist_run(project, root, result, workspace.workspace_path)
        return result
    if not inspected.changed_files and not inspected.added_files and not inspected.deleted_files:
        result.reason = result.reason or "executor produced no workspace changes"
        mark_workspace(project, root, workspace, STATUS_FAILED)
        _persist_run(project, root, result, workspace.workspace_path)
        return result
    plan = integrate_workspace(
        project,
        root,
        workspace.workspace_id,
        assignment=assignment,
        task=task,
    )
    result.apply_status = plan.apply_status
    result.conflict_status = plan.conflict_status
    result.validation_status = plan.validation_status
    result.allowed_changes = list(plan.allowed_changes)
    result.rejected_changes = list(plan.rejected_changes)
    result.rejected_reasons = dict(plan.rejected_reasons)
    result.scope_confidence = plan.scope_confidence
    result.claims_after = _claim_rows(project, root)
    if plan.apply_status == APPLY_APPLIED:
        result.ok = True
        result.reason = "integrated under Factory authority"
        mark_workspace(project, root, workspace, STATUS_COMPLETED)
        _persist_run(project, root, result, workspace.workspace_path)
        if cleanup_on_success:
            cleanup_workspace(project, root, workspace.workspace_id)
            result.cleaned = True
            _persist_run(project, root, result, "")
    else:
        result.reason = "; ".join(plan.reasons) or plan.conflict_status
        mark_workspace(project, root, workspace, STATUS_FAILED)
        _persist_run(project, root, result, workspace.workspace_path)
    return result


def render_isolated_run(result: IsolatedTaskRun) -> str:
    """Owner-facing summary. Does not claim claims were verified by apply."""
    lines = [
        f"isolated-task {'OK' if result.ok else 'FAILED'}",
        f"task: {result.task_id}",
        f"workspace: {result.workspace_id}",
        f"isolation: {result.isolation_kind}",
        f"base_revision: {result.base_revision or '(none)'}",
        f"intent_revision: {result.intent_revision}",
        f"executor: {result.executor_provider} ok={result.executor_ok}",
        f"summary: {result.executor_summary}",
        f"proposed: {', '.join(result.executor_proposed_files) or '(none)'}",
        f"workspace_changed: {', '.join(result.workspace_changed) or '(none)'}",
        f"apply: {result.apply_status} conflict={result.conflict_status or 'n/a'}",
        f"validation: {result.validation_status}",
        f"allowed: {', '.join(result.allowed_changes) or '(none)'}",
        f"rejected: {', '.join(result.rejected_changes) or '(none)'}",
        f"canonical_untouched_until_apply: {result.canonical_untouched_until_apply}",
        f"cleaned: {result.cleaned}",
        f"reason: {result.reason}",
        "claims_before:",
    ]
    for row in result.claims_before:
        lines.append(f"  {row.get('id')} ok={row.get('ok')} ({row.get('kind')})")
    lines.append("claims_after:")
    for row in result.claims_after:
        lines.append(f"  {row.get('id')} ok={row.get('ok')} ({row.get('kind')})")
    lines.append(
        "Integration is not claim verification. Evidence above is Factory-owned."
    )
    return "\n".join(lines) + "\n"
