#!/usr/bin/env python3
"""Agentic control: persist attempts, monitor evidence, decide the beat.

The coding plugin writes files. This module is the factory's working
memory and supervisor: Claude/OpenAI interpret runtime, validation,
prior writes, and attempt history, then choose outcome, objective,
stance, and recovery. Deterministic rails still veto: owner stop,
beat budget, unsafe start, and COMPLETE without acceptance evidence.

No LangChain, vector DB, or KAE-Memory. Persistence is files the
factory owns under the workbench task root.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from coding_llm import resolve_coding_backend
from llm_interaction import structured_call

KIND_CODE_BIRTH = "code_birth"
KIND_COMPLETE = "complete"
KIND_IMPLEMENT = "implement"
KIND_IMPLEMENT_DELTA = "implement_delta"
KIND_REPAIR_PROGRESS = "repair_progress"
KIND_REPAIR_RUNTIME = "repair_runtime"
KIND_REPAIR_VALIDATION = "repair_validation"
KIND_SPECIFY = "specify_intent"
STANCE_BIRTH = "birth"
STANCE_IMPLEMENT = "implement"
STANCE_INVESTIGATE = "investigate"
STANCE_NEED_CONTEXT = "need_context"
STANCE_REPAIR = "repair"

ATTEMPTS_FILE = "attempts.jsonl"
MEMORY_FILE = "control_memory.json"
DECISION_FILE = "control_decision.json"
ATTEMPT_CAP = 12
ATTEMPT_LINE_CAP = 4000
MEMORY_NOTES_CAP = 1200

COMPLETE = "COMPLETE"
MORE_WORK = "MORE_WORK"
RECOVERABLE = "RECOVERABLE_FAILURE"
HUMAN_REQUIRED = "HUMAN_REQUIRED"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
RUNNABLE_PREVIEW = "RUNNABLE_PREVIEW"

ALLOWED_OUTCOMES = frozenset(
    {
        COMPLETE,
        MORE_WORK,
        RECOVERABLE,
        HUMAN_REQUIRED,
        BUDGET_EXHAUSTED,
        RUNNABLE_PREVIEW,
    }
)
ALLOWED_KINDS = frozenset(
    {
        KIND_CODE_BIRTH,
        KIND_SPECIFY,
        KIND_IMPLEMENT,
        KIND_IMPLEMENT_DELTA,
        KIND_REPAIR_RUNTIME,
        KIND_REPAIR_VALIDATION,
        KIND_REPAIR_PROGRESS,
        KIND_COMPLETE,
    }
)
ALLOWED_STANCES = frozenset(
    {
        STANCE_BIRTH,
        STANCE_IMPLEMENT,
        STANCE_REPAIR,
        STANCE_INVESTIGATE,
        STANCE_NEED_CONTEXT,
    }
)
ALLOWED_RECOVERY = frozenset({"continue", "retry", "park", "human"})

_CONTROL_SYSTEM = (
    "You are Crazy Factory control intelligence. You own mission "
    "continuation, objective selection, engineering stance, quality "
    "judgment, and recovery. You do not write application files. "
    "Respond with ONLY JSON. Never claim COMPLETE when files, tests, "
    "or a declared start command are still failing. Never claim "
    "COMPLETE when compiled product claims are unsatisfied. Never "
    "override an owner stop flag or beat budget. Safety floor: no "
    "push, merge, delete, or engine-source writes."
)
_CONTROL_PRIMING = (
    "Respond with JSON keys: outcome, quality_ok, kind, stance, "
    "title, focus, rationale, recovery, director_why, memory_notes. "
    "outcome is one of COMPLETE, MORE_WORK, RECOVERABLE_FAILURE, "
    "HUMAN_REQUIRED, BUDGET_EXHAUSTED, RUNNABLE_PREVIEW. kind is one "
    "of code_birth, specify_intent, implement, implement_delta, "
    "repair_runtime, repair_validation, "
    "repair_progress, complete. stance is one of birth, implement, "
    "repair, investigate, need_context. recovery is continue, retry, "
    "park, or human. quality_ok is boolean."
)


@dataclass
class ControlDecision:
    """One control-plane decision for the current beat."""

    outcome: str
    quality_ok: bool
    kind: str
    stance: str
    title: str = ""
    focus: str = ""
    rationale: str = ""
    recovery: str = "continue"
    director_why: str = ""
    memory_notes: str = ""
    provider: str = ""
    source: str = "fallback"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _task_dir(project: dict[str, Any], root: Path) -> Path:
    raw = project.get("task_root") or "factory_tasks"
    path = Path(str(raw))
    return path if path.is_absolute() else (root / path)


def _app_dir(project: dict[str, Any], root: Path) -> Path:
    path = Path(str(project["app_path"]))
    return path if path.is_absolute() else (root / path)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def control_model_enabled() -> bool:
    """Live control LLM: on when a cloud key exists, off under pytest.

    Tests opt in with ``CRAZY_FACTORY_CONTROL=1`` plus a mocked backend.
    Owners disable with ``CRAZY_FACTORY_CONTROL=0``.
    """
    flag = (os.environ.get("CRAZY_FACTORY_CONTROL") or "").strip()
    if flag == "0":
        return False
    if os.environ.get("PYTEST_CURRENT_TEST") and flag != "1":
        return False
    return resolve_coding_backend() is not None


def load_attempts(task_root: Path, *, limit: int = ATTEMPT_CAP) -> list[dict]:
    """Latest attempt records, oldest first, capped."""
    path = task_root / ATTEMPTS_FILE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            rows.append(raw)
    return rows


def load_memory(task_root: Path) -> dict[str, Any]:
    return _load_json(task_root / MEMORY_FILE) or {}


def load_decision(task_root: Path) -> ControlDecision | None:
    raw = _load_json(task_root / DECISION_FILE)
    if not raw:
        return None
    try:
        return ControlDecision(
            outcome=str(raw.get("outcome") or MORE_WORK),
            quality_ok=bool(raw.get("quality_ok")),
            kind=str(raw.get("kind") or KIND_IMPLEMENT),
            stance=str(raw.get("stance") or STANCE_IMPLEMENT),
            title=str(raw.get("title") or ""),
            focus=str(raw.get("focus") or ""),
            rationale=str(raw.get("rationale") or ""),
            recovery=str(raw.get("recovery") or "continue"),
            director_why=str(raw.get("director_why") or ""),
            memory_notes=str(raw.get("memory_notes") or ""),
            provider=str(raw.get("provider") or ""),
            source=str(raw.get("source") or "fallback"),
        )
    except (TypeError, ValueError):
        return None


def persist_decision(decision: ControlDecision, task_root: Path) -> Path:
    task_root.mkdir(parents=True, exist_ok=True)
    path = task_root / DECISION_FILE
    path.write_text(
        json.dumps(asdict(decision), indent=2) + "\n", encoding="utf-8"
    )
    return path


def persist_memory(notes: str, task_root: Path, extra: dict[str, Any]) -> Path:
    task_root.mkdir(parents=True, exist_ok=True)
    path = task_root / MEMORY_FILE
    body = {
        "notes": (notes or "")[:MEMORY_NOTES_CAP],
        "updated_at": _now(),
        **extra,
    }
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def append_attempt(task_root: Path, record: dict[str, Any]) -> Path:
    """Append one beat to the durable attempt log."""
    task_root.mkdir(parents=True, exist_ok=True)
    path = task_root / ATTEMPTS_FILE
    payload = dict(record)
    payload.setdefault("at", _now())
    line = json.dumps(payload, ensure_ascii=True)
    if len(line) > ATTEMPT_LINE_CAP:
        line = line[: ATTEMPT_LINE_CAP - 3] + "..."
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return path


def file_hashes(app: Path, names: list[str]) -> dict[str, str]:
    """Short content hashes so the monitor can see unchanged rewrites."""
    out: dict[str, str] = {}
    for name in names[:8]:
        path = app / name
        try:
            data = path.read_bytes()
        except OSError:
            out[name] = "missing"
            continue
        out[name] = hashlib.sha256(data).hexdigest()[:16]
    return out


def assemble_monitor(
    project: dict[str, Any],
    root: Path,
    *,
    beat: int,
    max_beats: int,
    candidate_outcome: str,
    candidate_reason: str,
    accepted: bool,
    runtime_status: str,
) -> dict[str, Any]:
    """Bounded evidence packet for the control model."""
    task_root = _task_dir(project, root)
    app = _app_dir(project, root)
    previous = _load_json(task_root / "executor_result.json") or {}
    files = [
        str(name)
        for name in (previous.get("files") or [])
        if isinstance(name, str)
    ]
    validation = _load_json(task_root / "validation_result.json") or {}
    runtime = _load_json(task_root / "runtime_result.json") or {}
    objective = _load_json(task_root / "current_objective.json") or {}
    judgment = _load_json(task_root / "judgment.json") or {}
    attempts = load_attempts(task_root)
    memory = load_memory(task_root)
    return {
        "beat": beat,
        "max_beats": max_beats,
        "candidate_outcome": candidate_outcome,
        "candidate_reason": candidate_reason,
        "accepted": accepted,
        "runtime_status": runtime_status,
        "runtime": {
            "status": runtime.get("status"),
            "ok": runtime.get("ok"),
            "required": runtime.get("required"),
            "safe": runtime.get("safe"),
            "reason": runtime.get("reason"),
        },
        "validation": {
            "status": validation.get("status"),
            "checks": (validation.get("checks") or [])[:5]
            if isinstance(validation.get("checks"), list)
            else [],
        },
        "executor": {
            "ok": previous.get("ok"),
            "provider": previous.get("provider"),
            "files": files,
            "stance": previous.get("stance"),
            "reason": previous.get("reason"),
            "hashes": file_hashes(app, files),
        },
        "objective": {
            "id": objective.get("id"),
            "kind": objective.get("kind"),
            "title": objective.get("title"),
        },
        "judgment": {
            "outcome": judgment.get("outcome"),
            "accepted": judgment.get("accepted"),
            "executor_ok_is_not_acceptance": judgment.get(
                "executor_ok_is_not_acceptance"
            ),
        },
        "attempts": attempts[-ATTEMPT_CAP:],
        "memory_notes": memory.get("notes") or "",
    }


def fallback_decision(
    *,
    outcome: str,
    reason: str,
    kind: str = KIND_IMPLEMENT,
    stance: str = STANCE_IMPLEMENT,
) -> ControlDecision:
    return ControlDecision(
        outcome=outcome if outcome in ALLOWED_OUTCOMES else MORE_WORK,
        quality_ok=outcome == COMPLETE,
        kind=kind if kind in ALLOWED_KINDS else KIND_IMPLEMENT,
        stance=stance if stance in ALLOWED_STANCES else STANCE_IMPLEMENT,
        rationale=reason,
        director_why=reason,
        source="fallback",
        recovery="continue",
    )


def _parse_decision(
    data: dict[str, Any], *, provider: str, fallback: ControlDecision
) -> ControlDecision:
    outcome = str(data.get("outcome") or fallback.outcome)
    if outcome not in ALLOWED_OUTCOMES:
        outcome = fallback.outcome
    kind = str(data.get("kind") or fallback.kind)
    if kind not in ALLOWED_KINDS:
        kind = fallback.kind
    stance = str(data.get("stance") or fallback.stance)
    if stance not in ALLOWED_STANCES:
        stance = fallback.stance
    recovery = str(data.get("recovery") or "continue")
    if recovery not in ALLOWED_RECOVERY:
        recovery = "continue"
    quality = data.get("quality_ok")
    if not isinstance(quality, bool):
        quality = fallback.quality_ok
    return ControlDecision(
        outcome=outcome,
        quality_ok=quality,
        kind=kind,
        stance=stance,
        title=str(data.get("title") or "")[:200],
        focus=str(data.get("focus") or "")[:800],
        rationale=str(data.get("rationale") or "")[:800],
        recovery=recovery,
        director_why=str(data.get("director_why") or "")[:400],
        memory_notes=str(data.get("memory_notes") or "")[:MEMORY_NOTES_CAP],
        provider=provider,
        source="model",
    )


def apply_rails(
    decision: ControlDecision,
    *,
    candidate_outcome: str,
    candidate_reason: str,
    accepted: bool,
    runtime_safe: bool,
) -> tuple[str, str]:
    """Model decides quality and continuation; rails keep the floor."""
    if candidate_outcome == BUDGET_EXHAUSTED:
        return BUDGET_EXHAUSTED, candidate_reason
    if candidate_outcome == HUMAN_REQUIRED:
        return HUMAN_REQUIRED, candidate_reason
    if not runtime_safe:
        return HUMAN_REQUIRED, candidate_reason
    if candidate_outcome == RUNNABLE_PREVIEW:
        # No coding plugin: do not burn budget or fake COMPLETE.
        return RUNNABLE_PREVIEW, candidate_reason
    if candidate_outcome == COMPLETE:
        if decision.source == "model" and (
            not decision.quality_ok or decision.outcome == MORE_WORK
        ):
            why = decision.rationale or "control intelligence: quality gap"
            return MORE_WORK, why
        return COMPLETE, candidate_reason
    if not accepted and decision.outcome == COMPLETE:
        return candidate_outcome, candidate_reason
    if (
        decision.source == "model"
        and decision.outcome == HUMAN_REQUIRED
        and decision.recovery == "human"
    ):
        why = decision.rationale or "control intelligence: human required"
        return HUMAN_REQUIRED, why
    if (
        decision.source == "model"
        and decision.outcome == RECOVERABLE
        and candidate_outcome == MORE_WORK
    ):
        why = decision.rationale or candidate_reason
        return RECOVERABLE, why
    return candidate_outcome, candidate_reason


def reason_control(
    project: dict[str, Any],
    root: Path,
    *,
    beat: int,
    max_beats: int,
    candidate_outcome: str,
    candidate_reason: str,
    accepted: bool,
    runtime_status: str,
    runtime_safe: bool = True,
    heuristic_kind: str = KIND_IMPLEMENT,
    heuristic_stance: str = STANCE_IMPLEMENT,
) -> ControlDecision:
    """Ask the cloud model to monitor and decide; fall back if needed."""
    task_root = _task_dir(project, root)
    fallback = fallback_decision(
        outcome=candidate_outcome,
        reason=candidate_reason,
        kind=heuristic_kind,
        stance=heuristic_stance,
    )
    packet = assemble_monitor(
        project,
        root,
        beat=beat,
        max_beats=max_beats,
        candidate_outcome=candidate_outcome,
        candidate_reason=candidate_reason,
        accepted=accepted,
        runtime_status=runtime_status,
    )
    decision = fallback
    if control_model_enabled():
        pack = resolve_coding_backend()
        if pack is not None:
            provider, client, model = pack
            data, note = structured_call(
                client=client,
                model=model,
                system=_CONTROL_SYSTEM,
                user=json.dumps(packet, indent=2)[:12000],
                priming=_CONTROL_PRIMING,
                required_keys=("outcome", "quality_ok", "kind", "stance"),
                retries=1,
            )
            if data is not None:
                decision = _parse_decision(
                    data, provider=provider, fallback=fallback
                )
            else:
                fallback.rationale = f"{candidate_reason} ({note})"
                decision = fallback
    persist_decision(decision, task_root)
    persist_memory(
        decision.memory_notes or load_memory(task_root).get("notes") or "",
        task_root,
        {
            "last_outcome": decision.outcome,
            "last_kind": decision.kind,
            "last_stance": decision.stance,
            "source": decision.source,
            "provider": decision.provider,
        },
    )
    previous = _load_json(task_root / "executor_result.json") or {}
    files = [
        str(name)
        for name in (previous.get("files") or [])
        if isinstance(name, str)
    ]
    append_attempt(
        task_root,
        {
            "beat": beat,
            "outcome": decision.outcome,
            "kind": decision.kind,
            "stance": decision.stance,
            "source": decision.source,
            "provider": decision.provider,
            "accepted": accepted,
            "runtime": runtime_status,
            "executor_ok": previous.get("ok"),
            "files": files,
            "hashes": file_hashes(_app_dir(project, root), files),
            "rationale": decision.rationale,
        },
    )
    return decision
