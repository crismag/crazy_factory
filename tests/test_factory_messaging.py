"""Tests for the factory messaging layer (the factory's "voice")."""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import factory_messaging as msg  # noqa: E402


class MessagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = msg.get_verbosity()
        msg.set_verbosity(10)  # show everything for assertions

    def tearDown(self) -> None:
        msg.set_verbosity(self._saved)

    def _out(self, fn) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn()
        return buf.getvalue()

    def _err(self, fn) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            fn()
        return buf.getvalue()

    def test_iprint_outputs_info(self) -> None:
        out = self._out(lambda: msg.iprint("hello"))
        self.assertIn("[INFO]", out)
        self.assertIn("hello", out)

    def test_wprint_outputs_warn_to_stderr(self) -> None:
        err = self._err(lambda: msg.wprint("careful"))
        self.assertIn("[WARN]", err)
        self.assertIn("careful", err)

    def test_eprint_outputs_error_to_stderr(self) -> None:
        err = self._err(lambda: msg.eprint("bad"))
        self.assertIn("[ERROR]", err)
        self.assertIn("bad", err)

    def test_cprint_outputs_cmd(self) -> None:
        out = self._out(lambda: msg.cprint("python -m pytest"))
        self.assertIn("[CMD]", out)
        self.assertIn("python -m pytest", out)

    def test_post_message_is_a_banner_with_fields(self) -> None:
        # post_message is reserved for emphasized banner events: a framed block
        # with each field as an indented "Label:\n    value" stanza.
        err = self._err(
            lambda: msg.post_message(
                "CONTRACT_REJECTED",
                "Contract rejected",
                reason="write outside allowed dir",
                action="review proposal",
            )
        )
        self.assertIn("=" * 80, err)  # heavy frame for a rejection
        self.assertIn("[CONTRACT REJECTED] Contract rejected", err)
        self.assertIn("Reason:", err)
        self.assertIn("    write outside allowed dir", err)  # indented value
        self.assertIn("Action:", err)
        self.assertIn("    review proposal", err)

    def test_banner_frame_char_reflects_severity(self) -> None:
        # warnings use '-', success/approval use '+', errors use '='.
        warn = self._err(lambda: msg.post_message("WARNING", "w", impact="x"))
        self.assertIn("-" * 80, warn)
        ok = self._out(lambda: msg.post_message("SUCCESS", "done", checks="x"))
        self.assertIn("+" * 80, ok)

    def test_banner_renders_custom_fields_in_order(self) -> None:
        out = self._out(
            lambda: msg.post_message(
                "VALIDATION_PASSED", "ok", check="syntax", duration="2s"
            )
        )
        # Custom keys become Title-Case labels, in caller order.
        self.assertIn("Check:", out)
        self.assertIn("Duration:", out)
        self.assertLess(out.index("Check:"), out.index("Duration:"))

    def test_post_message_routes_error_banner_to_stderr(self) -> None:
        # Error-class banners go to stderr, not stdout.
        self.assertEqual(self._out(lambda: msg.post_message("error", "x")), "")
        self.assertIn("[ERROR]", self._err(lambda: msg.post_message("e", "x")))

    def test_alias_normalization(self) -> None:
        # "warn"/"w" both resolve to WARNING.
        self.assertIn(
            "[WARN]", self._err(lambda: msg.post_message("warn", "a"))
        )
        self.assertIn("[WARN]", self._err(lambda: msg.post_message("w", "b")))

    def test_unknown_type_falls_back_safely(self) -> None:
        # An unknown type prints with its own upper-cased label (no crash).
        out = self._out(lambda: msg.post_message("milestone", "done"))
        self.assertIn("[MILESTONE]", out)
        self.assertIn("done", out)

    def test_post_message_items_checklist(self) -> None:
        out = self._out(
            lambda: msg.post_message("reject", "proposal", items=["a", "b"])
        )
        self.assertIn("[REJECT] proposal", out)
        self.assertIn("- a", out)
        self.assertIn("- b", out)

    def test_json_print(self) -> None:
        out = self._out(
            lambda: msg.json_print({"project": "x", "status": "failed"})
        )
        self.assertIn('"project": "x"', out)
        self.assertIn('"status": "failed"', out)

    def test_table_print_list_of_dicts(self) -> None:
        out = self._out(
            lambda: msg.table_print(
                [{"name": "a", "ok": "yes"}, {"name": "b", "ok": "no"}]
            )
        )
        self.assertIn("name", out)
        self.assertIn("ok", out)
        self.assertIn("a", out)
        self.assertIn("no", out)

    def test_table_print_list_of_lists(self) -> None:
        out = self._out(
            lambda: msg.table_print(
                [["1", "x"], ["2", "y"]], headers=["id", "val"]
            )
        )
        self.assertIn("id", out)
        self.assertIn("val", out)
        self.assertIn("y", out)

    def test_key_value_and_sections(self) -> None:
        kv = self._out(
            lambda: msg.key_value_print(
                {"Project": "ttt", "Phase": "validation"}
            )
        )
        self.assertIn("Project", kv)
        self.assertIn("ttt", kv)
        self.assertIn("====", self._out(lambda: msg.banner_print("Summary")))
        self.assertIn(
            "Summary", self._out(lambda: msg.section_print("Summary"))
        )

    def test_silent_suppresses_everything(self) -> None:
        msg.set_verbosity(0)
        self.assertEqual(self._out(lambda: msg.iprint("x")), "")
        self.assertEqual(self._err(lambda: msg.eprint("x")), "")
        self.assertEqual(self._out(lambda: msg.json_print({"a": 1})), "")

    def test_debug_gated_by_verbosity(self) -> None:
        msg.set_verbosity(4)
        self.assertEqual(self._out(lambda: msg.dprint("dbg")), "")
        msg.set_verbosity(7)
        self.assertIn("[DEBUG]", self._out(lambda: msg.dprint("dbg")))


if __name__ == "__main__":
    unittest.main()
