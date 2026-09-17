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

Passing tests is evidence, not product quality. Executor ``ok`` is not
acceptance. Blind "fix the errors" is not the recovery stance.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from control_intelligence import load_decision
from conversation_delta import delta_prompts
from diagnosis_packet import DiagnosisPacket, executor_slice
from product_intent import unsatisfied_claims

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
INVENTORY_CAP = 40
ASSIGNMENT_FILE = "execution_assignment.md"
JUDGMENT_FILE = "judgment.json"

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
    constraints: tuple[str, ...] = (
        (
            "Write only under src/, tests/, data/, docs/, README.md, "
            "architecture.json, and requirements.txt."
        ),
        "Never write scripts/, factory/, config/, .git/, or engine source.",
        "Do not push, merge, delete, or rewrite git history.",
        "Do not invent a product when the seed is a placeholder.",
        "Executor completion is not acceptance; tests and runtime are.",
        "Banner or title text is not product evidence.",
    )


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
) -> ExecutionAssignment:
    """Answer the task-intelligence questions from existing artifacts."""
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
    claim_gaps = unsatisfied_claims(project, root)
    if claim_gaps:
        success = [cap.claim for cap in claim_gaps] + success
    if not verification:
        verification = [
            "python3 -m compileall on workbench sources",
            "pytest on workbench tests when present",
            "runtime probe when start_command is declared",
        ]
    prev_note = ""
    if prev_files:
        prev_note = (
            f"provider={previous.get('provider') or '?'} "
            f"wrote {', '.join(prev_files[:12])}"
        )
    return ExecutionAssignment(
        objective_id=str(getattr(objective, "id", "") or ""),
        kind=kind,
        title=str(getattr(objective, "title", "") or ""),
        why=str(getattr(objective, "why", "") or ""),
        gap=str(getattr(objective, "gap", "") or ""),
        focus=str(getattr(objective, "focus", "") or ""),
        stance=stance,
        success=success,
        verification=verification,
        inventory=_inventory(app),
        missing=missing,
        validation_summary=val_text,
        runtime_summary=run_text,
        evidence=evidence,
        seed_excerpt=_seed_excerpt(project, root),
        architecture_excerpt=_architecture_excerpt(app),
        owner_deltas=deltas[-5:],
        previous_executor=prev_note,
    )


def render_assignment(assignment: ExecutionAssignment) -> str:
    """Purpose-built user message for a coding plugin."""
    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- (none)"

    sections = [
        "# Engineering assignment",
        "## Objective",
        f"- id: `{assignment.objective_id}`",
        f"- kind: `{assignment.kind}`",
        f"- title: {assignment.title}",
        f"- gap: {assignment.gap}",
        f"- why: {assignment.why}",
        f"- stance: `{assignment.stance}`",
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
    if assignment.seed_excerpt:
        sections.extend(["", "## Seed", assignment.seed_excerpt])
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
    """Write the assignment markdown under the workbench task root."""
    task_root.mkdir(parents=True, exist_ok=True)
    path = task_root / ASSIGNMENT_FILE
    path.write_text(render_assignment(assignment), encoding="utf-8")
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
    data.pop("seed_excerpt", None)
    data.pop("architecture_excerpt", None)
    data.pop("evidence", None)
    return data
