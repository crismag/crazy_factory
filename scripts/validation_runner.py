#!/usr/bin/env python3
"""Phase 6 validation runner for Crazy Factory.

The validation runner executes a test plan's checks, but only commands that
match a strict allowlist, only with shell features disabled, and only when the
owner has enabled execution. Anything outside the allowlist is *blocked* (never
executed); execution is gated by ``validation.allow_run`` and is off by
default. The result feeds future checkpoint promotion: failed or blocked
checks must prevent a checkpoint.

No command is ever run through a shell. Each check is tokenized, screened for
shell metacharacters and forbidden tokens, matched against an allowlist of
command prefixes, then run with ``shell=False`` and a timeout.
"""

from __future__ import annotations

import shlex
import subprocess  # noqa: S404 - usage is allowlisted and shell-free
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repo_tools import resolve_repo_path, safe_write_json, safe_write_text

# Allowlisted command prefixes. A check is permitted only when its tokenized
# argv begins with one of these exact sequences.
ALLOWED_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python3", "--version"),
    ("python3", "-m", "pytest"),
    ("python3", "-m", "ruff"),
    ("python3", "-m", "mypy"),
    ("python3", "-m", "unittest"),
    ("pytest",),
    ("ruff", "check"),
    ("ruff", "format"),
    ("mypy",),
    ("php", "-v"),
    ("composer", "test"),
    ("phpunit",),
)

# Tokens that are never allowed anywhere in a check, for clear messaging.
FORBIDDEN_TOKENS: frozenset[str] = frozenset(
    {"sudo", "rm", "git", "curl", "wget", "bash", "sh", "-rf", "--force"}
)

# Shell metacharacters that disqualify a check outright.
SHELL_METACHARACTERS: str = "|&;<>`$(){}*?!\\"


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one validation check.

    Attributes:
        command: The original command string.
        status: ``"passed"``, ``"failed"``, ``"blocked"``, ``"skipped"``, or
            ``"error"``.
        returncode: Process exit code, or ``None`` when not executed.
        detail: Human-readable explanation.
    """

    command: str
    status: str
    returncode: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class ValidationResult:
    """Aggregate outcome of running a test plan's checks.

    Attributes:
        test_plan_id: Identifier of the test plan validated.
        checks: Per-check results.
        status: Overall status across all checks.
        executed: Whether any command was actually run.
    """

    test_plan_id: str
    checks: list[CheckResult] = field(default_factory=list)
    status: str = "skipped"
    executed: bool = False


def is_command_allowed(command: str) -> bool:
    """Report whether one check command may be executed.

    A command is allowed only when it tokenizes cleanly, contains no shell
    metacharacters or forbidden tokens, and its argv begins with an allowlisted
    prefix.

    Args:
        command: The check command string.

    Returns:
        ``True`` only when the command is safe and allowlisted.
    """
    if not command or any(ch in command for ch in SHELL_METACHARACTERS):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if not argv:
        return False
    if any(token in FORBIDDEN_TOKENS for token in argv):
        return False
    return any(
        argv[: len(prefix)] == list(prefix) for prefix in ALLOWED_COMMANDS
    )


def _run_one_check(
    command: str, *, root: Path, timeout_seconds: int
) -> CheckResult:
    """Execute one allowlisted check with the shell disabled.

    Args:
        command: An already-allowlisted command string.
        root: Working directory for the check.
        timeout_seconds: Maximum seconds to wait.

    Returns:
        The check result.
    """
    argv = shlex.split(command)
    try:
        completed = subprocess.run(  # noqa: S603 - argv allowlisted, no shell
            argv,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            command, "failed", None, f"Timed out after {timeout_seconds}s"
        )
    except (FileNotFoundError, OSError) as exc:
        return CheckResult(command, "error", None, f"Could not run: {exc}")
    status = "passed" if completed.returncode == 0 else "failed"
    detail = f"exit code {completed.returncode}"
    if completed.returncode != 0:
        # Surface the tail of the command output so a failed check is
        # diagnosable from the report. stderr is preferred; stdout is a
        # fallback. The snippet is bounded and single-lined.
        raw = (completed.stderr or completed.stdout or "").strip()
        snippet = " ".join(raw.split())[-400:]
        if snippet:
            detail = f"{detail} | {snippet}"
    return CheckResult(command, status, completed.returncode, detail)


def run_checks(
    commands: list[str],
    *,
    root: Path,
    allow_run: bool,
    timeout_seconds: int,
) -> list[CheckResult]:
    """Screen and (optionally) execute a list of check commands.

    Non-allowlisted commands are blocked and never executed. Allowlisted
    commands are executed only when ``allow_run`` is enabled; otherwise they
    are recorded as skipped.

    Args:
        commands: Check command strings from the test plan.
        root: Working directory for execution.
        allow_run: Whether execution is enabled by owner policy.
        timeout_seconds: Per-check timeout.

    Returns:
        Per-check results.
    """
    results: list[CheckResult] = []
    for command in commands:
        if not is_command_allowed(command):
            results.append(
                CheckResult(
                    command, "blocked", None, "Command is not allowlisted"
                )
            )
            continue
        if not allow_run:
            results.append(
                CheckResult(
                    command,
                    "skipped",
                    None,
                    "Execution disabled (validation.allow_run is false)",
                )
            )
            continue
        results.append(
            _run_one_check(command, root=root, timeout_seconds=timeout_seconds)
        )
    return results


def summarize_status(checks: list[CheckResult]) -> str:
    """Aggregate per-check results into an overall status.

    Blocked checks dominate (the plan cannot be trusted), then failures/errors,
    then passes; an all-skipped or empty set is ``"skipped"``.

    Args:
        checks: Per-check results.

    Returns:
        Overall status string.
    """
    statuses = {check.status for check in checks}
    if "blocked" in statuses:
        return "blocked"
    if "failed" in statuses or "error" in statuses:
        return "failed"
    if "passed" in statuses:
        return "passed"
    return "skipped"


def validation_to_dict(result: ValidationResult) -> dict[str, Any]:
    """Build the machine-readable ``validation_result.json`` record.

    Args:
        result: Validation result to serialize.

    Returns:
        JSON-serializable validation record.
    """
    return {
        "test_plan_id": result.test_plan_id,
        "status": result.status,
        "executed": result.executed,
        "checks": [
            {
                "command": check.command,
                "status": check.status,
                "returncode": check.returncode,
                "detail": check.detail,
            }
            for check in result.checks
        ],
    }


def render_validation_md(result: ValidationResult) -> str:
    """Render a human-readable ``VALIDATION_REPORT.md``.

    Args:
        result: Validation result to render.

    Returns:
        Markdown validation report.
    """
    lines = [
        "# Validation Report",
        "",
        f"- Test plan: `{result.test_plan_id}`",
        f"- Overall status: `{result.status}`",
        f"- Executed: `{str(result.executed).lower()}`",
        "",
        "## Checks",
        "",
    ]
    if result.checks:
        for check in result.checks:
            lines.append(
                f"- `{check.status}` `{check.command}` — {check.detail}"
            )
    else:
        lines.append("_No checks defined._")
    lines.append("")
    return "\n".join(lines)


def run_validation(
    *,
    test_plan_id: str,
    required_checks: list[str],
    root: Path,
    allow_run: bool,
    timeout_seconds: int,
) -> ValidationResult:
    """Run a validated test plan's required checks and aggregate results.

    Args:
        test_plan_id: Identifier of the test plan being validated.
        required_checks: Allowlist-screened check commands to run.
        root: Working directory for execution.
        allow_run: Whether execution is enabled by owner policy.
        timeout_seconds: Per-check timeout.

    Returns:
        Aggregate validation result.
    """
    checks = run_checks(
        required_checks,
        root=root,
        allow_run=allow_run,
        timeout_seconds=timeout_seconds,
    )
    executed = any(
        check.status in {"passed", "failed", "error"} for check in checks
    )
    return ValidationResult(
        test_plan_id=test_plan_id,
        checks=checks,
        status=summarize_status(checks),
        executed=executed,
    )


def validation_status_label(result: ValidationResult) -> str:
    """Return the reporting label for a validation outcome.

    Args:
        result: Validation result for the current advance.

    Returns:
        The overall validation status string.
    """
    return result.status


def validation_paths(root: Path, project: dict[str, Any]) -> tuple[str, str]:
    """Return the two fixed validation files writable in Phase 6.

    Args:
        root: Absolute repository root.
        project: Active project configuration mapping.

    Returns:
        Repository-relative ``validation_result.json`` and
        ``VALIDATION_REPORT.md`` paths.

    Raises:
        RuntimeError: If the task directory escapes the project workbench.
    """
    project_root = resolve_repo_path(str(project["root"]), root)
    task_root = resolve_repo_path(str(project["task_root"]), root)
    if task_root != project_root and project_root not in task_root.parents:
        raise RuntimeError("Task root must stay inside the project workbench")
    base = Path(str(project["task_root"]))
    return (
        str(base / "validation_result.json"),
        str(base / "VALIDATION_REPORT.md"),
    )


def run_validation_stage(
    *,
    test_plan_id: str,
    required_checks: list[str],
    plan_valid: bool,
    root: Path,
    project: dict[str, Any],
    allow_run: bool,
    timeout_seconds: int,
) -> tuple[ValidationResult, str, str]:
    """Run validation only for a valid test plan and persist the result.

    When there is no valid test plan, validation is skipped with no execution
    and no artifacts. Otherwise the plan's allowlist-screened checks run (only
    if execution is enabled) and the result is written to the two fixed
    validation files. Primitive inputs avoid an import cycle with the Test
    Builder.

    Args:
        test_plan_id: Identifier of the test plan being validated.
        required_checks: Check commands declared by the test plan.
        plan_valid: Whether the backing test plan validated.
        root: Absolute repository root.
        project: Active project configuration mapping.
        allow_run: Whether execution is enabled by owner policy.
        timeout_seconds: Per-check timeout.

    Returns:
        Validation result and the validation JSON and Markdown paths.
    """
    task_root = str(project["task_root"])
    json_path, md_path = validation_paths(root, project)

    if not plan_valid:
        result = ValidationResult(test_plan_id="", checks=[], status="skipped")
        return result, json_path, md_path

    result = run_validation(
        test_plan_id=test_plan_id,
        required_checks=required_checks,
        root=root,
        allow_run=allow_run,
        timeout_seconds=timeout_seconds,
    )
    safe_write_json(
        json_path,
        validation_to_dict(result),
        repo_root=root,
        allowed_roots=[task_root],
    )
    safe_write_text(
        md_path,
        render_validation_md(result),
        repo_root=root,
        allowed_roots=[task_root],
    )
    return result, json_path, md_path
