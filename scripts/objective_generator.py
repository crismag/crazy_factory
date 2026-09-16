#!/usr/bin/env python3
"""P2 execute-objective generator.

Turns the current mission/workbench evidence into **one** next
objective the execution kernel should pursue. This is not "next file
on the checklist." Failures (runtime, validation) outrank product
gaps, which outrank greenfield code-birth.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from product_kernel import (
    focus_module_payload,
    inspect_project,
    select_focus_module,
)
from workbench_growth import workbench_metrics

OBJECTIVE_FILE = "current_objective.json"
MODULE_FILE = "current_module.json"

KIND_CODE_BIRTH = "code_birth"
KIND_SPECIFY = "specify_intent"
KIND_IMPLEMENT = "implement"
KIND_REPAIR_RUNTIME = "repair_runtime"
KIND_REPAIR_VALIDATION = "repair_validation"
KIND_REPAIR_PROGRESS = "repair_progress"
KIND_COMPLETE = "complete"


@dataclass(frozen=True)
class ExecuteObjective:
    """The single next thing EXECUTE should try to close."""

    id: str
    kind: str
    title: str
    gap: str
    why: str
    focus: str
    source: str
    module: str = ""


def _as_path(value: object, root: Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (root / path)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _task_dir(project: dict[str, Any], root: Path) -> Path:
    return _as_path(project.get("task_root") or "factory_tasks", root)


def _app_dir(project: dict[str, Any], root: Path) -> Path:
    return _as_path(project["app_path"], root)


def render_objective_focus(obj: ExecuteObjective) -> str:
    """Planner/coder block: close this gap, not an arbitrary next file."""
    return (
        "## Current execute objective\n"
        f"- id: `{obj.id}`\n"
        f"- kind: `{obj.kind}`\n"
        f"- title: {obj.title}\n"
        f"- gap: {obj.gap}\n"
        f"- why: {obj.why}\n"
        f"- source: `{obj.source}`\n"
        + (f"- module: `{obj.module}`\n" if obj.module else "")
        + "\n"
        "Plan and build ONLY this objective. A later checklist filename "
        "is out of scope unless it is required to close this gap.\n"
        f"\n### Focus\n{obj.focus}\n"
    )


def persist_objective(obj: ExecuteObjective, task_root: Path) -> Path:
    """Write ``current_objective.json`` under the workbench task root."""
    task_root.mkdir(parents=True, exist_ok=True)
    path = task_root / OBJECTIVE_FILE
    path.write_text(json.dumps(asdict(obj), indent=2) + "\n", encoding="utf-8")
    return path


def persist_focus_module(
    payload: dict[str, Any] | None, task_root: Path
) -> Path:
    """Write ``current_module.json`` for the nested module loop."""
    task_root.mkdir(parents=True, exist_ok=True)
    path = task_root / MODULE_FILE
    body: dict[str, Any] = payload or {
        "id": None,
        "open": False,
        "done": True,
    }
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def load_focus_module(task_root: Path) -> dict[str, Any] | None:
    """Latest persisted focus module, or None if never written."""
    raw = _load_json(task_root / MODULE_FILE)
    return raw if raw else None


def load_objective(task_root: Path) -> ExecuteObjective | None:
    raw = _load_json(task_root / OBJECTIVE_FILE)
    if not raw:
        return None
    try:
        return ExecuteObjective(
            id=str(raw.get("id") or "OBJ-000"),
            kind=str(raw.get("kind") or KIND_IMPLEMENT),
            title=str(raw.get("title") or ""),
            gap=str(raw.get("gap") or ""),
            why=str(raw.get("why") or ""),
            focus=str(raw.get("focus") or ""),
            source=str(raw.get("source") or ""),
            module=str(raw.get("module") or ""),
        )
    except (TypeError, ValueError):
        return None


def _from_runtime(task_root: Path) -> ExecuteObjective | None:
    raw = _load_json(task_root / "runtime_result.json")
    if not raw:
        return None
    if raw.get("safe") is False:
        return ExecuteObjective(
            id="OBJ-RUNTIME-UNSAFE",
            kind=KIND_REPAIR_RUNTIME,
            title="Replace the unsafe start command",
            gap=str(raw.get("reason") or "start command is unsafe"),
            why="A start command that escapes the workbench cannot be run.",
            focus=(
                "Declare a workbench-scoped python3 start_command in "
                "architecture.json (module or script inside the app)."
            ),
            source="runtime",
        )
    if raw.get("required") and not raw.get("ok"):
        reason = str(raw.get("reason") or "application did not start")
        return ExecuteObjective(
            id="OBJ-RUNTIME",
            kind=KIND_REPAIR_RUNTIME,
            title="Make the application start",
            gap=reason,
            why="File acceptance is not a running product.",
            focus=(
                "Implement or repair the declared start_command so the "
                "process starts (and answers HTTP if listen_port is set). "
                f"Observed: {reason}"
            ),
            source="runtime",
        )
    return None


def _from_validation(task_root: Path) -> ExecuteObjective | None:
    raw = _load_json(task_root / "validation_result.json")
    if not raw:
        return None
    status = str(raw.get("status") or "")
    if status in {"failed", "blocked", "error"}:
        checks = (
            raw.get("checks") if isinstance(raw.get("checks"), list) else []
        )
        failed = [
            str(c.get("command") or c.get("detail") or status)
            for c in checks
            if isinstance(c, dict)
            and c.get("status") in {"failed", "blocked", "error"}
        ]
        detail = "; ".join(failed[:3]) or status
        return ExecuteObjective(
            id="OBJ-VALIDATE",
            kind=KIND_REPAIR_VALIDATION,
            title="Repair automated validation",
            gap=detail,
            why="A product that does not validate is not demoable.",
            focus=(
                "Diagnose and repair the failing validation checks, then "
                f"re-run them. Failures: {detail}"
            ),
            source="validation",
        )
    return None


def _kind_for_director(chosen: Any) -> str:
    gap_l = str(chosen.gap or "").lower()
    title_l = str(chosen.title or "").lower()
    if "placeholder" in gap_l or "intended product" in title_l:
        return KIND_SPECIFY
    if "ZERO_CODE_OUTPUT" in str(chosen.gap) or "code birth" in title_l:
        return KIND_CODE_BIRTH
    if "validat" in title_l or "validat" in gap_l:
        return KIND_REPAIR_VALIDATION
    return KIND_IMPLEMENT


def _execute_from_director(
    chosen: Any, *, module: str = ""
) -> ExecuteObjective:
    extra = ""
    if module:
        extra = f" Stay inside module `{module}` until it is VERIFIED."
    return ExecuteObjective(
        id=str(chosen.id),
        kind=_kind_for_director(chosen),
        title=str(chosen.title),
        gap=str(chosen.gap),
        why=str(chosen.why),
        focus=(
            f"{chosen.title}. Expected evidence: "
            + "; ".join(chosen.expected_evidence)
            + extra
        ),
        source="product_kernel",
        module=module,
    )


def _from_product(
    project: dict[str, Any], root: Path
) -> ExecuteObjective | None:
    try:
        assessment = inspect_project(project, root)
    except Exception:  # noqa: BLE001 - generator must not break EXECUTE
        return None
    if assessment.convergence.demo_ready and not assessment.objectives:
        return ExecuteObjective(
            id="OBJ-DONE",
            kind=KIND_COMPLETE,
            title="Product evidence is complete",
            gap="",
            why="Acceptance evidence is complete.",
            focus="No further execute objective.",
            source="product_kernel",
        )
    product_level = [
        o for o in assessment.objectives if not o.related_modules
    ]
    blocking_product = [o for o in product_level if o.blocking]
    if blocking_product:
        return _execute_from_director(blocking_product[0])
    focus = select_focus_module(assessment.model)
    if focus is not None:
        module_objs = [
            o
            for o in assessment.objectives
            if focus.id in (o.related_modules or [])
        ]
        blocking_mod = [o for o in module_objs if o.blocking]
        chosen = (blocking_mod or module_objs or [None])[0]
        if chosen is not None:
            return _execute_from_director(chosen, module=focus.id)
    blocking = [o for o in assessment.objectives if o.blocking]
    chosen = (blocking or assessment.objectives or [None])[0]
    if chosen is None:
        return None
    module = ""
    if chosen.related_modules:
        module = str(chosen.related_modules[0])
    return _execute_from_director(chosen, module=module)


def progress_repair_objective(reason: str = "") -> ExecuteObjective:
    """Objective emitted when a no-progress streak trips the first time."""
    detail = reason or (
        "several beats applied no code and completed no checklist item"
    )
    return ExecuteObjective(
        id="OBJ-PROGRESS",
        kind=KIND_REPAIR_PROGRESS,
        title="Unstick the loop: produce observable product change",
        gap=detail,
        why=(
            "A silent NO_PROGRESS park is not a product decision. "
            "Retry once with an explicit gap, then escalate to a human."
        ),
        focus=(
            "Produce at least one real source or test change that advances "
            "the current gap (code birth, missing module, failing test, "
            f"or start command). Stall: {detail}"
        ),
        source="progress",
    )


def next_execute_objective(
    project: dict[str, Any],
    root: Path,
    *,
    force: ExecuteObjective | None = None,
) -> ExecuteObjective:
    """Return the single next execute objective for this workbench."""
    task_root = _task_dir(project, root)
    if force is not None:
        obj = force
    else:
        obj = (
            _from_runtime(task_root)
            or _from_validation(task_root)
            or _from_product(project, root)
        )
        if obj is None:
            app = _app_dir(project, root)
            growth = workbench_metrics(str(app))
            if growth.is_greenfield:
                obj = ExecuteObjective(
                    id="OBJ-BIRTH",
                    kind=KIND_CODE_BIRTH,
                    title="Reach code birth",
                    gap="ZERO_CODE_OUTPUT",
                    why="The workbench has no real source or tests.",
                    focus=(
                        "Create the first real source file and a "
                        "matching test."
                    ),
                    source="growth",
                )
            else:
                obj = ExecuteObjective(
                    id="OBJ-REMAINING",
                    kind=KIND_IMPLEMENT,
                    title="Close remaining acceptance gaps",
                    gap="work remains",
                    why="Acceptance evidence is not complete.",
                    focus=(
                        "Implement remaining required files, tests, "
                        "and validation."
                    ),
                    source="acceptance",
                )
    try:
        assessment = inspect_project(project, root)
        persist_focus_module(
            focus_module_payload(select_focus_module(assessment.model)),
            task_root,
        )
    except Exception:  # noqa: BLE001 - persistence must not break EXECUTE
        persist_focus_module(
            {"id": obj.module or None, "open": bool(obj.module)}
            if obj.module
            else None,
            task_root,
        )
    return obj
