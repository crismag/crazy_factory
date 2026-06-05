#!/usr/bin/env python3
"""Adjudication decision core (Phase 9E.S2).

Replaces the binary accept/reject gate with a graded **disposition** for a set of
findings. Per the governing principle (scripts are rails, not a brain):

- **Python is the rail.** The deterministic severity policy (9E.S0) resolves the
  clear cases — all-fixable → ``fix``; only advisory → ``accept`` — and the
  **safety floor always wins** (secrets/destructive-git/path-escape/self-auth →
  ``reject_unsafe``, never auto-fixed, never LLM-overridable).
- **The LLM is the judgment.** Only genuinely ambiguous *blocking* findings
  (syntax/placeholder/forbidden-tech, i.e. not the safety floor) are sent to the
  adjudicator model to choose among ``scope_down | revise | redirect | escalate
  | reject_unsafe``. It can never ``accept``/``fix`` a blocking finding away.
- **Degrade to the rail.** No model (or an indeterminate reply) → ``escalate``
  to the owner (9E.S0b), never a fake pass.

This module decides; it does not execute. The caller runs the returned skills
(9E.S1) and/or surfaces the owner-review checkpoint. It is intentionally not yet
wired into the live apply path — it is the decision rail other phases build on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from llm_interaction import structured_call
from severity import BLOCK, FIX, WARN, classify_reasons
from skill_library import is_known_skill

# The full disposition vocabulary (shared with the plan docs).
ACCEPT = "accept"
FIXIT = "fix"
SCOPE_DOWN = "scope_down"
REVISE = "revise"
REDIRECT = "redirect"
ESCALATE = "escalate"
REJECT_UNSAFE = "reject_unsafe"

DISPOSITIONS: frozenset[str] = frozenset(
    {ACCEPT, FIXIT, SCOPE_DOWN, REVISE, REDIRECT, ESCALATE, REJECT_UNSAFE}
)

# Dispositions the LLM is allowed to choose for a BLOCKING finding. It can never
# downgrade a block to accept/fix — only Python's fast-path yields those.
_LLM_BLOCK_CHOICES: frozenset[str] = frozenset(
    {SCOPE_DOWN, REVISE, REDIRECT, ESCALATE, REJECT_UNSAFE}
)

# The non-negotiable safety floor — these always reject, deterministically, with
# no LLM consultation and no auto-fix. (Subset of the severity BLOCK markers
# that are about safety rather than mere unrunnability.)
_SAFETY_FLOOR: tuple[str, ...] = (
    "secret",
    "credential",
    "password",
    "private key",
    "api key",
    "force push",
    " push",
    "merge",
    "reset --hard",
    "rm -rf",
    "sudo",
    "history rewrite",
    "escapes",
    "outside the project",
    "outside the workbench",
    "self-authoriz",
)


def _hits_safety_floor(reason: str) -> bool:
    low = reason.lower()
    return any(marker in low for marker in _SAFETY_FLOOR)


@dataclass(frozen=True)
class Adjudication:
    """A graded decision for a set of findings."""

    disposition: str
    rationale: str
    findings: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    source: str = "deterministic"  # deterministic | ollama | fallback


def adjudicate(
    reasons: list[str],
    *,
    client: Any | None = None,
    model: str | None = None,
    context: str = "",
) -> Adjudication:
    """Decide the disposition for ``reasons``.

    ``client``/``model`` are the optional adjudicator LLM; when absent, blocking
    ambiguity escalates to the owner rather than guessing.
    """
    if not reasons:
        return Adjudication(ACCEPT, "no findings")

    # 1. Safety floor wins, always — never auto-fixed, never LLM-overridable.
    floor = [r for r in reasons if _hits_safety_floor(r)]
    if floor:
        return Adjudication(
            REJECT_UNSAFE, "safety floor violated", findings=floor
        )

    buckets = classify_reasons(reasons)
    blocking = buckets[BLOCK]

    # 2. Deterministic fast-paths (no model needed).
    if not blocking:
        if buckets[FIX]:
            return Adjudication(
                FIXIT,
                "all findings are auto-fixable",
                findings=buckets[FIX],
                skills=["autofix_lint"],
            )
        return Adjudication(
            ACCEPT, "only advisory findings", findings=buckets[WARN]
        )

    # 3. Non-safety blocking findings (syntax/placeholder/forbidden) are the
    #    ambiguous case — consult the adjudicator model, else escalate.
    if client is None or model is None:
        return Adjudication(
            ESCALATE,
            "blocking findings need judgment; no adjudicator model available",
            findings=blocking,
            source="fallback",
        )

    priming = (
        "You are a build adjudicator. A patch has BLOCKING findings that are "
        "not auto-fixable. Decide the smallest safe disposition. Respond with "
        "ONLY a JSON object; never apologize or ask questions. You may NOT "
        "accept or ignore a blocking finding."
    )
    instruction = (
        "Output JSON: {disposition: one of scope_down|revise|redirect|escalate|"
        "reject_unsafe, rationale: string, skills: array of skill names}. "
        "Use 'revise' for incomplete/broken code, 'scope_down' for over-reach, "
        "'redirect' when it diverges from the goal, 'escalate' when unsure, "
        "'reject_unsafe' only for a true safety problem."
    )
    user = "## Blocking findings\n" + "\n".join(f"- {r}" for r in blocking)
    if context:
        user += f"\n\n## Context\n{context}"

    data, note = structured_call(
        client=client,
        model=model,
        system=instruction,
        user=user,
        priming=priming,
        required_keys=("disposition",),
    )
    disposition = str(data.get("disposition", "")) if data else ""
    if disposition not in _LLM_BLOCK_CHOICES:
        # Indeterminate or an attempt to accept/fix a block → escalate to owner.
        return Adjudication(
            ESCALATE,
            f"adjudicator indeterminate ({note})",
            findings=blocking,
            source="fallback",
        )
    assert data is not None  # a valid disposition implies a parsed object
    raw_skills = data.get("skills")
    # Only allow skills from the bounded catalog (the model cannot invent ops).
    skills = (
        [str(s) for s in raw_skills if is_known_skill(str(s))]
        if isinstance(raw_skills, list)
        else []
    )
    return Adjudication(
        disposition,
        str(data.get("rationale", "")).strip(),
        findings=blocking,
        skills=skills,
        source="ollama",
    )
