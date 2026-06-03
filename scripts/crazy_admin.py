#!/usr/bin/env python3
"""Crazy Factory admin CLI — the app builder usage flow.

Models the Django ``startproject`` / ``manage.py`` pattern for a general AI
software factory. An app to work on is created or attached explicitly,
registered in ``config/projects.yaml``, and activated; the factory then builds
the active project. Apps may live anywhere — under ``apps/<id>`` (embedded), a
sibling folder, or a completely separate repository (external).

Commands:
    crazy-admin startproject <id> [target_path]   scaffold a new app + register
    crazy-admin attachproject <id> <existing_path> register an existing codebase
    crazy-admin activate <id>                      set the active project
    crazy-admin status                             show the active project
    crazy-admin tick                               run one build tick on it

This CLI only writes the app scaffold (owner-driven), the per-project factory
state, and the registry. It never applies code, commits, pushes, or merges.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

import factory_tick  # noqa: E402
from project_registry import (  # noqa: E402
    RegistryError,
    active_project_id,
    app_is_external,
    load_registry,
    register_project,
    resolve_project,
    save_registry,
    set_active,
    state_path_for,
    workbench_exists,
)
from repo_tools import (  # noqa: E402
    find_repo_root,
    safe_load_json,
    safe_write_json,
    safe_write_text,
)
from seed_context import SeedError, validate_project_id  # noqa: E402

_STATE_SUBDIRS: tuple[str, ...] = (
    "factory_context",
    "factory_tasks",
    "factory_reports",
    "proposals",
    "contracts",
    "runs",
    "reflections",
)


class AdminError(RuntimeError):
    """Raised for user errors in the admin CLI."""


def _now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _abs_app_dir(app_path: str, root: Path) -> Path:
    """Resolve an app path (repo-relative or absolute) to an absolute dir."""
    candidate = Path(app_path)
    return (
        candidate.resolve()
        if candidate.is_absolute()
        else (root / candidate).resolve()
    )


def _scaffold_write(
    base: Path, relpath: str, content: str, *, force: bool
) -> None:
    """Write a scaffold file under an owner-chosen base, guarding traversal.

    Args:
        base: Absolute base directory the file must stay within.
        relpath: Path relative to ``base``.
        content: File content.
        force: Overwrite an existing file when ``True``.

    Raises:
        AdminError: If the path would escape ``base``.
    """
    target = (base / relpath).resolve()
    if ".." in Path(relpath).parts or (
        base != target and base not in target.parents
    ):
        raise AdminError(f"Refusing path outside the app dir: {relpath}")
    if target.exists() and not force:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _ensure_state_dirs(state_path: str, root: Path) -> None:
    """Create the per-project factory state directories (repo-internal)."""
    for sub in _STATE_SUBDIRS:
        safe_write_text(
            f"{state_path}/{sub}/.gitkeep",
            "",
            repo_root=root,
            allowed_roots=["factory_state"],
        )


def _crazy_project_yaml(project_id: str, repo_mode: str) -> str:
    """Render the per-app ``crazy_project.yaml`` marker."""
    return (
        f"project_id: {project_id}\n"
        f"repo_mode: {repo_mode}\n"
        "seed_file: docs/seed.md\n"
        "managed_by: crazy_factory\n"
    )


def _seed_template(project_id: str) -> str:
    """Render a starter seed for a new app."""
    return (
        "# Factory Seed\n\n"
        f"Goal:\nDescribe what {project_id} should do.\n\n"
        "Constraints:\n- \n\n"
        "Known Context:\nNone yet.\n\n"
        "Success:\nDescribe what 'done' looks like.\n"
    )


def startproject(
    project_id: str,
    target_path: str | None,
    *,
    root: Path,
    force: bool = False,
    reuse: bool = False,
) -> dict[str, Any]:
    """Scaffold a new app workbench and register it.

    Args:
        project_id: New project identifier.
        target_path: Where to create the app. Defaults to ``./<project_id>``.
        root: Absolute repository root.
        force: Overwrite existing scaffold files.
        reuse: Allow re-registering an existing project id.

    Returns:
        The registered entry summary.

    Raises:
        AdminError: If the project exists and neither --force nor --reuse set.
    """
    validate_project_id(project_id)
    registry = load_registry(root)
    if project_id in registry["projects"] and not (force or reuse):
        raise AdminError(
            f"Project '{project_id}' already exists. Use --force or --reuse."
        )
    app_path = target_path or project_id
    repo_mode = "external" if app_is_external(app_path, root) else "embedded"
    base = _abs_app_dir(app_path, root)

    _scaffold_write(
        base,
        "crazy_project.yaml",
        _crazy_project_yaml(project_id, repo_mode),
        force=force,
    )
    _scaffold_write(
        base,
        "README.md",
        f"# {project_id}\n\nBuilt with Crazy Factory.\n",
        force=force,
    )
    _scaffold_write(
        base, "docs/seed.md", _seed_template(project_id), force=force
    )
    _scaffold_write(
        base,
        "docs/requirements.md",
        "# Requirements\n\n_To be grown._\n",
        force=force,
    )
    _scaffold_write(
        base,
        "docs/decisions.md",
        "# Decisions\n\n_To be recorded._\n",
        force=force,
    )
    # Code lives under app/ (the coder's allowed write target), tests under
    # tests/, docs under docs/.
    _scaffold_write(base, "app/.gitkeep", "", force=force)
    _scaffold_write(base, "tests/.gitkeep", "", force=force)

    # The factory's per-tick working dirs live in the workbench so the
    # existing path-confinement checks hold (see resolve_project). Seed the
    # build context from the project goal so the first tick has something to
    # reason about.
    _scaffold_write(
        base,
        "factory_context/PROJECT_GOAL.md",
        _seed_template(project_id),
        force=force,
    )
    _scaffold_write(base, "factory_tasks/.gitkeep", "", force=force)
    _scaffold_write(base, "factory_reports/.gitkeep", "", force=force)

    state_path = state_path_for(project_id)
    _ensure_state_dirs(state_path, root)
    register_project(
        registry,
        project_id=project_id,
        app_path=app_path,
        state_path=state_path,
        repo_mode=repo_mode,
        seed_file="docs/seed.md",
        now=_now(),
    )
    save_registry(registry, root)
    return {
        "project_id": project_id,
        "app_path": app_path,
        "state_path": state_path,
        "repo_mode": repo_mode,
    }


def attachproject(
    project_id: str,
    existing_path: str,
    *,
    root: Path,
    write_config: bool = False,
) -> dict[str, Any]:
    """Register an existing codebase without moving it.

    Args:
        project_id: New project identifier.
        existing_path: Path to the existing project (repo-relative or absolute).
        root: Absolute repository root.
        write_config: Also write a ``crazy_project.yaml`` into the project.

    Returns:
        The registered entry summary.

    Raises:
        AdminError: If the path does not exist.
    """
    validate_project_id(project_id)
    base = _abs_app_dir(existing_path, root)
    if not base.is_dir():
        raise AdminError(f"Existing path not found: {existing_path}")
    repo_mode = (
        "external" if app_is_external(existing_path, root) else "embedded"
    )
    registry = load_registry(root)
    state_path = state_path_for(project_id)
    _ensure_state_dirs(state_path, root)
    register_project(
        registry,
        project_id=project_id,
        app_path=existing_path,
        state_path=state_path,
        repo_mode=repo_mode,
        seed_file="docs/seed.md",
        now=_now(),
    )
    save_registry(registry, root)
    if write_config:
        _scaffold_write(
            base,
            "crazy_project.yaml",
            _crazy_project_yaml(project_id, repo_mode),
            force=False,
        )
    return {
        "project_id": project_id,
        "app_path": existing_path,
        "state_path": state_path,
        "repo_mode": repo_mode,
    }


def activate(project_id: str, *, root: Path) -> None:
    """Set the active project and repoint durable state at it.

    Args:
        project_id: Project to activate.
        root: Absolute repository root.

    Raises:
        RegistryError: If the project is not registered.
    """
    registry = load_registry(root)
    set_active(registry, project_id)
    save_registry(registry, root)
    _sync_state_active(project_id, root)


def _sync_state_active(project_id: str, root: Path) -> None:
    """Keep ``state/*.json`` consistent with the active project."""
    for name, key in (
        ("factory_state.json", "active_project"),
        ("active_run.json", "active_project"),
        ("project_state.json", "project"),
    ):
        rel = f"state/{name}"
        state = safe_load_json(rel, root)
        state[key] = project_id
        safe_write_json(rel, state, repo_root=root, allowed_roots=["state"])


def status(root: Path) -> dict[str, Any]:
    """Return a status summary for the active project.

    Args:
        root: Absolute repository root.

    Returns:
        A mapping describing the active project's resolved paths and state.
    """
    registry = load_registry(root)
    pid = active_project_id(registry)
    if not pid:
        return {"active_project": "", "message": "No active project."}
    project = resolve_project(registry, pid)
    project_state = safe_load_json("state/project_state.json", root)
    return {
        "active_project": pid,
        "app_path": project["app_path"],
        "state_path": project["state_path"],
        "repo_mode": project["repo_mode"],
        "workbench_exists": workbench_exists(project["app_path"], root),
        "last_contract": project_state.get("last_contract_status"),
        "last_validation": project_state.get("last_validation_status"),
        "current_blocker": project_state.get("current_blocker"),
        "resume_from": safe_load_json("state/active_run.json", root).get(
            "resume_from"
        ),
    }


def _print_status(info: dict[str, Any]) -> None:
    """Print a status summary."""
    if not info.get("active_project"):
        print("Active project: (none)")
        print("Select one: crazy-admin startproject <id> | attachproject ...")
        return
    print(f"Active project: {info['active_project']}")
    print(f"App path:       {info['app_path']}")
    print(f"State path:     {info['state_path']}")
    print(f"Repo mode:      {info['repo_mode']}")
    print(f"Workbench OK:   {str(info['workbench_exists']).lower()}")
    print(f"Last contract:  {info.get('last_contract')}")
    print(f"Last validation:{info.get('last_validation')}")
    print(f"Current blocker:{info.get('current_blocker')}")
    print(f"Next:           {info.get('resume_from')}")


def main(argv: list[str] | None = None) -> int:
    """Run the crazy-admin CLI.

    Args:
        argv: Optional argument vector (for tests).

    Returns:
        Process exit code: ``0`` on success, ``2`` on a user error.
    """
    parser = argparse.ArgumentParser(prog="crazy-admin")
    sub = parser.add_subparsers(dest="command", required=True)
    sp = sub.add_parser("startproject")
    sp.add_argument("project_id")
    sp.add_argument("target_path", nargs="?", default=None)
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--reuse", action="store_true")
    ap = sub.add_parser("attachproject")
    ap.add_argument("project_id")
    ap.add_argument("existing_path")
    ap.add_argument("--write-config", action="store_true")
    av = sub.add_parser("activate")
    av.add_argument("project_id")
    sub.add_parser("status")
    sub.add_parser("tick")

    args = parser.parse_args(argv)
    root = find_repo_root()
    try:
        return _dispatch(args, root)
    except (AdminError, RegistryError, SeedError) as exc:
        print(f"crazy-admin error: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace, root: Path) -> int:
    """Dispatch a parsed command."""
    if args.command == "startproject":
        info = startproject(
            args.project_id,
            args.target_path,
            root=root,
            force=args.force,
            reuse=args.reuse,
        )
        print(
            f"Created project '{info['project_id']}' "
            f"({info['repo_mode']}) at {info['app_path']}."
        )
        print(f"State: {info['state_path']}")
        print(
            "Next: edit docs/seed.md, then `crazy-admin activate "
            f"{info['project_id']}`."
        )
        return 0
    if args.command == "attachproject":
        info = attachproject(
            args.project_id,
            args.existing_path,
            root=root,
            write_config=args.write_config,
        )
        print(
            f"Attached '{info['project_id']}' ({info['repo_mode']}) at "
            f"{info['app_path']}."
        )
        return 0
    if args.command == "activate":
        activate(args.project_id, root=root)
        print(f"Active project is now: {args.project_id}")
        return 0
    if args.command == "status":
        _print_status(status(root))
        return 0
    # tick
    return factory_tick.main()


if __name__ == "__main__":
    raise SystemExit(main())
