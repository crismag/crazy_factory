#!/usr/bin/env python3
"""Phase 9D situational-context (DiagnosisPacket) builder for Crazy Factory.

The packet is the factory's curated *evidence layer*: one bounded, deterministic
object assembled from structured artifacts + state, holding the ground truth a
model needs to act well on the current task — acceptance criteria, the exact
prior failures and rejection reasons, the workbench reality, and a short attempt
summary.

Design rules (see docs/report/context/phase-9d/01_diagnosis_packet.md):

- Feed FACTS, not factory prose: this reads structured JSON (planned_task.json,
  coder_proposal.json, patch_plan.json, validation_result.json) and the
  architecture contract — never the narrative ``*_REPORT.md`` files.
- Deterministic: no clock/random use; ``now`` and ids are passed in or derived
  from stable inputs, so the same inputs produce byte-identical output.
- Bounded: the source snapshot is capped by file count and bytes, and long
  texts are truncated, so the packet can never explode a prompt.
- Fresh: it reads only the current task's artifacts (overwritten each beat), so
  a prior session's data cannot leak in.

The packet is a derived *read-model*; ``project_state`` remains the write-model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from architecture import load_contract, missing_required
from completion import open_items, parse_checklist

# Bounds for the workbench source snapshot — keep the packet prompt-safe.
DEFAULT_MAX_SOURCE_FILES = 4
DEFAULT_MAX_SOURCE_BYTES = 8000
_PACKET_FILENAME = "diagnosis/current_packet.json"


@dataclass(frozen=True)
class FailingCheck:
    """One failed/blocked/errored validation check (ground truth)."""

    command: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class SourceFile:
    """A snapshot of one in-scope workbench file."""

    path: str
    content: str
    truncated: bool = False
    exists: bool = True


@dataclass(frozen=True)
class DiagnosisPacket:
    """Curated, bounded evidence for the current task (the read-model)."""

    packet_id: str
    project_id: str
    generated_at: str
    # current task / success definition
    task_id: str
    focus_item: str
    focus_file: str
    objective: str
    scope: list[str]
    acceptance_criteria: list[str]
    validation_expectations: list[str]
    # architecture / coverage
    required_files: list[str]
    missing_required_files: list[str]
    # workbench reality
    files_in_scope: list[str]
    source_snapshot: list[SourceFile]
    # last validation (ground truth)
    validation_status: str
    failing_checks: list[FailingCheck]
    # last rejections (ground truth, from JSON not prose)
    contract_rejections: list[str]
    proposal_rejections: list[str]
    patch_rejections: list[str]
    # attempt summary
    failure_count: int = 0
    remediation_attempt: int = 0
    current_blocker: str = ""


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON object from ``path``; return ``None`` if absent/invalid.

    Reads directly (not repo-confined) so external-app absolute task roots work.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _reasons(record: dict[str, Any] | None) -> list[str]:
    """Extract validation rejection reasons from an artifact record."""
    if not record:
        return []
    validation = record.get("validation")
    if not isinstance(validation, dict):
        return []
    reasons = validation.get("reasons")
    if not isinstance(reasons, list):
        return []
    return [str(r) for r in reasons]


def _str_list(value: Any) -> list[str]:
    """Coerce a scalar/list value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _focus(checklist_md: str) -> tuple[str, str]:
    """Return (first-open-item text, its path-like token) from the checklist."""
    items = open_items(parse_checklist(checklist_md))
    if not items:
        return "", ""
    text = items[0].text
    for token in text.split():
        if "/" in token:
            return text, token.strip(".,;:`")
    return text, ""


def _read_text_or_empty(path: Path) -> str:
    """Read a file directly; empty string when missing/unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _source_snapshot(
    app_path: str,
    files: list[str],
    *,
    max_files: int,
    max_bytes: int,
) -> list[SourceFile]:
    """Bounded snapshot of in-scope files' current contents."""
    snapshot: list[SourceFile] = []
    base = Path(app_path)
    for rel in files[:max_files]:
        # Proposal paths may be repo-relative or workbench-relative; try both.
        candidate = Path(rel)
        if not candidate.exists():
            candidate = base / rel
        if not candidate.exists():
            snapshot.append(SourceFile(rel, "", truncated=False, exists=False))
            continue
        text = _read_text_or_empty(candidate)
        truncated = len(text.encode("utf-8")) > max_bytes
        if truncated:
            text = text.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")
        snapshot.append(SourceFile(rel, text, truncated=truncated))
    return snapshot


def build_packet(
    *,
    project: dict[str, Any],
    root: Path,
    project_state: dict[str, Any],
    now: str,
    max_source_files: int = DEFAULT_MAX_SOURCE_FILES,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
) -> DiagnosisPacket:
    """Assemble the current-task diagnosis packet from artifacts + state.

    Args:
        project: Resolved project mapping (provides app_path/task_root/name).
        root: Absolute repository root.
        project_state: Current project state snapshot (read-model source).
        now: ISO timestamp for ``generated_at`` (passed in for determinism).
        max_source_files: Cap on snapshot file count.
        max_source_bytes: Per-file byte cap on snapshot contents.

    Returns:
        A bounded :class:`DiagnosisPacket`. Missing artifacts degrade to empty
        fields rather than failing.
    """
    app_path = str(project["app_path"])
    task_root = Path(str(project["task_root"]))
    project_id = str(project.get("name") or app_path)

    contract = _read_json(task_root / "planned_task.json")
    proposal = _read_json(task_root / "coder_proposal.json")
    patch = _read_json(task_root / "patch_plan.json")
    validation = _read_json(task_root / "validation_result.json")
    arch = load_contract(app_path) or {}

    checklist_md = _read_text_or_empty(task_root / "MASTER_CHECKLIST.md")
    focus_item, focus_file = _focus(checklist_md)

    task_id = str((contract or {}).get("task_id") or "")
    files_in_scope = _str_list(
        (proposal or {}).get("files_to_create")
    ) + _str_list((proposal or {}).get("files_to_modify"))

    failing = [
        FailingCheck(
            str(c.get("command", "")),
            str(c.get("status", "")),
            str(c.get("detail", "")),
        )
        for c in ((validation or {}).get("checks") or [])
        if isinstance(c, dict)
        and c.get("status") in {"failed", "blocked", "error"}
    ]

    required = _str_list(arch.get("required_files")) if arch else []

    return DiagnosisPacket(
        packet_id=f"{project_id}:{task_id}:{project_state.get('failure_count', 0)}",
        project_id=project_id,
        generated_at=now,
        task_id=task_id,
        focus_item=focus_item,
        focus_file=focus_file,
        objective=str((contract or {}).get("objective") or ""),
        scope=_str_list((contract or {}).get("scope")),
        acceptance_criteria=_str_list(
            (contract or {}).get("acceptance_criteria")
        ),
        validation_expectations=_str_list(
            (contract or {}).get("validation_plan")
        ),
        required_files=required,
        missing_required_files=(
            missing_required(app_path, arch) if arch else []
        ),
        files_in_scope=files_in_scope,
        source_snapshot=_source_snapshot(
            app_path,
            files_in_scope,
            max_files=max_source_files,
            max_bytes=max_source_bytes,
        ),
        validation_status=str((validation or {}).get("status") or "not_run"),
        failing_checks=failing,
        contract_rejections=_reasons(contract),
        proposal_rejections=_reasons(proposal),
        patch_rejections=_reasons(patch),
        failure_count=int(project_state.get("failure_count", 0) or 0),
        remediation_attempt=int(
            project_state.get("remediation_attempt", 0) or 0
        ),
        current_blocker=str(project_state.get("current_blocker") or ""),
    )


def packet_to_dict(packet: DiagnosisPacket) -> dict[str, Any]:
    """Return a JSON-serializable mapping of the packet."""
    return {
        "packet_id": packet.packet_id,
        "project_id": packet.project_id,
        "generated_at": packet.generated_at,
        "task_id": packet.task_id,
        "focus_item": packet.focus_item,
        "focus_file": packet.focus_file,
        "objective": packet.objective,
        "scope": packet.scope,
        "acceptance_criteria": packet.acceptance_criteria,
        "validation_expectations": packet.validation_expectations,
        "required_files": packet.required_files,
        "missing_required_files": packet.missing_required_files,
        "files_in_scope": packet.files_in_scope,
        "source_snapshot": [
            {
                "path": s.path,
                "content": s.content,
                "truncated": s.truncated,
                "exists": s.exists,
            }
            for s in packet.source_snapshot
        ],
        "validation_status": packet.validation_status,
        "failing_checks": [
            {"command": c.command, "status": c.status, "detail": c.detail}
            for c in packet.failing_checks
        ],
        "contract_rejections": packet.contract_rejections,
        "proposal_rejections": packet.proposal_rejections,
        "patch_rejections": packet.patch_rejections,
        "failure_count": packet.failure_count,
        "remediation_attempt": packet.remediation_attempt,
        "current_blocker": packet.current_blocker,
    }


def write_packet(
    packet: DiagnosisPacket, root: Path, project: dict[str, Any]
) -> str:
    """Persist the packet under the per-project state diagnosis dir.

    Returns the path written. Best-effort: a write failure is non-fatal (the
    packet is also passed in-memory to consumers).
    """
    from repo_tools import safe_write_json

    state_dir = str(project.get("factory_state_dir") or "factory_state")
    out_rel = f"{state_dir}/projects/{packet.project_id}/{_PACKET_FILENAME}"
    try:
        safe_write_json(
            out_rel,
            packet_to_dict(packet),
            repo_root=root,
            allowed_roots=[state_dir],
        )
    except Exception:  # pragma: no cover - persistence is best-effort
        return ""
    return out_rel


def _bullet(items: list[str], empty: str = "(none)") -> str:
    """Render a list as indented bullets, or a placeholder when empty."""
    return "\n".join(f"  - {i}" for i in items) if items else f"  {empty}"


def _ground_truth_block(packet: DiagnosisPacket) -> str:
    """Shared 'what happened last time' section (rejections + failures)."""
    parts: list[str] = []
    rejections = (
        packet.patch_rejections
        + packet.proposal_rejections
        + packet.contract_rejections
    )
    if rejections:
        parts.append(
            "Your previous attempt was REJECTED for these reasons "
            "(do not repeat them):\n" + _bullet(rejections)
        )
    if packet.failing_checks:
        parts.append(
            "The last validation FAILED on these checks:\n"
            + _bullet(
                [
                    f"`{c.command}` ({c.status}): {c.detail}".strip()
                    for c in packet.failing_checks
                ]
            )
        )
    if packet.missing_required_files:
        parts.append(
            "Required files still MISSING (must be created):\n"
            + _bullet(packet.missing_required_files)
        )
    return "\n\n".join(parts)


def coder_slice(packet: DiagnosisPacket) -> str:
    """Role slice for the coder proposal prompt."""
    sections = [
        f"Current focus: {packet.focus_item or packet.focus_file or '(n/a)'}",
        "Acceptance criteria (every one must be satisfied):\n"
        + _bullet(packet.acceptance_criteria),
    ]
    ground = _ground_truth_block(packet)
    if ground:
        sections.append(ground)
    return "\n\n".join(sections)


def patch_plan_slice(packet: DiagnosisPacket) -> str:
    """Role slice for the patch-plan (code) prompt."""
    sections = [
        "Acceptance criteria (the code must satisfy ALL of these):\n"
        + _bullet(packet.acceptance_criteria),
    ]
    if packet.source_snapshot:
        snap = "\n".join(
            f"  - {s.path}: "
            + ("MISSING (create it)" if not s.exists else "exists")
            for s in packet.source_snapshot
        )
        sections.append("Files in scope (current reality):\n" + snap)
    ground = _ground_truth_block(packet)
    if ground:
        sections.append(ground)
    return "\n\n".join(sections)
