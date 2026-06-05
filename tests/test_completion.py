"""Tests for the project completion engine.

The engine decomposes a goal into a checklist, surfaces the next open item for
planning, and ticks an item when a fresh build validates green — so the loop
converges to a finished project and satisfaction can be reached.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from completion import (  # noqa: E402
    build_checklist_items,
    checklist_focus,
    initial_checklist_markdown,
    is_complete,
    items_from_required_files,
    mark_first_open_done,
    next_open_item,
    parse_checklist,
    render_checklist,
    synthesize_checklist,
)
from ollama_client import OllamaConnectionError  # noqa: E402
from satisfaction_checker import evaluate_satisfaction  # noqa: E402

_MODELS = {"models": {"planner": "cogito:14b"}}
_FACTORY = {"ollama": {"base_url": "http://x", "timeout_seconds": 1}}


def _ai(items: list[str]) -> dict:
    return {"message": {"content": json.dumps(items)}}


class ParseTickTests(unittest.TestCase):
    def test_parse_open_and_done(self) -> None:
        md = "# Master Checklist\n\n- [ ] a\n- [x] b\n- [ ] c\n"
        items = parse_checklist(md)
        self.assertEqual([i.text for i in items], ["a", "b", "c"])
        self.assertEqual([i.done for i in items], [False, True, False])

    def test_next_open_and_complete(self) -> None:
        items = parse_checklist("- [x] a\n- [ ] b\n")
        self.assertEqual(next_open_item(items).text, "b")
        self.assertFalse(is_complete(items))
        self.assertTrue(is_complete(parse_checklist("- [x] a\n- [x] b\n")))
        # An empty checklist is NOT complete (nothing defined yet).
        self.assertFalse(is_complete([]))

    def test_mark_first_open_done_ticks_in_order(self) -> None:
        md = "- [ ] a\n- [ ] b\n"
        md, done = mark_first_open_done(md)
        self.assertEqual(done, "a")
        self.assertIn("- [x] a", md)
        self.assertIn("- [ ] b", md)
        md, done = mark_first_open_done(md)
        self.assertEqual(done, "b")
        # Nothing left open -> no-op.
        md, done = mark_first_open_done(md)
        self.assertIsNone(done)

    def test_render_roundtrip(self) -> None:
        items = parse_checklist("- [ ] x\n- [x] y\n")
        self.assertEqual(parse_checklist(render_checklist(items)), items)


class DecomposeTests(unittest.TestCase):
    def test_synthesize_pulls_bullets_skips_labels(self) -> None:
        text = (
            "# Goal\n\nWhat to build:\n- add a task\n- delete a task\n"
            "1. save to JSON\nConstraints:\n- nothing extra\n"
        )
        items = synthesize_checklist(text)
        self.assertIn("add a task", items)
        self.assertIn("save to JSON", items)
        self.assertNotIn("What to build", items)  # label, skipped

    def test_build_uses_ai_when_available(self) -> None:
        with patch(
            "completion.OllamaClient.chat",
            return_value=_ai(["data model", "storage", "ui"]),
        ):
            items = build_checklist_items(
                "goal", models_config=_MODELS, factory_config=_FACTORY
            )
        self.assertEqual(items, ["data model", "storage", "ui"])

    def test_build_falls_back_to_synth_when_ai_down(self) -> None:
        with patch(
            "completion.OllamaClient.chat",
            side_effect=OllamaConnectionError("down"),
        ):
            items = build_checklist_items(
                "- add task\n- delete task\n",
                models_config=_MODELS,
                factory_config=_FACTORY,
            )
        self.assertEqual(items, ["add task", "delete task"])

    def test_build_always_returns_at_least_one_item(self) -> None:
        # No configs and no bullets -> a generic definition of done.
        items = build_checklist_items("prose with no bullets")
        self.assertEqual(len(items), 1)

    def test_required_files_drive_deterministic_checklist(self) -> None:
        # When the contract declares required_files, decomposition is
        # deterministic + foundation-first and never calls the model.
        files = [
            "src/task_model.py",
            "tests/test_task_model.py",
            "src/storage.py",
        ]
        items = items_from_required_files(files)
        self.assertEqual(len(items), 3)
        self.assertIn("src/task_model.py", items[0])
        self.assertIn("Implement", items[0])  # source -> implement
        self.assertIn("Write", items[1])  # test file -> write tests
        # build_checklist_items prefers required_files over any AI call.
        with patch(
            "completion.OllamaClient.chat",
            side_effect=AssertionError("must not call model when files given"),
        ):
            built = build_checklist_items(
                "goal",
                models_config=_MODELS,
                factory_config=_FACTORY,
                required_files=files,
            )
        self.assertEqual(built, items)

    def test_initial_markdown_is_all_open(self) -> None:
        md = initial_checklist_markdown(
            "- one\n- two\n", models_config=None, factory_config=None
        )
        items = parse_checklist(md)
        self.assertEqual([i.done for i in items], [False, False])


class FocusTests(unittest.TestCase):
    def test_focus_names_next_open_item(self) -> None:
        focus = checklist_focus(
            "- [x] done one\n- [ ] build two\n- [ ] three\n"
        )
        self.assertIn("build two", focus)
        self.assertIn("single next OPEN item", focus)

    def test_focus_reports_completion_when_all_done(self) -> None:
        focus = checklist_focus("- [x] a\n- [x] b\n")
        self.assertIn("complete", focus.lower())

    def test_focus_empty_for_no_checklist(self) -> None:
        self.assertEqual(checklist_focus(""), "")


class SatisfactionIntegrationTests(unittest.TestCase):
    """The ticked checklist drives the existing satisfaction gate."""

    def test_open_items_block_satisfaction(self) -> None:
        v = evaluate_satisfaction(
            checklist_text="- [x] a\n- [ ] b\n",
            project_state={
                "last_validation_status": "passed",
                "current_blocker": None,
            },
        )
        self.assertFalse(v.satisfied)

    def test_all_done_and_green_is_satisfied(self) -> None:
        v = evaluate_satisfaction(
            checklist_text="- [x] a\n- [x] b\n",
            project_state={
                "last_validation_status": "passed",
                "current_blocker": None,
            },
        )
        self.assertTrue(v.satisfied, v.reasons)


class FocusFileTokenTests(unittest.TestCase):
    """9D.5: the retirement gate extracts the focus item's target file."""

    def test_picks_first_open_item_file(self) -> None:
        import factory_advance as fa

        md = (
            "# Master Checklist\n\n"
            "- [x] Write tests/test_task_model.py with unit tests; "
            "every test must pass.\n"
            "- [ ] Implement src/storage.py with the functionality the "
            "project goal assigns to it.\n"
        )
        self.assertEqual(fa._focus_file_token(md), "src/storage.py")

    def test_none_when_no_open_file_item(self) -> None:
        import factory_advance as fa

        self.assertIsNone(fa._focus_file_token("- [x] all done\n"))
        self.assertIsNone(fa._focus_file_token("- [ ] write the docs\n"))

    def test_item_evidence_record(self) -> None:
        import factory_advance as fa

        rec = fa.build_item_evidence(
            item="Implement src/storage.py",
            focus_file="src/storage.py",
            validation_status="passed",
            applied_files=["src/storage.py"],
            missing_required_files=[],
        )
        self.assertEqual(rec["status"], "complete")
        self.assertEqual(rec["focus_file"], "src/storage.py")
        self.assertEqual(rec["evidence"]["validation"], "passed")
        self.assertIn("src/storage.py", rec["evidence"]["files"])


if __name__ == "__main__":
    unittest.main()
