#!/usr/bin/env python3
"""Phase 9A context ingestion and catalog for Crazy Factory.

This module receives project knowledge and stores it in a project's context
store, then records it in a simple catalog. It performs NO intelligence: no
parsing, classification, conversion, OCR, embeddings, or analysis. Its only
responsibilities are file validation, archive extraction (via
:mod:`archive_utils`), and catalog maintenance. Understanding the content is
left entirely to the AI workflow.

Layout under the project workbench (``<app_path>/context/``)::

    context/
      imports/<import_id>/      # preserved originals (file, dir tree, archive)
      extracted/<import_id>/    # safe extraction output for archives
      catalog.yaml              # what was imported + which files are supported

Supported context file types (``.md .txt .yaml .yml .json .csv .sql``) are
flagged ``supported: true`` and become available to planning; all other files
are stored and cataloged but never interpreted. Secret-like files are refused
(never copied into the repository).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from archive_utils import is_archive, safe_extract
from project_registry import app_is_external
from repo_tools import (
    BLOCKED_NAMES,
    BLOCKED_SUFFIXES,
    load_simple_yaml,
    resolve_repo_path,
    safe_write_text,
)

# File types the factory actively exposes to the AI as context. Everything else
# is stored and cataloged but not interpreted (Phase 9A scope).
SUPPORTED_CONTEXT_EXTENSIONS: frozenset[str] = frozenset(
    {".md", ".txt", ".yaml", ".yml", ".json", ".csv", ".sql"}
)


class ContextError(RuntimeError):
    """Raised when context ingestion cannot proceed safely."""


def is_supported_file(path: str | Path) -> bool:
    """Report whether a file is a supported (AI-consumable) context type."""
    return Path(path).suffix.lower() in SUPPORTED_CONTEXT_EXTENSIONS


def _file_type(path: str | Path) -> str:
    """Return the lowercase extension without the dot (``md``, ``png``, …)."""
    return Path(path).suffix.lower().lstrip(".")


def _is_sensitive(path: str | Path) -> bool:
    """Report whether a path looks like a secret that must not be stored."""
    p = Path(path)
    name = p.name.lower()
    if name in BLOCKED_NAMES or name.startswith(".env"):
        return True
    return p.suffix.lower() in BLOCKED_SUFFIXES


def _max_suffix_number(keys: Any, prefix: str) -> int:
    """Return the highest numeric suffix among ids sharing ``prefix``."""
    highest = 0
    if isinstance(keys, dict):
        for key in keys:
            text = str(key)
            if text.startswith(prefix):
                try:
                    highest = max(highest, int(text[len(prefix) :]))
                except ValueError:
                    continue
    return highest


def _next_import_id(catalog: dict[str, Any]) -> str:
    """Return the next ``import_NNN`` id for the catalog."""
    return f"import_{_max_suffix_number(catalog.get('imports'), 'import_') + 1:03d}"


def load_catalog(root: Path, project: dict[str, Any]) -> dict[str, Any]:
    """Load a project's context catalog, or an empty one when absent.

    Args:
        root: Absolute repository root.
        project: Resolved project mapping (see ``resolve_project``).

    Returns:
        Catalog mapping with ``imports`` and ``files`` sub-mappings.
    """
    catalog_path = str(project["context_catalog_path"])
    if not resolve_repo_path(catalog_path, root).is_file():
        return {"imports": {}, "files": {}}
    data = load_simple_yaml(catalog_path, root)
    imports = data.get("imports")
    files = data.get("files")
    return {
        "imports": imports if isinstance(imports, dict) else {},
        "files": files if isinstance(files, dict) else {},
    }


def dump_catalog(catalog: dict[str, Any]) -> str:
    """Serialize a catalog to the bootstrap YAML subset.

    Uses synthetic ids as keys (``import_001`` / ``f0001``) with the real file
    path stored as a quoted scalar value, so the result round-trips through
    :func:`repo_tools.load_simple_yaml` (which does not parse lists of
    mappings).

    Args:
        catalog: Catalog mapping to serialize.

    Returns:
        YAML text parseable by ``load_simple_yaml``.
    """
    lines = [
        "# Context catalog. Maintained by `crazy-admin add-context`.",
        "# Tracks imports and stored files; not a search index or graph.",
        "",
        "imports:",
    ]
    for iid, entry in (catalog.get("imports") or {}).items():
        lines.append(f"  {iid}:")
        for key in ("source", "source_type", "imported_at", "extracted_to"):
            lines.append(f'    {key}: "{entry.get(key, "")}"')
        lines.append(
            f"    extracted: {str(bool(entry.get('extracted'))).lower()}"
        )
        lines.append(f"    file_count: {int(entry.get('file_count', 0))}")
    lines.append("files:")
    for fid, entry in (catalog.get("files") or {}).items():
        lines.append(f"  {fid}:")
        lines.append(f'    path: "{entry.get("path", "")}"')
        lines.append(f'    import_id: "{entry.get("import_id", "")}"')
        lines.append(f'    type: "{entry.get("type", "")}"')
        lines.append(
            f"    supported: {str(bool(entry.get('supported'))).lower()}"
        )
    return "\n".join(lines) + "\n"


def save_catalog(
    catalog: dict[str, Any], root: Path, project: dict[str, Any]
) -> None:
    """Persist a project's context catalog."""
    safe_write_text(
        str(project["context_catalog_path"]),
        dump_catalog(catalog),
        repo_root=root,
        allowed_roots=[str(project["context_store_root"])],
    )


def supported_file_count(catalog: dict[str, Any]) -> int:
    """Return the number of supported (AI-consumable) files in the catalog."""
    return sum(
        1
        for entry in (catalog.get("files") or {}).values()
        if bool(entry.get("supported"))
    )


def _classify_source(src: Path) -> str:
    """Classify an ingestion source as file, directory, or archive.

    Raises:
        ContextError: If the source does not exist.
    """
    if not src.exists():
        raise ContextError(f"Source not found: {src}")
    if src.is_dir():
        return "directory"
    if is_archive(src):
        return "archive"
    return "file"


def _copy_into_store(
    src_file: Path, dest_rel: str, root: Path, store_root: str
) -> None:
    """Copy bytes into the context store, repo-confined and never overwriting.

    Args:
        src_file: Absolute source file (may live outside the repo).
        dest_rel: Repository-relative destination path under the store.
        root: Absolute repository root.
        store_root: Repository-relative context store root for confinement.

    Raises:
        ContextError: If the destination escapes the store or already exists.
    """
    target = resolve_repo_path(dest_rel, root)
    store = resolve_repo_path(store_root, root)
    if target != store and store not in target.parents:
        raise ContextError(f"Destination escapes context store: {dest_rel}")
    if target.exists():
        raise ContextError(f"Refusing to overwrite: {dest_rel}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_file, target)


def _catalog_file(
    catalog: dict[str, Any], rel_path: str, import_id: str
) -> None:
    """Add one stored file to the catalog with its support status."""
    files = catalog["files"]
    fid = f"f{_max_suffix_number(files, 'f') + 1:04d}"
    files[fid] = {
        "path": rel_path,
        "import_id": import_id,
        "type": _file_type(rel_path),
        "supported": is_supported_file(rel_path),
    }


def add_context(
    *,
    project: dict[str, Any],
    source: str,
    root: Path,
    now: str,
) -> dict[str, Any]:
    """Ingest a source (file, directory, or archive) into the context store.

    Originals are preserved under ``context/imports/<import_id>/``; archives are
    also extracted under ``context/extracted/<import_id>/``. Every resulting
    file is cataloged with a support flag. Secret-like files are skipped.

    Args:
        project: Resolved project mapping (embedded apps only in Phase 9A).
        source: Path to the file/directory/archive to ingest.
        root: Absolute repository root.
        now: ISO timestamp recorded on the import.

    Returns:
        Summary mapping: import_id, source_type, stored, supported, skipped.

    Raises:
        ContextError: On external apps, a missing source, or unsafe storage.
    """
    app_path = str(project["app_path"])
    if app_is_external(app_path, root):
        raise ContextError(
            "Context ingestion is only supported for embedded apps "
            f"(under apps/); '{app_path}' is external."
        )
    src = Path(source)
    source_type = _classify_source(src)
    catalog = load_catalog(root, project)
    import_id = _next_import_id(catalog)
    imports_root = str(project["context_imports_root"])
    extracted_root = str(project["context_extracted_root"])

    stored: list[str] = []
    skipped: list[str] = []
    extracted = False
    extracted_to = ""

    if source_type == "directory":
        for child in sorted(p for p in src.rglob("*") if p.is_file()):
            rel = child.relative_to(src).as_posix()
            if _is_sensitive(child):
                skipped.append(rel)
                continue
            dest_rel = f"{imports_root}/{import_id}/{rel}"
            _copy_into_store(
                child, dest_rel, root, str(project["context_store_root"])
            )
            _catalog_file(catalog, dest_rel, import_id)
            stored.append(dest_rel)
    elif source_type == "file":
        if _is_sensitive(src):
            raise ContextError(
                f"Refusing to ingest secret-like file: {src.name}"
            )
        dest_rel = f"{imports_root}/{import_id}/{src.name}"
        _copy_into_store(
            src, dest_rel, root, str(project["context_store_root"])
        )
        _catalog_file(catalog, dest_rel, import_id)
        stored.append(dest_rel)
    else:  # archive — preserve the original, then extract safely
        if _is_sensitive(src):
            raise ContextError(
                f"Refusing to ingest secret-like file: {src.name}"
            )
        archive_rel = f"{imports_root}/{import_id}/{src.name}"
        _copy_into_store(
            src, archive_rel, root, str(project["context_store_root"])
        )
        _catalog_file(catalog, archive_rel, import_id)
        stored.append(archive_rel)
        extract_abs = resolve_repo_path(f"{extracted_root}/{import_id}", root)
        for abs_path in safe_extract(src, extract_abs):
            if _is_sensitive(abs_path):
                abs_path.unlink()
                skipped.append(str(abs_path.relative_to(root)))
                continue
            rel = str(abs_path.relative_to(root))
            _catalog_file(catalog, rel, import_id)
            stored.append(rel)
        extracted = True
        extracted_to = f"{extracted_root}/{import_id}"

    supported = sum(1 for p in stored if is_supported_file(p))
    catalog["imports"][import_id] = {
        "source": src.name,
        "source_type": source_type,
        "imported_at": now,
        "extracted": extracted,
        "extracted_to": extracted_to,
        "file_count": len(stored),
    }
    save_catalog(catalog, root, project)
    return {
        "import_id": import_id,
        "source_type": source_type,
        "stored": stored,
        "supported": supported,
        "skipped": skipped,
    }
