"""Tests for the Phase 9D DiagnosisPacket (situational-context) builder.

The packet must be deterministic, bounded, sourced from structured artifacts
(never narrative reports), and free of prior-session leakage.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from diagnosis_packet import (  # noqa: E402
    build_packet,
    coder_slice,
    packet_to_dict,
    patch_plan_slice,
)

_NOW = "2026-06-05T00:00:00Z"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _scaffold(root: Path, *, big: str = "x = 1\n") -> dict[str, object]:
    """Create a workbench with artifacts; return the project mapping."""
    app = root / "app"
    tasks = app / "factory_tasks"
    _write(
        app / "architecture.json",
        json.dumps(
            {
                "src_dirs": ["src"],
                "test_dirs": ["tests"],
                "required_files": ["src/a.py", "src/b.py"],
            }
        ),
    )
    _write(app / "src/a.py", big)  # exists; src/b.py intentionally missing
    _write(
        tasks / "planned_task.json",
        json.dumps(
            {
                "task_id": "T-1",
                "objective": "OBJ-MARK",
                "scope": ["scope-1"],
                "acceptance_criteria": ["AC-ALPHA", "AC-BETA"],
                "validation_plan": ["python3 -m pytest tests"],
                "validation": {"status": "valid", "reasons": []},
            }
        ),
    )
    _write(
        tasks / "coder_proposal.json",
        json.dumps(
            {
                "proposal_id": "CP-1",
                "task_id": "T-1",
                "files_to_create": ["src/a.py", "src/b.py"],
                "files_to_modify": [],
                "validation": {
                    "status": "rejected",
                    "reasons": ["PROP-REJECT-MARK"],
                },
            }
        ),
    )
    _write(
        tasks / "patch_plan.json",
        json.dumps(
            {
                "plan_id": "PP-1",
                "validation": {
                    "status": "rejected",
                    "reasons": ["PATCH-REJECT-MARK"],
                },
            }
        ),
    )
    _write(
        tasks / "validation_result.json",
        json.dumps(
            {
                "test_plan_id": "TP-1",
                "status": "failed",
                "executed": True,
                "checks": [
                    {
                        "command": "python3 -m pytest tests",
                        "status": "failed",
                        "returncode": 1,
                        "detail": "FAILCHECK-MARK",
                    },
                    {
                        "command": "ruff check src tests",
                        "status": "passed",
                        "returncode": 0,
                        "detail": "",
                    },
                ],
            }
        ),
    )
    _write(
        tasks / "MASTER_CHECKLIST.md",
        "# Master Checklist\n\n- [ ] Implement src/b.py with the storage layer.\n",
    )
    return {
        "app_path": str(app),
        "task_root": str(tasks),
        "name": "demo",
        "factory_state_dir": "factory_state",
    }


class BuildPacketTests(unittest.TestCase):
    def test_populates_from_structured_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = _scaffold(root)
            p = build_packet(
                project=project,
                root=root,
                project_state={"failure_count": 2, "current_blocker": "x"},
                now=_NOW,
            )
            self.assertEqual(p.task_id, "T-1")
            self.assertEqual(p.objective, "OBJ-MARK")
            self.assertIn("AC-ALPHA", p.acceptance_criteria)
            self.assertEqual(p.focus_file, "src/b.py")
            self.assertIn("src/b.py", p.missing_required_files)
            self.assertNotIn("src/a.py", p.missing_required_files)
            self.assertEqual(p.proposal_rejections, ["PROP-REJECT-MARK"])
            self.assertEqual(p.patch_rejections, ["PATCH-REJECT-MARK"])
            self.assertEqual(len(p.failing_checks), 1)
            self.assertEqual(p.failing_checks[0].detail, "FAILCHECK-MARK")
            self.assertEqual(p.failure_count, 2)

    def test_does_not_read_narrative_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = _scaffold(root)
            _write(
                Path(str(project["task_root"])) / "VALIDATION_REPORT.md",
                "POISON-PROSE should never reach the model\n",
            )
            p = build_packet(
                project=project, root=root, project_state={}, now=_NOW
            )
            self.assertNotIn("POISON-PROSE", json.dumps(packet_to_dict(p)))

    def test_source_snapshot_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = _scaffold(root, big="y = 2\n" * 5000)
            p = build_packet(
                project=project,
                root=root,
                project_state={},
                now=_NOW,
                max_source_bytes=100,
            )
            a = next(s for s in p.source_snapshot if s.path == "src/a.py")
            self.assertTrue(a.truncated)
            self.assertLessEqual(len(a.content.encode("utf-8")), 100)
            b = next(s for s in p.source_snapshot if s.path == "src/b.py")
            self.assertFalse(b.exists)

    def test_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = _scaffold(root)
            a = build_packet(
                project=project, root=root, project_state={}, now=_NOW
            )
            b = build_packet(
                project=project, root=root, project_state={}, now=_NOW
            )
            self.assertEqual(packet_to_dict(a), packet_to_dict(b))
            # Serializable.
            json.dumps(packet_to_dict(a))

    def test_missing_artifacts_degrade_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app/factory_tasks").mkdir(parents=True)
            project = {
                "app_path": str(root / "app"),
                "task_root": str(root / "app/factory_tasks"),
                "name": "empty",
                "factory_state_dir": "factory_state",
            }
            p = build_packet(
                project=project, root=root, project_state={}, now=_NOW
            )
            self.assertEqual(p.acceptance_criteria, [])
            self.assertEqual(p.failing_checks, [])
            self.assertEqual(p.validation_status, "not_run")


class SliceTests(unittest.TestCase):
    def test_slices_carry_acceptance_and_ground_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = _scaffold(root)
            p = build_packet(
                project=project, root=root, project_state={}, now=_NOW
            )
            coder = coder_slice(p)
            patch = patch_plan_slice(p)
            self.assertIn("AC-ALPHA", coder)
            self.assertIn("PATCH-REJECT-MARK", coder)
            self.assertIn("AC-ALPHA", patch)
            self.assertIn("FAILCHECK-MARK", patch)
            self.assertIn("src/b.py", patch)  # missing-file ground truth


if __name__ == "__main__":
    unittest.main()
