#!/usr/bin/env python3
"""Repository-local file helpers with conservative path and secret guards."""

from __future__ import annotations

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
    """Raised when an operation would cross a repository safety boundary."""


def find_repo_root(start: str | Path | None = None) -> Path:
    """Find the nearest parent containing .git."""
    current = Path(start or __file__).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RepoSafetyError("Could not locate repository root")


def resolve_repo_path(path: str | Path, repo_root: str | Path | None = None) -> Path:
    """Resolve a path and reject traversal or symlink escape outside the repo."""
    root = Path(repo_root or find_repo_root()).resolve()
    candidate = Path(path)
    target = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if target != root and root not in target.parents:
        raise RepoSafetyError(f"Path escapes repository: {path}")
    return target


def _assert_not_sensitive(path: Path) -> None:
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
    """Read a UTF-8 text file inside the repo unless it looks sensitive."""
    target = resolve_repo_path(path, repo_root)
    _assert_not_sensitive(target)
    if not target.is_file():
        raise RepoSafetyError(f"Expected readable file: {path}")
    text = target.read_text(encoding="utf-8")
    if max_lines is None:
        return text
    return "".join(text.splitlines(keepends=True)[:max_lines])


def safe_write_text(
    path: str | Path,
    content: str,
    *,
    repo_root: str | Path | None = None,
    allowed_roots: Iterable[str | Path],
    append: bool = False,
) -> Path:
    """Write only inside explicitly allowed repository-local directories."""
    root = Path(repo_root or find_repo_root()).resolve()
    target = resolve_repo_path(path, root)
    _assert_not_sensitive(target)
    allowed = [resolve_repo_path(item, root) for item in allowed_roots]
    if not any(target == item or item in target.parents for item in allowed):
        raise RepoSafetyError(f"Write path is not approved: {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with target.open(mode, encoding="utf-8") as handle:
        handle.write(content)
    return target


def read_markdown_directory(
    directory: str | Path,
    *,
    repo_root: str | Path | None = None,
    max_lines_per_file: int | None = None,
) -> dict[str, str]:
    """Read Markdown files directly inside one approved directory."""
    root = Path(repo_root or find_repo_root()).resolve()
    folder = resolve_repo_path(directory, root)
    if not folder.is_dir():
        raise RepoSafetyError(f"Expected directory: {directory}")
    return {
        str(path.relative_to(root)): safe_read_text(path, root, max_lines_per_file)
        for path in sorted(folder.glob("*.md"))
        if path.is_file()
    }


def _parse_scalar(value: str) -> Any:
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
    """Load the mapping-and-list YAML subset used by bootstrap configuration."""
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

        child: dict[str, Any] | list[Any] = {}
        for next_line in raw_lines[index + 1 :]:
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
