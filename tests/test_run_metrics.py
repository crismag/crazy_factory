"""Tests for the Phase 9D run-quality metrics harness."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from run_metrics import collect_metrics, render_metrics_md  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(root: Path) -> dict[str, object]:
    app = root / "app"
    tasks = app / "factory_tasks"
    _write(
        app / "architecture.json",
        json.dumps({"required_files": ["src/a.py", "src/b.py"]}),
    )
    _write(
        app / "src/a.py", "def f():\n    return 1\n"
    )  # b missing → not accepted
    _write(
        tasks / "MASTER_CHECKLIST.md",
        "# Master Checklist\n\n- [x] Implement src/a.py\n- [ ] Implement src/b.py\n",
    )
    _write(
        tasks / "validation_result.json",
        json.dumps(
            {
                "status": "failed",
                "checks": [
                    {"command": "pytest", "status": "failed", "detail": "x"}
                ],
            }
        ),
    )
    _write(
        tasks / "checklist_evidence.json",
        json.dumps({"items": [{"item": "Implement src/a.py"}]}),
    )
    return {"app_path": str(app), "task_root": str(tasks), "name": "demo"}


class MetricsTests(unittest.TestCase):
    def test_snapshot_reflects_partial_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m = collect_metrics(_project(root), root)
            self.assertFalse(m["accepted"])
            self.assertEqual(m["checklist"]["total"], 2)
            self.assertEqual(m["checklist"]["done"], 1)
            self.assertEqual(m["checklist"]["complete_pct"], 50)
            self.assertEqual(m["validation"]["status"], "failed")
            self.assertEqual(m["validation"]["failing"], 1)
            self.assertIn("src/b.py", m["missing_required_files"])
            self.assertEqual(m["evidence_records"], 1)
            # Serializable + renderable.
            json.dumps(m)
            self.assertIn("Run metrics", render_metrics_md(m))


if __name__ == "__main__":
    unittest.main()
