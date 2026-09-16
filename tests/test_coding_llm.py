"""Cloud coding plugins: Claude / OpenAI clients, no live vendor calls."""

from __future__ import annotations

import json
import os
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from coding_llm import (
    AnthropicClient,
    CodingLlmError,
    OpenAIClient,
    anthropic_api_key,
    openai_api_key,
    resolve_coding_backend,
)

_CLOUD_ENV = (
    "CRAZY_FACTORY_EXECUTOR",
    "CRAZY_FACTORY_CODING_PROVIDER",
    "CRAZY_FACTORY_CODER_MODEL",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CRAZY_FACTORY_OPENAI_API_KEY",
    "CRAZY_FACTORY_ANTHROPIC_API_KEY",
)


def _clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _CLOUD_ENV}
    env.update(extra)
    return env


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class KeyResolutionTests(unittest.TestCase):
    def test_factory_alias_beats_empty_vendor_key(self) -> None:
        env = _clean_env(CRAZY_FACTORY_ANTHROPIC_API_KEY="cf-a")
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(anthropic_api_key(), "cf-a")
            self.assertEqual(openai_api_key(), "")

    def test_no_backend_without_keys(self) -> None:
        with patch.dict(os.environ, _clean_env(), clear=True):
            self.assertIsNone(resolve_coding_backend())

    def test_prefers_claude_when_both_keys_present(self) -> None:
        env = _clean_env(ANTHROPIC_API_KEY="a", OPENAI_API_KEY="o")
        with patch.dict(os.environ, env, clear=True):
            pack = resolve_coding_backend()
        self.assertIsNotNone(pack)
        assert pack is not None
        self.assertEqual(pack[0], "anthropic")
        self.assertIsInstance(pack[1], AnthropicClient)
        self.assertEqual(pack[2], "claude-sonnet-4-0")

    def test_openai_only_when_that_key_exists(self) -> None:
        env = _clean_env(OPENAI_API_KEY="o")
        with patch.dict(os.environ, env, clear=True):
            pack = resolve_coding_backend()
        self.assertIsNotNone(pack)
        assert pack is not None
        self.assertEqual(pack[0], "openai")
        self.assertEqual(pack[2], "gpt-4o")

    def test_provider_env_forces_openai_even_with_claude_key(self) -> None:
        env = _clean_env(
            ANTHROPIC_API_KEY="a",
            OPENAI_API_KEY="o",
            CRAZY_FACTORY_CODING_PROVIDER="openai",
        )
        with patch.dict(os.environ, env, clear=True):
            pack = resolve_coding_backend()
        self.assertIsNotNone(pack)
        assert pack is not None
        self.assertEqual(pack[0], "openai")

    def test_forced_openai_without_key_is_none(self) -> None:
        env = _clean_env(ANTHROPIC_API_KEY="a")
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(resolve_coding_backend(prefer="openai"))

    def test_ollama_tag_is_not_sent_as_cloud_model(self) -> None:
        env = _clean_env(
            ANTHROPIC_API_KEY="a",
            CRAZY_FACTORY_CODER_MODEL="qwen2.5-coder:14b",
        )
        with patch.dict(os.environ, env, clear=True):
            pack = resolve_coding_backend()
        assert pack is not None
        self.assertEqual(pack[2], "claude-sonnet-4-0")

    def test_cloud_model_override(self) -> None:
        env = _clean_env(
            OPENAI_API_KEY="o",
            CRAZY_FACTORY_CODER_MODEL="gpt-4.1",
        )
        with patch.dict(os.environ, env, clear=True):
            pack = resolve_coding_backend()
        assert pack is not None
        self.assertEqual(pack[2], "gpt-4.1")


class OpenAIClientTests(unittest.TestCase):
    def test_wraps_choices_as_message_content(self) -> None:
        env = _clean_env(OPENAI_API_KEY="sk-test")
        with (
            patch.dict(os.environ, env, clear=True),
            patch("coding_llm.urlopen") as mock_open,
        ):
            mock_open.return_value = _FakeResp(
                {
                    "choices": [
                        {"message": {"content": '{"files": {"src/a.py": "x"}}'}}
                    ]
                }
            )
            out = OpenAIClient().chat(
                "gpt-4o",
                [{"role": "user", "content": "hi"}],
                response_format="json",
            )
        self.assertEqual(
            out["message"]["content"],
            '{"files": {"src/a.py": "x"}}',
        )
        req = mock_open.call_args[0][0]
        self.assertIsInstance(req, Request)
        self.assertIn("/chat/completions", req.full_url)
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        auth = req.get_header("Authorization")
        self.assertEqual(auth, "Bearer sk-test")

    def test_missing_key_does_not_open_socket(self) -> None:
        with (
            patch.dict(os.environ, _clean_env(), clear=True),
            patch("coding_llm.urlopen") as mock_open,
            self.assertRaises(CodingLlmError),
        ):
            OpenAIClient().chat("gpt-4o", [{"role": "user", "content": "x"}])
        mock_open.assert_not_called()

    def test_http_error_becomes_coding_llm_error(self) -> None:
        env = _clean_env(OPENAI_API_KEY="sk-test")
        err = HTTPError(
            "https://api.openai.com/v1/chat/completions",
            401,
            "unauthorized",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(b'{"error":{"message":"bad key"}}'),
        )
        with (
            patch.dict(os.environ, env, clear=True),
            patch("coding_llm.urlopen", side_effect=err),
            self.assertRaises(CodingLlmError) as caught,
        ):
            OpenAIClient().chat("gpt-4o", [{"role": "user", "content": "x"}])
        self.assertIn("401", str(caught.exception))


class AnthropicClientTests(unittest.TestCase):
    def test_wraps_text_blocks_and_lifts_system(self) -> None:
        env = _clean_env(ANTHROPIC_API_KEY="ant-test")
        with (
            patch.dict(os.environ, env, clear=True),
            patch("coding_llm.urlopen") as mock_open,
        ):
            mock_open.return_value = _FakeResp(
                {
                    "content": [
                        {"type": "text", "text": '{"files": {"src/b.py": "y"}}'}
                    ]
                }
            )
            out = AnthropicClient().chat(
                "claude-sonnet-4-0",
                [
                    {"role": "system", "content": "be json"},
                    {"role": "user", "content": "build it"},
                ],
                response_format="json",
            )
        self.assertEqual(
            out["message"]["content"],
            '{"files": {"src/b.py": "y"}}',
        )
        req = mock_open.call_args[0][0]
        self.assertIn("/v1/messages", req.full_url)
        payload = json.loads(req.data.decode("utf-8"))
        self.assertIn("be json", payload["system"])
        self.assertIn("JSON object", payload["system"])
        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertEqual(req.get_header("X-api-key"), "ant-test")


if __name__ == "__main__":
    unittest.main()
