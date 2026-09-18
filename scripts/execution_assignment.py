#!/usr/bin/env python3
"""Compile a purpose-built coding assignment from factory evidence.

Crazy Factory owns understanding, context, and judgment. Coding
plugins (Claude, OpenAI, later others) receive an assignment — not
"implement this task." No extra model calls and no new infrastructure:
this module reads artifacts the factory already writes.

The nine task-intelligence questions are answered here, deterministically:

1. What are we trying to accomplish?     objective title / gap
2. What does the repository contain?     workbench inventory
3. What information is missing?          missing required files
4. What needs investigation?             failing checks / runtime / prior write
5. What kind of engineering work?        control stance (else kind heuristic)
6. What context does the executor need?  seed excerpt + snapshot + architecture
7. What constraints must not be violated path confinement + safety floor
8. What constitutes success?             acceptance criteria
9. How will we know the result is good?  verification expectations

When a graph ``TaskNode`` is supplied, the assignment is also a bounded
context packet: selected claims, context refs, architecture/repo
slices, and the intent revision it was built against. Stale packets
are marked, never rewritten to look current. Completing a task does
not verify product claims — Factory evidence remains independent.

Slice 6 attaches ranked advisory pattern hits from the Factory
catalog. Patterns inform the worker; they never rewrite owner intent,
architecture, claims, repo scope, or COMPLETE.

Passing tests is evidence, not product quality. Executor ``ok`` is not
acceptance. Blind "fix the errors" is not the recovery stance.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from architecture import load_contract
from control_intelligence import load_decision
from conversation_delta import delta_prompts, load_deltas
from diagnosis_packet import DiagnosisPacket, executor_slice
from pattern_library import match_for_intent
from product_intent import (
    intent_capabilities,
    intent_revision,
    load_intent,
    unsatisfied_claims,
)

ALLOWED_TOPS = (
    "src",
    "tests",
    "data",
    "docs",
    "README.md",
    "architecture.json",
    "requirements.txt",
)
BLOCKED_PARTS = (
    "scripts",
    "factory",
    "config",
    ".git",
    "bin",
    "factory_tasks",
    "factory_state",
    "factory_reports",
    "factory_context",
    "state",
)
SEED_CHARS = 2000
ARCH_CHARS = 1500
INTENT_CHARS = 500
INVENTORY_CAP = 40
PATTERN_HIT_CAP = 4
ASSIGNMENT_FILE = "execution_assignment.md"
ASSIGNMENT_JSON = "execution_assignment.json"
JUDGMENT_FILE = "judgment.json"
_ARCH_SLICE_KEYS = (
    "stack",
    "start_command",
    "listen_port",
    "src_dirs",
    "test_dirs",
    "forbidden_imports",
    "forbidden_dirs",
    "forbidden_names",
    "required_files",
    "title",
)
DEFAULT_CONSTRAINTS = (
    (
        "Write only under src/, tests/, data/, docs/, README.md, "
        "architecture.json, and requirements.txt."
    ),
    "Never write scripts/, factory/, config/, .git/, or engine source.",
    "Do not push, merge, delete, or rewrite git history.",
    "Do not invent a product when the seed is a placeholder.",
    "Executor completion is not acceptance; tests and runtime are.",
    "Banner or title text is not product evidence.",
    "Task completion does not verify product claims; Factory evidence does.",
)
ADVISORY_PATTERN_CONSTRAINT = (
    "Advisory patterns inform; they do not override owner intent, "
    "architecture, or Factory COMPLETE."
)
ADVISORY_PATTERN_HEADING = (
    "## Advisory patterns (do not override owner intent or architecture)"
)

STANCE_BIRTH = "birth"
STANCE_IMPLEMENT = "implement"
STANCE_REPAIR = "repair"
STANCE_INVESTIGATE = "investigate"
STANCE_NEED_CONTEXT = "need_context"


@dataclass(frozen=True)
class ExecutionAssignment:
    """Curated assignment the coding plugin is allowed to see."""

    objective_id: str
    kind: str
    title: str
    why: str
    gap: str
    focus: str
    stance: str
    success: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    inventory: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    validation_summary: str = ""
    runtime_summary: str = ""
    evidence: str = ""
    seed_excerpt: str = ""
    architecture_excerpt: str = ""
    owner_deltas: list[str] = field(default_factory=list)
    previous_executor: str = ""
    constraints: tuple[str, ...] = DEFAULT_CONSTRAINTS
    task_id: str = ""
    parent_objective_id: str = ""
    intent_revision: int = 0
    stale: bool = False
    stale_reason: str = ""
    context_refs: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    evidence_targets: tuple[str, ...] = ()
    repo_scope: tuple[str, ...] = ()
    selection_notes: tuple[str, ...] = ()
    owner_intent_slice: str = ""
    pattern_ids: tuple[str, ...] = ()
    pattern_notes: tuple[str, ...] = ()


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _as_path(value: object, root: Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (root / path)


def _task_dir(project: dict[str, Any], root: Path) -> Path:
    return _as_path(project.get("task_root") or "factory_tasks", root)


def _app_dir(project: dict[str, Any], root: Path) -> Path:
    return _as_path(project["app_path"], root)


def _excerpt(text: str, limit: int) -> str:
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit].rstrip() + "\n…(truncated)"


def validation_summary(raw: dict[str, Any] | None) -> str:
    """Failing checks with detail — never a bare 'failed' if checks exist."""
    if not raw:
        return ""
    status = str(raw.get("status") or "")
    failed_status = status in {"failed", "blocked", "error"}
    if not failed_status and raw.get("ok") is not False:
        return ""
    checks = raw.get("checks") if isinstance(raw.get("checks"), list) else []
    failed: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        if check.get("status") not in {"failed", "blocked", "error"}:
            continue
        command = str(check.get("command") or "")
        detail = str(check.get("detail") or check.get("reason") or "")
        line = f"{command} ({check.get('status')})"
        if detail:
            line = f"{line}: {_excerpt(detail, 240)}"
        failed.append(line.strip())
    if failed:
        return "; ".join(failed[:5])
    return str(raw.get("reason") or status or "failed")


def runtime_summary(raw: dict[str, Any] | None) -> str:
    if not raw:
        return ""
    if raw.get("safe") is False or (
        raw.get("required") and not raw.get("ok")
    ):
        return str(raw.get("reason") or raw.get("status") or "runtime failed")
    return ""


def _inventory(app: Path) -> list[str]:
    found: list[str] = []
    if not app.is_dir():
        return found
    for path in sorted(app.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(app).as_posix()
        except ValueError:
            continue
        parts = Path(rel).parts
        if any(part in BLOCKED_PARTS for part in parts):
            continue
        if parts and parts[0] not in ALLOWED_TOPS:
            continue
        found.append(rel)
        if len(found) >= INVENTORY_CAP:
            break
    return found


def _architecture_excerpt(app: Path) -> str:
    path = app / "architecture.json"
    try:
        return _excerpt(path.read_text(encoding="utf-8"), ARCH_CHARS)
    except (OSError, UnicodeDecodeError):
        return ""


def path_in_scope(rel: str, scope: tuple[str, ...]) -> bool:
    """True when ``rel`` equals or sits under a declared scope path."""
    path = str(rel).replace("\\", "/").lstrip("./")
    if not path or not scope:
        return False
    for raw in scope:
        item = str(raw).replace("\\", "/").lstrip("./")
        if not item:
            continue
        if path == item:
            return True
        if path.startswith(item.rstrip("/") + "/"):
            return True
        if item.startswith(path.rstrip("/") + "/"):
            return True
    return False


def is_stale_assignment(
    assignment: ExecutionAssignment, current_revision: int
) -> bool:
    """True when a packet was built against a different intent revision."""
    return int(assignment.intent_revision) != int(current_revision)


def assignment_from_dict(raw: dict[str, Any]) -> ExecutionAssignment | None:
    """Rebuild an assignment from persisted JSON. Does not bump revision."""
    if not raw:
        return None
    constraints = raw.get("constraints")
    if not isinstance(constraints, (list, tuple)) or not constraints:
        constraints = DEFAULT_CONSTRAINTS
    return ExecutionAssignment(
        objective_id=str(raw.get("objective_id") or ""),
        kind=str(raw.get("kind") or ""),
        title=str(raw.get("title") or ""),
        why=str(raw.get("why") or ""),
        gap=str(raw.get("gap") or ""),
        focus=str(raw.get("focus") or ""),
        stance=str(raw.get("stance") or ""),
        success=[str(x) for x in (raw.get("success") or [])],
        verification=[str(x) for x in (raw.get("verification") or [])],
        inventory=[str(x) for x in (raw.get("inventory") or [])],
        missing=[str(x) for x in (raw.get("missing") or [])],
        validation_summary=str(raw.get("validation_summary") or ""),
        runtime_summary=str(raw.get("runtime_summary") or ""),
        evidence=str(raw.get("evidence") or ""),
        seed_excerpt=str(raw.get("seed_excerpt") or ""),
        architecture_excerpt=str(raw.get("architecture_excerpt") or ""),
        owner_deltas=[str(x) for x in (raw.get("owner_deltas") or [])],
        previous_executor=str(raw.get("previous_executor") or ""),
        constraints=tuple(str(x) for x in constraints),
        task_id=str(raw.get("task_id") or ""),
        parent_objective_id=str(raw.get("parent_objective_id") or ""),
        intent_revision=int(raw.get("intent_revision") or 0),
        stale=bool(raw.get("stale")),
        stale_reason=str(raw.get("stale_reason") or ""),
        context_refs=tuple(
            str(x) for x in (raw.get("context_refs") or []) if str(x)
        ),
        claim_ids=tuple(
            str(x) for x in (raw.get("claim_ids") or []) if str(x)
        ),
        evidence_targets=tuple(
            str(x) for x in (raw.get("evidence_targets") or []) if str(x)
        ),
        repo_scope=tuple(
            str(x) for x in (raw.get("repo_scope") or []) if str(x)
        ),
        selection_notes=tuple(
            str(x) for x in (raw.get("selection_notes") or []) if str(x)
        ),
        owner_intent_slice=str(raw.get("owner_intent_slice") or ""),
        pattern_ids=tuple(
            str(x) for x in (raw.get("pattern_ids") or []) if str(x)
        ),
        pattern_notes=tuple(
            str(x) for x in (raw.get("pattern_notes") or []) if str(x)
        ),
    )


def load_assignment(task_root: Path) -> ExecutionAssignment | None:
    """Load the persisted packet. Missing/invalid → None."""
    raw = _load_json(task_root / ASSIGNMENT_JSON)
    if not raw:
        return None
    return assignment_from_dict(raw)


def _architecture_slice(
    contract: dict[str, Any] | None,
    scope: tuple[str, ...],
    notes: list[str],
) -> str:
    """Smallest safe architecture subset. Does not invent domain modules."""
    if not contract:
        return ""
    notes.append(
        "architecture.json is monolithic; packet carries a key subset, "
        "not domain-addressable slices."
    )
    data: dict[str, Any] = {}
    for key in _ARCH_SLICE_KEYS:
        if key not in contract:
            continue
        data[key] = contract[key]
    files = data.get("required_files")
    if scope and isinstance(files, list):
        kept = [str(item) for item in files if path_in_scope(str(item), scope)]
        data["required_files"] = kept
        if not kept:
            notes.append(
                "required_files did not intersect task affected_scope; "
                "scope linkage is weak."
            )
    return json.dumps(data, sort_keys=True)


def _filter_inventory(
    paths: list[str], scope: tuple[str, ...], notes: list[str]
) -> list[str]:
    if not scope:
        notes.append(
            "affected_scope empty; inventory is a capped path list, "
            "not a relevance selection."
        )
        return paths
    kept = [path for path in paths if path_in_scope(path, scope)]
    for item in scope:
        text = str(item).replace("\\", "/").lstrip("./")
        if text and text not in kept:
            kept.append(text)
    if not kept:
        notes.append(
            "no workbench files intersect affected_scope; claim-to-module "
            "linkage is absent."
        )
    return kept[:INVENTORY_CAP]


def _repo_scope_refs(scope: tuple[str, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for item in scope:
        text = str(item).replace("\\", "/").lstrip("./")
        if text:
            refs.append(f"file:{text}")
    return tuple(refs)


def _owner_intent_slice(project: dict[str, Any], root: Path) -> str:
    prompt = str(load_intent(project, root).get("original_prompt") or "")
    return _excerpt(prompt, INTENT_CHARS)


def _stack_id(contract: dict[str, Any] | None) -> str:
    if not isinstance(contract, dict):
        return ""
    return str(contract.get("stack") or "").strip()


def _pattern_prompt(
    project: dict[str, Any],
    root: Path,
    task: Any | None,
) -> str:
    parts: list[str] = []
    prompt = str(
        load_intent(project, root).get("original_prompt") or ""
    ).strip()
    if prompt:
        parts.append(prompt)
    if task is not None:
        title = str(getattr(task, "title", "") or "").strip()
        if title:
            parts.append(title)
        for claim_id in getattr(task, "claim_ids", ()) or ():
            text = str(claim_id).replace("_", " ").strip()
            if text:
                parts.append(text)
    return " ".join(parts)


def _advisory_patterns(
    project: dict[str, Any],
    root: Path,
    task: Any | None,
    contract: dict[str, Any] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Ranked catalog hits. Empty on missing catalog or empty query.

    Query uses the workbench intent; the catalog is the Factory
    checkout (``pattern_library.REPO_ROOT``), not the workbench root.
    """
    prompt = _pattern_prompt(project, root, task)
    stack = _stack_id(contract)
    if not prompt and not stack:
        return (), ()
    hits = match_for_intent(
        prompt,
        stack_id=stack or None,
        limit=PATTERN_HIT_CAP,
    )
    ids: list[str] = []
    notes: list[str] = []
    for hit in hits:
        entry = hit.entry
        if entry.pattern_id in ids:
            continue
        ids.append(entry.pattern_id)
        note = f"{entry.pattern_id} [{entry.kind}] {entry.title}"
        if entry.summary:
            note = f"{note} — {_excerpt(entry.summary, 200)}"
        notes.append(note)
    return tuple(ids), tuple(notes)


def _delta_prompts_for_task(
    project: dict[str, Any], root: Path, task: Any
) -> list[str]:
    task_id = str(getattr(task, "task_id", "") or "")
    kind = str(getattr(task, "kind", "") or "")
    wanted = ""
    if task_id.startswith("TASK-DELTA-"):
        wanted = task_id[len("TASK-DELTA-") :]
    refs = tuple(getattr(task, "context_refs", ()) or ())
    for ref in refs:
        if str(ref).startswith("owner_delta:"):
            wanted = str(ref).split(":", 1)[-1]
            break
    if kind != "delta" and not wanted:
        return []
    found: list[str] = []
    for entry in load_deltas(project, root):
        if wanted and str(entry.get("id") or "") != wanted:
            continue
        prompt = str(entry.get("prompt") or "").strip()
        if prompt:
            found.append(prompt)
        if wanted:
            break
    return found


def _selected_capabilities(project: dict[str, Any], root: Path, task: Any):
    wanted = tuple(getattr(task, "claim_ids", ()) or ())
    if not wanted:
        return []
    by_id = {cap.id: cap for cap in intent_capabilities(project, root)}
    selected = []
    for claim_id in wanted:
        cap = by_id.get(str(claim_id))
        if cap is not None:
            selected.append(cap)
    return selected


def _context_refs_for(
    *,
    revision: int,
    objective_id: str,
    task: Any | None,
    claim_ids: tuple[str, ...],
    evidence_targets: tuple[str, ...],
    repo_refs: tuple[str, ...],
    has_arch: bool,
) -> tuple[str, ...]:
    refs: list[str] = [f"product_intent@revision-{int(revision)}"]
    if objective_id:
        refs.append(f"objective:{objective_id}")
    if task is not None:
        for item in getattr(task, "context_refs", ()) or ():
            text = str(item)
            if text and text not in refs:
                refs.append(text)
        task_id = str(getattr(task, "task_id", "") or "")
        if task_id:
            refs.append(f"task:{task_id}")
    for claim_id in claim_ids:
        ref = f"claim:{claim_id}"
        if ref not in refs:
            refs.append(ref)
    for kind in evidence_targets:
        ref = f"evidence:{kind}"
        if ref not in refs:
            refs.append(ref)
    if has_arch and "architecture:architecture.json" not in refs:
        refs.append("architecture:architecture.json")
    for ref in repo_refs:
        if ref not in refs:
            refs.append(ref)
    return tuple(refs)


def _constraints_with_architecture(
    contract: dict[str, Any] | None,
) -> tuple[str, ...]:
    extra: list[str] = []
    if contract:
        forbidden = contract.get("forbidden_imports") or []
        if isinstance(forbidden, list) and forbidden:
            extra.append(
                "Architecture forbids imports: "
                + ", ".join(str(item) for item in forbidden[:8])
            )
        extra.append(
            "Do not overwrite architecture.json because task prose "
            "disagrees with the contract."
        )
    extra.append("Factory owns integration; workers do not deploy.")
    extra.append(ADVISORY_PATTERN_CONSTRAINT)
    # DEFAULT already has no-push; keep architecture-specific extras unique.
    seen = set(DEFAULT_CONSTRAINTS)
    out = list(DEFAULT_CONSTRAINTS)
    for item in extra:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return tuple(out)


def _seed_excerpt(project: dict[str, Any], root: Path) -> str:
    app = _app_dir(project, root)
    seed = app / str(project.get("seed_file") or "docs/seed.md")
    try:
        return _excerpt(seed.read_text(encoding="utf-8"), SEED_CHARS)
    except (OSError, UnicodeDecodeError):
        return ""


def classify_stance(
    kind: str,
    *,
    previous_files: list[str],
    still_failing: bool,
) -> str:
    """Recovery stance. Blind 'fix the errors' is never the default."""
    kind_l = (kind or "").strip().lower()
    if kind_l in {"specify_intent", "specify"}:
        return STANCE_NEED_CONTEXT
    if previous_files and still_failing:
        return STANCE_INVESTIGATE
    if kind_l.startswith("repair_"):
        return STANCE_REPAIR
    if kind_l in {"code_birth", "birth"}:
        return STANCE_BIRTH
    return STANCE_IMPLEMENT


def _stance_instructions(stance: str) -> str:
    if stance == STANCE_NEED_CONTEXT:
        return (
            "The intended product is not specified. Do not invent a full "
            "application. Produce only the smallest clarifying artifacts "
            "(seed/architecture notes) or skip with no files."
        )
    if stance == STANCE_INVESTIGATE:
        return (
            "A previous executor already wrote files and the same class of "
            "failure remains. Diagnose against the evidence. Do not emit "
            "the same files unchanged. Change the failing behavior."
        )
    if stance == STANCE_REPAIR:
        return (
            "This is a targeted repair. Keep working behavior. Fix the "
            "cited evidence — not a greenfield rewrite unless required "
            "files are missing."
        )
    if stance == STANCE_BIRTH:
        return (
            "Create the application from the seed and architecture. Cover "
            "required files, tests, and the declared start command."
        )
    return (
        "Implement only this objective. Later checklist filenames are out "
        "of scope unless required to close the gap."
    )


def compile_assignment(
    project: dict[str, Any],
    root: Path,
    objective: Any,
    *,
    packet: DiagnosisPacket | None = None,
    task: Any | None = None,
) -> ExecutionAssignment:
    """Answer the task-intelligence questions from existing artifacts.

    ``task`` is optional. Legacy objective execution stays valid without
    a graph node. A stale ``TaskNode`` is recorded, not rewritten to the
    current revision. Advisory pattern hits attach on current packets
    only; stale packets stay empty.
    """
    current_rev = intent_revision(project, root)
    task_rev = int(getattr(task, "intent_revision", 0) or 0) if task else 0
    if task is not None and task_rev != int(current_rev):
        return _stale_packet(project, root, objective, task, current_rev)
    return _compile_current(
        project,
        root,
        objective,
        packet=packet,
        task=task,
        current_rev=current_rev,
    )


def _stale_packet(
    project: dict[str, Any],
    root: Path,
    objective: Any,
    task: Any,
    current_rev: int,
) -> ExecutionAssignment:
    """Preserve the historical packet identity. Do not fill current intent."""
    task_rev = int(getattr(task, "intent_revision", 0) or 0)
    claim_ids = tuple(
        str(item) for item in (getattr(task, "claim_ids", ()) or ()) if item
    )
    evidence = tuple(
        str(item)
        for item in (getattr(task, "evidence_targets", ()) or ())
        if item
    )
    refs = tuple(
        str(item) for item in (getattr(task, "context_refs", ()) or ()) if item
    )
    scope = tuple(
        str(item) for item in (getattr(task, "affected_scope", ()) or ()) if item
    )
    return ExecutionAssignment(
        objective_id=str(getattr(objective, "id", "") or "")
        or str(getattr(task, "parent_objective_id", "") or ""),
        kind=str(
            getattr(task, "kind", "") or getattr(objective, "kind", "") or ""
        ),
        title=str(
            getattr(task, "title", "")
            or getattr(objective, "title", "")
            or ""
        ),
        why=str(
            getattr(task, "purpose", "")
            or getattr(objective, "why", "")
            or ""
        ),
        gap=str(getattr(objective, "gap", "") or ""),
        focus=str(
            getattr(task, "purpose", "")
            or getattr(objective, "focus", "")
            or ""
        ),
        stance=STANCE_IMPLEMENT,
        task_id=str(getattr(task, "task_id", "") or ""),
        parent_objective_id=str(getattr(task, "parent_objective_id", "") or ""),
        intent_revision=task_rev,
        stale=True,
        stale_reason=(
            f"assignment revision {task_rev} != current intent "
            f"revision {current_rev}; regenerate against current state"
        ),
        context_refs=refs,
        claim_ids=claim_ids,
        evidence_targets=evidence,
        repo_scope=tuple(f"file:{item}" for item in scope),
        selection_notes=(
            "stale packet; current owner intent was not copied in",
        ),
        constraints=_constraints_with_architecture(
            load_contract(str(_app_dir(project, root)))
        ),
    )


def _compile_current(
    project: dict[str, Any],
    root: Path,
    objective: Any,
    *,
    packet: DiagnosisPacket | None,
    task: Any | None,
    current_rev: int,
) -> ExecutionAssignment:
    task_root = _task_dir(project, root)
    app = _app_dir(project, root)
    validation = _load_json(task_root / "validation_result.json")
    runtime = _load_json(task_root / "runtime_result.json")
    previous = _load_json(task_root / "executor_result.json") or {}
    prev_files = [
        str(name)
        for name in (previous.get("files") or [])
        if isinstance(name, str)
    ]
    val_text = validation_summary(validation)
    run_text = runtime_summary(runtime)
    still_failing = bool(val_text or run_text)
    kind = str(getattr(objective, "kind", "") or "")
    stance = classify_stance(
        kind, previous_files=prev_files, still_failing=still_failing
    )
    control = load_decision(task_root)
    if (
        control is not None
        and control.source == "model"
        and control.stance
        in {
            STANCE_BIRTH,
            STANCE_IMPLEMENT,
            STANCE_REPAIR,
            STANCE_INVESTIGATE,
            STANCE_NEED_CONTEXT,
        }
    ):
        stance = control.stance
    deltas = delta_prompts(project, root)
    preview = app / "src" / "app.py"
    if deltas and preview.is_file() and stance == STANCE_BIRTH:
        stance = STANCE_IMPLEMENT
    notes: list[str] = []
    scope = tuple(
        str(item)
        for item in (getattr(task, "affected_scope", ()) or ())
        if item
    ) if task is not None else ()
    contract = load_contract(str(app))
    success: list[str] = []
    verification: list[str] = []
    missing: list[str] = []
    evidence = ""
    if packet is not None:
        success = list(packet.acceptance_criteria)
        verification = list(packet.validation_expectations)
        missing = list(packet.missing_required_files)
        evidence = executor_slice(packet)
    if not success:
        success = [
            "Required workbench files exist and are not stubs.",
            "Allowlisted validation (compile, pytest, lint) passes.",
            "Declared start command runs if architecture sets one.",
        ]
    claim_ids: tuple[str, ...] = ()
    evidence_targets: tuple[str, ...] = ()
    if task is not None:
        selected = _selected_capabilities(project, root, task)
        claim_ids = tuple(cap.id for cap in selected) or tuple(
            str(item)
            for item in (getattr(task, "claim_ids", ()) or ())
            if item
        )
        evidence_targets = tuple(
            str(item)
            for item in (getattr(task, "evidence_targets", ()) or ())
            if item
        )
        if not evidence_targets:
            kinds: list[str] = []
            for cap in selected:
                kinds.extend(str(item) for item in (cap.evidence or ()) if item)
            evidence_targets = tuple(dict.fromkeys(kinds))
        if selected:
            success = (
                [cap.claim for cap in selected]
                + [
                    "Factory evidence, not this assignment, verifies claims."
                ]
                + success
            )
        else:
            notes.append(
                "task claim_ids did not match compiled capabilities; "
                "claim-to-module linkage is absent."
            )
    else:
        claim_gaps = unsatisfied_claims(project, root)
        if claim_gaps:
            success = [cap.claim for cap in claim_gaps] + success
            claim_ids = tuple(cap.id for cap in claim_gaps)
            kinds = []
            for cap in claim_gaps:
                kinds.extend(str(item) for item in (cap.evidence or ()) if item)
            evidence_targets = tuple(dict.fromkeys(kinds))
    if not verification:
        verification = [
            "python3 -m compileall on workbench sources",
            "pytest on workbench tests when present",
            "runtime probe when start_command is declared",
        ]
        if evidence_targets:
            verification.append(
                "Factory will collect independent evidence: "
                + ", ".join(evidence_targets)
            )
    prev_note = ""
    if prev_files:
        relevant = prev_files
        if task is not None and scope:
            relevant = [name for name in prev_files if path_in_scope(name, scope)]
            if not relevant and stance not in {STANCE_REPAIR, STANCE_INVESTIGATE}:
                notes.append(
                    "prior executor writes omitted; files outside task scope"
                )
                relevant = []
        if relevant:
            prev_note = (
                f"provider={previous.get('provider') or '?'} "
                f"wrote {', '.join(relevant[:12])}"
            )
    inventory = _inventory(app)
    if task is not None:
        inventory = _filter_inventory(inventory, scope, notes)
        owner_deltas = _delta_prompts_for_task(project, root, task)
        seed_excerpt = ""
        owner_slice = _owner_intent_slice(project, root)
        arch_excerpt = _architecture_slice(contract, scope, notes)
        title = str(
            getattr(task, "title", "")
            or getattr(objective, "title", "")
            or ""
        )
        why = str(
            getattr(task, "purpose", "")
            or getattr(objective, "why", "")
            or ""
        )
        focus = str(
            getattr(task, "purpose", "")
            or getattr(objective, "focus", "")
            or ""
        )
        task_id = str(getattr(task, "task_id", "") or "")
        parent_id = str(getattr(task, "parent_objective_id", "") or "") or str(
            getattr(objective, "id", "") or ""
        )
    else:
        owner_deltas = deltas[-5:]
        seed_excerpt = _seed_excerpt(project, root)
        owner_slice = _owner_intent_slice(project, root) or _excerpt(
            seed_excerpt, INTENT_CHARS
        )
        arch_excerpt = _architecture_excerpt(app)
        title = str(getattr(objective, "title", "") or "")
        why = str(getattr(objective, "why", "") or "")
        focus = str(getattr(objective, "focus", "") or "")
        task_id = ""
        parent_id = str(getattr(objective, "id", "") or "")
        notes.append(
            "legacy objective packet; no TaskNode selected"
        )
    repo_refs = _repo_scope_refs(scope)
    refs = _context_refs_for(
        revision=current_rev,
        objective_id=str(getattr(objective, "id", "") or ""),
        task=task,
        claim_ids=claim_ids,
        evidence_targets=evidence_targets,
        repo_refs=repo_refs,
        has_arch=bool(contract or arch_excerpt),
    )
    pattern_ids, pattern_notes = _advisory_patterns(
        project, root, task, contract
    )
    if pattern_ids:
        notes.append(
            "advisory patterns attached; they do not override owner "
            "intent or architecture"
        )
    return ExecutionAssignment(
        objective_id=str(getattr(objective, "id", "") or ""),
        kind=str(getattr(objective, "kind", "") or kind),
        title=title,
        why=why,
        gap=str(getattr(objective, "gap", "") or ""),
        focus=focus,
        stance=stance,
        success=success,
        verification=verification,
        inventory=inventory,
        missing=missing,
        validation_summary=val_text,
        runtime_summary=run_text,
        evidence=evidence,
        seed_excerpt=seed_excerpt,
        architecture_excerpt=arch_excerpt,
        owner_deltas=owner_deltas,
        previous_executor=prev_note,
        constraints=_constraints_with_architecture(contract),
        task_id=task_id,
        parent_objective_id=parent_id,
        intent_revision=current_rev,
        stale=False,
        context_refs=refs,
        claim_ids=claim_ids,
        evidence_targets=evidence_targets,
        repo_scope=repo_refs,
        selection_notes=tuple(dict.fromkeys(notes)),
        owner_intent_slice=owner_slice,
        pattern_ids=pattern_ids,
        pattern_notes=pattern_notes,
    )


def render_assignment(assignment: ExecutionAssignment) -> str:
    """Purpose-built user message for a coding plugin."""
    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- (none)"

    sections = ["# Engineering assignment"]
    if assignment.stale:
        sections.extend(
            [
                "## STALE CONTEXT — DO NOT EXECUTE",
                assignment.stale_reason
                or "intent revision does not match current owner intent",
                "Regenerate this packet against current product_intent.",
                "",
            ]
        )
    sections.extend(
        [
            "## Objective",
            f"- id: `{assignment.objective_id}`",
            f"- kind: `{assignment.kind}`",
            f"- title: {assignment.title}",
            f"- gap: {assignment.gap}",
            f"- why: {assignment.why}",
            f"- stance: `{assignment.stance}`",
            f"- intent_revision: `{assignment.intent_revision}`",
        ]
    )
    if assignment.task_id:
        sections.extend(
            [
                f"- task_id: `{assignment.task_id}`",
                f"- parent_objective_id: `{assignment.parent_objective_id}`",
            ]
        )
    sections.extend(
        [
            "",
            _stance_instructions(assignment.stance),
            "",
            "### Focus",
            assignment.focus or "(whole workbench)",
            "",
            "## Success",
            bullets(assignment.success),
            "",
            "## Verification (factory will run these; do not self-certify)",
            bullets(assignment.verification),
            "",
            "## Constraints",
            bullets(list(assignment.constraints)),
            "",
            "## Current workbench",
            bullets(assignment.inventory),
            "",
            "## Missing required files",
            bullets(assignment.missing),
        ]
    )
    if assignment.context_refs:
        sections.extend(
            ["", "## Context refs", bullets(list(assignment.context_refs))]
        )
    if assignment.claim_ids:
        sections.extend(
            [
                "",
                "## Product claims this task should enable",
                "These are expectations, not verified evidence.",
                bullets(list(assignment.claim_ids)),
            ]
        )
    if assignment.evidence_targets:
        sections.extend(
            [
                "",
                "## Evidence targets (Factory collects these)",
                bullets(list(assignment.evidence_targets)),
            ]
        )
    if assignment.repo_scope:
        sections.extend(
            [
                "",
                "## Repository scope (inspect the workbench; contents omitted)",
                bullets(list(assignment.repo_scope)),
            ]
        )
    if assignment.selection_notes:
        sections.extend(
            ["", "## Selection notes", bullets(list(assignment.selection_notes))]
        )
    if assignment.owner_deltas:
        sections.extend(
            [
                "",
                "## Owner deltas",
                (
                    "The Goal is already specified. Apply these "
                    "follow-up changes; do not replace the product."
                ),
                bullets(assignment.owner_deltas),
            ]
        )
    if assignment.validation_summary:
        sections.extend(
            ["", "## Validation evidence", assignment.validation_summary]
        )
    if assignment.runtime_summary:
        sections.extend(
            ["", "## Runtime evidence", assignment.runtime_summary]
        )
    if assignment.previous_executor:
        sections.extend(
            ["", "## Previous executor write", assignment.previous_executor]
        )
    if assignment.evidence:
        sections.extend(["", "## Situational evidence", assignment.evidence])
    if assignment.architecture_excerpt:
        sections.extend(
            ["", "## architecture.json", assignment.architecture_excerpt]
        )
    if assignment.owner_intent_slice and not assignment.seed_excerpt:
        sections.extend(
            ["", "## Owner intent", assignment.owner_intent_slice]
        )
    if assignment.seed_excerpt:
        sections.extend(["", "## Seed", assignment.seed_excerpt])
    if assignment.pattern_notes or assignment.pattern_ids:
        sections.extend(
            [
                "",
                ADVISORY_PATTERN_HEADING,
                bullets(
                    list(assignment.pattern_notes or assignment.pattern_ids)
                ),
            ]
        )
    sections.extend(
        [
            "",
            "## Expected artifacts",
            (
                'Return JSON {"files": {"relative/path": "content"}} '
                "covering only allowed tops. Include tests that lock the "
                "behavior this objective requires."
            ),
        ]
    )
    return "\n".join(sections).strip() + "\n"


def persist_assignment(assignment: ExecutionAssignment, task_root: Path) -> Path:
    """Write assignment markdown + JSON. Does not rewrite historical revision."""
    task_root.mkdir(parents=True, exist_ok=True)
    path = task_root / ASSIGNMENT_FILE
    path.write_text(render_assignment(assignment), encoding="utf-8")
    payload = asdict(assignment)
    payload["constraints"] = list(assignment.constraints)
    payload["context_refs"] = list(assignment.context_refs)
    payload["claim_ids"] = list(assignment.claim_ids)
    payload["evidence_targets"] = list(assignment.evidence_targets)
    payload["repo_scope"] = list(assignment.repo_scope)
    payload["selection_notes"] = list(assignment.selection_notes)
    payload["pattern_ids"] = list(assignment.pattern_ids)
    payload["pattern_notes"] = list(assignment.pattern_notes)
    (task_root / ASSIGNMENT_JSON).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return path


def persist_judgment(
    task_root: Path,
    *,
    outcome: str,
    reason: str,
    accepted: bool,
    validation_passed: bool,
    runtime_status: str = "",
    mechanical_ok: bool | None = None,
    product_ok: bool | None = None,
    intent_revision: int | None = None,
    accepted_revision: int | None = None,
) -> Path:
    """Record that process success is not product quality."""
    task_root.mkdir(parents=True, exist_ok=True)
    path = task_root / JUDGMENT_FILE
    payload = {
        "outcome": outcome,
        "reason": reason,
        "accepted": accepted,
        "validation_passed": validation_passed,
        "runtime_status": runtime_status,
        "mechanical_ok": mechanical_ok,
        "product_ok": product_ok,
        "intent_revision": intent_revision,
        "accepted_revision": accepted_revision,
        "executor_ok_is_not_acceptance": True,
        "tests_passed_is_not_product_quality": True,
        "title_or_banner_is_not_product_evidence": True,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def assignment_record(assignment: ExecutionAssignment) -> dict[str, Any]:
    """Compact JSON for executor_result.json."""
    data = asdict(assignment)
    data["constraints"] = list(assignment.constraints)
    data["context_refs"] = list(assignment.context_refs)
    data["claim_ids"] = list(assignment.claim_ids)
    data["evidence_targets"] = list(assignment.evidence_targets)
    data["repo_scope"] = list(assignment.repo_scope)
    data["selection_notes"] = list(assignment.selection_notes)
    data["pattern_ids"] = list(assignment.pattern_ids)
    data["pattern_notes"] = list(assignment.pattern_notes)
    data.pop("seed_excerpt", None)
    data.pop("architecture_excerpt", None)
    data.pop("evidence", None)
    data.pop("owner_intent_slice", None)
    return data
