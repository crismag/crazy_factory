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
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

import factory_tick  # noqa: E402
from mission_state import initial_state  # noqa: E402
from project_paths import (  # noqa: E402
    DEFAULT_FACTORY_CONFIG,
    assert_project_local,
    load_project_factory_config,
    project_config_exists,
)
from archive_utils import ArchiveError  # noqa: E402
from context_manager import (  # noqa: E402
    ContextError,
    add_context,
    dump_catalog,
    load_catalog,
    supported_file_count,
)
from owner_controls import (  # noqa: E402
    approve_proposal,
    authorize_task,
    describe_next,
    gather_status,
    revoke_proposal,
    revoke_task,
    set_capability,
)
from project_control import (  # noqa: E402
    ControlError,
    default_control,
    dump_control,
)
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
    resolve_repo_path,
    safe_load_json,
    safe_read_text,
    safe_write_json,
    safe_write_text,
)
from seed_context import SeedError, validate_project_id  # noqa: E402


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


def _crazy_project_yaml(project_id: str, repo_mode: str, app_path: str) -> str:
    """Render the per-app ``crazy_project.yaml`` owner-control file."""
    control = default_control(
        project_id=project_id,
        mode=repo_mode,
        app_path=app_path,
        state_path=state_path_for(project_id),
    )
    return dump_control(control)


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
        _crazy_project_yaml(project_id, repo_mode, app_path),
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

    # Phase 9A imported-context store: add-context lands files here and the
    # catalog tracks them. Start with an empty catalog so status reads cleanly.
    _scaffold_write(base, "context/imports/.gitkeep", "", force=force)
    _scaffold_write(base, "context/extracted/.gitkeep", "", force=force)
    _scaffold_write(
        base,
        "context/catalog.yaml",
        dump_catalog({"imports": {}, "files": {}}),
        force=force,
    )

    # Project-local runtime — config, run-state, and factory memory all live
    # inside the workbench so the engine root stays clean and each project owns
    # its files. The active factory config is copied from the root default
    # template; the resolver derives every other path from app_path.
    _scaffold_write(
        base,
        "config/factory.yaml",
        safe_read_text(DEFAULT_FACTORY_CONFIG, root),
        force=force,
    )
    for fname, body in initial_state(project_id).items():
        _scaffold_write(
            base,
            f"state/{fname}",
            json.dumps(body, indent=2) + "\n",
            force=force,
        )
    _scaffold_write(base, "factory_state/.gitkeep", "", force=force)

    register_project(
        registry,
        project_id=project_id,
        app_path=app_path,
        state_path=state_path_for(project_id),
        repo_mode=repo_mode,
        seed_file="docs/seed.md",
        now=_now(),
    )
    save_registry(registry, root)
    return {
        "project_id": project_id,
        "app_path": app_path,
        "state_path": f"{app_path}/state",
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
            _crazy_project_yaml(project_id, repo_mode, existing_path),
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
    project = resolve_project(registry, project_id)
    # External app runtime lives outside the repo (a deferred increment); its
    # project-local state cannot be written through the repo-confined helpers.
    if not app_is_external(project["app_path"], root):
        _sync_state_active(project_id, project, root)


def _sync_state_active(
    project_id: str, project: dict[str, Any], root: Path
) -> None:
    """Keep the project-local ``<app>/state/*.json`` pointed at the project.

    Materializes the bootstrap state first when missing (e.g. an attached
    project), so the project always owns its run-state.
    """
    state_dir = str(project["state_dir"])
    bootstrap = initial_state(project_id)
    for name, key in (
        ("factory_state.json", "active_project"),
        ("active_run.json", "active_project"),
        ("project_state.json", "project"),
    ):
        rel = f"{state_dir}/{name}"
        if resolve_repo_path(rel, root).is_file():
            state = safe_load_json(rel, root)
        else:
            state = bootstrap[name]
        state[key] = project_id
        safe_write_json(rel, state, repo_root=root, allowed_roots=[state_dir])


def _copy_legacy_tree(
    src_rel: str,
    dest_rel: str,
    app_path: str,
    root: Path,
    *,
    only_suffixes: tuple[str, ...] | None = None,
) -> dict[str, list[str]]:
    """Non-destructively copy a legacy runtime tree into the project folder.

    Files already present at the destination are left untouched (the project
    copy wins). Every write is funnelled through :func:`assert_project_local`
    so a mis-resolved destination fails loudly instead of landing in root.

    Args:
        src_rel: Repository-relative legacy source directory.
        dest_rel: Repository-relative destination under ``app_path``.
        app_path: The project's workbench path (the only writable root here).
        root: Absolute repository root.
        only_suffixes: When set, copy only files with these suffixes.

    Returns:
        Mapping with ``copied`` and ``skipped`` repository-relative paths.
    """
    copied: list[str] = []
    skipped: list[str] = []
    try:
        src_abs = resolve_repo_path(src_rel, root)
    except Exception:  # noqa: BLE001 - missing/odd legacy path → nothing to do
        return {"copied": copied, "skipped": skipped}
    if not src_abs.is_dir():
        return {"copied": copied, "skipped": skipped}
    for item in sorted(src_abs.rglob("*")):
        if not item.is_file():
            continue
        if only_suffixes and item.suffix not in only_suffixes:
            continue
        rel = item.relative_to(src_abs).as_posix()
        dest = f"{dest_rel}/{rel}"
        assert_project_local(dest, app_path, root)
        if resolve_repo_path(dest, root).exists():
            skipped.append(dest)
            continue
        safe_write_text(
            dest,
            safe_read_text(item, root),
            repo_root=root,
            allowed_roots=[app_path],
        )
        copied.append(dest)
    return {"copied": copied, "skipped": skipped}


def migrate_project_runtime(project_id: str, *, root: Path) -> dict[str, Any]:
    """Copy a project's pre-relocation root runtime into its workbench.

    Non-destructive: brings legacy root ``state/``, ``factory_state/projects/
    <id>/``, and ``reports/`` data into ``<app>/state``, ``<app>/factory_state``,
    and ``<app>/factory_reports``, and materializes a project-local
    ``config/factory.yaml`` when missing. Existing project files are never
    overwritten. The old root folders are left in place for the owner to remove.

    Args:
        project_id: Project to migrate.
        root: Absolute repository root.

    Returns:
        A summary with the copied/skipped paths per area and whether a config
        was materialized.

    Raises:
        AdminError: If the project is external (its runtime lives outside repo).
    """
    registry = load_registry(root)
    project = resolve_project(registry, project_id)
    if app_is_external(project["app_path"], root):
        raise AdminError(
            f"Project '{project_id}' is external; its runtime lives outside "
            "the repository and is not migrated by this command."
        )
    app_path = str(project["app_path"])
    legacy_state = str(project.get("legacy_state_path") or "")
    summary: dict[str, Any] = {"project_id": project_id, "areas": {}}

    # Legacy root run-state (shared state/*.json) → project-local state/.
    summary["areas"]["state"] = _copy_legacy_tree(
        "state",
        str(project["state_dir"]),
        app_path,
        root,
        only_suffixes=(".json",),
    )
    # Legacy per-project factory memory (factory_state/projects/<id>) →
    # project-local factory_state/.
    if legacy_state:
        summary["areas"]["factory_state"] = _copy_legacy_tree(
            legacy_state,
            str(project["factory_state_dir"]),
            app_path,
            root,
        )
    # Legacy root reports/ → project-local factory_reports/.
    summary["areas"]["reports"] = _copy_legacy_tree(
        "reports",
        str(project["report_root"]),
        app_path,
        root,
    )

    # Ensure the project owns its active factory config.
    summary["config_materialized"] = False
    if not project_config_exists(app_path, root):
        cfg_dest = str(project["factory_config_path"])
        assert_project_local(cfg_dest, app_path, root)
        safe_write_text(
            cfg_dest,
            safe_read_text(DEFAULT_FACTORY_CONFIG, root),
            repo_root=root,
            allowed_roots=[app_path],
        )
        summary["config_materialized"] = True
    return summary


def _print_migration(summary: dict[str, Any]) -> None:
    """Print the migrate-project-runtime result for the owner."""
    pid = summary["project_id"]
    print(f"Migrated runtime for '{pid}' into its workbench.")
    total_copied = 0
    for area, result in summary["areas"].items():
        copied = result["copied"]
        skipped = result["skipped"]
        total_copied += len(copied)
        print(
            f"  {area}: {len(copied)} copied, "
            f"{len(skipped)} skipped (already present)"
        )
    if summary["config_materialized"]:
        print("  config: materialized project-local config/factory.yaml")
    if total_copied == 0 and not summary["config_materialized"]:
        print("  Nothing to migrate — runtime is already project-local.")
    else:
        print(
            "\nLegacy root folders were left untouched. Once you've confirmed "
            "the project runs, you may remove the old root state/, reports/, "
            "and factory_state/projects/ data."
        )


def _resolve_project_arg(root: Path, project_id: str | None) -> dict[str, Any]:
    """Resolve an explicit project id, or the active project when omitted.

    Raises:
        AdminError: If no project is given and none is active.
        RegistryError: If the named project is not registered.
    """
    registry = load_registry(root)
    pid = project_id or active_project_id(registry)
    if not pid:
        raise AdminError(
            "No project specified and no active project. "
            "Pass a <project_id> or run `crazy-admin activate <id>`."
        )
    return resolve_project(registry, pid)


def status(root: Path) -> dict[str, Any]:
    """Return a detailed owner-facing status for the active project.

    Args:
        root: Absolute repository root.

    Returns:
        A mapping describing paths, context, contract/proposal state, effective
        capabilities, and the current blocker.
    """
    registry = load_registry(root)
    pid = active_project_id(registry)
    if not pid:
        return {"active_project": "", "message": "No active project."}
    project = resolve_project(registry, pid)
    info: dict[str, Any] = {
        "active_project": pid,
        "app_path": project["app_path"],
        "state_path": project["state_dir"],
        "repo_mode": project["repo_mode"],
        "workbench_exists": workbench_exists(project["app_path"], root),
    }
    if (
        not app_is_external(project["app_path"], root)
        and info["workbench_exists"]
    ):
        catalog = load_catalog(root, project)
        info["context_imports"] = len(catalog.get("imports") or {})
        info["context_supported_files"] = supported_file_count(catalog)
        info.update(
            gather_status(
                project,
                root,
                load_project_factory_config(project["app_path"], root),
            )
        )
    return info


def _print_status(info: dict[str, Any]) -> None:
    """Print the detailed owner-facing status."""
    if not info.get("active_project"):
        print("Active project: (none)")
        print("Select one: crazy-admin startproject <id> | attachproject ...")
        return
    print(f"Active project: {info['active_project']}")
    print(f"Project path:   {info['app_path']}")
    print(f"State path:     {info['state_path']}")
    print(
        f"Context:        {info.get('context_supported_files', 0)} supported "
        f"file(s), {info.get('context_imports', 0)} import(s)"
    )
    print("\nContract:")
    print(f"  exists:     {str(info.get('contract_exists', False)).lower()}")
    print(f"  validation: {info.get('contract_status', 'absent')}")
    print(
        f"  authorized: {str(info.get('contract_authorized', False)).lower()}"
    )
    for reason in info.get("contract_reasons", []) or []:
        print(f"    - {reason}")
    print("\nProposal:")
    print(f"  exists:   {str(info.get('proposal_exists', False)).lower()}")
    print(f"  approved: {str(info.get('proposal_approved', False)).lower()}")
    caps = info.get("capabilities", {})
    print("\nCapabilities (effective):")
    print(f"  apply:       {str(caps.get('allow_apply', False)).lower()}")
    print(f"  delete:      {str(caps.get('allow_delete', False)).lower()}")
    print(f"  validation:  {str(caps.get('allow_validation', False)).lower()}")
    print(
        f"  auto_commit: {str(caps.get('allow_auto_commit', False)).lower()}"
    )
    print(f"\nCurrent blocker:\n  {info.get('current_blocker')}")
    print(f"\nNext:\n  bin/crazy-admin next {info['active_project']}")


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
    mg = sub.add_parser("migrate-project-runtime")
    mg.add_argument("project_id")
    ac = sub.add_parser("add-context")
    ac.add_argument("project_id")
    ac.add_argument("source")
    sub.add_parser("status")
    sub.add_parser("tick")
    # Owner-control commands. project_id is optional → defaults to active.
    for name in (
        "next",
        "authorize-task",
        "revoke-task",
        "approve-proposal",
        "revoke-proposal",
        "enable-apply",
        "disable-apply",
        "enable-validation",
        "disable-validation",
        "enable-commit",
        "disable-commit",
    ):
        owner = sub.add_parser(name)
        owner.add_argument("project_id", nargs="?", default=None)

    args = parser.parse_args(argv)
    root = find_repo_root()
    try:
        return _dispatch(args, root)
    except (
        AdminError,
        RegistryError,
        SeedError,
        ContextError,
        ArchiveError,
        ControlError,
    ) as exc:
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
    if args.command == "migrate-project-runtime":
        _print_migration(migrate_project_runtime(args.project_id, root=root))
        return 0
    if args.command == "add-context":
        registry = load_registry(root)
        project = resolve_project(registry, args.project_id)
        result = add_context(
            project=project, source=args.source, root=root, now=_now()
        )
        print(
            f"Imported {result['import_id']} ({result['source_type']}): "
            f"{len(result['stored'])} file(s) stored, "
            f"{result['supported']} available to the AI."
        )
        if result["skipped"]:
            print(f"Skipped (secret-like): {', '.join(result['skipped'])}")
        return 0
    if args.command == "status":
        _print_status(status(root))
        return 0
    owner_result = _dispatch_owner(args, root)
    if owner_result is not None:
        return owner_result
    # tick
    return factory_tick.main()


_CAPABILITY_COMMANDS: dict[str, tuple[str, bool]] = {
    "enable-apply": ("allow_apply", True),
    "disable-apply": ("allow_apply", False),
    "enable-validation": ("allow_validation", True),
    "disable-validation": ("allow_validation", False),
    "enable-commit": ("allow_auto_commit", True),
    "disable-commit": ("allow_auto_commit", False),
}


def _dispatch_owner(args: argparse.Namespace, root: Path) -> int | None:
    """Dispatch an owner-control command; return ``None`` if not one."""
    cmd = args.command
    if cmd == "next":
        project = _resolve_project_arg(root, args.project_id)
        print(
            describe_next(
                project,
                root,
                load_project_factory_config(project["app_path"], root),
            )
        )
        return 0
    if cmd == "authorize-task":
        project = _resolve_project_arg(root, args.project_id)
        authorize_task(project, root)
        print("Task authorized.\n\nNext:\n  bin/crazy-admin tick")
        return 0
    if cmd == "revoke-task":
        project = _resolve_project_arg(root, args.project_id)
        revoke_task(project, root)
        print("Task authorization revoked.")
        return 0
    if cmd == "approve-proposal":
        project = _resolve_project_arg(root, args.project_id)
        result = approve_proposal(project, root)
        pid = project["name"]
        print(
            f"Proposal approved: {result['proposal_id']}\n\nNext:\n"
            f"  bin/crazy-admin enable-apply {pid}\n  bin/crazy-admin tick"
        )
        return 0
    if cmd == "revoke-proposal":
        project = _resolve_project_arg(root, args.project_id)
        revoke_proposal(project, root)
        print("Proposal approval cleared.")
        return 0
    if cmd in _CAPABILITY_COMMANDS:
        cap_key, value = _CAPABILITY_COMMANDS[cmd]
        project = _resolve_project_arg(root, args.project_id)
        set_capability(project, root, cap_key, value)
        print(f"{cap_key} = {str(value).lower()} for {project['name']}.")
        return 0
    return None


if __name__ == "__main__":
    raise SystemExit(main())
