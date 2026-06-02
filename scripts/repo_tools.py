#!/usr/bin/env python3
"""Provide repository-local file helpers with conservative safety guards.

All filesystem access used by the bootstrap engine should flow through this
module. The helpers resolve paths against the Git repository root, reject path
traversal and symlink escapes, block likely secret files, and require explicit
write roots.

The YAML loader intentionally supports only the small mapping-and-list subset
used by bootstrap configuration. It avoids a third-party dependency while
keeping the accepted configuration language easy to audit.

Example:
    Load repository-local configuration safely::

        config = load_simple_yaml("config/factory.yaml")
        mode = config["factory"]["mode"]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


BLOCKED_NAMES = {
    ".env",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
    "secrets",
    "secrets.json",
}
BLOCKED_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}


class RepoSafetyError(RuntimeError):
    """Indicate that a repository filesystem boundary would be crossed."""


def find_repo_root(start: str | Path | None = None) -> Path:
    """Find the nearest parent directory containing ``.git``.

    Args:
        start: Optional starting file or directory. When omitted, search starts
            from this module's location.

    Returns:
        Absolute path to the repository root.

    Raises:
        RepoSafetyError: If no repository root can be found.
    """
    current = Path(start or __file__).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RepoSafetyError("Could not locate repository root")


def resolve_repo_path(
    path: str | Path, repo_root: str | Path | None = None
) -> Path:
    """Resolve a path while rejecting traversal or symlink escape.

    Args:
        path: Absolute or repository-relative path to validate.
        repo_root: Optional explicit repository root.

    Returns:
        Absolute resolved path inside the repository.

    Raises:
        RepoSafetyError: If the resolved path is outside the repository.
    """
    root = Path(repo_root or find_repo_root()).resolve()
    candidate = Path(path)
    target = (
        candidate.resolve()
        if candidate.is_absolute()
        else (root / candidate).resolve()
    )
    # Resolving before the containment check also blocks symlink-based escapes.
    if target != root and root not in target.parents:
        raise RepoSafetyError(f"Path escapes repository: {path}")
    return target


def _assert_not_sensitive(path: Path) -> None:
    """Reject paths that look likely to contain credentials or private keys.

    Args:
        path: Resolved repository-local path to inspect.

    Raises:
        RepoSafetyError: If any path component or suffix is blocked.
    """
    for part in path.parts:
        lowered = part.lower()
        if lowered in BLOCKED_NAMES or lowered.startswith(".env."):
            raise RepoSafetyError(f"Blocked sensitive path: {path}")
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        raise RepoSafetyError(f"Blocked sensitive file type: {path}")


def safe_read_text(
    path: str | Path,
    repo_root: str | Path | None = None,
    max_lines: int | None = None,
) -> str:
    """Read a non-sensitive UTF-8 text file inside the repository.

    Args:
        path: Absolute or repository-relative file path.
        repo_root: Optional explicit repository root.
        max_lines: Optional maximum number of lines to return.

    Returns:
        UTF-8 file content, optionally truncated to ``max_lines``.

    Raises:
        RepoSafetyError: If the path escapes the repository, looks sensitive,
            or is not a file.
    """
    target = resolve_repo_path(path, repo_root)
    _assert_not_sensitive(target)
    if not target.is_file():
        raise RepoSafetyError(f"Expected readable file: {path}")
    text = target.read_text(encoding="utf-8")
    if max_lines is None:
        return text
    return "".join(text.splitlines(keepends=True)[:max_lines])


def safe_load_json(
    path: str | Path, repo_root: str | Path | None = None
) -> dict[str, Any]:
    """Load a repository-local JSON object safely.

    Args:
        path: Absolute or repository-relative JSON file path.
        repo_root: Optional explicit repository root.

    Returns:
        Parsed top-level JSON object.

    Raises:
        json.JSONDecodeError: If the file does not contain valid JSON.
        RepoSafetyError: If reading the file violates a safety boundary.
        ValueError: If the top-level JSON value is not an object.
    """
    data = json.loads(safe_read_text(path, repo_root))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def safe_write_text(
    path: str | Path,
    content: str,
    *,
    repo_root: str | Path | None = None,
    allowed_roots: Iterable[str | Path],
    append: bool = False,
) -> Path:
    """Write text only inside explicitly approved repository directories.

    Args:
        path: Absolute or repository-relative destination path.
        content: UTF-8 text to write.
        repo_root: Optional explicit repository root.
        allowed_roots: Repository-local directories that may receive writes.
        append: Whether to append instead of replacing the destination.

    Returns:
        Absolute path to the written file.

    Raises:
        RepoSafetyError: If the destination is outside the repository, looks
            sensitive, or is outside every approved write root.
    """
    root = Path(repo_root or find_repo_root()).resolve()
    target = resolve_repo_path(path, root)
    _assert_not_sensitive(target)
    # Callers must opt in to each writable subtree. Merely being inside the
    # repository is not sufficient permission to write.
    allowed = [resolve_repo_path(item, root) for item in allowed_roots]
    if not any(target == item or item in target.parents for item in allowed):
        raise RepoSafetyError(f"Write path is not approved: {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with target.open(mode, encoding="utf-8") as handle:
        handle.write(content)
    return target


def safe_write_json(
    path: str | Path,
    content: dict[str, Any],
    *,
    repo_root: str | Path | None = None,
    allowed_roots: Iterable[str | Path],
) -> Path:
    """Write a formatted JSON object inside an approved directory.

    Args:
        path: Absolute or repository-relative destination path.
        content: JSON object to serialize.
        repo_root: Optional explicit repository root.
        allowed_roots: Repository-local directories that may receive writes.

    Returns:
        Absolute path to the written JSON file.

    Raises:
        RepoSafetyError: If writing the file violates a safety boundary.
        TypeError: If ``content`` cannot be serialized as JSON.
    """
    return safe_write_text(
        path,
        json.dumps(content, indent=2) + "\n",
        repo_root=repo_root,
        allowed_roots=allowed_roots,
    )


def read_markdown_directory(
    directory: str | Path,
    *,
    repo_root: str | Path | None = None,
    max_lines_per_file: int | None = None,
) -> dict[str, str]:
    """Read Markdown files directly inside one repository directory.

    Args:
        directory: Repository-local directory containing Markdown files.
        repo_root: Optional explicit repository root.
        max_lines_per_file: Optional maximum lines read from each file.

    Returns:
        Mapping of repository-relative filenames to UTF-8 content.

    Raises:
        RepoSafetyError: If the directory is unsafe or does not exist.
    """
    root = Path(repo_root or find_repo_root()).resolve()
    folder = resolve_repo_path(directory, root)
    if not folder.is_dir():
        raise RepoSafetyError(f"Expected directory: {directory}")
    return {
        str(path.relative_to(root)): safe_read_text(
            path, root, max_lines_per_file
        )
        for path in sorted(folder.glob("*.md"))
        if path.is_file()
    }


def _parse_scalar(value: str) -> Any:
    """Parse one scalar from the supported bootstrap YAML subset.

    Args:
        value: Scalar text after a YAML key or list marker.

    Returns:
        Parsed string, boolean, integer, or ``None`` value.
    """
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def load_simple_yaml(
    path: str | Path, repo_root: str | Path | None = None
) -> dict[str, Any]:
    """Load the mapping-and-list YAML subset used by bootstrap configuration.

    Supported values are nested mappings, scalar lists, strings, booleans,
    integers, and null-like values. This is not a general YAML parser.

    Args:
        path: Absolute or repository-relative configuration file path.
        repo_root: Optional explicit repository root.

    Returns:
        Parsed configuration mapping.

    Raises:
        RepoSafetyError: If reading the file violates a safety boundary.
        ValueError: If indentation or syntax falls outside the supported
            subset.
    """
    text = safe_read_text(path, repo_root)
    raw_lines = text.splitlines()
    data: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any] | list[Any]]] = [(-1, data)]

    for index, raw_line in enumerate(raw_lines):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError(f"Invalid YAML indentation in {path}")
        container = stack[-1][1]

        if line.startswith("- "):
            if not isinstance(container, list):
                raise ValueError(f"Unexpected YAML list item in {path}")
            container.append(_parse_scalar(line[2:]))
            continue

        if ":" not in line or not isinstance(container, dict):
            raise ValueError(f"Unsupported YAML line in {path}: {line}")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value:
            container[key] = _parse_scalar(raw_value)
            continue

        # Look ahead to distinguish a nested mapping from a scalar list. The
        # bootstrap format deliberately avoids complex YAML constructs.
        child: dict[str, Any] | list[Any] = {}
        for next_line in raw_lines[index + 1 :]:  # noqa: E203
            if not next_line.strip() or next_line.lstrip().startswith("#"):
                continue
            next_indent = len(next_line) - len(next_line.lstrip(" "))
            if next_indent <= indent:
                break
            if next_line.strip().startswith("- "):
                child = []
            break
        container[key] = child
        stack.append((indent, child))

    return data
