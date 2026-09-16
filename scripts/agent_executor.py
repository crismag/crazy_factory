#!/usr/bin/env python3
"""P4 AgentExecutor — objective in, workbench files out.

Crazy Factory owns mission, observation, evaluation, and safety.
This module is the implementation actuator:

    objective + curated assignment + evidence
      → files → existing apply/observe/evaluate

The factory compiles the assignment
(``execution_assignment.compile_assignment``). Coding plugins do not
own understanding or judgment.

Productization is Lovable-like: a bounded prompt becomes a working
app. Coding intelligence is a plugin, not a local-model-first path.

Default chain:

1. ``CloudCodingExecutor`` — Claude (Anthropic) or OpenAI file map.
   Skips immediately when no API key is set (no network).
2. ``StdlibWebExecutor`` — capable bounded actuator for the first
   proof seed (stdlib task-board). Copies a verified implementation
   into the workbench. This is not a multi-agent org.

``LlmFileExecutor`` (Ollama) is opt-in via
``CRAZY_FACTORY_EXECUTOR=ollama``. None of the backends write engine
source, push, merge, or delete.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from coding_llm import resolve_coding_backend
from execution_assignment import compile_assignment, render_assignment
from llm_interaction import structured_call
from ollama_client import OllamaClient
from repo_tools import RepoSafetyError, safe_write_text

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTUATOR_DIR = REPO_ROOT / "examples" / "actuators" / "stdlib_task_board"

ALLOWED_TOPS = frozenset(
    {
        "src",
        "tests",
        "data",
        "docs",
        "README.md",
        "architecture.json",
        "requirements.txt",
    }
)
BLOCKED_PARTS = frozenset(
    {
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
    }
)


@dataclass(frozen=True)
class ExecutorRequest:
    """Everything the actuator may use. No extra capabilities."""

    objective_id: str
    objective_kind: str
    objective_title: str
    gap: str
    why: str
    focus: str
    seed_text: str
    validation_failure: str = ""
    runtime_failure: str = ""
    app_path: str = ""
    assignment_text: str = ""
    stance: str = ""


@dataclass
class ExecutorResult:
    """Files to write, relative to the workbench root."""

    ok: bool
    provider: str
    summary: str
    files: dict[str, str] = field(default_factory=dict)
    reason: str = ""


class AgentExecutor(Protocol):
    """Provider-neutral coding-agent adapter."""

    name: str

    def execute(self, request: ExecutorRequest) -> ExecutorResult:
        """Return workbench files or a skipped/failed result."""
        ...


def _seed_text(project: dict[str, Any], root: Path) -> str:
    app = Path(str(project["app_path"]))
    if not app.is_absolute():
        app = root / app
    seed = app / str(project.get("seed_file") or "docs/seed.md")
    try:
        return seed.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _json_reason(task_root: Path, name: str) -> str:
    path = task_root / name
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(raw, dict):
        return ""
    if raw.get("ok") is False or raw.get("status") in {
        "failed",
        "blocked",
        "error",
        "missing",
    }:
        return str(raw.get("reason") or raw.get("status") or "")
    return ""


def build_request(
    project: dict[str, Any],
    root: Path,
    *,
    objective: Any,
    packet: Any = None,
) -> ExecutorRequest:
    """Pack a purpose-built assignment plus failure evidence."""
    assignment = compile_assignment(
        project, root, objective, packet=packet
    )
    task = project.get("task_root") or "factory_tasks"
    task_root = Path(str(task))
    if not task_root.is_absolute():
        task_root = root / task_root
    validation = assignment.validation_summary or _json_reason(
        task_root, "validation_result.json"
    )
    runtime = assignment.runtime_summary or _json_reason(
        task_root, "runtime_result.json"
    )
    return ExecutorRequest(
        objective_id=assignment.objective_id,
        objective_kind=assignment.kind,
        objective_title=assignment.title,
        gap=assignment.gap,
        why=assignment.why,
        focus=assignment.focus,
        seed_text=assignment.seed_excerpt or _seed_text(project, root),
        validation_failure=validation,
        runtime_failure=runtime,
        app_path=str(project.get("app_path") or ""),
        assignment_text=render_assignment(assignment),
        stance=assignment.stance,
    )


def _rel_ok(rel: str) -> bool:
    path = Path(rel)
    parts = [p for p in path.parts if p not in (".", "/")]
    if not parts or path.is_absolute() or ".." in parts:
        return False
    if any(part in BLOCKED_PARTS for part in parts):
        return False
    return parts[0] in ALLOWED_TOPS


def _files_from_payload(data: dict[str, Any]) -> dict[str, str]:
    raw = data.get("files")
    if not isinstance(raw, dict):
        return {}
    return {
        str(path): str(body)
        for path, body in raw.items()
        if isinstance(path, str) and isinstance(body, str) and _rel_ok(path)
    }


_FILE_MAP_SYSTEM = (
    "You are the coding executor for Crazy Factory. The factory owns "
    "mission, judgment, and verification. Implement the assignment. "
    "Return JSON only. Do not claim the work is accepted."
)
_FILE_MAP_PRIMING = (
    'Respond with JSON {"files": {"relative/path": "content"}}. '
    "Only src/, tests/, data/, docs/, README.md, architecture.json, "
    "and requirements.txt. Never write scripts/, factory/, config/, "
    "or .git/."
)


def _file_map_user(request: ExecutorRequest) -> str:
    if request.assignment_text.strip():
        return request.assignment_text
    return (
        f"Objective: {request.objective_title} "
        f"({request.objective_kind})\n"
        f"Gap: {request.gap}\n"
        f"Why: {request.why}\n"
        f"Focus: {request.focus}\n"
        f"Runtime failure: {request.runtime_failure or 'none'}\n"
        f"Validation failure: {request.validation_failure or 'none'}\n"
        f"Seed:\n{request.seed_text[:4000]}\n"
    )


def apply_executor_result(
    result: ExecutorResult,
    project: dict[str, Any],
    root: Path,
) -> tuple[list[str], str | None]:
    """Write executor files into the workbench under path confinement."""
    if not result.ok or not result.files:
        return [], result.reason or "executor produced no files"
    app = Path(str(project["app_path"]))
    if not app.is_absolute():
        app = root / app
    allowed = [str(project["app_path"])]
    written: list[str] = []
    for rel, content in result.files.items():
        if not _rel_ok(rel):
            return written, f"blocked path: {rel}"
        dest = app / rel
        try:
            dest_arg = dest.relative_to(root).as_posix()
        except ValueError:
            dest_arg = str(dest)
        try:
            safe_write_text(
                dest_arg,
                content,
                repo_root=root,
                allowed_roots=allowed,
            )
        except (RepoSafetyError, OSError, ValueError) as exc:
            return written, f"apply stopped at {rel}: {exc}"
        written.append(rel)
    return written, None


class CloudCodingExecutor:
    """Claude / OpenAI file-map plugin. Skips when no API key is set."""

    name = "cloud_coding"

    def __init__(self, provider: str | None = None) -> None:
        self.prefer = provider

    def execute(self, request: ExecutorRequest) -> ExecutorResult:
        pack = resolve_coding_backend(prefer=self.prefer)
        if pack is None:
            return ExecutorResult(
                ok=False,
                provider=self.name,
                summary="no coding API key",
                reason="no_coding_api_key",
            )
        provider, client, model = pack
        data, note = structured_call(
            client=client,
            model=model,
            system=_FILE_MAP_SYSTEM,
            user=_file_map_user(request),
            priming=_FILE_MAP_PRIMING,
            required_keys=("files",),
            retries=0,
        )
        if not data:
            return ExecutorResult(
                ok=False,
                provider=provider,
                summary="cloud coding file map unavailable",
                reason=note,
            )
        files = _files_from_payload(data)
        if not files:
            return ExecutorResult(
                ok=False,
                provider=provider,
                summary="cloud coding returned no allowed files",
                reason=note,
            )
        return ExecutorResult(
            ok=True,
            provider=provider,
            summary=f"{provider} proposed {len(files)} file(s)",
            files=files,
        )


class LlmFileExecutor:
    """One-shot Ollama file-map backend. Opt-in; skips when down."""

    name = "ollama_files"

    def execute(self, request: ExecutorRequest) -> ExecutorResult:
        model = (
            os.environ.get("CRAZY_FACTORY_CODER_MODEL") or "qwen2.5-coder:14b"
        )
        client = OllamaClient(timeout_seconds=3)
        data, note = structured_call(
            client=client,
            model=model,
            system=_FILE_MAP_SYSTEM,
            user=_file_map_user(request),
            priming=_FILE_MAP_PRIMING,
            required_keys=("files",),
            retries=0,
        )
        if not data:
            return ExecutorResult(
                ok=False,
                provider=self.name,
                summary="ollama file map unavailable",
                reason=note,
            )
        files = _files_from_payload(data)
        if not files:
            return ExecutorResult(
                ok=False,
                provider=self.name,
                summary="ollama returned empty files",
                reason=note,
            )
        return ExecutorResult(
            ok=True,
            provider=self.name,
            summary=f"ollama proposed {len(files)} file(s)",
            files=files,
        )


def seed_looks_like_stdlib_task_board(seed: str) -> bool:
    """True when the seed is the bounded stdlib task-board proof."""
    text = seed.lower()
    if "http.server" not in text:
        return False
    if "tasks.json" not in text:
        return False
    return "task" in text and "python" in text


class StdlibWebExecutor:
    """Capable actuator for the stdlib task-board benchmark seed."""

    name = "stdlib_web"

    def execute(self, request: ExecutorRequest) -> ExecutorResult:
        if not seed_looks_like_stdlib_task_board(request.seed_text):
            return ExecutorResult(
                ok=False,
                provider=self.name,
                summary="seed is not the stdlib task-board proof",
                reason="seed mismatch",
            )
        if not ACTUATOR_DIR.is_dir():
            return ExecutorResult(
                ok=False,
                provider=self.name,
                summary="actuator package missing",
                reason=str(ACTUATOR_DIR),
            )
        skip_parts = {
            ".git",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
        }
        files: dict[str, str] = {}
        for path in sorted(ACTUATOR_DIR.rglob("*")):
            if not path.is_file():
                continue
            if any(part in skip_parts for part in path.parts):
                continue
            if path.suffix in {".pyc", ".pyo"}:
                continue
            rel = path.relative_to(ACTUATOR_DIR).as_posix()
            if not _rel_ok(rel):
                continue
            try:
                files[rel] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                return ExecutorResult(
                    ok=False,
                    provider=self.name,
                    summary=f"could not read {rel}",
                    reason=str(exc),
                )
        if "src/task_board.py" not in files:
            return ExecutorResult(
                ok=False,
                provider=self.name,
                summary="actuator package incomplete",
                reason="missing src/task_board.py",
            )
        return ExecutorResult(
            ok=True,
            provider=self.name,
            summary="stdlib task-board actuator",
            files=files,
        )


class ChainedExecutor:
    """Try backends in order; first ok result wins."""

    name = "chain"

    def __init__(self, backends: list[AgentExecutor]) -> None:
        self.backends = backends

    def execute(self, request: ExecutorRequest) -> ExecutorResult:
        last = ExecutorResult(
            ok=False,
            provider=self.name,
            summary="no executor produced files",
            reason="empty chain",
        )
        for backend in self.backends:
            last = backend.execute(request)
            if last.ok and last.files:
                return last
        return last


def default_executor() -> AgentExecutor:
    """Cloud coding plugin first; stdlib web closes the proof seed.

    Ollama is not the starting coding model. Force it with
    ``CRAZY_FACTORY_EXECUTOR=ollama``. Force a vendor with
    ``openai`` / ``anthropic``. Force the deterministic proof
    actuator with ``stdlib_web``.
    """
    forced = (os.environ.get("CRAZY_FACTORY_EXECUTOR") or "").strip().lower()
    if forced == "stdlib_web":
        return StdlibWebExecutor()
    if forced == "ollama":
        return LlmFileExecutor()
    if forced in {"openai", "anthropic", "claude", "cloud"}:
        prefer = None if forced == "cloud" else forced
        return CloudCodingExecutor(provider=prefer)
    return ChainedExecutor(
        [CloudCodingExecutor(), StdlibWebExecutor()]
    )
