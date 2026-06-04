# App Builder Usage Flow

> For the hands-on end-to-end guide (quick start, execution flow, owner
> switches) see [USAGE.md](USAGE.md). This document covers the registry design.


Crazy Factory advances **one targeted app per invocation**, and it never picks
that app for you. Before any advance runs, an owner must create or attach an
app and register it. This mirrors Django's `startproject` / `manage.py` split:
the admin CLI sets up a workbench, then each command targets a project by
`<id>`, by `--path`, or by running from inside that workbench.

An app can live **anywhere**:

- **embedded** — under `apps/<id>/` inside this repository, or
- **external** — a sibling folder or a completely separate repository, at any
  absolute path you choose.

The factory does **not** hardwire `apps/<active_project>`. It resolves the
target project through a registry that maps a `project_id` to where the app
actually lives, or from the project's own `crazy_project.yaml` when targeted by
path/cwd.

## The registry

`config/projects.yaml` is the registry. Each entry records:

| field        | meaning                                                        |
|--------------|----------------------------------------------------------------|
| `app_path`   | where the app being built lives (the workbench)                |
| `state_path` | where the factory keeps its own per-project memory under `factory_state/projects/<id>/` |
| `repo_mode`  | `embedded` (under `apps/`) or `external` (anywhere else)        |
| `seed_file`  | the seed document, relative to `app_path`                      |
| `created_at` / `updated_at` | bookkeeping timestamps                          |

```yaml
projects:
  widget:
    app_path: "apps/widget"
    state_path: "factory_state/projects/widget"
    repo_mode: "embedded"
    seed_file: "docs/seed.md"
    created_at: "2026-06-02T00:00:00Z"
    updated_at: "2026-06-02T00:00:00Z"
```

There is no global active project in the registry. An invocation without
`<id>`, `--path`, or a current directory inside a workbench exits with guidance.

## The CLI

```bash
# Create a new embedded app under apps/widget and register it.
bin/crazy-admin startproject widget apps/widget

# Create a new app anywhere on disk (registered as external).
bin/crazy-admin startproject myapp /home/me/code/myapp

# Register an existing codebase without moving or scaffolding it.
bin/crazy-admin attachproject legacy /home/me/code/legacy

# Show the project and its resolved paths / last status.
bin/crazy-admin status widget

# Run one build advance on that project.
bin/crazy-admin advance widget
```

`startproject` scaffolds a Django-like workbench:

```text
<app_path>/
  crazy_project.yaml      # per-app marker (project_id, repo_mode, seed_file)
  README.md
  docs/seed.md            # the seed — edit this to describe the app
  docs/requirements.md
  docs/decisions.md
  app/                    # application code (the coder's only write target)
  tests/                  # tests (a write target)
  factory_context/
    PROJECT_GOAL.md       # build context the advance reads
  factory_tasks/          # planned_task.json, contracts land here
  factory_reports/        # advance + checkpoint reports land here
```

`attachproject` does **not** scaffold or modify the existing code; it only
registers it (and, with `--write-config`, drops a `crazy_project.yaml` marker).

## What the factory resolves

When `factory_advance.py` (or `mission_loop.py`) runs, it:

1. resolves a target project by explicit id, explicit `--path`, or cwd;
2. exits cleanly with guidance if no target can be resolved;
3. resolves that project to a workbench rooted at `app_path`
   (`<app_path>/factory_context`, `factory_tasks`, `factory_reports`, and the
   coder's `app/`, `docs/`, `tests/` write targets);
4. fails loud (prints and exits `0`) if the workbench directory is missing.

There is no `apps/<active_project>` fallback and no default project.

## Embedded vs external (current boundary)

**Embedded apps build inside the repo.** Their workbench lives under the factory
repo, so the factory can read context and write contracts, proposals, patch
plans, and reports under that workbench.

**External apps are buildable only under an owner-approved apps base.** Set
`paths.engine.apps_base` or `CRAZY_FACTORY_APPS_BASE` to an absolute directory;
projects under `<apps_base>/<id>` may build while staying confined to that
project folder. External apps elsewhere can be registered and inspected, but
`advance` stops with `TARGET_PATH_UNSUPPORTED` rather than writing there.

## Safety

The admin CLI is owner-driven setup only. It writes the app scaffold, the
per-project factory state, and the registry. It **never** applies application
code, runs commands, commits, pushes, or merges. Every capability switch
(`proposal_application.allow_apply`, `validation.allow_run`,
`git.allow_auto_commit`, …) stays off by default; targeting an app does not
enable any of them. The model proposes; Python validates and, only when the
owner has flipped the relevant switch, applies.

## Relationship to seed-grown context

The [seed-grown context engine](../factory/SEED_GROWN_CONTEXT.md) grows a
project's context under `factory_state/projects/<id>/` and can `promote` a
grown task proposal into a workbench. `promote` and `crazy-admin startproject`
are two ways to land a registered workbench; both produce an unauthorized
planned task the owner must authorize before anything is built.
