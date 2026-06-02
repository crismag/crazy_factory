#!/usr/bin/env python3
"""Small non-streaming Ollama client reserved for later factory phases."""

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
    base_url: str = "http://localhost:11434"
    timeout_seconds: int = 120
    stream: bool = False

    def chat(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Call Ollama /api/chat in non-streaming mode."""
        if self.stream:
            raise ValueError("Bootstrap OllamaClient supports non-streaming mode only")
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
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OllamaConnectionError(f"Ollama chat request failed: {exc}") from exc
