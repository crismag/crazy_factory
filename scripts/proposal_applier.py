#!/usr/bin/env python3
"""Phase 5 proposal application engine for Crazy Factory.

This stage turns an owner-approved, valid coder proposal into a concrete patch
plan (exact file contents) and, only when explicitly enabled, applies it to the
application workbench. The model proposes file contents; Python validates every
path, line, and byte before anything is written.

Hard boundaries:

- Nothing happens without the full gate: the contract is owner-authorized and
  valid, the coder proposal is valid, and the owner has approved application
  (``approved_proposal.json`` with ``application_approved: true`` matching the
  proposal id).
- Writes only ever target ``apps/<project>/{app,docs,tests}``. Protected
  paths (root README, ``factory/``, ``.git/``, ``config/``, ``scripts/``,
  ``state/``, secrets, …) are rejected.
- The default mode is ``preview_only`` with ``allow_apply: false``: a patch
  plan and report are produced, but no files are written. Application happens
  only when the config explicitly enables it.
- Model unavailable or malformed output yields a *rejected* plan, never a
  fake-valid one. The run always exits cleanly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coder_proposal import (
    SECRET_MARKERS,
    _default_runtime_prefixes,
    classify_path,
    project_runtime_prefixes,
    resolve_workbench_path,
)
from architecture import load_contract, patch_contract_violations
from contract_stage import load_existing_contract
from json_parsing import coerce_str, coerce_str_list, strip_code_fence
from ollama_client import OllamaClient, OllamaConnectionError
from prompt_builder import build_prompt_package
from repo_tools import (
    RepoSafetyError,
    resolve_repo_path,
    safe_write_json,
    safe_write_text,
)
from task_contract import is_contract_actionable

# Top-level paths application may never touch, named explicitly for auditable
# rejection messages. The app/docs/tests allow-list already excludes them.
FORBIDDEN_APPLY_PREFIXES: tuple[str, ...] = (
    "factory/",
    ".git/",
    ".github/",
    "config/",
    "scripts/",
    "bin/",
    "cron/",
    "state/",
    "logs/",
    "reports/",
    "contexts/",
    "checkpoints/",
)

# Exact repository-root files application may never touch.
FORBIDDEN_EXACT_PATHS: tuple[str, ...] = (
    "readme.md",
    ".gitignore",
    "pyproject.toml",
)

VALID_ACTIONS: frozenset[str] = frozenset({"create", "modify", "delete"})


class PatchPlanParseError(ValueError):
    """Raised when coder output cannot be parsed into a patch plan."""


@dataclass(frozen=True)
class PatchFile:
    """One file operation within a patch plan.

    Attributes:
        path: Repository-relative target path.
        action: ``"create"``, ``"modify"``, or ``"delete"``.
        content: Full file content for create/modify; empty for delete.
    """

    path: str
    action: str
    content: str = ""


@dataclass(frozen=True)
class PatchPlan:
    """A concrete, owner-reviewable set of file operations.

    Attributes:
        plan_id: Stable identifier for the patch plan.
        task_id: Backing contract task identifier.
        proposal_id: Backing coder proposal identifier.
        files: Ordered file operations.
        notes: Free-form notes for the owner.
    """

    plan_id: str
    task_id: str
    proposal_id: str
    files: list[PatchFile] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class ApplicationVerdict:
    """Outcome of validating a :class:`PatchPlan`.

    Attributes:
        valid: Whether the plan satisfies every safety rule.
        reasons: Human-readable rejection reasons. Empty when ``valid``.
        blocked_paths: Specific paths that violated the target boundary.
        warnings: Non-fatal concerns worth surfacing to the owner.
    """

    valid: bool
    reasons: list[str] = field(default_factory=list)
    blocked_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ApplicationResult:
    """Outcome of the application stage.

    Attributes:
        plan: Parsed patch plan, or ``None`` when none was produced.
        verdict: Validation verdict for the plan.
        source: ``"ollama"``, ``"fallback"``, or ``"skipped"``.
        detail: Human-readable explanation for reports.
        mode: ``"preview_only"`` or ``"apply"``.
        activated: ``True`` when the full approval gate passed.
        applied: ``True`` when files were actually written.
        applied_files: Repository-relative files written or removed.
    """

    plan: PatchPlan | None
    verdict: ApplicationVerdict
    source: str
    detail: str
    mode: str
    activated: bool = False
    applied: bool = False
    applied_files: list[str] = field(default_factory=list)


def is_proposal_valid(proposal_record: object) -> bool:
    """Report whether a persisted coder proposal validated as ``valid``.

    Args:
        proposal_record: A parsed ``coder_proposal.json`` value.

    Returns:
        ``True`` only when the record is a mapping with validation valid.
    """
    if not isinstance(proposal_record, dict):
        return False
    validation = proposal_record.get("validation")
    return isinstance(validation, dict) and validation.get("status") == "valid"


def is_application_approved(
    approval_record: object, proposal_record: object
) -> bool:
    """Report whether the owner explicitly approved applying this proposal.

    Approval lives in a separate ``approved_proposal.json`` that the factory
    never overwrites, and must name the exact proposal id being applied so a
    stale approval cannot authorize a freshly generated proposal.

    Args:
        approval_record: A parsed ``approved_proposal.json`` value.
        proposal_record: The current ``coder_proposal.json`` mapping.

    Returns:
        ``True`` only when approval is explicit and matches the proposal id.
    """
    if not isinstance(approval_record, dict):
        return False
    if approval_record.get("application_approved") is not True:
        return False
    approved_id = approval_record.get("proposal_id")
    if not approved_id or not isinstance(proposal_record, dict):
        return False
    return approved_id == proposal_record.get("proposal_id")


def parse_patch_plan(raw: str) -> PatchPlan:
    """Parse a coder JSON patch plan into a :class:`PatchPlan`.

    Args:
        raw: Raw coder output expected to contain a single JSON object.

    Returns:
        Parsed patch plan.

    Raises:
        PatchPlanParseError: If the text is not a JSON object.
    """
    text = strip_code_fence(raw)
    if not text:
        raise PatchPlanParseError("Coder returned empty patch plan content")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PatchPlanParseError(
            f"Patch plan is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise PatchPlanParseError("Patch plan JSON must be an object")
    raw_files = data.get("files")
    files: list[PatchFile] = []
    if isinstance(raw_files, list):
        for item in raw_files:
            if not isinstance(item, dict):
                continue
            raw_content = item.get("content")
            content = raw_content if isinstance(raw_content, str) else ""
            files.append(
                PatchFile(
                    path=coerce_str(item.get("path")),
                    action=coerce_str(item.get("action")).lower(),
                    content=content,
                )
            )
    return PatchPlan(
        plan_id=coerce_str(data.get("plan_id")),
        task_id=coerce_str(data.get("task_id")),
        proposal_id=coerce_str(data.get("proposal_id")),
        files=files,
        notes=coerce_str(data.get("notes")),
    )


def validate_patch_plan(
    plan: PatchPlan | None,
    *,
    app_path: str,
    proposal_record: object,
    approved: bool,
    max_files: int,
    max_lines: int,
    allow_delete: bool = False,
    runtime_prefixes: tuple[str, ...] = (),
    contract: dict[str, Any] | None = None,
) -> ApplicationVerdict:
    """Validate a patch plan against the Phase 5 safety rules.

    Args:
        plan: Parsed patch plan, or ``None`` when none was produced.
        app_path: Active application workbench path (e.g. `apps/<id>`).
        proposal_record: The backing ``coder_proposal.json`` mapping.
        approved: Whether the owner approved applying this proposal.
        max_files: Maximum number of files the plan may touch.
        max_lines: Maximum line count per written file.
        allow_delete: Whether delete operations are permitted. Phase 5
            defaults to ``False`` (create/modify only); deletes require a
            separate, explicit opt-in.

    Returns:
        Validation verdict over all safety rules.
    """
    reasons: list[str] = []
    blocked: list[str] = []
    warnings: list[str] = []

    if not approved:
        reasons.append("Application is not owner-approved for this proposal")
    if plan is None:
        reasons.append("No patch plan was produced")
        return ApplicationVerdict(False, reasons, blocked, warnings)

    if not plan.files:
        reasons.append("Patch plan contains no file operations (empty)")

    expected_id = ""
    if isinstance(proposal_record, dict):
        expected_id = coerce_str(proposal_record.get("proposal_id"))
    if expected_id and plan.proposal_id and plan.proposal_id != expected_id:
        reasons.append(
            f"Patch plan proposal_id {plan.proposal_id!r} does not match the "
            f"approved proposal {expected_id!r}"
        )

    runtime = runtime_prefixes or _default_runtime_prefixes(app_path)
    declared = _declared_proposal_paths(proposal_record)
    blob_parts: list[str] = [plan.notes]
    for patch in plan.files:
        if patch.action not in VALID_ACTIONS:
            reasons.append(
                f"Invalid file action {patch.action!r} for {patch.path}"
            )
        if patch.action == "delete" and not allow_delete:
            reasons.append(
                f"Delete operations are disabled in this phase: {patch.path}"
            )
        # Workbench-relative paths are resolved against the workbench; anything
        # that still lands outside it (or in factory runtime) is blocked.
        if classify_path(patch.path, app_path, runtime) == "blocked":
            blocked.append(patch.path)
        if patch.action in {"create", "modify"} and not patch.content.strip():
            reasons.append(
                f"No content provided for {patch.action}: {patch.path}"
            )
        # Deterministic syntax guardrail: never write Python that does not
        # parse. Catches whole classes of broken generation (e.g. a JS-style
        # `//` comment) before it lands and poisons every later validation.
        if (
            patch.action in {"create", "modify"}
            and patch.path.endswith(".py")
            and patch.content.strip()
        ):
            try:
                compile(patch.content, patch.path or "<patch>", "exec")
            except SyntaxError as exc:
                reasons.append(
                    f"Python syntax error in {patch.path}: {exc.msg} "
                    f"(line {exc.lineno})"
                )
        line_count = len(patch.content.splitlines())
        if line_count > max_lines:
            reasons.append(
                f"{patch.path} has {line_count} lines, over the limit of "
                f"{max_lines}"
            )
        if declared and patch.path and patch.path not in declared:
            warnings.append(
                f"Patch path {patch.path} was not declared in the proposal"
            )
        blob_parts.append(patch.path)
        blob_parts.append(patch.content)

    if blocked:
        reasons.append(
            "Patch plan targets paths outside the project workbench or its "
            "factory-managed runtime: " + ", ".join(blocked)
        )

    secret_hits = sorted(
        {m for m in SECRET_MARKERS if m in " ".join(blob_parts).lower()}
    )
    if secret_hits:
        reasons.append(
            "Patch plan references secret-like material: "
            + ", ".join(secret_hits)
        )

    if len(plan.files) > max_files:
        reasons.append(
            f"Patch plan touches {len(plan.files)} files, over the limit of "
            f"{max_files}"
        )

    # Architecture-contract gate: reject patches that break the canonical tree
    # (forbidden dir/name, outside the allowed tree) or import a forbidden
    # dependency, so incoherent architecture never lands.
    if contract:
        contract_files = [
            (p.path, p.content)
            for p in plan.files
            if p.action in {"create", "modify"}
        ]
        reasons.extend(patch_contract_violations(contract_files, contract))

    return ApplicationVerdict(
        valid=not reasons,
        reasons=reasons,
        blocked_paths=blocked,
        warnings=warnings,
    )


def _declared_proposal_paths(proposal_record: object) -> set[str]:
    """Return the file paths the backing proposal declared, if any.

    Args:
        proposal_record: The backing ``coder_proposal.json`` mapping.

    Returns:
        Set of declared create/modify/delete paths.
    """
    if not isinstance(proposal_record, dict):
        return set()
    declared: set[str] = set()
    for key in ("files_to_create", "files_to_modify", "files_to_delete"):
        declared.update(coerce_str_list(proposal_record.get(key)))
    return declared


def application_status_label(result: ApplicationResult) -> str:
    """Return the reporting label for an application outcome.

    Args:
        result: Application result for the current advance.

    Returns:
        ``"not_approved"``, ``"rejected"``, ``"applied"``, or ``"preview"``.
    """
    if not result.activated:
        return "not_approved"
    if not result.verdict.valid:
        return "rejected"
    return "applied" if result.applied else "preview"


def patch_plan_to_dict(result: ApplicationResult) -> dict[str, Any]:
    """Build the machine-readable ``patch_plan.json`` record.

    Args:
        result: Application result to serialize.

    Returns:
        JSON-serializable patch-plan record.
    """
    plan = result.plan
    return {
        "plan_id": plan.plan_id if plan else None,
        "task_id": plan.task_id if plan else None,
        "proposal_id": plan.proposal_id if plan else None,
        "notes": plan.notes if plan else None,
        "files": [
            {
                "path": patch.path,
                "action": patch.action,
                "line_count": len(patch.content.splitlines()),
            }
            for patch in (plan.files if plan else [])
        ],
        "mode": result.mode,
        "activated": result.activated,
        "applied": result.applied,
        "applied_files": list(result.applied_files),
        "validation": {
            "status": application_status_label(result),
            "source": result.source,
            "reasons": list(result.verdict.reasons),
            "blocked_paths": list(result.verdict.blocked_paths),
            "warnings": list(result.verdict.warnings),
        },
    }


def _bullets(items: list[str]) -> list[str]:
    """Render a list as Markdown bullets, or a placeholder when empty."""
    return [f"- {item}" for item in items] if items else ["_None._"]


def render_patch_plan_md(result: ApplicationResult) -> str:
    """Render a human-readable ``PATCH_PLAN.md`` preview.

    Args:
        result: Application result to render.

    Returns:
        Markdown document describing the patch plan and its verdict.
    """
    plan = result.plan
    status = application_status_label(result)
    lines = [
        "# Patch Plan",
        "",
        "## Status",
        "",
        f"- Source: `{result.source}`",
        f"- Detail: {result.detail}",
        f"- Mode: `{result.mode}`",
        f"- Activated (approved gate): `{str(result.activated).lower()}`",
        f"- Verdict: `{status}`",
        f"- Applied: `{str(result.applied).lower()}`",
        "",
    ]
    if plan is None:
        lines.extend(["## Plan", "", "No patch plan was produced.", ""])
    else:
        lines.extend(
            [
                "## Plan",
                "",
                f"- Plan ID: `{plan.plan_id}`",
                f"- Task ID: `{plan.task_id}`",
                f"- Proposal ID: `{plan.proposal_id}`",
                "",
                "## File Operations",
                "",
            ]
        )
        if plan.files:
            for patch in plan.files:
                lines.append(
                    f"- `{patch.action}` `{patch.path}` "
                    f"({len(patch.content.splitlines())} lines)"
                )
        else:
            lines.append("_None._")
        lines.append("")
    lines.extend(
        [
            "## Validation Verdict",
            "",
            f"- Valid: `{plan is not None and result.verdict.valid}`",
            "",
            "### Reasons",
            "",
        ]
    )
    lines.extend(_bullets(result.verdict.reasons))
    lines.extend(["", "### Warnings", ""])
    lines.extend(_bullets(result.verdict.warnings))
    lines.extend(["", "### Blocked Paths", ""])
    lines.extend(_bullets(result.verdict.blocked_paths))
    lines.append("")
    return "\n".join(lines)


def render_application_report_md(result: ApplicationResult) -> str:
    """Render a human-readable ``APPLICATION_REPORT.md``.

    Args:
        result: Application result to render.

    Returns:
        Markdown application report.
    """
    status = application_status_label(result)
    lines = [
        "# Application Report",
        "",
        f"- Mode: `{result.mode}`",
        f"- Status: `{status}`",
        f"- Activated (approved gate): `{str(result.activated).lower()}`",
        f"- Applied: `{str(result.applied).lower()}`",
        f"- Detail: {result.detail}",
        "",
        "## Applied Files",
        "",
    ]
    lines.extend(_bullets(result.applied_files))
    lines.append("")
    return "\n".join(lines)


def application_paths(
    root: Path, project: dict[str, Any]
) -> tuple[str, str, str, str]:
    """Return the application artifact paths within the task workbench.

    Args:
        root: Absolute repository root.
        project: Active project configuration mapping.

    Returns:
        Repository-relative paths for ``approved_proposal.json`` (owner input),
        ``patch_plan.json``, ``PATCH_PLAN.md``, and ``APPLICATION_REPORT.md``.

    Raises:
        RuntimeError: If the task directory escapes the project workbench.
    """
    project_root = resolve_repo_path(str(project["root"]), root)
    task_root = resolve_repo_path(str(project["task_root"]), root)
    if task_root != project_root and project_root not in task_root.parents:
        raise RuntimeError("Task root must stay inside the project workbench")
    base = Path(str(project["task_root"]))
    return (
        str(base / "approved_proposal.json"),
        str(base / "patch_plan.json"),
        str(base / "PATCH_PLAN.md"),
        str(base / "APPLICATION_REPORT.md"),
    )


def request_patch_plan(
    *,
    app_path: str,
    project: dict[str, Any],
    proposal_record: dict[str, Any],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
    max_lines: int,
    max_files: int,
    mode: str,
    allow_delete: bool = False,
    contract: dict[str, Any] | None = None,
) -> ApplicationResult:
    """Ask the coder model for exact file contents and validate the plan.

    When Ollama is unavailable or the output is malformed, the result is a
    *rejected* plan rather than a trusted one. This function only produces and
    validates the plan; it never writes files.

    Args:
        app_path: Active application workbench path (e.g. `apps/<id>`).
        project: Active project configuration mapping.
        proposal_record: The approved, valid coder proposal record.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        models_config: Parsed ``config/models.yaml`` mapping.
        max_lines: Maximum line count per written file.
        max_files: Maximum number of files the plan may touch.
        mode: Active application mode (``preview_only`` or ``apply``).

    Returns:
        Application result with ``activated=True`` and ``applied=False``.
    """
    prompt_package = build_prompt_package(
        role="coder",
        project_name=str(project.get("name") or app_path),
        project_context_root=str(project["context_root"]),
        max_lines_per_file=max_lines,
    )
    model = str(models_config["models"]["coder"])
    ollama = factory_config["ollama"]
    client = OllamaClient(
        base_url=str(ollama["base_url"]),
        timeout_seconds=int(ollama["timeout_seconds"]),
        stream=bool(ollama["stream"]),
    )
    instruction = (
        "Return ONLY a single JSON object describing exact file changes. Use "
        "keys: plan_id, task_id, proposal_id, files (array of objects with "
        "path, action [create|modify|delete], content), notes. Provide the "
        "full file content for create/modify. Reuse the EXACT paths from the "
        "approved proposal below; they are relative to the project root (e.g. "
        "src/x.py, tests/test_x.py, README.md) — do NOT add an app/ prefix or "
        "any other prefix, and keep imports consistent with those paths. Never "
        "target the factory-managed folders (config/, state/, factory_state/, "
        "factory_reports/, factory_tasks/, factory_context/, context/), .git/, "
        f"or paths outside the project. Touch at most {max_files} files and "
        f"keep each file under {max_lines} lines. Never reference secrets."
    )
    proposal_summary = json.dumps(
        {
            "proposal_id": proposal_record.get("proposal_id"),
            "task_id": proposal_record.get("task_id"),
            "files_to_create": proposal_record.get("files_to_create"),
            "files_to_modify": proposal_record.get("files_to_modify"),
            "files_to_delete": proposal_record.get("files_to_delete"),
            "implementation_steps": proposal_record.get(
                "implementation_steps"
            ),
        },
        indent=2,
    )
    messages = [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": (
                f"{prompt_package.prompt}\n\n"
                f"## Approved Proposal\n\n{proposal_summary}\n"
            ),
        },
    ]
    try:
        response = client.chat(model, messages, response_format="json")
    except OllamaConnectionError as exc:
        reason = f"Ollama unavailable; no validated patch plan produced: {exc}"
        return ApplicationResult(
            None,
            ApplicationVerdict(False, [reason], [], []),
            "fallback",
            reason,
            mode,
            activated=True,
        )
    try:
        content = str(response["message"]["content"]).strip()
        if not content:
            raise ValueError("Ollama returned empty patch plan content")
        plan = parse_patch_plan(content)
    except (KeyError, TypeError, ValueError, PatchPlanParseError) as exc:
        reason = f"Patch plan parse failed: {exc}"
        return ApplicationResult(
            None,
            ApplicationVerdict(False, [reason], [], []),
            "ollama",
            f"Coder model `{model}` (unparseable patch plan)",
            mode,
            activated=True,
        )
    verdict = validate_patch_plan(
        plan,
        app_path=app_path,
        proposal_record=proposal_record,
        approved=True,
        max_files=max_files,
        max_lines=max_lines,
        allow_delete=allow_delete,
        runtime_prefixes=project_runtime_prefixes(project),
        contract=contract,
    )
    return ApplicationResult(
        plan, verdict, "ollama", f"Coder model `{model}`", mode, activated=True
    )


def apply_patch_plan(
    plan: PatchPlan,
    *,
    root: Path,
    project: dict[str, Any],
    allow_delete: bool = False,
) -> tuple[list[str], str | None]:
    """Write (and optionally remove) the plan's files in approved roots.

    Called only after every gate and validation has passed and apply mode is
    explicitly enabled. Each operation is re-checked against the approved write
    roots before touching the filesystem. Deletes are skipped unless
    ``allow_delete`` is set.

    There is intentionally no transactional rollback: if an operation fails
    mid-sequence the already-written files remain, and this function returns
    the files written so far plus an error string so the caller can report the
    *partial* application rather than silently losing track of it.

    Args:
        plan: Validated patch plan.
        root: Absolute repository root.
        project: Active project configuration mapping.
        allow_delete: Whether delete operations may run.

    Returns:
        A tuple of (files written or removed, error message or ``None``).
    """
    # The whole project workbench is the write root; validation has already
    # excluded factory-managed runtime folders inside it. Workbench-relative
    # patch paths are resolved against the workbench before writing.
    app_path = str(project["root"])
    allowed_roots = [app_path]
    runtime = project_runtime_prefixes(project) or _default_runtime_prefixes(
        app_path
    )
    touched: list[str] = []
    for patch in plan.files:
        # Re-check the boundary defensively before touching the filesystem.
        if classify_path(patch.path, app_path, runtime) == "blocked":
            return touched, f"Apply blocked unsafe path: {patch.path}"
        dest = resolve_workbench_path(patch.path, app_path)
        try:
            if patch.action == "delete":
                if not allow_delete:
                    # Deletes are disabled in this phase; validation should
                    # already have rejected the plan, but skip defensively.
                    continue
                target = resolve_repo_path(dest, root)
                if target.is_file():
                    target.unlink()
                touched.append(patch.path)
                continue
            safe_write_text(
                dest,
                patch.content,
                repo_root=root,
                allowed_roots=allowed_roots,
            )
            touched.append(patch.path)
        except (RepoSafetyError, OSError) as exc:
            return touched, f"Apply stopped at {patch.path}: {exc}"
    return touched, None


def run_application_stage(
    *,
    app_path: str,
    root: Path,
    project: dict[str, Any],
    factory_config: dict[str, Any],
    models_config: dict[str, Any],
    max_lines: int,
    max_files: int,
    contract_json_path: str,
    proposal_json_path: str,
) -> tuple[ApplicationResult, str, str, str]:
    """Run the proposal application stage under the full approval gate.

    The stage activates only when the contract is owner-authorized and valid,
    the coder proposal is valid, and the owner approved application. Otherwise
    it is skipped with no model call and no writes. When activated it produces
    a patch plan and report, and applies files only when apply mode is
    explicitly enabled and the plan validates.

    Args:
        app_path: Active application workbench path (e.g. `apps/<id>`).
        root: Absolute repository root.
        project: Active project configuration mapping.
        factory_config: Parsed ``config/factory.yaml`` mapping.
        models_config: Parsed ``config/models.yaml`` mapping.
        max_lines: Maximum line count per written file.
        max_files: Maximum number of files the plan may touch.
        contract_json_path: Repository-relative authorized contract path.
        proposal_json_path: Repository-relative coder proposal path.

    Returns:
        Application result and the patch-plan JSON, patch-plan Markdown, and
        application-report paths.
    """
    approved_path, plan_json_path, plan_md_path, report_md_path = (
        application_paths(root, project)
    )
    pa_config = factory_config.get("proposal_application", {})
    mode = str(pa_config.get("mode", "preview_only"))
    allow_apply = bool(pa_config.get("allow_apply", False))
    allow_delete = bool(pa_config.get("allow_delete", False))
    require_owner_approval = bool(
        pa_config.get("require_owner_approval", True)
    )

    contract_record = load_existing_contract(contract_json_path, root)
    proposal_record = load_existing_contract(proposal_json_path, root)
    approval_record = load_existing_contract(approved_path, root)

    contract_ok = contract_record is not None and is_contract_actionable(
        contract_record
    )
    proposal_ok = is_proposal_valid(proposal_record)
    approved = is_application_approved(approval_record, proposal_record) or (
        not require_owner_approval
    )

    if not (contract_ok and proposal_ok and approved):
        result = ApplicationResult(
            None,
            ApplicationVerdict(
                False,
                ["Application not activated: gate not satisfied"],
                [],
                [],
            ),
            "skipped",
            "Contract/proposal/owner-approval gate not satisfied; "
            "no patch plan generated.",
            mode,
            activated=False,
        )
        return result, plan_json_path, plan_md_path, report_md_path

    assert proposal_record is not None  # narrowed by proposal_ok

    # Preserve an already-applied patch plan for the SAME proposal instead of
    # regenerating it. request_patch_plan asks the model for file CONTENTS,
    # which is nondeterministic — regenerating on every advance would overwrite
    # an applied (possibly green) build with different, possibly broken code.
    # Once applied for this proposal the application is idempotent: keep the
    # plan and do not re-apply. A remediation fix is a NEW proposal id, so it
    # does not match and is regenerated/applied normally.
    existing_plan = load_existing_contract(plan_json_path, root)
    current_pid = coerce_str(proposal_record.get("proposal_id"))
    if (
        isinstance(existing_plan, dict)
        and existing_plan.get("applied") is True
        and current_pid
        and coerce_str(existing_plan.get("proposal_id")) == current_pid
    ):
        preserved_plan = parse_patch_plan(json.dumps(existing_plan))
        applied_files = [
            coerce_str(f) for f in (existing_plan.get("applied_files") or [])
        ]
        return (
            ApplicationResult(
                preserved_plan,
                ApplicationVerdict(True, [], [], []),
                "preserved",
                "Patch plan already applied for this proposal; preserved "
                "(not regenerated) to keep the applied code stable.",
                mode,
                activated=True,
                applied=True,
                applied_files=applied_files,
            ),
            plan_json_path,
            plan_md_path,
            report_md_path,
        )

    result = request_patch_plan(
        app_path=app_path,
        project=project,
        proposal_record=proposal_record,
        factory_config=factory_config,
        models_config=models_config,
        max_lines=max_lines,
        max_files=max_files,
        mode=mode,
        allow_delete=allow_delete,
        contract=load_contract(app_path),
    )

    if (
        mode == "apply"
        and allow_apply
        and result.verdict.valid
        and result.plan is not None
    ):
        applied_files, apply_error = apply_patch_plan(
            result.plan,
            root=root,
            project=project,
            allow_delete=allow_delete,
        )
        detail = (
            f"Partial application: {apply_error}"
            if apply_error
            else "Patch plan applied to the approved write roots."
        )
        result = ApplicationResult(
            result.plan,
            result.verdict,
            result.source,
            detail,
            mode,
            activated=True,
            applied=True,
            applied_files=applied_files,
        )

    task_root = str(project["task_root"])
    safe_write_json(
        plan_json_path,
        patch_plan_to_dict(result),
        repo_root=root,
        allowed_roots=[task_root],
    )
    safe_write_text(
        plan_md_path,
        render_patch_plan_md(result),
        repo_root=root,
        allowed_roots=[task_root],
    )
    safe_write_text(
        report_md_path,
        render_application_report_md(result),
        repo_root=root,
        allowed_roots=[task_root],
    )
    return result, plan_json_path, plan_md_path, report_md_path
