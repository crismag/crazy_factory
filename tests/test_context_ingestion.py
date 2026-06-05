"""Tests for Phase 9A context-aware project bootstrapping.

Covers safe archive extraction, context ingestion (file / directory / zip /
tar.gz), the catalog (import + supported/unsupported tracking), the context
loader and its volume guard, and the primary success metric: imported context
reaches the planner so supplied knowledge can change planning output. No Ollama
and no application code generation occur here.
"""

from __future__ import annotations

import contextlib
import io
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import context_manager as cm  # noqa: E402
import crazy_admin as ca  # noqa: E402
from archive_utils import ArchiveError, archive_kind, safe_extract  # noqa: E402
from context_loader import (  # noqa: E402
    DEFAULT_MAX_CONTEXT_BYTES,
    load_context_bundle,
    summarize_drops,
)
from planning_roles import request_architect_result  # noqa: E402


def _project(root: Path, app_rel: str = "apps/app") -> dict[str, object]:
    """Return a resolved-project mapping for a temp embedded workbench."""
    app = f"{app_rel}"
    (root / app / "context").mkdir(parents=True, exist_ok=True)
    return {
        "name": "app",
        "app_path": app,
        "context_root": f"{app}/factory_context",
        "context_store_root": f"{app}/context",
        "context_imports_root": f"{app}/context/imports",
        "context_extracted_root": f"{app}/context/extracted",
        "context_catalog_path": f"{app}/context/catalog.yaml",
    }


def _git_root(tmp: str) -> Path:
    """Make a temp dir look like a repo root (resolve_repo_path needs .git)."""
    root = Path(tmp)
    (root / ".git").mkdir(exist_ok=True)
    return root


class ArchiveSafetyTests(unittest.TestCase):
    """Archive extraction is safe and rejects malicious members."""

    def test_kind_detection(self) -> None:
        self.assertEqual(archive_kind("a.zip"), "zip")
        self.assertEqual(archive_kind("a.tar.gz"), "tar.gz")
        self.assertEqual(archive_kind("a.tgz"), "tar.gz")
        self.assertEqual(archive_kind("a.tar"), "tar")
        self.assertEqual(archive_kind("a.gz"), "gz")
        self.assertEqual(archive_kind("a.md"), "")

    def test_extract_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arc = root / "p.zip"
            with zipfile.ZipFile(arc, "w") as zf:
                zf.writestr("a.md", "# A\n")
                zf.writestr("sub/b.txt", "b")
            out = safe_extract(arc, root / "out")
            names = sorted(p.name for p in out)
            self.assertEqual(names, ["a.md", "b.txt"])

    def test_extract_tar_gz(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arc = root / "p.tar.gz"
            with tarfile.open(arc, "w:gz") as tf:
                data = b"# R\n"
                info = tarfile.TarInfo("req.md")
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
            out = safe_extract(arc, root / "out")
            self.assertEqual([p.name for p in out], ["req.md"])

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arc = root / "evil.zip"
            with zipfile.ZipFile(arc, "w") as zf:
                zf.writestr("../escape.md", "x")
            with self.assertRaises(ArchiveError):
                safe_extract(arc, root / "out")

    def test_rejects_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arc = root / "dup.zip"
            with zipfile.ZipFile(arc, "w") as zf:
                zf.writestr("dup.md", "1")
                zf.writestr("dup.md", "2")
            with self.assertRaises(ArchiveError):
                safe_extract(arc, root / "out")

    def test_rejects_unknown_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ArchiveError):
                safe_extract(Path(tmp) / "x.md", Path(tmp) / "out")


class IngestionTests(unittest.TestCase):
    """add_context stores, classifies, catalogs, and refuses secrets."""

    def test_add_single_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            (root / "req.md").write_text("# Req\n", encoding="utf-8")
            result = cm.add_context(
                project=project,
                source=str(root / "req.md"),
                root=root,
                now="T",
            )
            self.assertEqual(result["source_type"], "file")
            self.assertEqual(result["supported"], 1)
            catalog = cm.load_catalog(root, project)
            self.assertEqual(len(catalog["files"]), 1)
            self.assertEqual(cm.supported_file_count(catalog), 1)

    def test_add_directory_skips_secret_and_flags_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            seed = root / "seed"
            seed.mkdir()
            (seed / "vision.md").write_text("# V\n", encoding="utf-8")
            (seed / "logo.png").write_bytes(b"\x89PNG")
            (seed / ".env").write_text("SECRET=1\n", encoding="utf-8")
            result = cm.add_context(
                project=project, source=str(seed), root=root, now="T"
            )
            self.assertEqual(result["source_type"], "directory")
            self.assertIn(".env", result["skipped"])
            catalog = cm.load_catalog(root, project)
            # vision.md + logo.png stored; .env skipped.
            self.assertEqual(len(catalog["files"]), 2)
            self.assertEqual(cm.supported_file_count(catalog), 1)

    def test_add_zip_extracts_and_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            arc = root / "pkg.zip"
            with zipfile.ZipFile(arc, "w") as zf:
                zf.writestr("requirements.md", "# Reqs\n")
                zf.writestr("mock.jpg", "img")
            result = cm.add_context(
                project=project, source=str(arc), root=root, now="T"
            )
            self.assertEqual(result["source_type"], "archive")
            # archive preserved + 2 extracted = 3 stored; 1 supported (the md).
            self.assertEqual(len(result["stored"]), 3)
            self.assertEqual(result["supported"], 1)
            extracted = root / "apps/app/context/extracted/import_001"
            self.assertTrue((extracted / "requirements.md").is_file())
            preserved = root / "apps/app/context/imports/import_001/pkg.zip"
            self.assertTrue(preserved.is_file())

    def test_catalog_roundtrips_and_increments_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            (root / "a.md").write_text("a", encoding="utf-8")
            (root / "b.txt").write_text("b", encoding="utf-8")
            cm.add_context(
                project=project, source=str(root / "a.md"), root=root, now="T"
            )
            cm.add_context(
                project=project, source=str(root / "b.txt"), root=root, now="T"
            )
            catalog = cm.load_catalog(root, project)
            self.assertEqual(
                sorted(catalog["imports"]), ["import_001", "import_002"]
            )
            self.assertEqual(len(catalog["files"]), 2)

    def test_empty_catalog_with_stale_import_allocates_fresh_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            stale = root / "apps/app/context/imports/import_001"
            stale.mkdir(parents=True)
            (stale / "old.md").write_text("old", encoding="utf-8")
            (root / "new.md").write_text("new", encoding="utf-8")

            result = cm.add_context(
                project=project,
                source=str(root / "new.md"),
                root=root,
                now="T",
            )

            self.assertEqual(result["import_id"], "import_002")
            self.assertTrue(
                (root / "apps/app/context/imports/import_002/new.md").is_file()
            )
            catalog = cm.load_catalog(root, project)
            self.assertIn("import_002", catalog["imports"])

    def test_missing_source_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            with self.assertRaises(cm.ContextError):
                cm.add_context(
                    project=project,
                    source=str(root / "nope"),
                    root=root,
                    now="T",
                )

    def test_external_app_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as ext,
        ):
            root = _git_root(tmp)
            project = _project(root)
            project["app_path"] = str(Path(ext) / "outside")
            (root / "a.md").write_text("a", encoding="utf-8")
            with self.assertRaises(cm.ContextError):
                cm.add_context(
                    project=project,
                    source=str(root / "a.md"),
                    root=root,
                    now="T",
                )

    def test_single_secret_file_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            (root / "id_rsa").write_text("key", encoding="utf-8")
            with self.assertRaises(cm.ContextError):
                cm.add_context(
                    project=project,
                    source=str(root / "id_rsa"),
                    root=root,
                    now="T",
                )


class LoaderTests(unittest.TestCase):
    """The loader aggregates supported context and bounds volume."""

    def _seed(self, root: Path, project: dict[str, object]) -> None:
        (root / "vision.md").write_text("VISIONMARK\n", encoding="utf-8")
        (root / "cfg.yaml").write_text("k: CFGMARK\n", encoding="utf-8")
        (root / "pic.png").write_bytes(b"\x89PNG")
        for name in ("vision.md", "cfg.yaml", "pic.png"):
            cm.add_context(
                project=project, source=str(root / name), root=root, now="T"
            )

    def test_bundle_includes_supported_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            self._seed(root, project)
            bundle = load_context_bundle(root, project, max_lines_per_file=300)
            self.assertIn("VISIONMARK", bundle.text)
            self.assertIn("CFGMARK", bundle.text)
            self.assertNotIn("PNG", bundle.text)
            self.assertEqual(len(bundle.included), 2)
            self.assertTrue(bundle.text.startswith("Project Context"))

    def test_empty_when_no_supported_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            bundle = load_context_bundle(root, project, max_lines_per_file=300)
            self.assertEqual(bundle.text, "")
            self.assertEqual(bundle.included, [])

    def test_byte_budget_drops_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            self._seed(root, project)
            bundle = load_context_bundle(
                root, project, max_lines_per_file=300, max_total_bytes=40
            )
            # First file fits; the second is dropped by the byte budget.
            self.assertEqual(len(bundle.included), 1)
            self.assertEqual(len(bundle.dropped), 1)
            self.assertIn("byte budget", summarize_drops(bundle))

    def test_file_count_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_root(tmp)
            project = _project(root)
            self._seed(root, project)
            bundle = load_context_bundle(
                root, project, max_lines_per_file=300, max_files=1
            )
            self.assertEqual(len(bundle.included), 1)
            self.assertEqual(len(bundle.dropped), 1)


class PlannerIntegrationTests(unittest.TestCase):
    """The primary success metric: imported context reaches the planner."""

    _FACTORY = {
        "ollama": {
            "base_url": "http://localhost:11434",
            "timeout_seconds": 1,
            "stream": False,
        }
    }
    _MODELS = {"models": {"architect": "cogito:14b"}}
    _STATE = {"current_task": "T1", "current_milestone": "M1"}
    # context_root points at the real committed contexts/ dir so the prompt
    # package assembles; the imported bundle is passed as a plain string.
    _PROJECT = {"context_root": "contexts"}

    def _capture_prompt(self, context_bundle: str) -> str:
        captured: dict[str, str] = {}

        def fake_chat(
            model: str, messages: list[dict[str, str]], **_: object
        ) -> dict:
            captured["user"] = messages[1]["content"]
            return {"message": {"content": "ok"}}

        with patch("planning_roles.OllamaClient.chat", side_effect=fake_chat):
            request_architect_result(
                project_name="app",
                project=self._PROJECT,
                project_state=self._STATE,
                factory_config=self._FACTORY,
                models_config=self._MODELS,
                max_lines=300,
                tasks={},
                context_bundle=context_bundle,
            )
        return captured["user"]

    def test_planner_receives_imported_context(self) -> None:
        prompt = self._capture_prompt("===== req.md =====\nNEEDS_AUTH\n")
        self.assertIn("Project Imported Context", prompt)
        self.assertIn("NEEDS_AUTH", prompt)

    def test_different_context_changes_prompt(self) -> None:
        a = self._capture_prompt("CONTEXT_ALPHA")
        b = self._capture_prompt("CONTEXT_BETA")
        self.assertIn("CONTEXT_ALPHA", a)
        self.assertIn("CONTEXT_BETA", b)
        self.assertNotEqual(a, b)

    def test_no_context_omits_section(self) -> None:
        prompt = self._capture_prompt("")
        self.assertNotIn("Project Imported Context", prompt)


class CliTests(unittest.TestCase):
    """The crazy-admin add-context command wiring and its safety."""

    def _bootstrap(self, root: Path) -> None:
        (root / ".git").mkdir(exist_ok=True)
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "factory_state").mkdir(parents=True, exist_ok=True)
        (root / "apps").mkdir(parents=True, exist_ok=True)
        (root / "config/projects.yaml").write_text(
            'active_project: ""\nprojects:\n', encoding="utf-8"
        )
        (root / "config/factory.yaml").write_text(
            'factory:\n  mode: "dry_run"\n  state_dir: "state"\n'
            "proposal_application:\n  allow_apply: false\n"
            "validation:\n  allow_run: false\n"
            "git:\n  allow_auto_commit: false\n",
            encoding="utf-8",
        )
        for name in ("factory_state", "active_run", "project_state"):
            (root / f"state/{name}.json").write_text("{}", encoding="utf-8")

    def test_add_context_command_imports_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._bootstrap(root)
            ca.startproject("todo", "apps/todo", root=root)
            (root / "vision.md").write_text("# V\n", encoding="utf-8")
            with (
                patch("crazy_admin.find_repo_root", return_value=root),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = ca.main(
                    ["add-context", "todo", str(root / "vision.md")]
                )
            self.assertEqual(code, 0)
            project = ca.resolve_project(ca.load_registry(root), "todo")
            catalog = cm.load_catalog(root, project)
            self.assertEqual(cm.supported_file_count(catalog), 1)

    def test_add_context_unknown_project_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._bootstrap(root)
            (root / "v.md").write_text("v", encoding="utf-8")
            with patch("crazy_admin.find_repo_root", return_value=root):
                code = ca.main(["add-context", "ghost", str(root / "v.md")])
            self.assertEqual(code, 2)

    def test_startproject_creates_context_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._bootstrap(root)
            ca.startproject("todo", "apps/todo", root=root)
            store = root / "apps/todo/context"
            self.assertTrue((store / "imports/.gitkeep").exists())
            self.assertTrue((store / "extracted/.gitkeep").exists())
            self.assertTrue((store / "catalog.yaml").exists())


if __name__ == "__main__":
    # Reference the imported budget constant so linters keep the import.
    assert DEFAULT_MAX_CONTEXT_BYTES > 0
    unittest.main()
