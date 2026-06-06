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

from acceptance_check import (  # noqa: E402
    evaluate_acceptance,
    interface_gaps_for_file,
    is_stub_source,
)


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


class ContractEnforcementTests(unittest.TestCase):
    """9E ST9: a frozen file-contract's declared interfaces must be present."""

    def _with_contract(self, root: Path, interfaces: list[str]) -> dict:
        project = _scaffold(root, a_src="def f():\n    return 1\n")
        _write(
            root / "app/factory_context/file_contracts/src_a_py.json",
            json.dumps({"file": "src/a.py", "interfaces": interfaces}),
        )
        return project

    def test_satisfied_contract_accepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = evaluate_acceptance(
                self._with_contract(root, ["def f()"]), root
            )
            self.assertTrue(report.contracts_satisfied)
            self.assertTrue(report.accepted, report.reasons)

    def test_missing_interface_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = evaluate_acceptance(
                self._with_contract(root, ["def f()", "def g()"]), root
            )
            self.assertFalse(report.contracts_satisfied)
            self.assertFalse(report.accepted)
            self.assertTrue(
                any("missing interface `g`" in g for g in report.contract_gaps)
            )


class PerItemAcceptanceTests(unittest.TestCase):
    """Issue #35: per-item retirement evidence helpers."""

    def _setup(self, root: Path, a_src: str, interfaces: list[str]) -> str:
        app = root / "app"
        _write(app / "src/a.py", a_src)
        _write(
            app / "factory_context/file_contracts/src_a_py.json",
            json.dumps({"file": "src/a.py", "interfaces": interfaces}),
        )
        return str(app)

    def test_interface_gaps_for_file_detects_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self._setup(
                root, "def f():\n    return 1\n", ["def f()", "def g()"]
            )
            gaps = interface_gaps_for_file(
                app, f"{app}/factory_context", "src/a.py"
            )
            self.assertEqual(gaps, ["missing interface `g`"])

    def test_interface_gaps_empty_when_satisfied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self._setup(root, "def f():\n    return 1\n", ["def f()"])
            self.assertEqual(
                interface_gaps_for_file(
                    app, f"{app}/factory_context", "src/a.py"
                ),
                [],
            )

    def test_interface_gaps_empty_when_no_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            _write(app / "src/a.py", "def f():\n    return 1\n")
            self.assertEqual(
                interface_gaps_for_file(
                    str(app), f"{app}/factory_context", "src/a.py"
                ),
                [],
            )

    def test_is_stub_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            _write(app / "src/stub.py", "def f():\n    pass\n")
            _write(app / "src/real.py", "def f():\n    return 1\n")
            self.assertTrue(is_stub_source(str(app), "src/stub.py"))
            self.assertFalse(is_stub_source(str(app), "src/real.py"))
            self.assertFalse(is_stub_source(str(app), "src/missing.py"))


if __name__ == "__main__":
    unittest.main()
