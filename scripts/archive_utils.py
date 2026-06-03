#!/usr/bin/env python3
"""Phase 9A safe archive extraction for Crazy Factory context ingestion.

The factory may receive project knowledge as archives. This module extracts
them with stdlib only (no network, no third-party deps) and refuses anything
unsafe: member paths that escape the destination, absolute paths, ``..``
traversal, overwrites of existing files, and non-regular members (symlinks,
hardlinks, devices) in tar archives.

Supported archive kinds: ``zip``, ``tar``, ``tar.gz`` / ``tgz``, and plain
``gz`` (single-file gzip). Extraction never interprets file contents; it only
lays bytes down under the destination directory.
"""

from __future__ import annotations

import gzip
import tarfile
import zipfile
from pathlib import Path
from typing import Literal

# Recognized archive suffixes, longest first so ``.tar.gz`` wins over ``.gz``.
_ARCHIVE_SUFFIXES: tuple[tuple[str, str], ...] = (
    (".tar.gz", "tar.gz"),
    (".tgz", "tar.gz"),
    (".tar", "tar"),
    (".zip", "zip"),
    (".gz", "gz"),
)


class ArchiveError(RuntimeError):
    """Raised when an archive is malformed or unsafe to extract."""


def archive_kind(path: str | Path) -> str:
    """Return the archive kind for a path, or ``""`` if not an archive.

    Args:
        path: Candidate archive path.

    Returns:
        One of ``"zip"``, ``"tar"``, ``"tar.gz"``, ``"gz"``, or ``""``.
    """
    name = Path(path).name.lower()
    for suffix, kind in _ARCHIVE_SUFFIXES:
        if name.endswith(suffix):
            return kind
    return ""


def is_archive(path: str | Path) -> bool:
    """Report whether a path looks like a supported archive."""
    return archive_kind(path) != ""


def _safe_member_target(dest_dir: Path, member_name: str) -> Path:
    """Resolve an archive member to a path provably inside ``dest_dir``.

    Args:
        dest_dir: Absolute destination directory.
        member_name: Raw member name from the archive.

    Returns:
        The resolved absolute target path inside ``dest_dir``.

    Raises:
        ArchiveError: If the member is absolute, traverses upward, or would
            land outside ``dest_dir``.
    """
    member = member_name.replace("\\", "/").lstrip("/")
    if not member or member == ".":
        raise ArchiveError(f"Empty archive member name: {member_name!r}")
    parts = Path(member).parts
    if ".." in parts or Path(member).is_absolute():
        raise ArchiveError(f"Unsafe archive member path: {member_name!r}")
    target = (dest_dir / member).resolve()
    base = dest_dir.resolve()
    if target != base and base not in target.parents:
        raise ArchiveError(
            f"Archive member escapes destination: {member_name!r}"
        )
    return target


def _write_member(target: Path, data: bytes) -> None:
    """Write one extracted member, refusing to overwrite existing files.

    Args:
        target: Absolute destination path inside the extraction directory.
        data: File bytes.

    Raises:
        ArchiveError: If ``target`` already exists (overwrite attempt).
    """
    if target.exists():
        raise ArchiveError(f"Refusing to overwrite existing file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _extract_zip(archive_path: Path, dest_dir: Path) -> list[Path]:
    """Extract a zip archive safely. Returns extracted file paths."""
    written: list[Path] = []
    with zipfile.ZipFile(archive_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                target = _safe_member_target(dest_dir, info.filename)
                target.mkdir(parents=True, exist_ok=True)
                continue
            target = _safe_member_target(dest_dir, info.filename)
            _write_member(target, zf.read(info))
            written.append(target)
    return written


def _extract_tar(
    archive_path: Path, dest_dir: Path, mode: Literal["r:", "r:gz"]
) -> list[Path]:
    """Extract a tar archive safely (regular files + dirs only)."""
    written: list[Path] = []
    with tarfile.open(archive_path, mode) as tf:
        for member in tf.getmembers():
            if member.isdir():
                target = _safe_member_target(dest_dir, member.name)
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                # Skip symlinks, hardlinks, devices, fifos — never extracted.
                continue
            target = _safe_member_target(dest_dir, member.name)
            extracted = tf.extractfile(member)
            data = extracted.read() if extracted is not None else b""
            _write_member(target, data)
            written.append(target)
    return written


def _extract_gz(archive_path: Path, dest_dir: Path) -> list[Path]:
    """Decompress a single-file gzip archive into ``dest_dir``."""
    inner_name = Path(archive_path).name
    if inner_name.lower().endswith(".gz"):
        inner_name = inner_name[: -len(".gz")]
    if not inner_name:
        inner_name = "extracted.bin"
    target = _safe_member_target(dest_dir, inner_name)
    with gzip.open(archive_path, "rb") as gf:
        _write_member(target, gf.read())
    return [target]


def safe_extract(archive_path: str | Path, dest_dir: str | Path) -> list[Path]:
    """Safely extract an archive into ``dest_dir``.

    Args:
        archive_path: Path to the archive to extract.
        dest_dir: Destination directory (created if missing).

    Returns:
        Absolute paths of the regular files written, sorted.

    Raises:
        ArchiveError: If the kind is unsupported, the archive is corrupt, or a
            member is unsafe (traversal, absolute path, or overwrite).
    """
    src = Path(archive_path)
    dest = Path(dest_dir)
    kind = archive_kind(src)
    if not kind:
        raise ArchiveError(f"Unsupported archive type: {src.name}")
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if kind == "zip":
            written = _extract_zip(src, dest)
        elif kind == "tar":
            written = _extract_tar(src, dest, "r:")
        elif kind == "tar.gz":
            written = _extract_tar(src, dest, "r:gz")
        else:  # gz
            written = _extract_gz(src, dest)
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as exc:
        raise ArchiveError(f"Could not extract {src.name}: {exc}") from exc
    return sorted(written)
