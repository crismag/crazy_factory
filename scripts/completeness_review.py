#!/usr/bin/env python3
"""Phase 9D Layer 2 — pre-apply acceptance-completeness reviewer.

The deterministic patch gate (``proposal_applier._is_placeholder_body`` + path/
import/name rules) blocks the worst output — bare ``pass`` stubs, forbidden
paths. It cannot tell whether a *technically valid* patch actually satisfies the
task's behaviors (a ``Task`` that's constructor-only; one happy-path test). This
reviewer fills that gap, mirroring ``contract_review``: a deterministic floor
first, then the stronger reviewer model, returning ``valid | revise_proposal |
reject`` with the missing behaviors named.

Safety rules:

- **Floor first, and it can only tighten.** A deterministic signal (criteria
  exist but the patch ships no test) yields ``revise_proposal`` regardless of the
  model.
- **No fake pass when the model is down.** If the reviewer model is unavailable
  or malformed, fall back to ``floor_only``: do NOT block on behaviour we could
  not assess (the deterministic gates already ran), so an Ollama outage never
  wedges the pipeline — it degrades to today's behaviour.
- **Loop safety is inherited.** A blocking verdict routes through the existing
  ``application_rejected`` → recovery path, which is already attempt-bounded and
  parks on exhaustion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from json_parsing import coerce_str_list, strip_code_fence
from ollama_client import OllamaClient, OllamaConnectionError

DECISION_VALID = "valid"
DECISION_REVISE = "revise_proposal"
DECISION_REJECT = "reject"

_MAX_CONTENT_CHARS = 4000


@dataclass(frozen=True)
class ReviewVerdict:
    """Outcome of the completeness review."""

    decision: str
    missing_behaviors: list[str] = field(default_factory=list)
    missing_tests: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    source: str = "skipped"  # skipped | floor | ollama | floor_only

    @property
    def blocking(self) -> bool:
        """True when the patch must not be applied as-is."""
        return self.decision in {DECISION_REVISE, DECISION_REJECT}


def _has_test_file(patch_files: list[tuple[str, str]]) -> bool:
    """True when the patch creates/modifies at least one test file."""
    return any(
        "test" in path.lower().rsplit("/", 1)[-1] for path, _ in patch_files
    )


def _request_ai_review(
    *,
    acceptance_criteria: list[str],
    required_tests: list[str],
    patch_files: list[tuple[str, str]],
    models_config: dict[str, Any],
    factory_config: dict[str, Any],
    retries: int,
) -> ReviewVerdict | None:
    """Ask the reviewer model to judge completeness; ``None`` if unavailable."""
    models = models_config.get("models", {})
    model = str(models.get("reviewer") or models.get("planner") or "")
    ollama = factory_config.get("ollama", {})
    if not model or not ollama:
        return None
    client = OllamaClient(
        base_url=str(ollama.get("base_url", "http://localhost:11434")),
        timeout_seconds=int(ollama.get("timeout_seconds", 120)),
        stream=bool(ollama.get("stream", False)),
    )
    instruction = (
        "You are a strict completeness reviewer. Decide whether the proposed "
        "code FULLY satisfies the acceptance criteria, with a real test per "
        'behavior. Return ONLY a JSON object: {"verdict": '
        '"valid|revise_proposal|reject", "missing_behaviors": [..], '
        '"missing_tests": [..]}. Use revise_proposal when behaviors or tests '
        "are missing or only happy-path; reject only when the patch is "
        "fundamentally wrong for the task. Judge ONLY against the criteria "
        "given; do not invent scope."
    )
    files_block = "\n\n".join(
        f"### {path}\n```\n{content[:_MAX_CONTENT_CHARS]}\n```"
        for path, content in patch_files
    )
    user = (
        "## Acceptance criteria\n"
        + "\n".join(f"- {c}" for c in acceptance_criteria)
        + (
            "\n\n## Required tests\n"
            + "\n".join(f"- {t}" for t in required_tests)
            if required_tests
            else ""
        )
        + f"\n\n## Proposed files\n\n{files_block}"
    )
    for _ in range(max(1, retries)):
        try:
            response = client.chat(
                model,
                [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": user},
                ],
                response_format="json",
            )
            data = json.loads(
                strip_code_fence(str(response["message"]["content"]).strip())
            )
            if not isinstance(data, dict):
                continue
            verdict = str(data.get("verdict") or "").strip()
            if verdict not in {
                DECISION_VALID,
                DECISION_REVISE,
                DECISION_REJECT,
            }:
                continue
            missing_b = coerce_str_list(data.get("missing_behaviors"))
            missing_t = coerce_str_list(data.get("missing_tests"))
            return ReviewVerdict(
                decision=verdict,
                missing_behaviors=missing_b,
                missing_tests=missing_t,
                reasons=(
                    [f"missing behavior: {b}" for b in missing_b]
                    + [f"missing test: {t}" for t in missing_t]
                )
                or ([] if verdict == DECISION_VALID else ["completeness gap"]),
                source="ollama",
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            OllamaConnectionError,
            json.JSONDecodeError,
        ):
            continue
    return None


def review_completeness(
    *,
    acceptance_criteria: list[str],
    patch_files: list[tuple[str, str]],
    required_tests: list[str] | None = None,
    models_config: dict[str, Any] | None = None,
    factory_config: dict[str, Any] | None = None,
    retries: int = 2,
) -> ReviewVerdict:
    """Floor-first completeness review of a patch against acceptance criteria.

    Returns ``valid`` (source ``skipped``) when there are no criteria to review
    against. A deterministic floor can force ``revise_proposal``; otherwise the
    reviewer model decides. When the model is unavailable/malformed, returns a
    non-blocking ``floor_only`` verdict (never a fake pass that hides a gap, but
    also never a block on behaviour it could not assess).
    """
    if not acceptance_criteria:
        return ReviewVerdict(decision=DECISION_VALID, source="skipped")

    # Deterministic floor: criteria exist but the patch ships no test at all.
    if patch_files and not _has_test_file(patch_files):
        return ReviewVerdict(
            decision=DECISION_REVISE,
            reasons=[
                "Acceptance criteria require tests, but the patch includes no "
                "test file. Add a test for each required behavior."
            ],
            source="floor",
        )

    ai = (
        _request_ai_review(
            acceptance_criteria=acceptance_criteria,
            required_tests=required_tests or [],
            patch_files=patch_files,
            models_config=models_config,
            factory_config=factory_config,
            retries=retries,
        )
        if models_config and factory_config
        else None
    )
    if ai is not None:
        return ai
    # Model unavailable: do not block on un-assessable behaviour, do not fake a
    # pass — the deterministic gates already ran.
    return ReviewVerdict(decision=DECISION_VALID, source="floor_only")
