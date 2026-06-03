#!/usr/bin/env python3
"""Owner-gated, bounded remediation of a failed validation.

When the deterministic validation stage runs and FAILS, the factory normally
parks on a ``validation_failed`` blocker and waits for the owner. With the
``allow_remediation`` capability enabled, the factory may instead iterate: it
re-engages the Coder with the failing report as context, applies the fix, and
re-validates — up to a bounded number of attempts — until the checks pass or
the budget is exhausted.

Safety model (why auto-applying a fix here does not break "no auto-approval"):

- ``allow_remediation`` defaults OFF. Turning it on is the owner's explicit,
  pre-granted consent to let the factory iterate fixes WITHIN a task they have
  already authorized (``authorize-task``), already approved the first
  application for (``approve-proposal``), and already enabled apply +
  validation on. Remediation only ever triggers *after* such an owner-approved
  application has been validated and failed.
- Every deterministic floor still applies to each fix: the contract safety
  floor, full proposal validation (forbidden ops, workbench confinement,
  max-files), and the validation command allowlist. Remediation cannot relax
  any of them; it only removes the per-iteration approval typing.
- It is bounded by ``max_remediation_attempts`` and stops on a terminal
  ``remediation_exhausted`` blocker for owner review when the budget runs out.
- The owner can ``disable-remediation`` (or revoke the task) at any time.

This module is pure decision logic; the advance orchestrates the I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Blocker set by the validation stage on a first (non-remediated) failure, and
# the trigger this module looks for to begin remediation.
VALIDATION_FAILED = "validation_failed"
# Terminal blocker when the remediation budget is exhausted; owner must review.
REMEDIATION_EXHAUSTED = "remediation_exhausted"


@dataclass(frozen=True)
class RemediationPlan:
    """Whether this advance is a remediation attempt, and its bounds.

    Attributes:
        active: True when this advance should regenerate + auto-approve a fix.
        attempt: 1-based number of this advance's attempt (0 when inactive).
        max_attempts: Configured attempt budget.
        context: Coder context describing the failure (empty when inactive).
    """

    active: bool
    attempt: int
    max_attempts: int
    context: str = ""

    @property
    def is_last_attempt(self) -> bool:
        """True when an active attempt is the final one in the budget."""
        return self.active and self.attempt >= self.max_attempts


def remediation_settings(factory_config: dict[str, Any]) -> tuple[bool, int]:
    """Return ``(allow_remediation, max_attempts)`` from the effective config.

    ``allow_remediation`` is bridged from the owner capability; ``max_attempts``
    defaults to 3 and is clamped to a non-negative integer.
    """
    validation = (
        factory_config.get("validation", {})
        if isinstance(factory_config, dict)
        else {}
    )
    allow = bool(validation.get("allow_remediation", False))
    try:
        max_attempts = int(validation.get("max_remediation_attempts", 3))
    except (TypeError, ValueError):
        max_attempts = 3
    return allow, max(0, max_attempts)


def build_failure_context(report_text: str) -> str:
    """Build the Coder context that explains the failure and asks for a fix."""
    report = (report_text or "").strip()
    return (
        "## Remediation: the previous validation FAILED\n\n"
        "Your previous changes were applied but the validation checks did "
        "not pass. Propose the SMALLEST fix to the EXISTING files so the "
        "checks pass. Stay strictly within the authorized task scope and do "
        "not add new features. Common causes are a test file missing its "
        "import line, a wrong assertion or test fixture, or an unimplemented "
        "function body.\n\n"
        "### Failing validation report\n\n"
        + (report or "_No validation report text was available._")
    )


def plan_remediation(
    factory_config: dict[str, Any],
    project_state: dict[str, Any] | None,
    report_text: str,
) -> RemediationPlan:
    """Decide whether this advance should remediate a prior validation failure.

    Active only when remediation is enabled, a budget remains, and the prior
    advance left a ``validation_failed`` blocker. The attempt number is the
    persisted counter plus one.
    """
    allow, max_attempts = remediation_settings(factory_config)
    state = project_state or {}
    try:
        prior = int(state.get("remediation_attempt", 0) or 0)
    except (TypeError, ValueError):
        prior = 0
    blocked = state.get("current_blocker") == VALIDATION_FAILED
    if allow and max_attempts > 0 and blocked and prior < max_attempts:
        return RemediationPlan(
            active=True,
            attempt=prior + 1,
            max_attempts=max_attempts,
            context=build_failure_context(report_text),
        )
    return RemediationPlan(
        active=False, attempt=prior, max_attempts=max_attempts
    )


def fix_approval_record(proposal_id: str) -> dict[str, Any]:
    """Build the auto-approval artifact for a remediation fix proposal.

    Mirrors what ``owner_controls.approve_proposal`` writes, but is only ever
    produced under an active :class:`RemediationPlan` (owner-enabled).
    """
    return {
        "application_approved": True,
        "proposal_id": str(proposal_id),
        "approved_by": "remediation",
    }
