#!/usr/bin/env python3
"""Read-only Codex CLI adapter behind AgentExecutor.

Codex proposes a file map via ``codex exec --sandbox read-only --json``.
Crazy Factory still applies files through ``ALLOWED_TOPS`` confinement.
This adapter never passes ``workspace-write`` or the dangerous bypass
flag, and it refuses to use the factory engine tree as ``-C``.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_executor import (
    _FILE_MAP_PRIMING,
    _FILE_MAP_SYSTEM,
    REPO_ROOT,
    ExecutorRequest,
    ExecutorResult,
    _file_map_user,
    _files_from_payload,
)
from coding_llm import coding_timeout_seconds
from json_parsing import strip_code_fence

CODEX_SANDBOX = "read-only"
FORBIDDEN_CODEX_FLAGS = frozenset(
    {
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
    }
)

RunExec = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class CodexJsonlSummary:
    """Parsed ``codex exec --json`` stdout (no secrets)."""

    last_message: str
    command_exit_codes: tuple[int, ...]


def resolve_codex_bin() -> str | None:
    """Return the Codex CLI path, preferring a user-local install."""
    home_bin = Path.home() / ".local" / "bin" / "codex"
    candidates: list[Path] = []
    which = _which("codex")
    if which:
        candidates.append(Path(which))
    candidates.append(home_bin)
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return str(resolved)
    return None


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def is_factory_engine_root(path: Path) -> bool:
    """True when ``path`` is the Crazy Factory engine checkout."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if resolved == REPO_ROOT.resolve():
        return True
    return (resolved / "scripts" / "agent_executor.py").is_file() and (
        resolved / "factory"
    ).is_dir()


def select_codex_work_root(app_path: str) -> Path | None:
    """Pick a read-only ``-C`` directory that is not the engine tree."""
    raw = (app_path or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        path = path.resolve()
    except OSError:
        return None
    if path.is_dir() and not is_factory_engine_root(path):
        return path
    return None


def build_codex_exec_argv(
    binary: str,
    *,
    work_root: Path,
    last_message_path: Path,
    prompt: str,
) -> list[str]:
    """Build the only argv this adapter is allowed to spawn."""
    if is_factory_engine_root(work_root):
        raise ValueError("refusing to point Codex at the factory engine")
    argv = [
        binary,
        "exec",
        "--sandbox",
        CODEX_SANDBOX,
        "--skip-git-repo-check",
        "--ephemeral",
        "--color",
        "never",
        "--json",
        "--ignore-user-config",
        "-C",
        str(work_root),
        "-o",
        str(last_message_path),
        prompt,
    ]
    if any(flag in argv for flag in FORBIDDEN_CODEX_FLAGS):
        raise ValueError("refusing forbidden Codex flag")
    sandbox_at = argv.index("--sandbox")
    if argv[sandbox_at + 1] != CODEX_SANDBOX:
        raise ValueError("Codex adapter is read-only")
    return argv


def parse_codex_jsonl(stdout: str) -> CodexJsonlSummary:
    """Extract last agent message and inner command exits from JSONL."""
    last_message = ""
    exits: list[int] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        if kind == "agent_message":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                last_message = text
        if kind == "command_execution":
            code = item.get("exit_code")
            if isinstance(code, int):
                exits.append(code)
    return CodexJsonlSummary(
        last_message=last_message,
        command_exit_codes=tuple(exits),
    )


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from a Codex last message."""
    stripped = strip_code_fence(text or "")
    if not stripped:
        return None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def codex_is_logged_in(
    binary: str,
    *,
    run: RunExec | None = None,
) -> bool:
    """True when ``codex login status`` exits 0."""
    runner = run or subprocess.run
    try:
        completed = runner(
            [binary, "login", "status"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _codex_prompt(request: ExecutorRequest) -> str:
    return (
        f"{_FILE_MAP_PRIMING}\n\n{_FILE_MAP_SYSTEM}\n\n"
        "The sandbox is read-only: do not write the tree. Your JSON "
        '"files" map IS the implementation the factory will apply. '
        "An empty files object is a failure. Do not claim the work is "
        "accepted.\n\n"
        f"{_file_map_user(request)}"
    )


class CodexCodingExecutor:
    """ChatGPT-authenticated Codex CLI file-map plugin (read-only exec)."""

    name = "codex"

    def __init__(
        self,
        *,
        binary: str | None = None,
        logged_in: bool | None = None,
        run_exec: RunExec | None = None,
    ) -> None:
        self.binary = binary
        self.logged_in = logged_in
        self.run_exec = run_exec

    def can_implement(self) -> bool:
        binary = self.binary
        if binary is None:
            binary = resolve_codex_bin()
        if not binary:
            return False
        if self.logged_in is not None:
            return bool(self.logged_in)
        return codex_is_logged_in(binary)

    def execute(self, request: ExecutorRequest) -> ExecutorResult:
        binary = self.binary
        if binary is None:
            binary = resolve_codex_bin()
        if not binary:
            return ExecutorResult(
                ok=False,
                provider=self.name,
                summary="codex CLI not installed",
                reason="codex_not_installed",
            )
        authed = (
            self.logged_in
            if self.logged_in is not None
            else codex_is_logged_in(binary)
        )
        if not authed:
            return ExecutorResult(
                ok=False,
                provider=self.name,
                summary="codex is not authenticated",
                reason="codex_not_authenticated",
            )
        owned_root: tempfile.TemporaryDirectory[str] | None = None
        work_root = select_codex_work_root(request.app_path)
        if work_root is None:
            owned_root = tempfile.TemporaryDirectory(prefix="cf-codex-ro-")
            work_root = Path(owned_root.name)
        try:
            return self._exec_into(binary, request, work_root)
        finally:
            if owned_root is not None:
                owned_root.cleanup()

    def _exec_into(
        self,
        binary: str,
        request: ExecutorRequest,
        work_root: Path,
    ) -> ExecutorResult:
        with tempfile.TemporaryDirectory(prefix="cf-codex-out-") as tmp:
            last_path = Path(tmp) / "last_message.txt"
            try:
                argv = build_codex_exec_argv(
                    binary,
                    work_root=work_root,
                    last_message_path=last_path,
                    prompt=_codex_prompt(request),
                )
            except ValueError as exc:
                return ExecutorResult(
                    ok=False,
                    provider=self.name,
                    summary="codex argv rejected",
                    reason=str(exc),
                )
            runner = self.run_exec or subprocess.run
            try:
                completed = runner(
                    argv,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=coding_timeout_seconds(),
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return ExecutorResult(
                    ok=False,
                    provider=self.name,
                    summary="codex exec timed out",
                    reason="codex_timeout",
                )
            except OSError as exc:
                return ExecutorResult(
                    ok=False,
                    provider=self.name,
                    summary="codex exec failed to start",
                    reason=str(exc),
                )
            from_file = ""
            if last_path.is_file():
                try:
                    from_file = last_path.read_text(encoding="utf-8")
                except OSError:
                    from_file = ""
            parsed = parse_codex_jsonl(completed.stdout or "")
            last_message = from_file.strip() or parsed.last_message
            data = extract_json_object(last_message)
            files = _files_from_payload(data) if data else {}
            if files:
                inner = ",".join(
                    str(code) for code in parsed.command_exit_codes
                )
                return ExecutorResult(
                    ok=True,
                    provider=self.name,
                    summary=(
                        f"codex proposed {len(files)} file(s) "
                        f"(session_exit={completed.returncode}"
                        f"{'; cmds=' + inner if inner else ''})"
                    ),
                    files=files,
                )
            reason = "codex_no_allowed_files"
            if completed.returncode != 0:
                reason = f"codex_session_exit_{completed.returncode}"
            preview = " ".join((last_message or "").split())[:120]
            summary = "codex returned no allowed files"
            if preview:
                summary = f"{summary}: {preview}"
            return ExecutorResult(
                ok=False,
                provider=self.name,
                summary=summary,
                reason=reason,
            )
