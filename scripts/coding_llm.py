#!/usr/bin/env python3
"""Cloud coding-model plugins (Claude / OpenAI) for AgentExecutor.

Productization target is Lovable-like: a bounded prompt/seed becomes a
runnable app through Crazy Factory's existing loop. Coding intelligence
is a plugin behind ``AgentExecutor`` — Anthropic and OpenAI first,
other providers later. The same clients serve control intelligence
(continuation, objective, stance, quality). Architect/Planner prefer
this backend when a key is present; Ollama remains the local fallback.

Live HTTP is skipped when no API key is present so CI never calls a
vendor.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-0"
DEFAULT_OPENAI_MODEL = "gpt-4o"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 8192


class CodingLlmError(RuntimeError):
    """Raised when a cloud coding provider cannot complete a chat call."""


def coding_timeout_seconds() -> int:
    """Owner-overridable HTTP timeout, capped so missions cannot hang."""
    raw = (os.environ.get("CRAZY_FACTORY_CODING_TIMEOUT") or "60").strip()
    try:
        return max(1, min(int(raw), 300))
    except ValueError:
        return 60


def anthropic_api_key() -> str:
    return (
        os.environ.get("CRAZY_FACTORY_ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    ).strip()


def openai_api_key() -> str:
    return (
        os.environ.get("CRAZY_FACTORY_OPENAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()


def _cloud_model(provider: str) -> str:
    """Use CRAZY_FACTORY_CODER_MODEL when it looks like a cloud id.

    Ollama tags are ``name:tag`` (colon). Those stay local-only so a
    leftover coder-model env does not get sent to Claude or OpenAI.
    """
    override = (os.environ.get("CRAZY_FACTORY_CODER_MODEL") or "").strip()
    if override and ":" not in override:
        return override
    if provider == "anthropic":
        return DEFAULT_ANTHROPIC_MODEL
    return DEFAULT_OPENAI_MODEL


def _normalize_provider(name: str) -> str:
    raw = (name or "").strip().lower()
    if raw in {"claude", "anthropic"}:
        return "anthropic"
    if raw in {"openai"}:
        return "openai"
    return ""


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = str(exc.reason)
        try:
            detail = exc.read().decode("utf-8")[:300]
        except (OSError, UnicodeDecodeError):
            pass
        raise CodingLlmError(
            f"coding LLM HTTP {exc.code}: {detail}"
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CodingLlmError(f"coding LLM request failed: {exc}") from exc
    if not isinstance(parsed, dict):
        raise CodingLlmError("coding LLM returned a non-object")
    error = parsed.get("error")
    if isinstance(error, dict):
        raise CodingLlmError(str(error.get("message") or error))
    return parsed


def _split_system(
    messages: list[dict[str, str]],
) -> tuple[str, list[dict[str, str]]]:
    systems: list[str] = []
    rest: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        if role == "system":
            if content:
                systems.append(content)
            continue
        mapped = "assistant" if role == "assistant" else "user"
        rest.append({"role": mapped, "content": content})
    if rest and rest[0]["role"] != "user":
        rest.insert(0, {"role": "user", "content": "Continue."})
    if not rest:
        rest = [{"role": "user", "content": "Respond with JSON."}]
    return "\n\n".join(systems), rest


@dataclass
class OpenAIClient:
    """Chat Completions client with the Ollama-shaped ``chat`` return."""

    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = field(default_factory=coding_timeout_seconds)

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        response_format: str | None = None,
    ) -> dict[str, Any]:
        key = openai_api_key()
        if not key:
            raise CodingLlmError("OPENAI_API_KEY is not set")
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": MAX_TOKENS,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        data = _post_json(
            f"{self.base_url.rstrip('/')}/chat/completions",
            payload,
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
            self.timeout_seconds,
        )
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise CodingLlmError("OpenAI response missing choices")
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first, dict) else None
        if not isinstance(message, dict) or message.get("content") is None:
            raise CodingLlmError("OpenAI response missing message content")
        return {"message": {"content": str(message["content"])}}


@dataclass
class AnthropicClient:
    """Messages client with the Ollama-shaped ``chat`` return."""

    base_url: str = "https://api.anthropic.com"
    timeout_seconds: int = field(default_factory=coding_timeout_seconds)

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        response_format: str | None = None,
    ) -> dict[str, Any]:
        key = anthropic_api_key()
        if not key:
            raise CodingLlmError("ANTHROPIC_API_KEY is not set")
        system, rest = _split_system(messages)
        if response_format == "json":
            extra = "Return a single JSON object and nothing else."
            system = f"{system}\n\n{extra}".strip() if system else extra
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "messages": rest,
        }
        if system:
            payload["system"] = system
        data = _post_json(
            f"{self.base_url.rstrip('/')}/v1/messages",
            payload,
            {
                "Content-Type": "application/json",
                "x-api-key": key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            self.timeout_seconds,
        )
        blocks = data.get("content")
        parts: list[str] = []
        if isinstance(blocks, str):
            parts.append(blocks)
        elif isinstance(blocks, list):
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
        text = "".join(parts).strip()
        if not text:
            raise CodingLlmError("Anthropic response had no text")
        return {"message": {"content": text}}


def resolve_coding_backend(
    *, prefer: str | None = None
) -> tuple[str, Any, str] | None:
    """Pick a cloud coding plugin. Prefer Claude when both keys exist.

    Returns ``(provider, client, model)`` or ``None`` when no key is
    configured so callers skip without opening a socket.
    """
    forced = _normalize_provider(
        prefer or os.environ.get("CRAZY_FACTORY_CODING_PROVIDER") or ""
    )
    order = (forced,) if forced else ("anthropic", "openai")
    for name in order:
        pack = _backend_for(name)
        if pack is not None:
            return pack
    return None


def _backend_for(name: str) -> tuple[str, Any, str] | None:
    if name == "anthropic":
        if not anthropic_api_key():
            return None
        return ("anthropic", AnthropicClient(), _cloud_model("anthropic"))
    if name == "openai":
        if not openai_api_key():
            return None
        return ("openai", OpenAIClient(), _cloud_model("openai"))
    return None
