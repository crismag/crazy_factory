#!/usr/bin/env python3
"""Provide a small non-streaming Ollama chat client for future phases.

The Phase 1.5 dry-run loop uses this deliberately narrow integration boundary
around Ollama's ``/api/chat`` endpoint for planning-only Architect requests.
Connection failures are converted into a domain-specific exception so the
coordinator can fall back cleanly.

Example:
    Create a client for a later approved integration phase::

        client = OllamaClient()
        response = client.chat(
            model="cogito:14b",
            messages=[{"role": "user", "content": "Summarize the task."}],
        )
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OllamaConnectionError(RuntimeError):
    """Raised when Ollama cannot be reached or returns an invalid response."""


@dataclass
class OllamaClient:
    """Configuration and request helper for Ollama chat calls.

    Attributes:
        base_url: Base URL for a locally running Ollama service.
        timeout_seconds: Maximum time to wait for one response.
        stream: Whether streaming responses are requested. Bootstrap supports
            only ``False``.
    """

    base_url: str = "http://localhost:11434"
    timeout_seconds: int = 120
    stream: bool = False

    def chat(
        self, model: str, messages: list[dict[str, str]]
    ) -> dict[str, Any]:
        """Send one non-streaming chat request to Ollama.

        Args:
            model: Ollama model identifier, such as ``"cogito:14b"``.
            messages: Ordered chat messages. Each dictionary should include
                ``role`` and ``content`` keys.

        Returns:
            Parsed JSON object returned by Ollama.

        Raises:
            OllamaConnectionError: If Ollama is unavailable, times out, returns
                an HTTP error, or returns invalid JSON.
            ValueError: If streaming mode is enabled.
        """
        if self.stream:
            raise ValueError(
                "Bootstrap OllamaClient supports non-streaming mode only"
            )
        # Always send ``stream: false`` because response streaming requires a
        # separate incremental parser and is intentionally outside bootstrap.
        payload = json.dumps(
            {"model": model, "messages": messages, "stream": False}
        ).encode("utf-8")
        request = Request(
            f"{self.base_url.rstrip('/')}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (
            HTTPError,
            URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            raise OllamaConnectionError(
                f"Ollama chat request failed: {exc}"
            ) from exc
