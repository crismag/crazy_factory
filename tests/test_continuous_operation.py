"""Tests for the Phase 8 continuous-operation modules.

These cover control flags, stall detection, recovery, satisfaction, and the
mission-loop decision logic without running the full advance or calling Ollama.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from flags import (  # noqa: E402
    active_flags,
    clear_flag,
    control_decision,
    flag_active,
    set_flag,
)
from datetime import datetime, timedelta, timezone  # noqa: E402

from mission_loop import (  # noqa: E402
    acquire_lock,
    decide_action,
    release_lock,
    render_mission_status_md,
)
from recovery_manager import build_recovery_plan, run_recovery  # noqa: E402
from satisfaction_checker import (  # noqa: E402
    evaluate_satisfaction,
    run_satisfaction,
)
from stall_detector import detect_stall  # noqa: E402


def _demo_project(root: Path) -> dict[str, object]:
    (root / "state").mkdir()
    task_root = root / "apps/demo/factory_tasks"
    report_root = root / "apps/demo/factory_reports"
    task_root.mkdir(parents=True)
    report_root.mkdir(parents=True)
    return {
        "root": "apps/demo",
        "task_root": "apps/demo/factory_tasks",
        "report_root": "apps/demo/factory_reports",
    }


class FlagTests(unittest.TestCase):
    """Verify control flag files."""

    def test_set_active_clear(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "state").mkdir()
            self.assertFalse(flag_active("pause", root))
            set_flag("pause", root, note="testing")
            self.assertTrue(flag_active("pause", root))
            self.assertEqual(active_flags(root), ["pause"])
            self.assertTrue(clear_flag("pause", root))
            self.assertFalse(flag_active("pause", root))

    def test_unknown_flag_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "state").mkdir()
            with self.assertRaises(ValueError):
                set_flag("bogus", root)

    def test_control_decision_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "state").mkdir()
            # JSON boolean honored.
            self.assertEqual(
                control_decision(root, {"pause_requested": True}), "paused"
            )
            # Stop flag file wins over pause.
            set_flag("pause", root)
            set_flag("stop", root)
            self.assertEqual(control_decision(root, {}), "stopped")
            clear_flag("stop", root)
            self.assertEqual(control_decision(root, {}), "paused")


class StallTests(unittest.TestCase):
    """Verify stall detection."""

    def test_no_stall_when_healthy(self) -> None:
        signal = detect_stall(
            factory_state={},
            project_state={"failure_count": 0, "current_blocker": None},
        )
        self.assertFalse(signal.stalled)

    def test_stall_on_failure_threshold(self) -> None:
        signal = detect_stall(
            factory_state={},
            project_state={"failure_count": 5},
            max_failures=2,
        )
        self.assertTrue(signal.stalled)

    def test_recoverable_blocker_does_not_stall_immediately(self) -> None:
        signal = detect_stall(
            factory_state={},
            project_state={
                "failure_count": 0,
                "current_blocker": "validation_failed",
            },
        )
        self.assertFalse(signal.stalled)

    def test_stall_on_remediation_exhausted(self) -> None:
        # A spent fix budget is terminal: the loop must park, not churn.
        signal = detect_stall(
            factory_state={},
            project_state={
                "failure_count": 0,
                "current_blocker": "remediation_exhausted",
            },
        )
        self.assertTrue(signal.stalled)

    def test_self_rejection_routes_to_recovery_before_stall(self) -> None:
        signal = detect_stall(
            factory_state={},
            project_state={
                "failure_count": 0,
                "current_blocker": "self_rejection",
            },
        )
        self.assertFalse(signal.stalled)

    def test_stall_on_repeated_fallback(self) -> None:
        signal = detect_stall(
            factory_state={
                "last_architect_source": "fallback",
                "last_planner_source": "fallback",
                "last_contract_source": "fallback",
            },
            project_state={"failure_count": 1},
        )
        self.assertTrue(signal.stalled)


class RecoveryTests(unittest.TestCase):
    """Verify recovery plan and artifacts."""

    def test_build_plan_recommends_block(self) -> None:
        signal = detect_stall(
            factory_state={},
            project_state={"current_blocker": "remediation_exhausted"},
        )
        plan = build_recovery_plan(
            signal, {"current_blocker": "remediation_exhausted"}
        )
        self.assertTrue(plan.set_blocked)
        self.assertTrue(plan.actions)

    def test_run_recovery_writes_and_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = _demo_project(root)
            project_state = {
                "current_task": "DEMO-002",
                "failure_count": 5,
                "current_blocker": "remediation_exhausted",
            }
            signal = detect_stall(
                factory_state={}, project_state=project_state
            )
            run_recovery(
                root=root,
                project=project,
                stall_signal=signal,
                project_state=project_state,
            )
            # Stall/recovery reports land in the project's report folder,
            # never the engine root.
            self.assertTrue(
                (root / "apps/demo/factory_reports/STALL_REPORT.md").is_file()
            )
            self.assertTrue(
                (
                    root / "apps/demo/factory_reports/RECOVERY_REPORT.md"
                ).is_file()
            )
            self.assertTrue(
                (root / "apps/demo/factory_tasks/RECOVERY_PLAN.md").is_file()
            )
            self.assertFalse((root / "reports").exists())
            self.assertTrue(flag_active("blocked", root))


class SatisfactionTests(unittest.TestCase):
    """Verify satisfaction evaluation and artifacts."""

    def test_not_satisfied_with_open_items(self) -> None:
        verdict = evaluate_satisfaction(
            checklist_text="## M\n- [ ] do thing\n",
            project_state={"last_validation_status": "passed"},
        )
        self.assertFalse(verdict.satisfied)

    def test_satisfied_when_complete(self) -> None:
        verdict = evaluate_satisfaction(
            checklist_text="## M\n- [x] done\n",
            project_state={
                "last_validation_status": "passed",
                "current_blocker": None,
            },
        )
        self.assertTrue(verdict.satisfied, verdict.reasons)

    def test_not_satisfied_with_blocker(self) -> None:
        verdict = evaluate_satisfaction(
            checklist_text="- [x] done\n",
            project_state={
                "last_validation_status": "passed",
                "current_blocker": "validation_failed",
            },
        )
        self.assertFalse(verdict.satisfied)

    def test_run_satisfaction_sets_flag_when_satisfied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = _demo_project(root)
            verdict = run_satisfaction(
                root=root,
                project=project,
                checklist_text="- [x] done\n",
                project_state={
                    "last_validation_status": "passed",
                    "current_blocker": None,
                    "project": "demo",
                },
            )
            self.assertTrue(verdict.satisfied)
            self.assertTrue(flag_active("satisfied", root))
            self.assertTrue(
                (
                    root / "apps/demo/factory_reports/SATISFACTION_REPORT.md"
                ).is_file()
            )


class MissionLoopTests(unittest.TestCase):
    """Verify the mission-loop decision logic."""

    def test_decide_run_when_clear(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "state").mkdir()
            action = decide_action(
                root=root,
                factory_state={},
                project_state={"failure_count": 0},
                state_dir="state",
            )
            self.assertEqual(action, "run")

    def test_decide_stopped_when_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "state").mkdir()
            set_flag("stop", root)
            action = decide_action(
                root=root,
                factory_state={},
                project_state={"failure_count": 0},
                state_dir="state",
            )
            self.assertEqual(action, "stopped")

    def test_decide_stalled_on_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "state").mkdir()
            action = decide_action(
                root=root,
                factory_state={},
                project_state={"failure_count": 9},
                state_dir="state",
            )
            self.assertEqual(action, "stalled")

    def test_render_mission_status(self) -> None:
        text = render_mission_status_md(
            action="run",
            flags=["pause"],
            factory_state={"mode": "dry_run"},
            project_state={
                "project": "demo",
                "current_milestone": "M",
                "current_task": "DEMO-002",
                "failure_count": 0,
                "current_blocker": None,
            },
        )
        self.assertIn("Mission Status", text)
        self.assertIn("Action: `run`", text)
        self.assertIn("pause", text)


class LockTests(unittest.TestCase):
    """Verify the mission lock prevents overlapping runs."""

    def test_acquire_then_blocks_fresh_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "state").mkdir()
            now = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)
            self.assertTrue(
                acquire_lock(
                    root, "state", pid=111, now=now, stale_seconds=3600
                )
            )
            self.assertTrue((root / "state/mission.lock").is_file())
            # A second run a minute later cannot acquire the fresh lock.
            later = now + timedelta(minutes=1)
            self.assertFalse(
                acquire_lock(
                    root, "state", pid=222, now=later, stale_seconds=3600
                )
            )

    def test_stale_lock_is_taken_over(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "state").mkdir()
            now = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)
            acquire_lock(root, "state", pid=111, now=now, stale_seconds=3600)
            # Two hours later the lock is stale and may be taken over.
            much_later = now + timedelta(hours=2)
            self.assertTrue(
                acquire_lock(
                    root,
                    "state",
                    pid=333,
                    now=much_later,
                    stale_seconds=3600,
                )
            )

    def test_release_allows_reacquire(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "state").mkdir()
            now = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)
            acquire_lock(root, "state", pid=111, now=now, stale_seconds=3600)
            release_lock(root, "state")
            self.assertFalse((root / "state/mission.lock").is_file())
            self.assertTrue(
                acquire_lock(
                    root, "state", pid=222, now=now, stale_seconds=3600
                )
            )


if __name__ == "__main__":
    unittest.main()
