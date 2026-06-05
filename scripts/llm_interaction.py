#!/usr/bin/env python3
"""Robust structured LLM role interaction for Crazy Factory (9E.7).

A model can refuse or reply conversationally instead of doing the role's job —
and the factory must **never use such a reply**. This module wraps a role call
with: pre-prompt priming (tell the model the exact response shape up front),
enforced JSON output, response **classification** (know a bad reply when we see
one), and a bounded **reframe-retry** loop that hardens the answer — falling back
to the caller's deterministic path when no usable structured reply is produced.

Used first by the planner/architect (the roles still on free-form chat); the
coder/contract/test roles can route through it for uniform refusal handling.
"""

from __future__ import annotations

import json
from typing import Any

from json_parsing import strip_code_fence
from ollama_client import OllamaConnectionError

# Conversational/refusal tells. If any appears, the reply is NOT a role result.
REFUSAL_MARKERS: tuple[str, ...] = (
    "i'm sorry",
    "i am sorry",
    "i apologize",
    "i cannot",
    "i can't",
    "i can not",
    "unable to",
    "cannot complete",
    "can't complete",
    "cannot assist",
    "can't assist",
    "as an ai",
    "as a language model",
    "feel free to ask",
    "if you have any questions",
    "could you clarify",
    "please provide more",
)


def classify_response(text: str) -> str:
    """Classify a raw model reply: ``empty | refusal | json | prose``."""
    stripped = (text or "").strip()
    if not stripped:
        return "empty"
    low = stripped.lower()
    if any(marker in low for marker in REFUSAL_MARKERS):
        return "refusal"
    if strip_code_fence(stripped).lstrip().startswith("{"):
        return "json"
    return "prose"


def _parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(strip_code_fence(text.strip()))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _reframe(kind: str, required_keys: tuple[str, ...]) -> str:
    """Build the correction message that hardens the next attempt."""
    keys = ", ".join(required_keys) or "the required keys"
    base = (
        "Your previous reply was not a valid result for this role: it was "
        f"{kind}. Do NOT apologize, refuse, or ask questions. Respond with "
        f"ONLY a single JSON object containing: {keys}. If information is "
        "missing, choose the smallest safe next step rather than asking."
    )
    return base


def structured_call(
    *,
    client: Any,
    model: str,
    system: str,
    user: str,
    priming: str,
    required_keys: tuple[str, ...] = (),
    retries: int = 2,
) -> tuple[dict[str, Any] | None, str]:
    """Prime + JSON call + classify + bounded reframe-retry.

    Args:
        client: An ``OllamaClient`` (so callers control base_url/timeout).
        model: Model name.
        system: The role's task instruction (appended after the priming).
        user: The (curated) user content.
        priming: Pre-prompt conditioning — the expected response shape + the
            "no refusals/questions" contract, set BEFORE the task.
        required_keys: Keys the parsed object must contain to be usable.
        retries: Reframe-retry budget after the first attempt.

    Returns:
        ``(data, note)`` where ``data`` is the validated object, or
        ``(None, note)`` when no usable structured reply was produced (the
        caller then uses its deterministic fallback — never a refusal/garbage).
    """
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": f"{priming.strip()}\n\n{system.strip()}",
        },
        {"role": "user", "content": user},
    ]
    for attempt in range(1, retries + 2):
        try:
            response = client.chat(model, messages, response_format="json")
            content = str(response["message"]["content"]).strip()
        except (KeyError, TypeError, ValueError, OllamaConnectionError) as exc:
            return None, f"ollama_unavailable: {exc}"

        kind = classify_response(content)
        if kind in ("json", "prose"):
            data = _parse_json_object(content)
            if data is not None and all(k in data for k in required_keys):
                return data, f"ok (attempt {attempt})"
            kind = "malformed" if data is None else "missing_keys"

        # Bad reply: harden via reframe and retry (bounded).
        messages.append({"role": "assistant", "content": content})
        messages.append(
            {"role": "user", "content": _reframe(kind, required_keys)}
        )

    return None, f"non_actionable after {retries + 1} attempt(s)"
