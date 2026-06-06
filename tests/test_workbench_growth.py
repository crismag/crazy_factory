"""Tests for workbench growth metrics + code-birth gating (Issue #38)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from workbench_growth import (  # noqa: E402
    is_code_birth_pending,
    workbench_metrics,
)


def _mk(base: Path, rel: str, content: str = "x = 1\n") -> None:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class GreenfieldTests(unittest.TestCase):
    def test_only_gitkeep_is_greenfield(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _mk(base, "app/.gitkeep", "")
            _mk(base, "tests/.gitkeep", "")
            m = workbench_metrics(tmp)
            self.assertTrue(m.is_greenfield)
            self.assertFalse(m.has_real_code)
            self.assertEqual(m.source_files, 0)
            self.assertEqual(m.test_files, 0)
            self.assertTrue(is_code_birth_pending(tmp))

    def test_empty_py_file_is_not_real_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _mk(base, "src/empty.py", "   \n")
            self.assertTrue(workbench_metrics(tmp).is_greenfield)

    def test_runtime_dirs_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            # Factory runtime python must not count as product code.
            _mk(base, "factory_tasks/planned_task.py", "x = 1\n")
            _mk(base, "factory_state/projects/x/note.py", "y = 2\n")
            self.assertTrue(workbench_metrics(tmp).is_greenfield)


class GrowthTests(unittest.TestCase):
    def test_counts_source_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _mk(base, "src/task_model.py", "class Task:\n    pass\n")
            _mk(base, "src/storage.py", "tasks = []\n")
            _mk(base, "tests/test_storage.py", "def test_x():\n    assert True\n")
            m = workbench_metrics(tmp)
            self.assertEqual(m.source_files, 2)
            self.assertEqual(m.test_files, 1)
            self.assertTrue(m.has_real_code)
            self.assertFalse(m.is_greenfield)
            self.assertFalse(is_code_birth_pending(tmp))
            self.assertGreater(m.lines_of_code, 0)

    def test_test_detected_by_dir_or_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _mk(base, "tests/helpers.py", "z = 1\n")  # in tests/ dir
            _mk(base, "src/test_inline.py", "w = 1\n")  # test_ prefix
            m = workbench_metrics(tmp)
            self.assertEqual(m.test_files, 2)
            self.assertEqual(m.source_files, 0)


if __name__ == "__main__":
    unittest.main()
