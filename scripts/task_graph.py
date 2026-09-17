#!/usr/bin/env python3
"""Durable task-graph projection for one workbench.

Crazy Factory still schedules **one** ``ExecuteObjective``. This module
records a dependency-aware, revision-aware graph of grounded work
beside that objective so later slices can distribute specialists
without a parallel planner.

The graph is rebuilt from current Factory truth (intent, evidence,
runtime, validation, deltas, architecture). Stale
``TASK_EXPANSION.md`` is never an input. Claim-to-claim domain
dependencies are not invented.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from architecture import load_contract
from conversation_delta import STATUS_VERIFIED as DELTA_VERIFIED
from conversation_delta import load_deltas
from product_intent import (
    ACCEPTANCE_FILE,
    Capability,
    intent_capabilities,
    intent_revision,
)
from workbench_growth import workbench_metrics

GRAPH_FILE = "task_graph.json"

STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_VERIFIED = "verified"
STATUS_BLOCKED = "blocked"
STATUS_SUPERSEDED = "superseded"

KIND_IMPLEMENT = "implement"
KIND_REPAIR = "repair"
KIND_VERIFY = "verify"
KIND_DELTA = "delta"
KIND_BIRTH = "birth"
KIND_SPECIFY = "specify"

_CONFIG_FILES = frozenset(
    {
        "requirements.txt",
        "architecture.json",
        "pyproject.toml",
        "package.json",
        "package-lock.json",
    }
)
_SCHEMA_PARTS = frozenset({"migrations", "alembic", "schema"})
_REPO_TOPS = ("src", "tests", "data")


@dataclass(frozen=True)
class TaskNode:
    """One grounded unit of work. Every field has a consumer."""

    task_id: str
    parent_objective_id: str
    intent_revision: int
    title: str
    purpose: str
    status: str
    kind: str
    dependencies: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    evidence_targets: tuple[str, ...] = ()
    context_refs: tuple[str, ...] = ()
    affected_scope: tuple[str, ...] = ()


@dataclass
class TaskGraph:
    """Revision-aware graph persisted under the task root."""

    intent_revision: int
    parent_objective_id: str
    nodes: list[TaskNode] = field(default_factory=list)
    fingerprint: str = ""
    repo_fingerprint: str = ""
    prior_fingerprint: str = ""
    prior_repo_fingerprint: str = ""
    churn_without_progress: bool = False


def _as_path(value: object, root: Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (root / path)


def _task_dir(project: dict[str, Any], root: Path) -> Path:
    return _as_path(project.get("task_root") or "factory_tasks", root)


def _app_dir(project: dict[str, Any], root: Path) -> Path:
    return _as_path(project["app_path"], root)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _tuple_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item))
    text = str(value).strip()
    return (text,) if text else ()


def context_ref_intent(revision: int) -> str:
    return f"product_intent@revision-{int(revision)}"


def context_ref_claim(claim_id: str) -> str:
    return f"claim:{claim_id}"


def node_from_dict(raw: dict[str, Any]) -> TaskNode | None:
    task_id = str(raw.get("task_id") or "").strip()
    if not task_id:
        return None
    return TaskNode(
        task_id=task_id,
        parent_objective_id=str(raw.get("parent_objective_id") or ""),
        intent_revision=int(raw.get("intent_revision") or 0),
        title=str(raw.get("title") or ""),
        purpose=str(raw.get("purpose") or ""),
        status=str(raw.get("status") or STATUS_PENDING),
        kind=str(raw.get("kind") or KIND_IMPLEMENT),
        dependencies=_tuple_str(raw.get("dependencies")),
        blocked_by=_tuple_str(raw.get("blocked_by")),
        claim_ids=_tuple_str(raw.get("claim_ids")),
        evidence_targets=_tuple_str(raw.get("evidence_targets")),
        context_refs=_tuple_str(raw.get("context_refs")),
        affected_scope=_tuple_str(raw.get("affected_scope")),
    )


def get_task(graph: TaskGraph, task_id: str) -> TaskNode | None:
    """Return the named node, or None. Does not invent a synthetic task."""
    wanted = str(task_id or "").strip()
    if not wanted:
        return None
    for node in graph.nodes:
        if node.task_id == wanted:
            return node
    return None


def graph_from_dict(raw: dict[str, Any]) -> TaskGraph:
    nodes: list[TaskNode] = []
    for item in raw.get("nodes") or []:
        if not isinstance(item, dict):
            continue
        node = node_from_dict(item)
        if node is not None:
            nodes.append(node)
    return TaskGraph(
        intent_revision=int(raw.get("intent_revision") or 0),
        parent_objective_id=str(raw.get("parent_objective_id") or ""),
        nodes=nodes,
        fingerprint=str(raw.get("fingerprint") or ""),
        repo_fingerprint=str(raw.get("repo_fingerprint") or ""),
        prior_fingerprint=str(raw.get("prior_fingerprint") or ""),
        prior_repo_fingerprint=str(raw.get("prior_repo_fingerprint") or ""),
        churn_without_progress=bool(raw.get("churn_without_progress")),
    )


def load_task_graph(task_root: Path) -> TaskGraph | None:
    raw = _load_json(task_root / GRAPH_FILE)
    if not raw:
        return None
    return graph_from_dict(raw)


def progress_fingerprint(nodes: list[TaskNode], revision: int) -> str:
    """Stable hash of task identity, status, claims, and revision."""
    payload = {
        "revision": int(revision),
        "nodes": [
            {
                "id": node.task_id,
                "status": node.status,
                "claims": list(node.claim_ids),
                "evidence": list(node.evidence_targets),
            }
            for node in sorted(nodes, key=lambda item: item.task_id)
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def repo_fingerprint(app: Path) -> str:
    """Hash of application file paths (not contents) under src/tests/data."""
    names: list[str] = []
    if app.is_dir():
        for top in _REPO_TOPS:
            folder = app / top
            if not folder.is_dir():
                continue
            for path in sorted(folder.rglob("*")):
                if not path.is_file():
                    continue
                if any(
                    part.startswith(".") or part == "__pycache__"
                    for part in path.parts
                ):
                    continue
                try:
                    names.append(path.relative_to(app).as_posix())
                except ValueError:
                    continue
    blob = "\n".join(names)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def detect_cycles(nodes: list[TaskNode]) -> list[str]:
    """Return task ids that participate in a dependency cycle."""
    edges = {node.task_id: list(node.dependencies) for node in nodes}
    visiting: set[str] = set()
    seen: set[str] = set()
    cyclic: set[str] = set()

    def walk(task_id: str) -> None:
        if task_id in seen:
            return
        if task_id in visiting:
            cyclic.add(task_id)
            cyclic.update(visiting)
            return
        visiting.add(task_id)
        for dep in edges.get(task_id, ()):
            walk(dep)
        visiting.remove(task_id)
        seen.add(task_id)

    for node in nodes:
        walk(node.task_id)
    return sorted(cyclic)


def scope_tokens(paths: tuple[str, ...]) -> set[str]:
    """Normalize write-scope paths into overlap tokens."""
    tokens: set[str] = set()
    for raw in paths:
        norm = str(raw).replace("\\", "/").lstrip("./")
        if not norm:
            continue
        tokens.add(norm)
        parts = Path(norm).parts
        if parts:
            if len(parts) >= 2:
                tokens.add(f"{parts[0]}/{parts[1]}")
            if parts[0] not in {"src", "tests"}:
                tokens.add(parts[0])
        name = Path(norm).name
        if name in _CONFIG_FILES:
            tokens.add(f"config:{name}")
        if any(part in _SCHEMA_PARTS for part in parts) or name.endswith(
            ".sql"
        ):
            tokens.add("schema")
        if parts and parts[0] == "data":
            tokens.add("schema:data")
    return tokens


def scopes_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    """True when two write scopes share files, modules, config, or schema."""
    return bool(scope_tokens(left) & scope_tokens(right))


def _is_writer(node: TaskNode) -> bool:
    return node.kind != KIND_VERIFY


def unmet_dependencies(node: TaskNode, by_id: dict[str, TaskNode]) -> bool:
    for dep_id in node.dependencies:
        dep = by_id.get(dep_id)
        if dep is None or dep.status != STATUS_VERIFIED:
            return True
    return False


def is_parallelizable(node: TaskNode, graph: TaskGraph) -> bool:
    """Derived: deps independent AND write-scope independent.

    Unknown write scope on a writing task is not treated as safe.
    """
    if node.status != STATUS_READY:
        return False
    by_id = {item.task_id: item for item in graph.nodes}
    if unmet_dependencies(node, by_id):
        return False
    if not _is_writer(node):
        return True
    if not node.affected_scope:
        return False
    for other in graph.nodes:
        if other.task_id == node.task_id:
            continue
        if other.status not in {STATUS_READY, STATUS_PENDING}:
            continue
        if not _is_writer(other):
            continue
        if not other.affected_scope:
            return False
        if scopes_overlap(node.affected_scope, other.affected_scope):
            return False
    return True


def ready_tasks(graph: TaskGraph) -> list[TaskNode]:
    """Nodes whose status is ready and whose dependencies are verified."""
    by_id = {item.task_id: item for item in graph.nodes}
    return [
        node
        for node in graph.nodes
        if node.status == STATUS_READY and not unmet_dependencies(node, by_id)
    ]


def refresh_statuses(nodes: list[TaskNode]) -> list[TaskNode]:
    """Recompute pending/ready from dependencies without inventing work."""
    by_id = {node.task_id: node for node in nodes}
    refreshed: list[TaskNode] = []
    for node in nodes:
        if node.status in {STATUS_VERIFIED, STATUS_SUPERSEDED}:
            refreshed.append(node)
            continue
        blockers = tuple(
            dep
            for dep in node.blocked_by
            if by_id.get(dep) is not None
            and by_id[dep].status != STATUS_VERIFIED
        )
        if blockers:
            status = STATUS_BLOCKED
        elif unmet_dependencies(node, by_id):
            status = STATUS_PENDING
        else:
            status = STATUS_READY
        payload = asdict(node)
        payload["status"] = status
        updated = node_from_dict(payload)
        refreshed.append(updated if updated is not None else node)
    return refreshed


def stale_revision(graph: TaskGraph, current_revision: int) -> bool:
    """True when a persisted graph predates the current intent revision."""
    return int(graph.intent_revision) != int(current_revision)


def graph_telemetry(graph: TaskGraph) -> dict[str, Any]:
    """Lightweight counts for later evaluation. No analytics UI."""
    kinds = [node.kind for node in graph.nodes]
    return {
        "total_tasks": len(graph.nodes),
        "ready_tasks": sum(
            1 for node in graph.nodes if node.status == STATUS_READY
        ),
        "verified_tasks": sum(
            1 for node in graph.nodes if node.status == STATUS_VERIFIED
        ),
        "blocked_tasks": sum(
            1 for node in graph.nodes if node.status == STATUS_BLOCKED
        ),
        "pending_tasks": sum(
            1 for node in graph.nodes if node.status == STATUS_PENDING
        ),
        "implementation_tasks": sum(
            1
            for kind in kinds
            if kind in {KIND_IMPLEMENT, KIND_BIRTH, KIND_DELTA}
        ),
        "verification_tasks": sum(1 for kind in kinds if kind == KIND_VERIFY),
        "repair_tasks": sum(1 for kind in kinds if kind == KIND_REPAIR),
        "parallelizable_tasks": sum(
            1 for node in graph.nodes if is_parallelizable(node, graph)
        ),
        "churn_without_progress": graph.churn_without_progress,
    }


def _claim_evidence_map(task_root: Path) -> dict[str, dict[str, Any]]:
    """Persisted evidence only — never re-run live product probes."""
    found: dict[str, dict[str, Any]] = {}
    acceptance = _load_json(task_root / ACCEPTANCE_FILE) or {}
    for item in acceptance.get("evidence") or []:
        if isinstance(item, dict) and item.get("id"):
            found[str(item["id"])] = item
    evidence = _load_json(task_root / "product_evidence.json") or {}
    for item in evidence.get("claims") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        found.setdefault(str(item["id"]), item)
    return found


def _runtime_failed(raw: dict[str, Any] | None) -> bool:
    if not raw:
        return False
    if raw.get("safe") is False:
        return True
    return bool(raw.get("required") and not raw.get("ok"))


def _validation_failed(raw: dict[str, Any] | None) -> bool:
    if not raw:
        return False
    return str(raw.get("status") or "") in {"failed", "blocked", "error"}


def _base_refs(
    *,
    revision: int,
    parent_id: str,
    extra: tuple[str, ...] = (),
) -> tuple[str, ...]:
    refs = [context_ref_intent(revision), f"objective:{parent_id}"]
    refs.extend(extra)
    return tuple(dict.fromkeys(item for item in refs if item))


def _repair_nodes(
    *,
    parent_id: str,
    revision: int,
    runtime_raw: dict[str, Any] | None,
    validation_raw: dict[str, Any] | None,
    arch_ref: tuple[str, ...],
) -> list[TaskNode]:
    nodes: list[TaskNode] = []
    if _runtime_failed(runtime_raw):
        reason = str(
            (runtime_raw or {}).get("reason") or "application did not start"
        )
        nodes.append(
            TaskNode(
                task_id="TASK-RUNTIME",
                parent_objective_id=parent_id,
                intent_revision=revision,
                title="Make the application start",
                purpose=(
                    "Runtime evidence is missing until the process starts. "
                    f"Observed: {reason}"
                ),
                status=STATUS_READY,
                kind=KIND_REPAIR,
                evidence_targets=("runtime",),
                context_refs=_base_refs(
                    revision=revision,
                    parent_id=parent_id,
                    extra=arch_ref + ("evidence:runtime",),
                ),
                affected_scope=(),
            )
        )
    if _validation_failed(validation_raw):
        nodes.append(
            TaskNode(
                task_id="TASK-VALIDATE",
                parent_objective_id=parent_id,
                intent_revision=revision,
                title="Repair automated validation",
                purpose="Mechanical validation must pass before product claims.",
                status=STATUS_READY,
                kind=KIND_REPAIR,
                evidence_targets=("validation",),
                context_refs=_base_refs(
                    revision=revision,
                    parent_id=parent_id,
                    extra=arch_ref + ("evidence:validation",),
                ),
                affected_scope=(),
            )
        )
    return nodes


def _claim_node(
    cap: Capability,
    *,
    parent_id: str,
    revision: int,
    evidence: dict[str, Any] | None,
    repair_ids: tuple[str, ...],
    arch_ref: tuple[str, ...],
) -> TaskNode:
    ok = bool(evidence and evidence.get("ok"))
    kinds = tuple(
        str(item)
        for item in (getattr(cap, "evidence", ()) or ())
        if str(item)
    )
    if evidence and evidence.get("kind"):
        kinds = tuple(dict.fromkeys(kinds + (str(evidence["kind"]),)))
    if not kinds:
        kinds = ("static",)
    if ok:
        status = STATUS_VERIFIED
        blocked: tuple[str, ...] = ()
        deps: tuple[str, ...] = ()
    elif repair_ids:
        status = STATUS_BLOCKED
        blocked = repair_ids
        deps = repair_ids
    else:
        status = STATUS_READY
        blocked = ()
        deps = ()
    scope = tuple(str(item) for item in (cap.files or ()) if str(item))
    return TaskNode(
        task_id=f"TASK-CLAIM-{cap.id}",
        parent_objective_id=parent_id,
        intent_revision=revision,
        title=f"Implement claim: {cap.claim}",
        purpose=f"Advances product claim `{cap.id}`.",
        status=status,
        kind=KIND_IMPLEMENT,
        dependencies=deps,
        blocked_by=blocked,
        claim_ids=(cap.id,),
        evidence_targets=kinds,
        context_refs=_base_refs(
            revision=revision,
            parent_id=parent_id,
            extra=arch_ref
            + (context_ref_claim(cap.id),)
            + tuple(f"evidence:{kind}" for kind in kinds),
        ),
        affected_scope=scope,
    )


def _delta_node(
    entry: dict[str, Any],
    *,
    parent_id: str,
    revision: int,
    repair_ids: tuple[str, ...],
    arch_ref: tuple[str, ...],
) -> TaskNode:
    delta_id = str(entry.get("id") or "open")
    prompt = str(entry.get("prompt") or "").strip()
    claims = tuple(
        str(item.get("id") or item.get("claim") or "").strip()
        for item in (entry.get("capabilities") or [])
        if isinstance(item, dict)
        and str(item.get("id") or item.get("claim") or "").strip()
    )
    verified = str(entry.get("status") or "").upper() == DELTA_VERIFIED
    if verified:
        status = STATUS_VERIFIED
        blocked: tuple[str, ...] = ()
        deps: tuple[str, ...] = ()
    elif repair_ids:
        status = STATUS_BLOCKED
        blocked = repair_ids
        deps = repair_ids
    else:
        status = STATUS_READY
        blocked = ()
        deps = ()
    return TaskNode(
        task_id=f"TASK-DELTA-{delta_id}",
        parent_objective_id=parent_id,
        intent_revision=revision,
        title=f"Implement owner delta: {prompt[:72]}",
        purpose="Owner delta changed requested product behavior.",
        status=status,
        kind=KIND_DELTA,
        dependencies=deps,
        blocked_by=blocked,
        claim_ids=claims,
        evidence_targets=("runtime", "persistence"),
        context_refs=_base_refs(
            revision=revision,
            parent_id=parent_id,
            extra=arch_ref + (f"owner_delta:{delta_id}",),
        ),
        affected_scope=(),
    )


def derive_task_graph(
    project: dict[str, Any],
    root: Path,
    *,
    objective: Any | None = None,
) -> TaskGraph:
    """Project current product truth into a task graph.

    Does not call ``score_claims`` / live habit probes. Uses persisted
    acceptance and evidence only.
    """
    task_root = _task_dir(project, root)
    app = _app_dir(project, root)
    parent_id = str(getattr(objective, "id", "") or "OBJ-000")
    kind = str(getattr(objective, "kind", "") or "")
    revision = intent_revision(project, root)
    arch = load_contract(str(app))
    arch_ref = ("architecture:architecture.json",) if arch else ()
    runtime_raw = _load_json(task_root / "runtime_result.json")
    validation_raw = _load_json(task_root / "validation_result.json")
    claim_hits = _claim_evidence_map(task_root)
    caps = intent_capabilities(project, root)
    nodes: list[TaskNode] = []

    repairs = _repair_nodes(
        parent_id=parent_id,
        revision=revision,
        runtime_raw=runtime_raw,
        validation_raw=validation_raw,
        arch_ref=arch_ref,
    )
    nodes.extend(repairs)
    repair_ids = tuple(node.task_id for node in repairs)

    for cap in caps:
        nodes.append(
            _claim_node(
                cap,
                parent_id=parent_id,
                revision=revision,
                evidence=claim_hits.get(cap.id),
                repair_ids=repair_ids,
                arch_ref=arch_ref,
            )
        )

    for entry in load_deltas(project, root):
        nodes.append(
            _delta_node(
                entry,
                parent_id=parent_id,
                revision=revision,
                repair_ids=repair_ids,
                arch_ref=arch_ref,
            )
        )

    if kind in {"specify_intent", "specify"}:
        nodes.append(
            TaskNode(
                task_id="TASK-SPECIFY",
                parent_objective_id=parent_id,
                intent_revision=revision,
                title="Specify the intended product",
                purpose="Owner intent is not yet a compiled product claim set.",
                status=STATUS_READY if not repair_ids else STATUS_BLOCKED,
                kind=KIND_SPECIFY,
                blocked_by=repair_ids,
                dependencies=repair_ids,
                context_refs=_base_refs(
                    revision=revision, parent_id=parent_id, extra=arch_ref
                ),
            )
        )

    if not caps and not load_deltas(project, root) and kind != "complete":
        growth = workbench_metrics(str(app))
        if growth.is_greenfield or kind in {"code_birth", "birth"}:
            nodes.append(
                TaskNode(
                    task_id="TASK-BIRTH",
                    parent_objective_id=parent_id,
                    intent_revision=revision,
                    title="Reach code birth",
                    purpose="The workbench has no real source or tests yet.",
                    status=(
                        STATUS_READY if not repair_ids else STATUS_BLOCKED
                    ),
                    kind=KIND_BIRTH,
                    blocked_by=repair_ids,
                    dependencies=repair_ids,
                    evidence_targets=("runtime",),
                    context_refs=_base_refs(
                        revision=revision,
                        parent_id=parent_id,
                        extra=arch_ref,
                    ),
                )
            )

    implement_ids = tuple(
        node.task_id
        for node in nodes
        if node.kind in {KIND_IMPLEMENT, KIND_DELTA, KIND_BIRTH}
    )
    if implement_ids:
        verify_status = STATUS_PENDING
        if all(
            node.status == STATUS_VERIFIED
            for node in nodes
            if node.task_id in implement_ids
        ):
            verify_status = STATUS_VERIFIED
        elif repair_ids:
            verify_status = STATUS_BLOCKED
        nodes.append(
            TaskNode(
                task_id="TASK-VERIFY-PRODUCT",
                parent_objective_id=parent_id,
                intent_revision=revision,
                title="Verify product claims with Factory evidence",
                purpose=(
                    "Implementation self-report is not proof. Product "
                    "truth must change."
                ),
                status=verify_status,
                kind=KIND_VERIFY,
                dependencies=implement_ids,
                blocked_by=(
                    repair_ids if verify_status == STATUS_BLOCKED else ()
                ),
                claim_ids=tuple(cap.id for cap in caps),
                evidence_targets=("runtime", "persistence", "visible"),
                context_refs=_base_refs(
                    revision=revision,
                    parent_id=parent_id,
                    extra=arch_ref + ("evidence:product",),
                ),
            )
        )

    nodes = refresh_statuses(nodes)
    return TaskGraph(
        intent_revision=revision,
        parent_objective_id=parent_id,
        nodes=nodes,
        fingerprint=progress_fingerprint(nodes, revision),
        repo_fingerprint=repo_fingerprint(app),
    )


def attach_history(graph: TaskGraph, previous: TaskGraph | None) -> TaskGraph:
    """Copy prior fingerprints and flag repo churn without task progress."""
    if previous is None:
        return graph
    prior_fp = previous.fingerprint or progress_fingerprint(
        previous.nodes, previous.intent_revision
    )
    prior_repo = previous.repo_fingerprint
    tasks_unchanged = bool(prior_fp) and prior_fp == graph.fingerprint
    repo_changed = bool(prior_repo) and prior_repo != graph.repo_fingerprint
    graph.prior_fingerprint = prior_fp
    graph.prior_repo_fingerprint = prior_repo
    graph.churn_without_progress = tasks_unchanged and repo_changed
    return graph


def persist_task_graph(graph: TaskGraph, task_root: Path) -> Path:
    task_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "intent_revision": graph.intent_revision,
        "parent_objective_id": graph.parent_objective_id,
        "fingerprint": graph.fingerprint,
        "repo_fingerprint": graph.repo_fingerprint,
        "prior_fingerprint": graph.prior_fingerprint,
        "prior_repo_fingerprint": graph.prior_repo_fingerprint,
        "churn_without_progress": graph.churn_without_progress,
        "cycles": detect_cycles(graph.nodes),
        "stale_revision": False,
        "telemetry": graph_telemetry(graph),
        "nodes": [asdict(node) for node in graph.nodes],
    }
    path = task_root / GRAPH_FILE
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def sync_task_graph(
    project: dict[str, Any],
    root: Path,
    *,
    objective: Any | None = None,
) -> TaskGraph:
    """Rebuild and persist the graph. Does not select the next objective."""
    task_root = _task_dir(project, root)
    previous = load_task_graph(task_root)
    graph = derive_task_graph(project, root, objective=objective)
    graph = attach_history(graph, previous)
    persist_task_graph(graph, task_root)
    return graph
