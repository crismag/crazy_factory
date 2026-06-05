"""Tests for robust structured LLM role interaction (9E.7).

A bad reply (refusal/empty/malformed) must never be returned as a result — it
is classified, hardened via reframe-retry, and ultimately yields None so the
caller falls back deterministically.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from llm_interaction import classify_response, structured_call  # noqa: E402
from ollama_client import OllamaConnectionError  # noqa: E402

_REFUSAL = (
    "I'm sorry, I can't complete the request as it appears to be a task "
    "contract and validation report. Feel free to ask!"
)


class FakeClient:
    """Returns scripted replies (or raises) per chat() call."""

    def __init__(self, replies: list) -> None:
        self._replies = replies
        self.calls = 0

    def chat(self, model: object, messages: object, **_: object) -> dict:
        reply = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        if isinstance(reply, Exception):
            raise reply
        return {"message": {"content": reply}}


def _call(client: FakeClient, *, required_keys=("next_action",)):
    return structured_call(
        client=client,
        model="m",
        system="output the action",
        user="context",
        priming="respond with only json",
        required_keys=required_keys,
    )


class ClassifyTests(unittest.TestCase):
    def test_cases(self) -> None:
        self.assertEqual(classify_response(""), "empty")
        self.assertEqual(classify_response("   "), "empty")
        self.assertEqual(classify_response(_REFUSAL), "refusal")
        self.assertEqual(classify_response('{"next_action": "x"}'), "json")
        self.assertEqual(classify_response('```json\n{"a":1}\n```'), "json")
        self.assertEqual(classify_response("just some prose"), "prose")


class StructuredCallTests(unittest.TestCase):
    def test_immediate_valid(self) -> None:
        c = FakeClient(['{"next_action": "Implement src/x.py"}'])
        data, note = _call(c)
        self.assertEqual(data, {"next_action": "Implement src/x.py"})
        self.assertEqual(c.calls, 1)
        self.assertIn("attempt 1", note)

    def test_refusal_then_valid_hardens(self) -> None:
        c = FakeClient([_REFUSAL, '{"next_action": "do it"}'])
        data, note = _call(c)
        self.assertEqual(data, {"next_action": "do it"})
        self.assertEqual(c.calls, 2)  # retried after the refusal

    def test_all_refusals_returns_none(self) -> None:
        c = FakeClient([_REFUSAL])  # same refusal every call
        data, note = _call(c)
        self.assertIsNone(data)
        self.assertEqual(c.calls, 3)  # 1 + 2 retries
        self.assertIn("non_actionable", note)

    def test_ollama_unavailable_returns_none(self) -> None:
        c = FakeClient([OllamaConnectionError("offline")])
        data, note = _call(c)
        self.assertIsNone(data)
        self.assertIn("ollama_unavailable", note)

    def test_missing_required_key_rejected(self) -> None:
        c = FakeClient(['{"something_else": 1}'])  # valid json, wrong shape
        data, note = _call(c)
        self.assertIsNone(data)
        self.assertIn("non_actionable", note)


if __name__ == "__main__":
    unittest.main()
