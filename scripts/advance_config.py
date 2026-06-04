#!/usr/bin/env python3
"""Validate Crazy Factory advance configuration.

This module refuses settings that exceed dry-run authority. Project selection
is no longer here — there is no global active project; a project is targeted by
id, path, or cwd via :mod:`project_registry`.
"""

from __future__ import annotations

from typing import Any


def validate_dry_run_settings(factory: dict[str, Any]) -> None:
    """Reject settings that exceed Phase 2 authority.

    Args:
        factory: Parsed ``factory`` configuration mapping.

    Raises:
        RuntimeError: If dry-run mode is disabled or a broad write capability
            is enabled.
    """
    mode = str(factory["mode"])
    if mode != "dry_run":
        raise RuntimeError(
            f"Validation advance refuses non-dry-run mode: {mode}"
        )
    if factory.get("allow_commit") or factory.get("allow_push"):
        raise RuntimeError(
            "Validation advance refuses enabled commit or push settings"
        )
    if factory.get("allow_application_writes") or factory.get(
        "allow_factory_writes"
    ):
        raise RuntimeError(
            "Validation advance refuses broad application or factory writes"
        )
