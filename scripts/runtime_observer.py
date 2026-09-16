#!/usr/bin/env python3
"""P1 workbench runtime observer.

Discovers a start command from the workbench, verifies it is confined to
that workbench, runs it briefly, and records whether the process started
(and optionally answered HTTP on a declared listen port).

This is not a generic shell. ``python3 -c``, arbitrary pip, npm, curl,
and anything outside the workbench are refused.
"""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess  # noqa: S404 - argv confined, no shell
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

FORBIDDEN_TOKENS: frozenset[str] = frozenset(
    {
        "sudo",
        "rm",
        "git",
        "curl",
        "wget",
        "bash",
        "sh",
        "npm",
        "npx",
        "node",
        "pip",
        "-c",
        "-rf",
        "--force",
    }
)

_START_RE = re.compile(r"`(python3?\s+-m\s+[A-Za-z_][\w.]*)`")

PROBE_SECONDS = 0.9
KILL_SECONDS = 1.0


@dataclass
class RuntimeReport:
    """Outcome of one runtime observation."""

    required: bool
    ok: bool
    safe: bool
    status: str
    reason: str
    command: list[str]
    listen_port: int | None = None
    http_status: int | None = None

    @property
    def attempted(self) -> bool:
        return self.required and self.safe


def _as_argv(value: object) -> list[str] | None:
    if isinstance(value, str) and value.strip():
        return value.split()
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        parts = [x for x in value if x]
        return parts or None
    return None


def discover_start(
    app: Path,
) -> tuple[list[str] | None, int | None]:
    """Return ``(argv, listen_port)`` from architecture.json or README."""
    port: int | None = None
    contract_path = app / "architecture.json"
    if contract_path.is_file():
        try:
            data = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            argv = _as_argv(data.get("start_command"))
            raw_port = data.get("listen_port")
            if isinstance(raw_port, int) and 1 <= raw_port <= 65535:
                port = raw_port
            if argv:
                return argv, port
    readme = app / "README.md"
    if readme.is_file():
        try:
            text = readme.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        match = _START_RE.search(text)
        if match:
            return match.group(1).split(), port
    return None, port


def _module_file(app: Path, module: str) -> Path | None:
    if not module or module.startswith(".") or ".." in module:
        return None
    rel = Path(*module.split("."))
    for candidate in (app / rel.with_suffix(".py"), app / rel / "__init__.py"):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file() and app.resolve() in resolved.parents:
            return resolved
    return None


def _script_file(app: Path, script: str) -> Path | None:
    path = Path(script)
    target = path if path.is_absolute() else (app / path)
    try:
        resolved = target.resolve()
    except OSError:
        return None
    if not resolved.is_file() or resolved.suffix != ".py":
        return None
    if app.resolve() not in resolved.parents and resolved != app.resolve():
        return None
    return resolved


def confine_start(argv: list[str], app: Path) -> tuple[str, str]:
    """Classify a start command.

    Returns ``("ok", "")`` when the process may be launched,
    ``("missing", reason)`` when the command is well-formed but the
    target is not in the workbench yet, or ``("unsafe", reason)`` when
    the command must not be executed.
    """
    if not argv:
        return "unsafe", "empty start command"
    if any(tok in FORBIDDEN_TOKENS for tok in argv):
        return "unsafe", "start command contains a forbidden token"
    if argv[0] not in {"python3", "python"}:
        return "unsafe", "start command must begin with python3"
    if len(argv) >= 3 and argv[1] == "-m":
        if argv[2] in {"pip", "http.server", "ensurepip"}:
            return "unsafe", f"python3 -m {argv[2]} is not a workbench start"
        if _module_file(app, argv[2]) is None:
            return "missing", f"module {argv[2]} is not in the workbench"
        return "ok", ""
    if len(argv) >= 2:
        if _script_file(app, argv[1]) is None:
            path = Path(argv[1])
            if path.is_absolute():
                return "unsafe", "script path is not a workbench Python file"
            return "missing", "script path is not a workbench Python file"
        return "ok", ""
    return "unsafe", "start command is not a workbench python module or script"


def _probe_http(port: int, timeout: float = 0.5) -> int | None:
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return int(resp.status)
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        return None


def _close_pipes(proc: subprocess.Popen[str]) -> None:
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


def _kill(proc: subprocess.Popen[str]) -> None:
    try:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.terminate()
            try:
                proc.wait(timeout=KILL_SECONDS)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    proc.kill()
    finally:
        _close_pipes(proc)


def observe_runtime(app: Path) -> RuntimeReport:
    """Observe whether the workbench application can be started."""
    argv, port = discover_start(app)
    if not argv:
        return RuntimeReport(
            required=False,
            ok=True,
            safe=True,
            status="unspecified",
            reason="no start command declared",
            command=[],
            listen_port=port,
        )
    verdict, refusal = confine_start(argv, app)
    if verdict == "unsafe":
        return RuntimeReport(
            required=True,
            ok=False,
            safe=False,
            status="unsafe",
            reason=refusal,
            command=argv,
            listen_port=port,
        )
    if verdict == "missing":
        return RuntimeReport(
            required=True,
            ok=False,
            safe=True,
            status="missing",
            reason=refusal,
            command=argv,
            listen_port=port,
        )
    try:
        proc = subprocess.Popen(  # noqa: S603 - confined argv, no shell
            argv,
            cwd=str(app),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError) as exc:
        return RuntimeReport(
            required=True,
            ok=False,
            safe=True,
            status="error",
            reason=f"could not start: {exc}",
            command=argv,
            listen_port=port,
        )
    time.sleep(0.2)
    deadline = time.monotonic() + PROBE_SECONDS
    http_status: int | None = None
    code = proc.poll()
    while code is None and time.monotonic() < deadline:
        if port is not None:
            http_status = _probe_http(port)
            if http_status is not None:
                break
        time.sleep(0.15)
        code = proc.poll()
    if code is None:
        if port is not None and http_status is None:
            http_status = _probe_http(port)
        _kill(proc)
        if port is not None and http_status is None:
            return RuntimeReport(
                required=True,
                ok=False,
                safe=True,
                status="no_http",
                reason=f"process started but port {port} did not answer",
                command=argv,
                listen_port=port,
            )
        return RuntimeReport(
            required=True,
            ok=True,
            safe=True,
            status="running",
            reason="process stayed up for the probe window",
            command=argv,
            listen_port=port,
            http_status=http_status,
        )
    if code == 0:
        _close_pipes(proc)
        return RuntimeReport(
            required=True,
            ok=True,
            safe=True,
            status="exited",
            reason="process exited 0 (CLI-style start)",
            command=argv,
            listen_port=port,
        )
    err = ""
    try:
        err = (proc.stderr.read() if proc.stderr else "")[-200:]
    except OSError:
        err = ""
    detail = f"process exited {code}"
    if err:
        detail = f"{detail}: {err.strip()}"
    _close_pipes(proc)
    return RuntimeReport(
        required=True,
        ok=False,
        safe=True,
        status="failed",
        reason=detail,
        command=argv,
        listen_port=port,
    )


def persist_runtime(report: RuntimeReport, task_root: Path) -> Path:
    """Write runtime and preview evidence under the workbench task root."""
    task_root.mkdir(parents=True, exist_ok=True)
    path = task_root / "runtime_result.json"
    payload: dict[str, Any] = asdict(report)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    preview_path = task_root / "preview.json"
    preview_path.write_text(
        json.dumps(preview_record(report), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def preview_record(report: RuntimeReport) -> dict[str, Any]:
    """First-class preview URL for Director / MCP / the owner."""
    port = report.listen_port
    url = None
    if isinstance(port, int) and 1 <= port <= 65535:
        url = f"http://127.0.0.1:{port}/"
    http_ok = report.ok and report.http_status is not None
    return {
        "url": url,
        "ok": bool(http_ok),
        "http_status": report.http_status,
        "listen_port": port,
        "status": report.status,
        "reason": report.reason,
        "command": list(report.command),
    }
