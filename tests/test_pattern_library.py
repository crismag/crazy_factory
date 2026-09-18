"""Advisory pattern library — no scheduler, packet, or evidence coupling."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from architecture import load_contract
from execution_assignment import compile_assignment
from pattern_library import (
    AUTHORITY,
    KIND_ARCHETYPE,
    KIND_FEATURE,
    KIND_REFERENCE,
    KIND_UX,
    catalog_path,
    load_catalog,
    match_for_intent,
    search_patterns,
)
from product_intent import persist_intent


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class CatalogTests(unittest.TestCase):
    def test_shipped_catalog_has_all_kinds(self) -> None:
        entries = load_catalog(ROOT)
        self.assertGreaterEqual(len(entries), 8)
        kinds = {item.kind for item in entries}
        self.assertEqual(
            kinds, {KIND_ARCHETYPE, KIND_FEATURE, KIND_UX, KIND_REFERENCE}
        )
        self.assertTrue(all(item.authority == AUTHORITY for item in entries))
        ids = [item.pattern_id for item in entries]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(catalog_path(ROOT).is_file())

    def test_invalid_and_missing_catalogs_are_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(load_catalog(root), ())
            path = catalog_path(root)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_catalog(root), ())
            path.write_text(
                json.dumps(
                    {
                        "patterns": [
                            {"pattern_id": "x", "kind": "nope", "title": "X"},
                            {"kind": "feature", "title": "missing id"},
                            {
                                "pattern_id": "feature.ok",
                                "kind": "feature",
                                "title": "Ok",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_catalog(root)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].pattern_id, "feature.ok")
            self.assertEqual(loaded[0].authority, AUTHORITY)


class SearchTests(unittest.TestCase):
    def test_habit_streak_finds_feature_not_stack_doc_only(self) -> None:
        hits = search_patterns("habit streak", root=ROOT, kind=KIND_FEATURE)
        self.assertTrue(hits)
        self.assertEqual(hits[0].entry.pattern_id, "feature.habit-streak")
        self.assertGreater(hits[0].score, 0)
        self.assertIn("streak", hits[0].matched)

    def test_stdlib_search_finds_archetype(self) -> None:
        hits = search_patterns("stdlib web preview", root=ROOT)
        ids = [hit.entry.pattern_id for hit in hits]
        self.assertIn("archetype.stdlib-web", ids)

    def test_kind_and_applies_to_filters(self) -> None:
        ux = search_patterns("preview", root=ROOT, kind=KIND_UX)
        self.assertTrue(ux)
        self.assertTrue(all(hit.entry.kind == KIND_UX for hit in ux))
        habit = search_patterns(
            "habit", root=ROOT, kind=KIND_FEATURE, applies_to="habit"
        )
        self.assertTrue(habit)
        self.assertTrue(
            all("habit" in hit.entry.applies_to for hit in habit)
        )

    def test_match_for_intent_is_advisory_lookup(self) -> None:
        hits = match_for_intent(
            "build a habit tracker with streaks",
            stack_id="stdlib-web",
            root=ROOT,
        )
        ids = [hit.entry.pattern_id for hit in hits]
        self.assertTrue(
            any(item.startswith("archetype.") for item in ids)
            or any(item.startswith("feature.") for item in ids)
        )


class IsolationTests(unittest.TestCase):
    def test_search_does_not_rewrite_architecture_or_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            _write(app / "src/app.py", "X = 1\n")
            _write(app / "docs/seed.md", "Goal: calendar\n")
            _write(
                app / "architecture.json",
                json.dumps({"stack": "stdlib-web", "title": "keep-me"}),
            )
            persist_intent(
                {
                    "name": "demo",
                    "app_path": str(app),
                    "task_root": str(app / "factory_tasks"),
                    "seed_file": "docs/seed.md",
                },
                root,
                prompt="keep this prompt",
                capabilities=[],
                source="compile",
                revision=1,
            )
            search_patterns("habit streak", root=ROOT)
            match_for_intent("habit tracker", stack_id="stdlib-web", root=ROOT)
            contract = load_contract(str(app))
            self.assertEqual(contract["title"], "keep-me")
            intent = json.loads(
                (app / "factory_tasks" / "product_intent.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(intent["original_prompt"], "keep this prompt")

    def test_scheduler_evidence_and_graph_still_do_not_import_the_library(
        self,
    ) -> None:
        assignment_src = (ROOT / "scripts/execution_assignment.py").read_text(
            encoding="utf-8"
        )
        advance_src = (ROOT / "scripts/factory_advance.py").read_text(
            encoding="utf-8"
        )
        isolated_src = (ROOT / "scripts/isolated_task_run.py").read_text(
            encoding="utf-8"
        )
        evidence_src = (ROOT / "scripts/product_evidence.py").read_text(
            encoding="utf-8"
        )
        graph_src = (ROOT / "scripts/task_graph.py").read_text(encoding="utf-8")
        self.assertIn("pattern_library", assignment_src)
        self.assertIn("match_for_intent", assignment_src)
        for src in (advance_src, isolated_src, evidence_src, graph_src):
            self.assertNotIn("pattern_library", src)
            self.assertNotIn("search_patterns", src)
            self.assertNotIn("match_for_intent", src)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "demo"
            _write(app / "docs/seed.md", "Goal: calendar\n")
            _write(app / "src/app.py", "X = 1\n")
            obj = SimpleNamespace(
                id="OBJ-PRODUCT",
                kind="implement",
                title="Implement",
                gap="gap",
                why="why",
                focus="focus",
            )
            assignment = compile_assignment(
                {
                    "name": "demo",
                    "app_path": str(app),
                    "task_root": str(app / "factory_tasks"),
                    "seed_file": "docs/seed.md",
                },
                root,
                obj,
            )
            self.assertEqual(assignment.task_id, "")
            self.assertTrue(hasattr(assignment, "pattern_ids"))
            self.assertEqual(assignment.pattern_ids, ())


if __name__ == "__main__":
    unittest.main()
