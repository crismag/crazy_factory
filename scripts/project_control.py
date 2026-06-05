#!/usr/bin/env python3
"""Project-local owner-control file for Crazy Factory.

``apps/<id>/crazy_project.yaml`` is the human-facing control surface. It holds
project metadata, context limits, owner decisions (task authorization, proposal
approval), and per-project capability switches. Owners drive it through
``crazy-admin`` commands rather than hand-editing generated JSON.

This module owns only the control file and how its capabilities bridge into the
runtime config. It does NOT relax any safety boundary: capabilities still
default OFF, the model still only proposes, and Python still validates.

Capability resolution (per project): a capability is **effective** when the
project's control file explicitly sets it; otherwise the global
``config/factory.yaml`` default applies (which is OFF). Setting a capability is
an explicit, per-project owner opt-in — it never weakens the global default for
other projects.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from repo_tools import load_simple_yaml, resolve_repo_path, safe_write_text

CONTROL_FILENAME = "crazy_project.yaml"

# Map a control-file capability key to its global config (section, key).
CAPABILITY_BRIDGE: dict[str, tuple[str, str]] = {
    "allow_apply": ("proposal_application", "allow_apply"),
    "allow_delete": ("proposal_application", "allow_delete"),
    "allow_validation": ("validation", "allow_run"),
    "allow_remediation": ("validation", "allow_remediation"),
    "allow_completeness_review": (
        "proposal_application",
        "completeness_review",
    ),
    "allow_autonomous": ("autonomy", "enabled"),
    "allow_auto_commit": ("git", "allow_auto_commit"),
}

_CAPABILITY_KEYS: tuple[str, ...] = tuple(CAPABILITY_BRIDGE)


class ControlError(RuntimeError):
    """Raised when the control file cannot be used safely."""


def control_path(app_path: str) -> str:
    """Return the repository-relative path of a project's control file."""
    return f"{str(app_path).rstrip('/')}/{CONTROL_FILENAME}"


def default_control(
    *, project_id: str, mode: str, app_path: str, state_path: str
) -> dict[str, Any]:
    """Return a fresh control mapping with safe defaults (all switches OFF)."""
    return {
        "project": {
            "id": project_id,
            "mode": mode,
            "app_path": app_path,
            "state_path": state_path,
        },
        "context": {
            "enabled": True,
            "max_files": 25,
            "max_lines_per_file": 500,
            "max_total_lines": 5000,
        },
        "owner_controls": {
            "task_authorized": False,
            "proposal_approved": False,
            "approved_proposal_id": None,
        },
        "capabilities": {
            "allow_apply": False,
            "allow_delete": False,
            "allow_validation": False,
            "allow_auto_commit": False,
        },
    }


def read_control(app_path: str, root: Path) -> dict[str, Any] | None:
    """Read a project's control file as parsed, or ``None`` when absent.

    Args:
        app_path: Repository-relative workbench path.
        root: Absolute repository root.

    Returns:
        The parsed control mapping, or ``None`` if no control file exists.
    """
    rel = control_path(app_path)
    if not resolve_repo_path(rel, root).is_file():
        return None
    return load_simple_yaml(rel, root)


def normalize_control(
    raw: dict[str, Any] | None, *, base: dict[str, Any]
) -> dict[str, Any]:
    """Return an editable control mapping with all sections present.

    Unknown top-level keys in ``raw`` are preserved. Known sections are filled
    from ``base`` defaults without overwriting values already present.

    Args:
        raw: Parsed control mapping (or ``None``).
        base: Default control mapping to fill gaps from.

    Returns:
        A normalized control mapping safe to edit and serialize.
    """
    result = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    for section, defaults in base.items():
        existing = result.get(section)
        if not isinstance(existing, dict):
            result[section] = copy.deepcopy(defaults)
            continue
        for key, value in defaults.items():
            existing.setdefault(key, value)
    return result


def _scalar(value: Any) -> str:
    """Serialize a scalar for the bootstrap YAML subset."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return f'"{value}"'


def _emit(data: dict[str, Any], indent: int, lines: list[str]) -> None:
    """Recursively emit a mapping into ``lines`` at the given indent."""
    pad = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            if value:
                _emit(value, indent + 2, lines)
        elif isinstance(value, list):
            lines.append(f"{pad}{key}:")
            for item in value:
                lines.append(f"{pad}  - {_scalar(item)}")
        else:
            lines.append(f"{pad}{key}: {_scalar(value)}")


def dump_control(control: dict[str, Any]) -> str:
    """Serialize a control mapping to the bootstrap YAML subset.

    Generic and order-preserving so unknown fields survive a round-trip.
    """
    lines = [
        "# Crazy Factory project control file. Owner-editable, but prefer the",
        "# crazy-admin commands (authorize-task, approve-proposal, enable-*).",
    ]
    _emit(control, 0, lines)
    return "\n".join(lines) + "\n"


def save_control(control: dict[str, Any], app_path: str, root: Path) -> None:
    """Persist a project's control file inside its workbench."""
    safe_write_text(
        control_path(app_path),
        dump_control(control),
        repo_root=root,
        allowed_roots=[str(app_path)],
    )


def load_or_init_control(
    app_path: str, root: Path, *, project: dict[str, Any]
) -> dict[str, Any]:
    """Return an editable control mapping, creating defaults if absent.

    Args:
        app_path: Repository-relative workbench path.
        root: Absolute repository root.
        project: Resolved project mapping (for default metadata).

    Returns:
        A normalized, editable control mapping.
    """
    base = default_control(
        project_id=str(project.get("name") or ""),
        mode=str(project.get("repo_mode") or "embedded"),
        app_path=str(project.get("app_path") or app_path),
        state_path=str(project.get("state_dir") or ""),
    )
    return normalize_control(read_control(app_path, root), base=base)


def capability_set(raw_control: dict[str, Any] | None, cap_key: str) -> bool:
    """Report whether a capability is explicitly present in the control file."""
    if not isinstance(raw_control, dict):
        return False
    caps = raw_control.get("capabilities")
    return isinstance(caps, dict) and cap_key in caps


def effective_capability(
    raw_control: dict[str, Any] | None,
    factory_config: dict[str, Any],
    cap_key: str,
) -> bool:
    """Resolve a capability: project-local when set, else the global default.

    Args:
        raw_control: Parsed control mapping (or ``None`` when no control file).
        factory_config: Parsed ``config/factory.yaml`` mapping.
        cap_key: One of ``CAPABILITY_BRIDGE``.

    Returns:
        The effective boolean capability.
    """
    section, global_key = CAPABILITY_BRIDGE[cap_key]
    if capability_set(raw_control, cap_key):
        return bool(raw_control["capabilities"][cap_key])  # type: ignore[index]
    return bool(factory_config.get(section, {}).get(global_key, False))


def apply_project_controls(
    factory_config: dict[str, Any], raw_control: dict[str, Any] | None
) -> dict[str, Any]:
    """Return a config copy with project-local capabilities overlaid.

    When no control file exists the global config is returned unchanged. Only
    the four bridged capability switches are ever overridden; nothing else in
    the config is touched.

    Args:
        factory_config: Parsed ``config/factory.yaml`` mapping.
        raw_control: Parsed control mapping (or ``None``).

    Returns:
        An effective config mapping for this project's advance.
    """
    if raw_control is None:
        return factory_config
    effective = copy.deepcopy(factory_config)
    for cap_key, (section, global_key) in CAPABILITY_BRIDGE.items():
        if capability_set(raw_control, cap_key):
            effective.setdefault(section, {})
            effective[section][global_key] = bool(
                raw_control["capabilities"][cap_key]
            )
    # The application stage gates on BOTH allow_apply and mode == "apply".
    # mode defaults to preview_only in the template, so without this the owner
    # would have to hand-edit config to apply approved code even after running
    # `enable-apply`. Tie the two together: enabling the allow_apply capability
    # flips the effective mode to "apply"; disabling it restores preview_only.
    if capability_set(raw_control, "allow_apply"):
        pa = effective.setdefault("proposal_application", {})
        pa["mode"] = "apply" if pa.get("allow_apply") else "preview_only"
    return effective


def capability_keys() -> tuple[str, ...]:
    """Return the recognized control-file capability keys."""
    return _CAPABILITY_KEYS
