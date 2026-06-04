#!/usr/bin/env python3
"""Phase 8 stall detector for Crazy Factory.

A stall is when the factory is no longer making safe progress and should stop
retrying blindly. This module reads persistent state and reports a stall
signal so the recovery manager can write a plan and, if needed, block the
factory for owner attention. It never mutates state or runs anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StallSignal:
    """Whether the factory appears stalled and why.

    Attributes:
        stalled: ``True`` when at least one stall condition holds.
        reasons: Human-readable stall conditions.
    """

    stalled: bool
    reasons: list[str] = field(default_factory=list)


# Blockers that indicate repeated, unresolved trouble in a single phase.
PERSISTENT_BLOCKERS: frozenset[str] = frozenset(
    {
        "planning_contract_rejected",
        "coder_proposal_rejected",
        "application_rejected",
        "validation_failed",
        "test_plan_rejected",
        "remediation_exhausted",
        "self_rejection",
    }
)


def detect_stall(
    *,
    factory_state: dict[str, Any],
    project_state: dict[str, Any],
    max_failures: int = 2,
) -> StallSignal:
    """Detect whether the factory is stalled from persistent state.

    Stall conditions: the failure counter exceeded its threshold, a persistent
    phase blocker is set, or repeated reliance on deterministic fallbacks shows
    the local model is unavailable.

    Args:
        factory_state: Global state snapshot.
        project_state: Active project state snapshot.
        max_failures: Failure-count threshold above which a stall is declared.

    Returns:
        The stall signal.
    """
    reasons: list[str] = []

    failure_count = int(project_state.get("failure_count", 0))
    if failure_count > max_failures:
        reasons.append(
            f"Failure count {failure_count} exceeds threshold {max_failures}"
        )

    blocker = project_state.get("current_blocker")
    if blocker in PERSISTENT_BLOCKERS:
        reasons.append(f"Persistent blocker: {blocker}")

    sources = (
        factory_state.get("last_architect_source"),
        factory_state.get("last_planner_source"),
        factory_state.get("last_contract_source"),
    )
    if failure_count > 0 and all(s == "fallback" for s in sources if s):
        reasons.append(
            "Local model unavailable (all sources fell back) with failures"
        )

    return StallSignal(stalled=bool(reasons), reasons=reasons)
