#!/usr/bin/env python3
"""P0 closed-loop mission runner for Crazy Factory.

``advance`` is one beat. ``mission_loop`` is also one beat (cron).
This module is the missing continuation controller:

    evaluate → (if more work) execute one beat → observe → evaluate → …

It stops only when acceptance evidence is complete, a genuine human
blocker is set, the owner stop flag is set, or the beat budget is
spent.

A *workbench autonomous* profile turns on apply/validation/remediation/
autonomy for **this project only**. It does not allow push, merge,
deletes, or writes outside the workbench.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import factory_advance
import factory_messaging as msg
from acceptance_check import evaluate_acceptance
from flags import flag_active, set_flag
from mission_state import load_state
from owner_controls import set_capability
from runtime_observer import observe_runtime, persist_runtime
from workbench_growth import workbench_metrics

COMPLETE = "COMPLETE"
MORE_WORK = "MORE_WORK"
RECOVERABLE = "RECOVERABLE_FAILURE"
HUMAN_REQUIRED = "HUMAN_REQUIRED"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"

HUMAN_BLOCKERS = frozenset(
    {
        "self_rejection",
        "needs_owner_decision",
        "recovery_exhausted",
        "remediation_exhausted",
    }
)
STUCK_BLOCKERS = frozenset({"no_progress"})

PROFILE_CAPABILITIES: tuple[str, ...] = (
    "allow_apply",
    "allow_validation",
    "allow_remediation",
    "allow_autonomous",
)

DEFAULT_MAX_BEATS = 12
TRACE_FILE = "MISSION_TRACE.md"
RESULT_FILE = "mission_result.json"
_PATH_KEYS = (
    "app_path",
    "root",
    "task_root",
    "state_dir",
    "factory_state_dir",
    "context_root",
    "report_root",
    "context_store_root",
    "context_imports_root",
    "context_extracted_root",
    "context_catalog_path",
    "factory_config_path",
    "config_dir",
)

AdvanceFn = Callable[[dict[str, Any]], int]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_path(value: object, root: Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (root / path)


def _absolute_project(project: dict[str, Any], root: Path) -> dict[str, Any]:
    """Return a copy whose workbench paths are absolute under ``root``.

    The execution kernel still consumes the relative registry mapping.
    Evaluation, blockers, and traces must not depend on process CWD.
    """
    resolved = dict(project)
    for key in _PATH_KEYS:
        value = resolved.get(key)
        if value:
            resolved[key] = str(_as_path(value, root))
    return resolved


def enable_workbench_profile(project: dict[str, Any], root: Path) -> list[str]:
    """Enable isolated autonomous execution for one workbench.

    Safety floor stays: no push/merge/delete, no engine writes, path
    confinement still enforced by the apply/validation rails.
    """
    enabled: list[str] = []
    for cap in PROFILE_CAPABILITIES:
        set_capability(project, root, cap, True)
        enabled.append(cap)
    return enabled


def _blocker(project: dict[str, Any], root: Path) -> str:
    state_dir = str(project["state_dir"])
    try:
        _factory, _run, project_state = load_state(
            root, state_dir, str(project["name"])
        )
    except Exception:  # noqa: BLE001 - evaluate must not crash the loop
        return ""
    raw = project_state.get("current_blocker")
    return str(raw) if raw else ""


def evaluate_mission(
    project: dict[str, Any], root: Path, *, beat: int, max_beats: int
) -> tuple[str, str]:
    """Return ``(status, reason)`` for the current workbench evidence."""
    project = _absolute_project(project, root)
    state_dir = str(project.get("state_dir") or "state")
    if flag_active("stop", root, state_dir):
        return HUMAN_REQUIRED, "owner stop flag is set"
    if flag_active("pause", root, state_dir):
        return HUMAN_REQUIRED, "owner pause flag is set"
    blocker = _blocker(project, root)
    if blocker in HUMAN_BLOCKERS:
        return HUMAN_REQUIRED, f"blocker={blocker}"
    if blocker in STUCK_BLOCKERS:
        return BUDGET_EXHAUSTED, f"blocker={blocker} (loop produced no code)"
    acceptance = evaluate_acceptance(project, root)
    if acceptance.accepted:
        app = Path(str(project["app_path"]))
        runtime = observe_runtime(app)
        task_root = project.get("task_root")
        if task_root:
            persist_runtime(runtime, Path(str(task_root)))
        if not runtime.safe:
            return HUMAN_REQUIRED, f"runtime unsafe: {runtime.reason}"
        if runtime.required and not runtime.ok:
            if beat >= max_beats:
                return (
                    BUDGET_EXHAUSTED,
                    f"beat budget {max_beats} exhausted ({runtime.reason})",
                )
            return MORE_WORK, f"runtime: {runtime.reason}"
        extra = ""
        if runtime.required:
            extra = f" (runtime {runtime.status})"
        return COMPLETE, "acceptance evidence is complete" + extra
    if beat >= max_beats:
        return BUDGET_EXHAUSTED, f"beat budget {max_beats} exhausted"
    if blocker:
        return RECOVERABLE, f"blocker={blocker}"
    growth = workbench_metrics(str(_as_path(project["app_path"], root)))
    if growth.is_greenfield:
        return MORE_WORK, "ZERO_CODE_OUTPUT: no source or tests yet"
    return MORE_WORK, "; ".join(acceptance.reasons) or "work remains"


@dataclass
class BeatRecord:
    """One observed mission beat."""

    index: int
    evaluation: str
    reason: str
    blocker: str
    source_files: int
    test_files: int
    accepted: bool
    runtime: str = ""
    at: str = field(default_factory=_now)


@dataclass
class MissionResult:
    """Outcome of ``run_mission``."""

    project_id: str
    outcome: str
    reason: str
    beats: int
    max_beats: int
    profile_enabled: list[str]
    records: list[BeatRecord]
    artifact: str
    trace_path: str


def _growth(project: dict[str, Any], root: Path) -> tuple[int, int]:
    metrics = workbench_metrics(str(_as_path(project["app_path"], root)))
    return metrics.source_files, metrics.test_files


def _record(
    project: dict[str, Any],
    root: Path,
    *,
    index: int,
    status: str,
    reason: str,
) -> BeatRecord:
    src, tests = _growth(project, root)
    accepted = evaluate_acceptance(project, root).accepted
    runtime = ""
    task_root = project.get("task_root")
    if task_root:
        result_path = Path(str(task_root)) / "runtime_result.json"
        if result_path.is_file():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                runtime = str(payload.get("status") or "")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                runtime = ""
    return BeatRecord(
        index=index,
        evaluation=status,
        reason=reason,
        blocker=_blocker(project, root),
        source_files=src,
        test_files=tests,
        accepted=accepted,
        runtime=runtime,
    )


def _trace_lines(result: MissionResult) -> str:
    lines = [
        f"# Mission trace — {result.project_id}",
        "",
        f"- Outcome: `{result.outcome}`",
        f"- Reason: {result.reason}",
        f"- Beats: {result.beats}/{result.max_beats}",
        f"- Profile: {', '.join(result.profile_enabled) or '(none)'}",
        f"- Artifact: `{result.artifact}`",
        "",
        "## Beats",
        "",
    ]
    if not result.records:
        lines.append("(no beats)")
    for rec in result.records:
        lines.append(
            f"- beat {rec.index}: `{rec.evaluation}` "
            f"src={rec.source_files} tests={rec.test_files} "
            f"accepted={str(rec.accepted).lower()} "
            f"runtime={rec.runtime or 'none'} "
            f"blocker={rec.blocker or 'none'} — {rec.reason}"
        )
    lines.append("")
    return "\n".join(lines)


def _write_trace(
    result: MissionResult, project: dict[str, Any], root: Path
) -> Path:
    report_root = _as_path(project["report_root"], root)
    report_root.mkdir(parents=True, exist_ok=True)
    trace = report_root / TRACE_FILE
    trace.write_text(_trace_lines(result), encoding="utf-8")
    payload = {
        "project_id": result.project_id,
        "outcome": result.outcome,
        "reason": result.reason,
        "beats": result.beats,
        "max_beats": result.max_beats,
        "profile_enabled": result.profile_enabled,
        "artifact": result.artifact,
        "records": [asdict(r) for r in result.records],
    }
    (report_root / RESULT_FILE).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return trace


def run_mission(
    project: dict[str, Any],
    root: Path,
    *,
    max_beats: int = DEFAULT_MAX_BEATS,
    apply_profile: bool = True,
    advance: AdvanceFn | None = None,
) -> MissionResult:
    """Keep executing beats until a terminal evaluation.

    ``advance`` is injectable for tests. The default is one real
    ``factory_advance.main`` beat (Architect→…→report), which still
    honors remaining safety rails.
    """
    advance_fn = advance or factory_advance.main
    budget = max(1, int(max_beats))
    pid = str(project.get("name") or "project")
    view = _absolute_project(project, root)
    profile: list[str] = []
    if apply_profile:
        profile = enable_workbench_profile(project, root)
        msg.info(
            "Workbench autonomous profile enabled "
            f"for '{pid}': {', '.join(profile)}"
        )

    records: list[BeatRecord] = []
    status, reason = evaluate_mission(view, root, beat=0, max_beats=budget)
    records.append(_record(view, root, index=0, status=status, reason=reason))
    beats = 0
    while status in {MORE_WORK, RECOVERABLE}:
        msg.phase(f"Mission beat {beats + 1}/{budget} for '{pid}'")
        # Kernel stages still consume the relative registry mapping.
        advance_fn(project)
        beats += 1
        status, reason = evaluate_mission(
            view, root, beat=beats, max_beats=budget
        )
        records.append(
            _record(view, root, index=beats, status=status, reason=reason)
        )
        if status in {COMPLETE, HUMAN_REQUIRED, BUDGET_EXHAUSTED}:
            break

    result = MissionResult(
        project_id=pid,
        outcome=status,
        reason=reason,
        beats=beats,
        max_beats=budget,
        profile_enabled=profile,
        records=records,
        artifact=str(view.get("app_path") or ""),
        trace_path="",
    )
    trace = _write_trace(result, view, root)
    result.trace_path = str(trace)
    msg.info(f"Mission {status}: {reason}")
    msg.info(f"Trace: {trace}")
    return result


def stop_mission(
    project: dict[str, Any], root: Path, *, note: str = ""
) -> str:
    """Request the runner to halt at the next evaluation."""
    return set_flag(
        "stop",
        root,
        state_dir=str(project["state_dir"]),
        note=note or "owner requested mission stop",
    )


def render_mission(result: MissionResult) -> str:
    """Owner-facing summary (trace is the durable record)."""
    return (
        f"Mission {result.outcome} for '{result.project_id}' "
        f"after {result.beats} beat(s): {result.reason}\n"
        f"Artifact: {result.artifact}\n"
        f"Trace: {result.trace_path}\n"
    )
