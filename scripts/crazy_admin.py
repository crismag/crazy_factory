#!/usr/bin/env python3
"""Crazy Factory admin CLI — the app builder usage flow.

Models the Django ``startproject`` / ``manage.py`` pattern for a general AI
software factory. An app to work on is created or attached explicitly and
registered in ``config/projects.yaml`` (a pure id->path directory). There is no
global active project: every command targets a project by ``<id>``, by
``--path``, or by the workbench it runs inside (cwd), so projects are
independently addressable and can run concurrently. Apps may live anywhere —
under ``apps/<id>`` (embedded), a sibling folder, or a separate repo (external).

Commands:
    crazy-admin startproject <id> [target_path]   scaffold a new app + register
    crazy-admin attachproject <id> <existing_path> register an existing codebase
    crazy-admin status [<id>] [--path DIR]        show a project's status
    crazy-admin advance [<id>] [--path DIR] [--all] run build advance(s)

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

import factory_advance  # noqa: E402
from mission_state import initial_state  # noqa: E402
from project_paths import (  # noqa: E402
    assert_project_local,
    load_project_factory_config,
    project_config_exists,
)
from settings import (  # noqa: E402
    WORKBENCH_DEFAULTS,
    load_engine_settings,
    project_app_path,
    workbench_defaults,
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
    all_project_ids,
    app_is_buildable,
    app_is_external,
    load_registry,
    register_project,
    resolve_project,
    resolve_target,
    save_registry,
    state_path_for,
    workbench_exists,
)
from repo_tools import (  # noqa: E402
    find_repo_root,
    resolve_repo_path,
    safe_read_text,
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


def _crazy_project_yaml(
    project_id: str, repo_mode: str, app_path: str, root: Path
) -> str:
    """Render the per-app ``crazy_project.yaml`` owner-control file."""
    control = default_control(
        project_id=project_id,
        mode=repo_mode,
        app_path=app_path,
        state_path=state_path_for(project_id, root),
    )
    return dump_control(control)


_WORKBENCH_KEYS: frozenset[str] = frozenset(WORKBENCH_DEFAULTS)


def parse_path_overrides(
    items: list[str] | None, root: Path
) -> dict[str, str]:
    """Parse ``KEY=VALUE`` workbench path overrides from CLI flags.

    Defaults come from the config ``paths.workbench`` block; only values that
    differ from the built-in defaults (config edits) plus any explicit CLI
    overrides are returned, so an unchanged project keeps an empty ``paths``.

    Args:
        items: Raw ``KEY=VALUE`` strings (may be ``None``).
        root: Absolute repository root.

    Returns:
        Mapping of workbench keys to override folder names.

    Raises:
        AdminError: On an unknown key or an unsafe (absolute/``..``) value.
    """
    overrides: dict[str, str] = {}
    # Config-level defaults that differ from the built-ins become overrides too,
    # so a project records the layout it was created under.
    for key, value in workbench_defaults(root).items():
        if value != WORKBENCH_DEFAULTS[key]:
            overrides[key] = value
    for item in items or []:
        if "=" not in item:
            raise AdminError(f"--path expects KEY=VALUE, got: {item!r}")
        key, _, value = item.partition("=")
        key, value = key.strip(), value.strip()
        if key not in _WORKBENCH_KEYS:
            raise AdminError(
                f"Unknown path key {key!r}. Valid keys: "
                f"{', '.join(sorted(_WORKBENCH_KEYS))}."
            )
        if not value or value.startswith("/") or ".." in Path(value).parts:
            raise AdminError(
                f"Path value for {key!r} must be a relative in-workbench "
                f"path (no leading '/', no '..'): {value!r}"
            )
        overrides[key] = value
    return overrides


def _seed_template(project_id: str) -> str:
    """Render a starter seed for a new app."""
    return (
        "# Factory Seed\n\n"
        f"Goal:\nDescribe what {project_id} should do.\n\n"
        "Constraints:\n- \n\n"
        "Known Context:\nNone yet.\n\n"
        "Success:\nDescribe what 'done' looks like.\n"
    )


def _persist_apps_base(value: str, root: Path) -> None:
    """Persist ``paths.engine.apps_base`` into the engine config file.

    So a separate runtime process (advance/mission-loop) honors the same base.
    """
    rel = "config/factory.yaml"
    out: list[str] = []
    replaced = False
    for line in safe_read_text(rel, root).splitlines(keepends=True):
        if line.startswith("    apps_base:"):
            out.append(f"    apps_base: {value}\n")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        raise AdminError(
            "Could not set apps_base: no 'apps_base:' line under paths.engine "
            "in config/factory.yaml."
        )
    safe_write_text(
        rel, "".join(out), repo_root=root, allowed_roots=["config"]
    )


def startproject(
    project_id: str,
    target_path: str | None,
    *,
    root: Path,
    force: bool = False,
    reuse: bool = False,
    paths: dict[str, str] | None = None,
    apps_base: str | None = None,
    target_location: str | None = None,
) -> dict[str, Any]:
    """Scaffold a new app workbench and register it.

    Args:
        project_id: New project identifier.
        target_path: Explicit app path (positional). When omitted, the app path
            is composed as ``<apps_base>/<project_id>``.
        root: Absolute repository root.
        force: Overwrite existing scaffold files.
        reuse: Allow re-registering an existing project id.
        paths: Optional workbench sub-folder overrides (the scaffold and the
            registry both use these so the layout is self-consistent).
        apps_base: Owner-configured apps base; persisted to the engine config so
            the runtime honors it, then used to compose the app path.
        target_location: Explicit full app path (wins over apps_base/positional).

    Returns:
        The registered entry summary.

    Raises:
        AdminError: If the project exists, or the target path is not an
            owner-approved build location (``TARGET_PATH_UNSUPPORTED``).
    """
    validate_project_id(project_id)
    registry = load_registry(root)
    if project_id in registry["projects"] and not (force or reuse):
        raise AdminError(
            f"Project '{project_id}' already exists. Use --force or --reuse."
        )
    # Persist an owner-supplied apps base first, so buildability is judged
    # against (and the runtime later honors) the same configured base.
    if apps_base:
        _persist_apps_base(apps_base, root)
    # Decide the app path: explicit target_location > positional > composed
    # <apps_base>/<id>. The requested path is honored as-is — never silently
    # substituted. Building is gated later by app_is_buildable at advance time,
    # so a path not under an approved base registers but will not build.
    app_path = (
        target_location or target_path or project_app_path(project_id, root)
    )
    repo_mode = "external" if app_is_external(app_path, root) else "embedded"
    base = _abs_app_dir(app_path, root)
    overrides = paths or {}
    # Effective workbench folder names: built-in defaults overlaid by overrides.
    # The scaffold and the resolver must agree, so both read this map.
    wb = {**WORKBENCH_DEFAULTS, **overrides}

    _scaffold_write(
        base,
        "crazy_project.yaml",
        _crazy_project_yaml(project_id, repo_mode, app_path, root),
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

    # The factory's per-advance working dirs live in the workbench so the
    # existing path-confinement checks hold (see resolve_project). Seed the
    # build context from the project goal so the first advance has something to
    # reason about.
    _scaffold_write(
        base,
        f"{wb['factory_context_dir']}/PROJECT_GOAL.md",
        _seed_template(project_id),
        force=force,
    )
    _scaffold_write(base, f"{wb['tasks_dir']}/.gitkeep", "", force=force)
    _scaffold_write(base, f"{wb['reports_dir']}/.gitkeep", "", force=force)

    # Phase 9A imported-context store: add-context lands files here and the
    # catalog tracks them. Start with an empty catalog so status reads cleanly.
    ctx = wb["context_dir"]
    _scaffold_write(base, f"{ctx}/imports/.gitkeep", "", force=force)
    _scaffold_write(base, f"{ctx}/extracted/.gitkeep", "", force=force)
    _scaffold_write(
        base,
        f"{ctx}/catalog.yaml",
        dump_catalog({"imports": {}, "files": {}}),
        force=force,
    )

    # Project-local runtime — config, run-state, and factory memory all live
    # inside the workbench so the engine root stays clean and each project owns
    # its files. The active factory config is copied from the configured
    # template; the resolver derives every other path from app_path + overrides.
    template = load_engine_settings(root)["factory_config_template"]
    _scaffold_write(
        base,
        "config/factory.yaml",
        safe_read_text(template, root),
        force=force,
    )
    for fname, body in initial_state(project_id).items():
        _scaffold_write(
            base,
            f"{wb['state_dir']}/{fname}",
            json.dumps(body, indent=2) + "\n",
            force=force,
        )
    _scaffold_write(
        base, f"{wb['factory_state_dir']}/.gitkeep", "", force=force
    )

    register_project(
        registry,
        project_id=project_id,
        app_path=app_path,
        state_path=state_path_for(project_id, root),
        repo_mode=repo_mode,
        seed_file="docs/seed.md",
        now=_now(),
        paths=overrides,
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
    state_path = state_path_for(project_id, root)
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
            _crazy_project_yaml(project_id, repo_mode, existing_path, root),
            force=False,
        )
    return {
        "project_id": project_id,
        "app_path": existing_path,
        "state_path": state_path,
        "repo_mode": repo_mode,
    }


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
        template = load_engine_settings(root)["factory_config_template"]
        assert_project_local(cfg_dest, app_path, root)
        safe_write_text(
            cfg_dest,
            safe_read_text(template, root),
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


def _resolve_project_arg(
    root: Path, project_id: str | None, *, path: str | None = None
) -> dict[str, Any]:
    """Resolve which project a command targets: by id, by --path, or by cwd.

    There is no global active project. When neither an id nor a path is given,
    the project is discovered from the current working directory.

    Raises:
        RegistryError: If nothing resolves (also wrapped from the resolver).
    """
    return resolve_target(
        load_registry(root),
        root,
        project_id=project_id,
        path=path,
        cwd=Path.cwd(),
    )


def status(project: dict[str, Any], root: Path) -> dict[str, Any]:
    """Return a detailed owner-facing status for one resolved project.

    Args:
        project: The resolved project mapping (by id, path, or cwd).
        root: Absolute repository root.

    Returns:
        A mapping describing paths, context, contract/proposal state, effective
        capabilities, and the current blocker.
    """
    pid = str(project["name"])
    info: dict[str, Any] = {
        "active_project": pid,
        "app_path": project["app_path"],
        "state_path": project["state_dir"],
        "repo_mode": project["repo_mode"],
        "workbench_exists": workbench_exists(project["app_path"], root),
    }
    if (
        app_is_buildable(project["app_path"], root)
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
        f"  remediation: {str(caps.get('allow_remediation', False)).lower()}"
    )
    print(f"  autonomous:  {str(caps.get('allow_autonomous', False)).lower()}")
    print(
        f"  auto_commit: {str(caps.get('allow_auto_commit', False)).lower()}"
    )
    print(f"\nCurrent blocker:\n  {info.get('current_blocker')}")
    print(f"\nNext:\n  bin/crazy-admin next {info['active_project']}")


def set_path(
    project_id: str, items: list[str], *, root: Path
) -> dict[str, str]:
    """Set or update a registered project's workbench path overrides.

    Merges ``KEY=VALUE`` overrides into the registry entry's ``paths`` map.
    Note this re-points where the factory reads/writes; it does not move any
    existing files — run before a project accumulates runtime, or relocate by
    hand.

    Args:
        project_id: Registered project to update.
        items: ``KEY=VALUE`` override strings.
        root: Absolute repository root.

    Returns:
        The merged override map now stored for the project.

    Raises:
        AdminError: On an unknown key or unsafe value.
        RegistryError: If the project is not registered.
    """
    if not items:
        raise AdminError("set-path expects at least one KEY=VALUE.")
    registry = load_registry(root)
    entry = (registry.get("projects") or {}).get(project_id)
    if not isinstance(entry, dict):
        raise RegistryError(f"Project is not registered: {project_id}")
    merged = dict(entry.get("paths") or {})
    merged.update(parse_path_overrides(items, root))
    register_project(
        registry,
        project_id=project_id,
        app_path=str(entry["app_path"]),
        state_path=str(entry.get("state_path") or ""),
        repo_mode=str(entry.get("repo_mode") or "embedded"),
        seed_file=str(entry.get("seed_file") or "docs/seed.md"),
        now=_now(),
        paths=merged,
    )
    save_registry(registry, root)
    return merged


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
    sp.add_argument(
        "--path",
        action="append",
        metavar="KEY=VALUE",
        help="Override a workbench folder, e.g. --path reports_dir=out.",
    )
    sp.add_argument(
        "--apps-base",
        default=None,
        help="Owner apps base (persisted); apps build at <apps-base>/<id>.",
    )
    sp.add_argument(
        "--target-location",
        default=None,
        help="Explicit full app path (must be under an approved apps base).",
    )
    spath = sub.add_parser("set-path")
    spath.add_argument("project_id")
    spath.add_argument("overrides", nargs="+", metavar="KEY=VALUE")
    ap = sub.add_parser("attachproject")
    ap.add_argument("project_id")
    ap.add_argument("existing_path")
    ap.add_argument("--write-config", action="store_true")
    mg = sub.add_parser("migrate-project-runtime")
    mg.add_argument("project_id")
    ac = sub.add_parser("add-context")
    ac.add_argument("project_id")
    ac.add_argument("source")
    st = sub.add_parser("status")
    st.add_argument("project_id", nargs="?", default=None)
    st.add_argument("--path", default=None)
    adv = sub.add_parser("advance")
    adv.add_argument("project_id", nargs="?", default=None)
    adv.add_argument("--path", default=None)
    adv.add_argument(
        "--all", action="store_true", help="advance every registered project"
    )
    # Owner-control commands target a project by <id>, by --path, or by the
    # workbench the command runs inside (cwd). There is no global active project.
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
        "enable-remediation",
        "disable-remediation",
        "enable-autonomous",
        "disable-autonomous",
        "enable-commit",
        "disable-commit",
    ):
        owner = sub.add_parser(name)
        owner.add_argument("project_id", nargs="?", default=None)
        owner.add_argument("--path", default=None)

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
            paths=parse_path_overrides(args.path, root),
            apps_base=args.apps_base,
            target_location=args.target_location,
        )
        print(
            f"Created project '{info['project_id']}' "
            f"({info['repo_mode']}) at {info['app_path']}."
        )
        print(f"State: {info['state_path']}")
        print(
            "Next: edit docs/seed.md, then "
            f"`crazy-admin advance {info['project_id']}`."
        )
        return 0
    if args.command == "set-path":
        merged = set_path(args.project_id, args.overrides, root=root)
        print(f"Path overrides for '{args.project_id}':")
        for key, value in sorted(merged.items()):
            print(f"  {key}: {value}")
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
        project = _resolve_project_arg(root, args.project_id, path=args.path)
        _print_status(status(project, root))
        return 0
    owner_result = _dispatch_owner(args, root)
    if owner_result is not None:
        return owner_result
    return _dispatch_advance(args, root)


def _dispatch_advance(args: argparse.Namespace, root: Path) -> int:
    """Run a planning advance for one project or, with --all, every one."""
    if getattr(args, "all", False):
        registry = load_registry(root)
        ids = all_project_ids(registry)
        if not ids:
            print("No registered projects to advance.")
            return 0
        for pid in ids:
            print(f"\n=== advance: {pid} ===")
            try:
                project = resolve_project(registry, pid)
            except RegistryError as exc:
                print(f"Skipping '{pid}': {exc}")
                continue
            factory_advance.main(project)
        return 0
    project = _resolve_project_arg(root, args.project_id, path=args.path)
    return factory_advance.main(project)


_CAPABILITY_COMMANDS: dict[str, tuple[str, bool]] = {
    "enable-apply": ("allow_apply", True),
    "disable-apply": ("allow_apply", False),
    "enable-validation": ("allow_validation", True),
    "disable-validation": ("allow_validation", False),
    "enable-remediation": ("allow_remediation", True),
    "disable-remediation": ("allow_remediation", False),
    "enable-autonomous": ("allow_autonomous", True),
    "disable-autonomous": ("allow_autonomous", False),
    "enable-commit": ("allow_auto_commit", True),
    "disable-commit": ("allow_auto_commit", False),
}


def _dispatch_owner(args: argparse.Namespace, root: Path) -> int | None:
    """Dispatch an owner-control command; return ``None`` if not one."""
    cmd = args.command
    if cmd == "next":
        project = _resolve_project_arg(root, args.project_id, path=args.path)
        print(
            describe_next(
                project,
                root,
                load_project_factory_config(project["app_path"], root),
            )
        )
        return 0
    if cmd == "authorize-task":
        project = _resolve_project_arg(root, args.project_id, path=args.path)
        authorize_task(project, root)
        print("Task authorized.\n\nNext:\n  bin/crazy-admin advance")
        return 0
    if cmd == "revoke-task":
        project = _resolve_project_arg(root, args.project_id, path=args.path)
        revoke_task(project, root)
        print("Task authorization revoked.")
        return 0
    if cmd == "approve-proposal":
        project = _resolve_project_arg(root, args.project_id, path=args.path)
        result = approve_proposal(project, root)
        pid = project["name"]
        print(
            f"Proposal approved: {result['proposal_id']}\n\nNext:\n"
            f"  bin/crazy-admin enable-apply {pid}\n  bin/crazy-admin advance"
        )
        return 0
    if cmd == "revoke-proposal":
        project = _resolve_project_arg(root, args.project_id, path=args.path)
        revoke_proposal(project, root)
        print("Proposal approval cleared.")
        return 0
    if cmd in _CAPABILITY_COMMANDS:
        cap_key, value = _CAPABILITY_COMMANDS[cmd]
        project = _resolve_project_arg(root, args.project_id, path=args.path)
        set_capability(project, root, cap_key, value)
        print(f"{cap_key} = {str(value).lower()} for {project['name']}.")
        return 0
    return None


if __name__ == "__main__":
    raise SystemExit(main())
