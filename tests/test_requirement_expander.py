"""Tests for Phase 9D Layer 1 — seed-derived requirement expansion.

Expansion must enrich the focus with concrete behaviors when the model is
available, freeze the contract (one expansion per file), and degrade to a
generic fallback when the model is down or malformed — never regressing the flow.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from ollama_client import OllamaConnectionError  # noqa: E402
from requirement_expander import (  # noqa: E402
    expand_focus_requirements,
    fallback_spec,
    load_or_expand,
    render_focus_with_spec,
    spec_from_dict,
    spec_to_dict,
)

_MODELS = {"models": {"planner": "cogito:14b"}}
_FACTORY = {"ollama": {"base_url": "http://x", "timeout_seconds": 1}}

_SPEC_JSON = {
    "purpose": "JSON persistence layer",
    "required_behaviors": [
        "save tasks to data/tasks.json",
        "missing file returns empty list",
        "corrupt JSON handled without crashing",
    ],
    "required_tests": ["test_roundtrip", "test_missing", "test_corrupt"],
    "interfaces": ["save_tasks(tasks)", "load_tasks()"],
    "dependencies": ["src/task_model.py"],
    "done_definition": ["pytest passes"],
}


def _ai(obj: dict) -> dict:
    return {"message": {"content": json.dumps(obj)}}


class ExpandTests(unittest.TestCase):
    def test_ai_spec_is_used(self) -> None:
        with patch(
            "requirement_expander.OllamaClient.chat",
            return_value=_ai(_SPEC_JSON),
        ):
            spec = expand_focus_requirements(
                seed_context="build a task board",
                focus_file="src/storage.py",
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(spec.source, "ollama")
        self.assertIn("save tasks to data/tasks.json", spec.required_behaviors)
        self.assertEqual(spec.file, "src/storage.py")

    def test_ollama_down_falls_back(self) -> None:
        with patch(
            "requirement_expander.OllamaClient.chat",
            side_effect=OllamaConnectionError("offline"),
        ):
            spec = expand_focus_requirements(
                seed_context="x",
                focus_file="src/storage.py",
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(spec.source, "fallback")
        self.assertEqual(spec.required_behaviors, [])

    def test_malformed_no_behaviors_falls_back(self) -> None:
        with patch(
            "requirement_expander.OllamaClient.chat",
            return_value=_ai({"purpose": "x", "required_behaviors": []}),
        ):
            spec = expand_focus_requirements(
                seed_context="x",
                focus_file="src/storage.py",
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(spec.source, "fallback")

    def test_no_config_returns_fallback(self) -> None:
        spec = expand_focus_requirements(
            seed_context="x", focus_file="src/a.py"
        )
        self.assertEqual(spec.source, "fallback")


class FreezeTests(unittest.TestCase):
    def _project(self, root: Path) -> dict[str, object]:
        return {"context_root": str(root / "factory_context")}

    def test_first_expands_then_freezes_and_reuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self._project(root)

            with patch(
                "requirement_expander.OllamaClient.chat",
                return_value=_ai(_SPEC_JSON),
            ) as chat:
                first = load_or_expand(
                    focus_file="src/storage.py",
                    seed_context="build a task board",
                    architecture_brief="",
                    project=project,
                    root=root,
                    models_config=_MODELS,
                    factory_config=_FACTORY,
                )
                self.assertEqual(chat.call_count, 1)
            self.assertEqual(first.source, "ollama")
            frozen = (
                root / "factory_context/file_contracts/src_storage_py.json"
            )
            self.assertTrue(frozen.is_file())

            # Second call must NOT hit the model — load the frozen contract.
            def _boom(*_a: object, **_k: object) -> dict:
                raise AssertionError("model must not be called when frozen")

            with patch(
                "requirement_expander.OllamaClient.chat", side_effect=_boom
            ):
                second = load_or_expand(
                    focus_file="src/storage.py",
                    seed_context="build a task board",
                    architecture_brief="",
                    project=project,
                    root=root,
                    models_config=_MODELS,
                    factory_config=_FACTORY,
                )
            self.assertEqual(
                second.required_behaviors, first.required_behaviors
            )


class RenderTests(unittest.TestCase):
    def test_render_includes_behaviors(self) -> None:
        spec = spec_from_dict({"file": "src/storage.py", **_SPEC_JSON})
        out = render_focus_with_spec("- [ ] Implement src/storage.py", spec)
        self.assertIn("File contract for src/storage.py", out)
        self.assertIn("missing file returns empty list", out)
        self.assertIn("test_roundtrip", out)

    def test_fallback_leaves_focus_unchanged(self) -> None:
        spec = fallback_spec("src/storage.py")
        focus = "- [ ] Implement src/storage.py"
        self.assertEqual(render_focus_with_spec(focus, spec), focus)

    def test_spec_dict_roundtrip(self) -> None:
        spec = spec_from_dict({"file": "src/x.py", **_SPEC_JSON})
        self.assertEqual(spec_from_dict(spec_to_dict(spec)), spec)


if __name__ == "__main__":
    unittest.main()
