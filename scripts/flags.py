#!/usr/bin/env python3
"""Phase 8 runtime control flags for Crazy Factory.

The owner controls a continuous worker through simple flag files in the state
directory — ``stop.flag``, ``pause.flag``, ``blocked.flag``, ``satisfied.flag``
— which are easy to ``touch`` or remove from a shell or cron without parsing
JSON. These coexist with the JSON control booleans
(``stop_requested``/``pause_requested``) used by the tick: either surface can
halt or pause the factory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from repo_tools import resolve_repo_path, safe_write_text

FLAG_NAMES: tuple[str, ...] = ("stop", "pause", "blocked", "satisfied")


def flag_relpath(name: str, state_dir: str = "state") -> str:
    """Return the repository-relative path of a flag file.

    Args:
        name: Flag name (one of :data:`FLAG_NAMES`).
        state_dir: Repository-relative state directory.

    Returns:
        Repository-relative flag-file path.
    """
    return str(Path(state_dir) / f"{name}.flag")


def flag_active(name: str, root: Path, state_dir: str = "state") -> bool:
    """Report whether a flag file is present.

    Args:
        name: Flag name.
        root: Absolute repository root.
        state_dir: Repository-relative state directory.

    Returns:
        ``True`` when the flag file exists.
    """
    return resolve_repo_path(flag_relpath(name, state_dir), root).is_file()


def active_flags(root: Path, state_dir: str = "state") -> list[str]:
    """Return the names of all currently active flags.

    Args:
        root: Absolute repository root.
        state_dir: Repository-relative state directory.

    Returns:
        Active flag names in canonical order.
    """
    return [n for n in FLAG_NAMES if flag_active(n, root, state_dir)]


def set_flag(
    name: str,
    root: Path,
    *,
    state_dir: str = "state",
    note: str = "",
) -> str:
    """Create a flag file with an optional note.

    Args:
        name: Flag name (must be in :data:`FLAG_NAMES`).
        root: Absolute repository root.
        state_dir: Repository-relative state directory.
        note: Optional human-readable note written into the flag file.

    Returns:
        Repository-relative path written.

    Raises:
        ValueError: If ``name`` is not a known flag.
    """
    if name not in FLAG_NAMES:
        raise ValueError(f"Unknown flag: {name}")
    path = flag_relpath(name, state_dir)
    safe_write_text(
        path,
        f"{name} flag set by the factory.\n{note}\n".strip() + "\n",
        repo_root=root,
        allowed_roots=[state_dir],
    )
    return path


def clear_flag(name: str, root: Path, state_dir: str = "state") -> bool:
    """Remove a flag file if present.

    Args:
        name: Flag name.
        root: Absolute repository root.
        state_dir: Repository-relative state directory.

    Returns:
        ``True`` when a flag file was removed.
    """
    target = resolve_repo_path(flag_relpath(name, state_dir), root)
    if target.is_file():
        target.unlink()
        return True
    return False


def control_decision(
    root: Path, factory_state: dict[str, Any], state_dir: str = "state"
) -> str | None:
    """Resolve the highest-priority owner control signal.

    File flags and the JSON control booleans are both honored. Precedence is
    stop, then pause, then blocked, then satisfied, so a halt always wins.

    Args:
        root: Absolute repository root.
        factory_state: Global state snapshot.
        state_dir: Repository-relative state directory.

    Returns:
        ``"stopped"``, ``"paused"``, ``"blocked"``, ``"satisfied"``, or
        ``None`` when the factory may proceed.
    """
    if flag_active("stop", root, state_dir) or factory_state.get(
        "stop_requested"
    ):
        return "stopped"
    if flag_active("pause", root, state_dir) or factory_state.get(
        "pause_requested"
    ):
        return "paused"
    if flag_active("blocked", root, state_dir):
        return "blocked"
    if flag_active("satisfied", root, state_dir):
        return "satisfied"
    return None
