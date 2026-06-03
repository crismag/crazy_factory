# App Builder Usage Flow

> For the hands-on end-to-end guide (quick start, execution flow, owner
> switches) see [USAGE.md](USAGE.md). This document covers the registry design.


Crazy Factory builds **one app at a time**, and it never picks that app for
you. Before any tick runs, an owner must create or attach an app, register it,
and activate it. This mirrors Django's `startproject` / `manage.py` split: the
admin CLI sets up and selects the project; the factory then works the active
project.

An app can live **anywhere**:

- **embedded** — under `apps/<id>/` inside this repository, or
- **external** — a sibling folder or a completely separate repository, at any
  absolute path you choose.

The factory does **not** hardwire `apps/<active_project>`. It resolves the
active project through a registry that maps a `project_id` to where the app
actually lives.

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
active_project: "widget"

projects:
  widget:
    app_path: "apps/widget"
    state_path: "factory_state/projects/widget"
    repo_mode: "embedded"
    seed_file: "docs/seed.md"
    created_at: "2026-06-02T00:00:00Z"
    updated_at: "2026-06-02T00:00:00Z"
```

`active_project: ""` (the shipped default) means **no app is selected** and the
factory stays idle.

## The CLI

```bash
# Create a new embedded app under apps/widget and register it.
bin/crazy-admin startproject widget apps/widget

# Create a new app anywhere on disk (registered as external).
bin/crazy-admin startproject myapp /home/me/code/myapp

# Register an existing codebase without moving or scaffolding it.
bin/crazy-admin attachproject legacy /home/me/code/legacy

# Select the app to work on.
bin/crazy-admin activate widget

# Show the active project and its resolved paths / last status.
bin/crazy-admin status

# Run one build tick on the active project.
bin/crazy-admin tick
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
    PROJECT_GOAL.md       # build context the tick reads
  factory_tasks/          # planned_task.json, contracts land here
  factory_reports/        # tick + checkpoint reports land here
```

`attachproject` does **not** scaffold or modify the existing code; it only
registers it (and, with `--write-config`, drops a `crazy_project.yaml` marker).

## What the factory resolves

When `factory_tick.py` (or `mission_loop.py`) runs, it:

1. loads the registry and reads `active_project`;
2. exits cleanly with guidance if nothing is selected;
3. resolves the entry to a workbench rooted at `app_path`
   (`<app_path>/factory_context`, `factory_tasks`, `factory_reports`, and the
   coder's `app/`, `docs/`, `tests/` write targets);
4. fails loud (prints and exits `0`) if the workbench directory is missing.

There is no `apps/<active_project>` fallback and no default project.

## Embedded vs external (current boundary)

**Embedded apps build today.** Their workbench is inside the repo, so the
factory's repo-confined write helpers can read context and write contracts,
proposals, patch plans, and reports.

**External apps are first-class in the registry** — you can `startproject` /
`attachproject` / `activate` / `status` them — but a `tick` on an external app
**stops with a notice instead of building**. Writing a build into a separate
repository crosses the factory's repo-confined write boundary, which is the
next increment. Until then, build under `apps/<id>/`.

## Safety

The admin CLI is owner-driven setup only. It writes the app scaffold, the
per-project factory state, and the registry. It **never** applies application
code, runs commands, commits, pushes, or merges. Every capability switch
(`proposal_application.allow_apply`, `validation.allow_run`,
`git.allow_auto_commit`, …) stays off by default; selecting an app does not
enable any of them. The model proposes; Python validates and, only when the
owner has flipped the relevant switch, applies.

## Relationship to seed-grown context

The [seed-grown context engine](../factory/SEED_GROWN_CONTEXT.md) grows a
project's context under `factory_state/projects/<id>/` and can `promote` a
grown task proposal into a workbench. `promote` and `crazy-admin startproject`
are two ways to land a registered, activated workbench; both produce an
unauthorized planned task the owner must authorize before anything is built.
