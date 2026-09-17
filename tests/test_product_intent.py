"""Product claims: compile-time intent, not title/banner matching."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from conversation_delta import (
    STATUS_CLAIMED,
    STATUS_PENDING,
    append_delta,
    load_deltas,
    mark_deltas_claimed,
    refresh_delta_verification,
)
from product_intent import (
    claim_satisfied,
    fallback_capabilities,
    intent_revision,
    load_intent,
    unsatisfied_claims,
    workbench_probes,
)
from prompt_compiler import compile_into_workbench


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(app: Path) -> dict[str, str]:
    tasks = app / "factory_tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    return {
        "name": app.name,
        "app_path": str(app),
        "task_root": str(tasks),
        "seed_file": "docs/seed.md",
    }


class FallbackClaimTests(unittest.TestCase):
    def test_habit_tracker_compiles_explicit_claims(self) -> None:
        caps = fallback_capabilities("build a habit tracker")
        ids = {c.id for c in caps}
        self.assertEqual(
            ids,
            {
                "define_habits",
                "record_completion",
                "dated_completion",
                "persist_habits",
            },
        )
        self.assertTrue(all(c.claim for c in caps))

    def test_streak_delta_adds_streak_and_week_claims(self) -> None:
        caps = fallback_capabilities(
            "add a streak counter and a weekly view", origin="delta-1"
        )
        ids = {c.id for c in caps}
        self.assertEqual(ids, {"habit_streaks", "weekly_view"})
        self.assertTrue(all(c.origin == "delta-1" for c in caps))


class PersistIntentTests(unittest.TestCase):
    def test_compile_writes_revision_one_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "habit"
            project = _project(app)
            compile_into_workbench(project, root, "build a habit tracker")
            intent = load_intent(project, root)
            self.assertEqual(intent["revision"], 1)
            ids = {c["id"] for c in intent["capabilities"]}
            self.assertIn("define_habits", ids)
            self.assertEqual(intent_revision(project, root), 1)

    def test_delta_bumps_revision_and_keeps_compile_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "habit"
            project = _project(app)
            compile_into_workbench(project, root, "build a habit tracker")
            append_delta(
                project, root, "add a streak counter and a weekly view"
            )
            intent = load_intent(project, root)
            self.assertEqual(intent["revision"], 2)
            ids = {c["id"] for c in intent["capabilities"]}
            self.assertIn("define_habits", ids)
            self.assertIn("habit_streaks", ids)
            self.assertIn("weekly_view", ids)


class ProbeTests(unittest.TestCase):
    def test_banner_html_is_not_product_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            _write(
                app / "src/app.py",
                "TITLE = 'habit tracker'\n"
                "page = '<h1>habit tracker</h1>"
                "<p>streak counter weekly view current_streak</p>'\n",
            )
            _write(app / "data/items.json", "[]\n")
            _write(
                app / "data/change_requests.json",
                json.dumps(["add a streak counter and a weekly view"]) + "\n",
            )
            identifiers, keys, files = workbench_probes(app)
            self.assertNotIn("current_streak", identifiers)
            self.assertNotIn("add_habit", identifiers)
            self.assertNotIn("streak", keys)
            self.assertIn("data/change_requests.json", files)
            streak = fallback_capabilities(
                "add a streak counter and a weekly view"
            )[0]
            self.assertFalse(
                claim_satisfied(
                    streak,
                    identifiers=identifiers,
                    json_keys=keys,
                    files=files,
                )
            )

    def test_real_habit_symbols_are_not_enough(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "habit"
            project = _project(app)
            compile_into_workbench(project, root, "build a habit tracker")
            _write(
                app / "src/habits.py",
                "habits = []\n"
                "def add_habit(name):\n"
                "    return name\n"
                "def complete_habit(habit_id, completed_on):\n"
                "    return completed_on\n"
                "def save_habits():\n"
                "    return load_habits()\n"
                "def load_habits():\n"
                "    return habits\n",
            )
            _write(
                app / "data/habits.json",
                json.dumps([{"name": "run", "completed_on": "2026-09-16"}])
                + "\n",
            )
            gaps = {c.id for c in unsatisfied_claims(project, root)}
            self.assertIn("define_habits", gaps)
            self.assertIn("dated_completion", gaps)
            self.assertIn("persist_habits", gaps)


class DeltaLifecycleTests(unittest.TestCase):
    def test_new_delta_is_pending_until_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "habit"
            project = _project(app)
            compile_into_workbench(project, root, "build a habit tracker")
            append_delta(
                project, root, "add a streak counter and a weekly view"
            )
            entries = load_deltas(project, root)
            self.assertEqual(entries[0]["status"], STATUS_PENDING)
            mark_deltas_claimed(project, root)
            self.assertEqual(
                load_deltas(project, root)[0]["status"], STATUS_CLAIMED
            )
            refresh_delta_verification(project, root)
            self.assertEqual(
                load_deltas(project, root)[0]["status"], STATUS_CLAIMED
            )
            _write(
                app / "src/habits.py",
                "def current_streak(history):\n"
                "    return 0\n"
                "def weekly_view(history):\n"
                "    return []\n",
            )
            _write(
                app / "data/habits.json",
                json.dumps(
                    [{"streak": 1, "current_streak": 1, "week": "2026-W38"}]
                )
                + "\n",
            )
            refresh_delta_verification(project, root)
            self.assertEqual(
                load_deltas(project, root)[0]["status"], STATUS_CLAIMED
            )


if __name__ == "__main__":
    unittest.main()
