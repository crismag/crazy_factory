#!/usr/bin/env python3
"""Crazy Factory messaging — the factory's human-readable "voice".

This is the standard messaging and printable-output layer: console output,
run reports, diagnostics, validation summaries, task decisions, and LLM
activity. It only FORMATS, ROUTES, and PRINTS messages — it never decides
factory policy.

Three layers:

1. Purpose helpers — ``iprint`` (info), ``eprint`` (error), ``wprint`` (warn),
   ``nprint`` (notice), ``dprint`` (debug), ``sprint`` (success).
2. Generic dispatcher — ``_emit_line(message_type, message, ...)`` with alias
   normalization ("err"/"e" -> ERROR), routing errors/warnings to stderr.
3. Structured helpers — ``json_print``, ``table_print``, ``section_print``,
   ``banner_print``, ``key_value_print``, plus run-flow kinds (``phase``,
   ``stage``, ``decision``, ``rejection``, ``checkpoint`` …).

Everything respects a 0–10+ VERBOSITY dial (0 silent, higher = more detail);
each message type declares the minimum verbosity at which it appears. Set
``CRAZY_FACTORY_VERBOSITY`` (int) for the default, or call ``set_verbosity()``
(the CLI flags do). Set ``CRAZY_FACTORY_LOGFILE`` to also tee EVERYTHING
(timestamped) to a file regardless of console verbosity — a full run trace.

Design: stdlib only, plain text by default (color optional later), deterministic
and testable, safe to call from any script with no setup.
"""

from __future__ import annotations

import json as _json
import os
import sys
from datetime import datetime, timezone
from typing import Any, TextIO

# --- verbosity dial ---------------------------------------------------------

L_ERROR = 1
L_WARN = 2
L_PHASE = 3
L_STAGE = 3
L_CHECKPOINT = 3
L_DECISION = 4
L_REJECT = 4
L_INFO = 4
L_NOTICE = 4
L_ACTION = 4
L_APPROVAL = 4
L_VALIDATION = 4
L_SUMMARY = 4
L_LLM = 4
L_SYSTEM = 4
L_SUCCESS = 4
L_DETAIL = 5
L_DEBUG = 7
L_TRACE = 9
L_MAX = 10

_DEFAULT_VERBOSITY = 4


def _initial_verbosity() -> int:
    raw = os.environ.get("CRAZY_FACTORY_VERBOSITY")
    if raw is None:
        return _DEFAULT_VERBOSITY
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_VERBOSITY


_verbosity = _initial_verbosity()
_logfile: TextIO | None = None
_logfile_path = os.environ.get("CRAZY_FACTORY_LOGFILE") or ""


def set_verbosity(level: int) -> None:
    """Set the console verbosity (clamped to >= 0)."""
    global _verbosity
    _verbosity = max(0, int(level))


def get_verbosity() -> int:
    """Return the current console verbosity."""
    return _verbosity


def enabled(level: int) -> bool:
    """Whether a message needing ``level`` would be shown on the console."""
    return _verbosity > 0 and _verbosity >= level


def _file() -> TextIO | None:
    """Lazily open the optional full-trace log file."""
    global _logfile
    if not _logfile_path:
        return None
    if _logfile is None:
        try:
            _logfile = open(  # noqa: SIM115 - process-lifetime sink
                _logfile_path, "a", encoding="utf-8"
            )
        except OSError:
            return None
    return _logfile


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _write(lines: list[str], level: int, stream: TextIO) -> None:
    """Tee lines to the optional log file (always) and console (if enabled)."""
    sink = _file()
    if sink is not None and level <= L_MAX:
        for line in lines:
            sink.write(f"{_ts()} {line}\n")
        sink.flush()
    if not enabled(level):
        return
    for line in lines:
        print(line, file=stream)


# --- message type registry --------------------------------------------------

MESSAGE_TYPES: dict[str, dict[str, Any]] = {
    "INFO": {"label": "INFO", "stream": "stdout", "level": L_INFO},
    "ERROR": {"label": "ERROR", "stream": "stderr", "level": L_ERROR},
    "WARNING": {
        "label": "WARN",
        "stream": "stderr",
        "level": L_WARN,
        "rule": "-",
    },
    "NOTICE": {"label": "NOTE", "stream": "stdout", "level": L_NOTICE},
    "DEBUG": {"label": "DEBUG", "stream": "stdout", "level": L_DEBUG},
    "SUCCESS": {
        "label": "OK",
        "stream": "stdout",
        "level": L_SUCCESS,
        "rule": "+",
    },
    "STEP": {"label": "STEP", "stream": "stdout", "level": L_PHASE},
    "ACTION": {"label": "ACTION", "stream": "stdout", "level": L_ACTION},
    "DECISION": {"label": "DECISION", "stream": "stdout", "level": L_DECISION},
    "REJECTION": {"label": "REJECT", "stream": "stdout", "level": L_REJECT},
    "APPROVAL": {
        "label": "APPROVE",
        "stream": "stdout",
        "level": L_APPROVAL,
        "rule": "+",
    },
    "VALIDATION": {
        "label": "VALIDATION",
        "stream": "stdout",
        "level": L_VALIDATION,
    },
    "SUMMARY": {"label": "SUMMARY", "stream": "stdout", "level": L_SUMMARY},
    "LLM": {"label": "LLM", "stream": "stdout", "level": L_LLM},
    "SYSTEM": {"label": "SYSTEM", "stream": "stdout", "level": L_SYSTEM},
    "CMD": {"label": "CMD", "stream": "stdout", "level": L_INFO},
    # Emphasized banner events (used with post_message). Attention-grabbing
    # checkpoints shown at low verbosity. ``rule`` is the frame character:
    # "=" heavy (errors/blocks), "-" light (warnings), "+" positive (success).
    "FATAL": {
        "label": "FATAL",
        "stream": "stderr",
        "level": L_ERROR,
        "rule": "=",
    },
    "IMPORTANT": {
        "label": "IMPORTANT",
        "stream": "stdout",
        "level": L_PHASE,
        "rule": "=",
    },
    "ACTION_REQUIRED": {
        "label": "ACTION REQUIRED",
        "stream": "stderr",
        "level": L_WARN,
        "rule": "-",
    },
    "SECURITY_BLOCK": {
        "label": "SECURITY BLOCK",
        "stream": "stderr",
        "level": L_ERROR,
        "rule": "=",
    },
    "CONTRACT_REJECTED": {
        "label": "CONTRACT REJECTED",
        "stream": "stderr",
        "level": L_WARN,
        "rule": "=",
    },
    "VALIDATION_FAILED": {
        "label": "VALIDATION FAILED",
        "stream": "stderr",
        "level": L_WARN,
        "rule": "=",
    },
    "VALIDATION_PASSED": {
        "label": "VALIDATION PASSED",
        "stream": "stdout",
        "level": L_PHASE,
        "rule": "+",
    },
}

ALIASES: dict[str, str] = {
    "i": "INFO",
    "info": "INFO",
    "e": "ERROR",
    "err": "ERROR",
    "error": "ERROR",
    "w": "WARNING",
    "warn": "WARNING",
    "warning": "WARNING",
    "n": "NOTICE",
    "note": "NOTICE",
    "notice": "NOTICE",
    "d": "DEBUG",
    "debug": "DEBUG",
    "s": "SUCCESS",
    "ok": "SUCCESS",
    "success": "SUCCESS",
    "step": "STEP",
    "action": "ACTION",
    "decision": "DECISION",
    "rejection": "REJECTION",
    "reject": "REJECTION",
    "approval": "APPROVAL",
    "approve": "APPROVAL",
    "validation": "VALIDATION",
    "summary": "SUMMARY",
    "llm": "LLM",
    "system": "SYSTEM",
    "c": "CMD",
    "cmd": "CMD",
    "command": "CMD",
    "console": "CMD",
    "fatal": "FATAL",
    "important": "IMPORTANT",
    "action_required": "ACTION_REQUIRED",
    "security_block": "SECURITY_BLOCK",
    "contract_rejected": "CONTRACT_REJECTED",
    "validation_failed": "VALIDATION_FAILED",
    "validation_passed": "VALIDATION_PASSED",
}


def resolve_type(message_type: str) -> dict[str, Any]:
    """Normalize a type/alias to its registry spec.

    Known names and aliases resolve to a registered spec. An UNKNOWN type falls
    back safely: it is shown with its own upper-cased name as the label, at INFO
    level on stdout — so a typo never crashes a run, but the intent is kept.
    """
    key = str(message_type).strip()
    canonical = ALIASES.get(key.lower(), key.upper())
    spec = MESSAGE_TYPES.get(canonical)
    if spec is not None:
        return spec
    return {"label": canonical or "INFO", "stream": "stdout", "level": L_INFO}


def _join(message: object, args: tuple[object, ...]) -> str:
    """Combine a message with extra positional parts, predictably."""
    text = str(message)
    if args:
        text = (text + " " + " ".join(str(a) for a in args)).strip()
    return text


def _emit_line(
    message_type: str,
    message: object = "",
    *args: object,
    **kwargs: Any,
) -> None:
    """Format, route, and print one message of ``message_type``.

    ``items=`` is an optional reason/detail CHECKLIST printed beneath the
    message (so a rejection shows WHAT was rejected, not just that it was).
    ``level=`` overrides the type's default verbosity threshold. Unknown
    keyword arguments are ignored, so callers can pass extras safely.
    """
    spec = resolve_type(message_type)
    level = kwargs.get("level")
    use_level = spec["level"] if level is None else int(level)
    stream = sys.stderr if spec["stream"] == "stderr" else sys.stdout
    items = kwargs.get("items") or []
    lines = [f"[{spec['label']}] {_join(message, args)}"]
    lines.extend(f"    - {it}" for it in items if str(it).strip())
    _write(lines, use_level, stream)


# --- purpose-specific helpers ----------------------------------------------


def iprint(message: object = "", *args: object, **kwargs: Any) -> None:
    """Info message -> ``[INFO]`` on stdout."""
    _emit_line("INFO", message, *args, **kwargs)


def eprint(message: object = "", *args: object, **kwargs: Any) -> None:
    """Error message -> ``[ERROR]`` on stderr."""
    _emit_line("ERROR", message, *args, **kwargs)


def wprint(message: object = "", *args: object, **kwargs: Any) -> None:
    """Warning message -> ``[WARN]`` on stderr."""
    _emit_line("WARNING", message, *args, **kwargs)


def nprint(message: object = "", *args: object, **kwargs: Any) -> None:
    """Notice / narrative message -> ``[NOTE]`` on stdout."""
    _emit_line("NOTICE", message, *args, **kwargs)


def dprint(message: object = "", *args: object, **kwargs: Any) -> None:
    """Debug message -> ``[DEBUG]`` (verbosity 7+)."""
    _emit_line("DEBUG", message, *args, **kwargs)


def sprint(message: object = "", *args: object, **kwargs: Any) -> None:
    """Success message -> ``[OK]`` on stdout."""
    _emit_line("SUCCESS", message, *args, **kwargs)


def cprint(message: object = "", *args: object, **kwargs: Any) -> None:
    """Command / console / execution-detail message -> ``[CMD]``."""
    _emit_line("CMD", message, *args, **kwargs)


# --- run-flow kinds (used by the advance pipeline) --------------------------


def phase(name: str) -> None:
    """A top-level run phase header."""
    _emit_line("STEP", name)


def stage(name: str, status: str, *, detail: str = "") -> None:
    """A stage outcome (contract/coder/application/validation/checkpoint)."""
    text = f"{name}: {status}" + (f" — {detail}" if detail else "")
    _emit_line("STEP", text)


def checkpoint(
    name: str, status: str, *, items: list[str] | None = None
) -> None:
    """A checkpoint / milestone report."""
    _emit_line("SUMMARY", f"{name}: {status}", items=items)


def decision(
    what: str, choice: str, *, reasons: list[str] | None = None
) -> None:
    """A decision point and (optionally) why it was made."""
    _emit_line("DECISION", f"{what} -> {choice}", items=reasons)


def rejection(what: str, reasons: list[str]) -> None:
    """A rejection with the full checklist of reasons it was rejected."""
    _emit_line(
        "REJECTION", f"{what} ({len(reasons)} reason(s))", items=reasons
    )


def approval(what: str) -> None:
    """An approval/acceptance message."""
    _emit_line("APPROVAL", what)


def info(message: object = "", *, items: list[str] | None = None) -> None:
    """General progress information."""
    _emit_line("INFO", message, items=items)


def warn(message: object = "", *, items: list[str] | None = None) -> None:
    """A warning (stderr)."""
    _emit_line("WARNING", message, items=items)


def error(message: object = "", *, checklist: list[str] | None = None) -> None:
    """An error, with an optional checklist of WHAT failed (stderr)."""
    _emit_line("ERROR", message, items=checklist)


def detail(message: object = "", *, items: list[str] | None = None) -> None:
    """Extra detail shown only at higher verbosity."""
    _emit_line("INFO", message, items=items, level=L_DETAIL)


def debug(message: object = "", *, items: list[str] | None = None) -> None:
    """Debug-level detail (``--debug``)."""
    _emit_line("DEBUG", message, items=items)


def trace(message: object = "") -> None:
    """Very verbose trace (payloads, prompts) at the top of the dial."""
    _emit_line("DEBUG", message, level=L_TRACE)


def report(message: str) -> None:
    """Print a verbatim run-summary line (no tag), gated like a stage."""
    _write([message], L_STAGE, sys.stdout)


# --- emphasized banner events ----------------------------------------------

_FIELD_WIDTH = 80


def _label_of(key: str) -> str:
    """Render a field key as a Title-Case label ('rule_violated' -> ...)."""
    return key.replace("_", " ").title()


def post_message(
    message_type: str,
    title: str,
    *,
    items: list[str] | None = None,
    level: int | None = None,
    **fields: Any,
) -> None:
    """Emit an EMPHASIZED, banner-style attention event.

    Reserved for events that should draw human attention — a fatal error, a
    hard rejection, a security/path block, a validation pass/fail checkpoint,
    an approval, or a required owner action. NOT for ordinary status lines (use
    ``iprint``/``wprint``/``eprint``/``dprint``/``cprint``/``nprint``).

    A good banner answers WHAT / WHY / IMPACT / EVIDENCE / WHAT-NEXT. Pass those
    as keyword fields — ``reason=``, ``impact=``, ``evidence=``,
    ``recommendation=``, ``action=``, or any custom key (``rule_violated=`` ->
    "Rule Violated"). Fields render in the order given, each as an indented
    block::

        ================================================================
        [FATAL] Factory startup aborted
        ================================================================

        Reason:
            No active project configured

        Impact:
            Factory cannot continue

        Required Action:
            Select an active project

        ================================================================

    ``items`` adds a bulleted checklist. The frame character reflects severity
    (``=`` default, ``-`` warnings, ``+`` success/approval), set per type.
    """
    spec = resolve_type(message_type)
    use_level = spec["level"] if level is None else int(level)
    stream = sys.stderr if spec["stream"] == "stderr" else sys.stdout
    rule = str(spec.get("rule", "=")) * _FIELD_WIDTH

    lines = [rule, f"[{spec['label']}] {title}", rule]
    rendered = [(k, v) for k, v in fields.items() if v is not None]
    has_body = bool(rendered or items)
    if has_body:
        lines.append("")
    for key, value in rendered:
        lines.append(f"{_label_of(str(key))}:")
        lines.extend(f"    {vl}" for vl in str(value).splitlines() or [""])
        lines.append("")
    if items:
        cleaned = [str(it) for it in items if str(it).strip()]
        if cleaned:
            lines.append("Details:")
            lines.extend(f"    - {it}" for it in cleaned)
            lines.append("")
    if has_body:
        lines.append(rule)
    _write(lines, use_level, stream)


# --- structured print helpers ----------------------------------------------


def section_print(
    title: str, *, level: int = L_PHASE, **_kwargs: object
) -> None:
    """A titled section header (rule + title + rule)."""
    rule = "-" * min(80, max(len(title), 8))
    _write([rule, title, rule], level, sys.stdout)


def banner_print(
    title: str, *, level: int = L_PHASE, **_kwargs: object
) -> None:
    """A prominent banner (heavy rule + title + heavy rule)."""
    rule = "=" * 80
    _write([rule, title, rule], level, sys.stdout)


def key_value_print(
    mapping: dict[str, Any],
    *,
    title: str | None = None,
    level: int = L_INFO,
    **_kwargs: object,
) -> None:
    """Aligned ``Key: value`` lines, with an optional title.

    When a title is given, the pairs are indented beneath it so the block reads
    as a single titled message (e.g. "Loading active project:" + indented
    Project/Context), per the message-quality standard.
    """
    lines: list[str] = []
    indent = "    " if title else ""
    if title:
        lines.append(title)
    width = max((len(str(k)) for k in mapping), default=0)
    lines.extend(
        f"{indent}{str(k).ljust(width)} : {v}" for k, v in mapping.items()
    )
    _write(lines, level, sys.stdout)


def json_print(
    data: Any,
    *,
    title: str | None = None,
    indent: int = 2,
    sort_keys: bool = False,
    level: int = L_INFO,
    **_kwargs: object,
) -> None:
    """Pretty-print JSON-serializable data, with an optional title."""
    try:
        body = _json.dumps(
            data, indent=indent, sort_keys=sort_keys, default=str
        )
    except (TypeError, ValueError):
        body = str(data)
    lines = ([title] if title else []) + body.splitlines()
    _write(lines, level, sys.stdout)


def _rows_to_matrix(
    rows: list[Any], headers: list[str] | None
) -> tuple[list[str], list[list[str]]]:
    """Normalize list-of-dicts or list-of-lists into (headers, string rows)."""
    if rows and isinstance(rows[0], dict):
        cols = headers or list(dict.fromkeys(k for row in rows for k in row))
        matrix = [[str(row.get(c, "")) for c in cols] for row in rows]
        return cols, matrix
    cols = headers or []
    matrix = [[str(c) for c in row] for row in rows]
    return cols, matrix


def table_print(
    rows: list[Any],
    *,
    headers: list[str] | None = None,
    title: str | None = None,
    level: int = L_INFO,
    **_kwargs: object,
) -> None:
    """Render a list-of-dicts or list-of-lists as an aligned text table."""
    cols, matrix = _rows_to_matrix(rows, headers)
    all_rows = ([cols] if cols else []) + matrix
    if not all_rows:
        return
    ncols = max(len(r) for r in all_rows)
    widths = [0] * ncols
    for r in all_rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    lines: list[str] = []
    if title:
        lines.append(title)
    if cols:
        lines.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(cols)))
        lines.append("  ".join("-" * widths[i] for i in range(ncols)))
    lines.extend(
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r))
        for r in matrix
    )
    _write(lines, level, sys.stdout)
