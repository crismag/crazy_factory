#!/usr/bin/env python3
"""Central path settings for Crazy Factory — the single source of truth.

Config provides defaults (the ``paths:`` block in the engine config file) and
environment variables override engine-level locations at invocation, so no
read/write location is hardcoded across the codebase.

Two groups of locations:

- **Workbench** sub-folder names, relative to a project's ``app_path`` (state,
  factory_state, reports, tasks, context). Per-project overrides are persisted
  in the registry entry (see :mod:`project_registry`) and resolved by
  :func:`project_paths.resolve_paths`. ``config_dir``/``factory_config_path``
  are deliberately NOT configurable — the project config file lives at a
  resolved path, so making them configurable would be a bootstrap recursion.
- **Engine** locations, relative to the repo root (the registry, the factory
  config template, the models config, the seed-staging base, logs). These are
  global; the ``CRAZY_FACTORY_*`` environment variables are the override
  channel shared by every ``bin/*`` entry point.

The engine config file itself sits at a fixed bootstrap location
(:data:`ENGINE_CONFIG`) — the anchor from which the configurable locations are
read.
"""

from __future__ import annotations

import os
from pathlib import Path

from repo_tools import RepoSafetyError, load_simple_yaml, resolve_repo_path

# Fixed bootstrap anchor: the engine's own config.
ENGINE_CONFIG = "config/factory.yaml"

# Per-project workbench sub-folder names (relative to app_path).
WORKBENCH_DEFAULTS: dict[str, str] = {
    "state_dir": "state",
    "factory_state_dir": "factory_state",
    "reports_dir": "factory_reports",
    "tasks_dir": "factory_tasks",
    "factory_context_dir": "factory_context",
    "context_dir": "context",
}

# Engine-level locations (relative to the repo root).
ENGINE_DEFAULTS: dict[str, str] = {
    "registry_path": "config/projects.yaml",
    "factory_config_template": "config/factory.yaml",
    "models_config": "config/models.yaml",
    "seed_staging_base": "factory_state/projects",
    "logs_dir": "logs",
}

# Environment override channel for engine locations (env var -> engine key).
_ENGINE_ENV: dict[str, str] = {
    "CRAZY_FACTORY_REGISTRY": "registry_path",
    "CRAZY_FACTORY_CONFIG_TEMPLATE": "factory_config_template",
    "CRAZY_FACTORY_MODELS_CONFIG": "models_config",
    "CRAZY_FACTORY_SEED_STAGING_BASE": "seed_staging_base",
    "CRAZY_FACTORY_LOGS_DIR": "logs_dir",
}


def _load_paths_block(root: Path) -> dict:
    """Return the ``paths:`` mapping from the engine config (``{}`` if absent).

    Never raises: a missing or unparsable config falls back to ``{}`` so the
    built-in defaults always apply and the bootstrap can never be broken by a
    bad config.
    """
    try:
        if not resolve_repo_path(ENGINE_CONFIG, root).is_file():
            return {}
        config = load_simple_yaml(ENGINE_CONFIG, root)
    except (RepoSafetyError, ValueError):
        return {}
    paths = config.get("paths")
    return paths if isinstance(paths, dict) else {}


def _overlay(defaults: dict[str, str], block: object) -> dict[str, str]:
    """Overlay a config sub-block of string values onto the built-in defaults."""
    result = dict(defaults)
    if isinstance(block, dict):
        for key in defaults:
            value = block.get(key)
            if isinstance(value, str) and value.strip():
                result[key] = value.strip()
    return result


def workbench_defaults(root: Path) -> dict[str, str]:
    """Return workbench sub-folder names: built-in defaults overlaid by config.

    Args:
        root: Absolute repository root.

    Returns:
        Mapping of workbench keys to folder names (relative to ``app_path``).
    """
    return _overlay(
        WORKBENCH_DEFAULTS, _load_paths_block(root).get("workbench")
    )


def load_engine_settings(root: Path) -> dict[str, str]:
    """Return engine locations: defaults, overlaid by config, then env vars.

    Args:
        root: Absolute repository root.

    Returns:
        Mapping of engine keys to repo-relative locations.
    """
    result = _overlay(ENGINE_DEFAULTS, _load_paths_block(root).get("engine"))
    for env_var, key in _ENGINE_ENV.items():
        override = os.environ.get(env_var)
        if override and override.strip():
            result[key] = override.strip()
    return result
