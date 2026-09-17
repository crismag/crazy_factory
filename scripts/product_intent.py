#!/usr/bin/env python3
"""Compile owner intent into explicit product claims and score them.

Natural language becomes capabilities with probes. COMPLETE may only
follow when those claims are evidenced as capability — runtime,
persistence, visible output, tests, or static source — not because a
title or banner quotes the prompt, and not because an identifier list
matched. Banner HTML and ``change_requests.json`` are ignored.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

INTENT_FILE = "product_intent.json"
ACCEPTANCE_FILE = "product_acceptance.json"
SKIP_JSON = {"change_requests.json"}
SKIP_SRC_PARTS = {"__pycache__", ".git"}

_WORD = re.compile(r"[a-z][a-z0-9]+")


@dataclass(frozen=True)
class Capability:
    """One explicit product claim with admissible evidence kinds."""

    id: str
    claim: str
    symbols: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    origin: str = "compile"
    evidence: tuple[str, ...] = ()


def _slug(text: str) -> str:
    words = _WORD.findall((text or "").lower().replace("-", " "))
    skip = {
        "build",
        "make",
        "create",
        "add",
        "a",
        "an",
        "the",
        "me",
        "my",
        "please",
        "app",
        "application",
        "for",
        "with",
        "and",
        "to",
        "of",
    }
    kept = [w for w in words if w not in skip]
    return "_".join(kept[:4]) or "item"


def _cap(
    cap_id: str,
    claim: str,
    *,
    symbols: tuple[str, ...] = (),
    fields: tuple[str, ...] = (),
    files: tuple[str, ...] = (),
    origin: str = "compile",
    evidence: tuple[str, ...] = (),
) -> Capability:
    return Capability(
        id=cap_id,
        claim=claim,
        symbols=symbols,
        fields=fields,
        files=files,
        origin=origin,
        evidence=evidence,
    )


def fallback_capabilities(
    prompt: str, *, origin: str = "compile"
) -> list[Capability]:
    """Turn a prompt into domain claims. This is compile-time, not accept."""
    text = (prompt or "").strip()
    low = text.lower()
    if re.search(r"\bhabits?\b", low) or "habit tracker" in low:
        caps = [
            _cap(
                "define_habits",
                "User can define habits.",
                origin=origin,
                evidence=("runtime",),
            ),
            _cap(
                "record_completion",
                "User can record completion for a habit.",
                origin=origin,
                evidence=("runtime",),
            ),
            _cap(
                "dated_completion",
                "Completion is associated with a date.",
                origin=origin,
                evidence=("runtime",),
            ),
            _cap(
                "persist_habits",
                "Persisted habit state survives restart.",
                origin=origin,
                evidence=("persistence",),
            ),
        ]
        if "streak" in low:
            caps.append(_streak_cap(origin))
        if "week" in low:
            caps.append(_weekly_cap(origin))
        return caps
    if "streak" in low or "week" in low:
        caps: list[Capability] = []
        if "streak" in low:
            caps.append(_streak_cap(origin))
        if "week" in low:
            caps.append(_weekly_cap(origin))
        return caps
    noun = _slug(text)
    singular = noun.rstrip("s") or "item"
    plural = singular + "s"
    adder = f"add_{singular}"
    return [
        _cap(
            f"define_{plural}",
            f"User can define {plural.replace('_', ' ')}.",
            symbols=(adder, f"create_{singular}", plural),
            files=(f"data/{plural}.json",),
            origin=origin,
        ),
        _cap(
            f"persist_{plural}",
            f"Persisted {plural.replace('_', ' ')} survive restart.",
            symbols=(f"save_{plural}", f"load_{plural}", plural),
            files=(f"data/{plural}.json",),
            origin=origin,
        ),
    ]


def _streak_cap(origin: str) -> Capability:
    return _cap(
        "habit_streaks",
        "Streak information is calculated from completion history "
        "and visible to the user.",
        origin=origin,
        evidence=("visible", "runtime"),
    )


def _weekly_cap(origin: str) -> Capability:
    return _cap(
        "weekly_view",
        "A weekly representation of habit completion exists.",
        origin=origin,
        evidence=("visible", "runtime"),
    )


def capability_from_dict(raw: dict[str, Any]) -> Capability | None:
    claim = str(raw.get("claim") or "").strip()
    if not claim:
        return None
    cap_id = str(raw.get("id") or _slug(claim))[:80]

    def names(key: str) -> tuple[str, ...]:
        vals = raw.get(key) or []
        if isinstance(vals, str):
            vals = [vals]
        if not isinstance(vals, (list, tuple)):
            return ()
        out: list[str] = []
        for item in vals:
            text = str(item).strip()
            if text.isidentifier():
                out.append(text)
        return tuple(out)

    symbols = names("symbols")
    fields = names("fields")
    files_raw = raw.get("files") or []
    if isinstance(files_raw, str):
        files_raw = [files_raw]
    if not isinstance(files_raw, (list, tuple)):
        files_raw = []
    files = tuple(
        str(v).strip()
        for v in files_raw
        if isinstance(v, str)
        and str(v).strip()
        and not str(v).startswith("/")
        and ".." not in str(v)
    )
    origin = str(raw.get("origin") or "compile")
    ev_raw = raw.get("evidence") or []
    if isinstance(ev_raw, str):
        ev_raw = [ev_raw]
    if not isinstance(ev_raw, (list, tuple)):
        ev_raw = []
    allowed = {
        "static",
        "test",
        "runtime",
        "persistence",
        "visible",
    }
    evidence = tuple(
        str(item).strip() for item in ev_raw if str(item).strip() in allowed
    )
    return Capability(
        id=cap_id,
        claim=claim,
        symbols=symbols,
        fields=fields,
        files=files,
        origin=origin,
        evidence=evidence,
    )


def _task_dir(project: dict[str, Any], root: Path) -> Path:
    raw = project.get("task_root") or "factory_tasks"
    path = Path(str(raw))
    return path if path.is_absolute() else (root / path)


def _app_dir(project: dict[str, Any], root: Path) -> Path:
    path = Path(str(project["app_path"]))
    return path if path.is_absolute() else (root / path)


def load_intent(project: dict[str, Any], root: Path) -> dict[str, Any]:
    path = _task_dir(project, root) / INTENT_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def persist_intent(
    project: dict[str, Any],
    root: Path,
    *,
    prompt: str,
    capabilities: list[Capability],
    source: str,
    revision: int | None = None,
) -> dict[str, Any]:
    """Write compiled claims. Replaces compile-origin caps on first write."""
    task = _task_dir(project, root)
    task.mkdir(parents=True, exist_ok=True)
    current = load_intent(project, root)
    rev = revision
    if rev is None:
        rev = int(current.get("revision") or 0) + 1
        rev = max(rev, 1)
    payload = {
        "revision": rev,
        "original_prompt": prompt,
        "source": source,
        "capabilities": [asdict(c) for c in capabilities],
    }
    path = task / INTENT_FILE
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def bump_revision(
    project: dict[str, Any],
    root: Path,
    extra: list[Capability],
) -> int:
    """Append delta claims and increment the intent revision."""
    current = load_intent(project, root)
    rev = int(current.get("revision") or 1) + 1
    caps = []
    for raw in current.get("capabilities") or []:
        if isinstance(raw, dict):
            cap = capability_from_dict(raw)
            if cap:
                caps.append(cap)
    caps.extend(extra)
    payload = {
        "revision": rev,
        "original_prompt": current.get("original_prompt") or "",
        "source": current.get("source") or "delta",
        "capabilities": [asdict(c) for c in caps],
    }
    task = _task_dir(project, root)
    task.mkdir(parents=True, exist_ok=True)
    (task / INTENT_FILE).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return rev


def intent_revision(project: dict[str, Any], root: Path) -> int:
    return int(load_intent(project, root).get("revision") or 0)


def intent_capabilities(
    project: dict[str, Any], root: Path
) -> list[Capability]:
    caps: list[Capability] = []
    for raw in load_intent(project, root).get("capabilities") or []:
        if not isinstance(raw, dict):
            continue
        cap = capability_from_dict(raw)
        if cap:
            caps.append(cap)
    return caps


def _py_identifiers(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            names.add(node.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def _json_keys(path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    keys: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                keys.add(str(key))
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return keys


def workbench_probes(app: Path) -> tuple[set[str], set[str], set[str]]:
    """Return (identifiers, json_keys, files) for product evidence."""
    identifiers: set[str] = set()
    json_keys: set[str] = set()
    files: set[str] = set()
    if not app.is_dir():
        return identifiers, json_keys, files
    for path in app.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_SRC_PARTS for part in path.parts):
            continue
        try:
            rel = path.relative_to(app).as_posix()
        except ValueError:
            continue
        files.add(rel)
        if path.suffix == ".py" and rel.startswith(("src/", "tests/")):
            identifiers |= _py_identifiers(path)
        if (
            path.suffix == ".json"
            and path.name not in SKIP_JSON
            and rel.startswith("data/")
        ):
            json_keys |= _json_keys(path)
    return identifiers, json_keys, files


def claim_satisfied(
    cap: Capability,
    *,
    identifiers: set[str],
    json_keys: set[str],
    files: set[str],
) -> bool:
    """Static-only probe. Habit-class claims use ``score_claims`` instead."""
    from product_evidence import static_claim_satisfied

    return static_claim_satisfied(
        cap,
        identifiers=identifiers,
        json_keys=json_keys,
        files=files,
    )


def score_claims(project: dict[str, Any], root: Path) -> list[Any]:
    """Score compiled claims with the strongest practical evidence."""
    from product_evidence import evaluate_claims

    caps = intent_capabilities(project, root)
    if not caps:
        return []
    app = _app_dir(project, root)
    identifiers, json_keys, files = workbench_probes(app)
    return evaluate_claims(
        caps,
        app=app,
        identifiers=identifiers,
        json_keys=json_keys,
        files=files,
        task_root=_task_dir(project, root),
    )


def unsatisfied_claims(
    project: dict[str, Any], root: Path
) -> list[Capability]:
    """Compiled + delta claims that the workbench does not evidence."""
    return [score.cap for score in score_claims(project, root) if not score.ok]


def persist_acceptance(
    project: dict[str, Any],
    root: Path,
    payload: dict[str, Any],
) -> Path:
    task = _task_dir(project, root)
    task.mkdir(parents=True, exist_ok=True)
    path = task / ACCEPTANCE_FILE
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load_acceptance(project: dict[str, Any], root: Path) -> dict[str, Any]:
    path = _task_dir(project, root) / ACCEPTANCE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
