"""Tests for the Phase 9D deterministic acceptance checker.

A project is accepted only when required files exist, no source file is a stub,
the checklist is complete, and the last validation passed — so the autopilot can
exit 0 only on a genuinely finished app.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from acceptance_check import evaluate_acceptance  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _scaffold(
    root: Path,
    *,
    a_src: str = "def f():\n    return 1\n",
    create_b: bool = True,
    checklist: str = "- [x] Implement src/a.py\n- [x] Implement src/b.py\n",
    validation_status: str = "passed",
) -> dict[str, object]:
    app = root / "app"
    tasks = app / "factory_tasks"
    _write(
        app / "architecture.json",
        json.dumps({"required_files": ["src/a.py", "src/b.py"]}),
    )
    _write(app / "src/a.py", a_src)
    if create_b:
        _write(app / "src/b.py", "VALUE = 2\n")
    _write(tasks / "MASTER_CHECKLIST.md", "# Master Checklist\n\n" + checklist)
    _write(
        tasks / "validation_result.json",
        json.dumps({"status": validation_status, "checks": []}),
    )
    return {"app_path": str(app), "task_root": str(tasks), "name": "demo"}


class AcceptanceTests(unittest.TestCase):
    def test_accepted_when_all_green(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = evaluate_acceptance(_scaffold(root), root)
            self.assertTrue(report.accepted, report.reasons)

    def test_missing_required_file_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = evaluate_acceptance(_scaffold(root, create_b=False), root)
            self.assertFalse(report.accepted)
            self.assertIn("src/b.py", report.missing_files)

    def test_stub_source_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = evaluate_acceptance(
                _scaffold(root, a_src="def f():\n    pass\n"), root
            )
            self.assertFalse(report.accepted)
            self.assertIn("src/a.py", report.stub_files)

    def test_open_checklist_item_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = evaluate_acceptance(
                _scaffold(
                    root,
                    checklist="- [x] Implement src/a.py\n- [ ] Implement src/b.py\n",
                ),
                root,
            )
            self.assertFalse(report.accepted)
            self.assertFalse(report.checklist_complete)

    def test_failed_validation_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = evaluate_acceptance(
                _scaffold(root, validation_status="failed"), root
            )
            self.assertFalse(report.accepted)
            self.assertFalse(report.validation_passed)


if __name__ == "__main__":
    unittest.main()
