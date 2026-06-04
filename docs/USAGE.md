# Crazy Factory — Usage & Execution Flow

This is the practical "how do I drive it" guide. It covers creating a project,
giving it context, running the advance pipeline, and the owner-controlled switches
that gate every action. For the design rationale behind each layer see
[app-builder-usage-flow.md](app-builder-usage-flow.md),
[phase-9a-context-aware-project-bootstrapping.md](phase-9a-context-aware-project-bootstrapping.md),
and [../factory/SEED_GROWN_CONTEXT.md](../factory/SEED_GROWN_CONTEXT.md).

The golden rule: **the model proposes, Python validates, and nothing acts
without an owner switch.** Every capability is off by default.

---

## 1. Quick start

```bash
# 1. Create an app to work on (scaffolds a workbench, registers it).
bin/crazy-admin startproject todo_app apps/todo_app

# 2. Give it project knowledge (a file, a folder, or an archive).
bin/crazy-admin add-context todo_app ./seed/

# 3. See where things stand for that project.
bin/crazy-admin status todo_app

# 4. Run one planning advance (reads context, plans, proposes — never builds yet).
bin/crazy-admin advance todo_app
```

After step 4 the factory has produced a **planned task** with
`authorized: false`. Nothing was written to your app, committed, or pushed. You
move it forward by flipping switches (Section 5); the Coder proposes only after
the owner authorizes a valid task and runs another advance.

---

## 2. Core concepts

| Concept | What it is |
|---------|-----------|
| **Project registry** | `config/projects.yaml` maps each `project_id` to where its app lives (`app_path`), `repo_mode`, and `seed_file`. Every runtime path is derived from `app_path` (the `state_path` entry is retained only so legacy data can be migrated). The factory never picks a project. Each command targets one by id, by `--path`, or by running from inside a workbench. |
| **Embedded vs external** | *Embedded* apps live under `apps/<id>` and build inside the repo. *External* apps are buildable only under the owner-approved apps base (`paths.engine.apps_base` or `CRAZY_FACTORY_APPS_BASE`); other external paths are registerable and inspectable, but refuse writes with `TARGET_PATH_UNSUPPORTED`. |
| **Engine vs workbench** | The Crazy Factory root is the *engine* (code, templates, global defaults, docs). A project's *runtime* — its `config/factory.yaml`, run state, factory memory, reports, tasks, and context — lives entirely inside its workbench (`app_path`). Nothing project-specific is written to the root. |
| **Workbench** | The app directory. Holds your code plus the factory's per-advance working files and project-local runtime (see layout below). |
| **Context store** | `<app_path>/context/` — imported project knowledge (Phase 9A). Separate from `factory_context/` (the goal + grown context). |
| **Capability switches** | Flags in the project-local `<app_path>/config/factory.yaml` (copied from the root template at `startproject`). All default OFF. They are the only way actions escalate from "proposed" to "applied". |

### Workbench layout

```text
apps/todo_app/
  crazy_project.yaml        # owner-control file: metadata, owner decisions,
                            #   per-project capability switches (driven by CLI)
  README.md
  app/                      # YOUR CODE — the coder's only write target
  docs/                     # docs the coder may write
  tests/                    # tests the coder may write
  config/factory.yaml       # project-local active config (copied from root template)
  state/                    # run state: factory_state.json, project_state.json,
                            #   active_run.json, flags, mission.lock
  factory_state/            # factory memory (seed-grown context, checkpoints)
  context/                  # Phase 9A imported knowledge
    imports/<import_id>/     #   preserved originals
    extracted/<import_id>/   #   safe archive extraction output
    catalog.yaml             #   what was imported + which files feed the AI
  factory_context/          # PROJECT_GOAL.md + seed-grown context (prompt input)
  factory_tasks/            # planned_task.json, TASK_EXPANSION.md, NEXT_ACTION.md,
                            #   coder_proposal.json, patch_plan.json, approved_proposal.json
  factory_reports/          # per-advance reports + CHECKPOINT_HISTORY.md
```

> **Project-local runtime.** Everything the factory writes for a project lives
> under its workbench — config, state, memory, reports (including the mission
> status and checkpoint log). The engine root holds only the default
> `config/factory.yaml` *template* and the registry. A project-specific write
> that would land in the root fails loudly. Projects created before this layout
> can be brought forward with `crazy-admin migrate-project-runtime <id>`.

### Configuring where the factory reads and writes

Locations are config-driven with CLI/env overrides — nothing is hardcoded (see
[scripts/settings.py](scripts/settings.py)). The `paths:` block in
`config/factory.yaml` holds the defaults:

```yaml
paths:
  workbench:                 # per-project folders, relative to a project's app_path
    state_dir: state
    factory_state_dir: factory_state
    reports_dir: factory_reports
    tasks_dir: factory_tasks
    factory_context_dir: factory_context
    context_dir: context
  engine:                    # engine-level, relative to the repo root
    registry_path: config/projects.yaml
    factory_config_template: config/factory.yaml
    models_config: config/models.yaml
    seed_staging_base: factory_state/projects
    logs_dir: logs
    apps_base: apps          # where generated app workbenches live
```

- **Workbench folders** — editing the `workbench:` block changes the default
  layout for *newly created* projects. Override one project at creation with
  `startproject <id> --path reports_dir=out`, or later with
  `set-path <id> state_dir=run`; overrides are stored in that project's registry
  entry. (`config/` inside a workbench is fixed and not configurable — the
  project config file must live at a known path.)
- **Engine locations** — override per invocation with `CRAZY_FACTORY_*`
  environment variables: `CRAZY_FACTORY_REGISTRY`, `CRAZY_FACTORY_CONFIG_TEMPLATE`,
  `CRAZY_FACTORY_MODELS_CONFIG`, `CRAZY_FACTORY_SEED_STAGING_BASE`,
  `CRAZY_FACTORY_LOGS_DIR`. These share across every `bin/*` entry point.

Override values for workbench folders must be in-workbench relative paths (no
leading `/`, no `..`); the fail-loud guard rejects anything that would escape.

### Building apps outside the repo (external workbench)

By default apps build in-repo at `apps/<id>`. To emit generated apps to a
location you choose, set `paths.engine.apps_base` to an **absolute** path (or
`CRAZY_FACTORY_APPS_BASE`). Then a project builds at `<apps_base>/<id>`:

```bash
# config persists the base; the app builds at /mnt/ai/workspaces/crazy_apps/tic-tac-toe
bin/crazy-admin startproject tic-tac-toe --apps-base /mnt/ai/workspaces/crazy_apps
# or an explicit full path:
bin/crazy-admin startproject tic-tac-toe --target-location /mnt/ai/workspaces/crazy_apps/tic-tac-toe
```

Confinement is preserved: each project may write only inside its own
`<apps_base>/<id>` folder. Attempts to reach a sibling project, the factory
repo, `/etc`, the home directory, `..`, or through a symlink are rejected. An
app at a location **not** under an approved base registers but refuses to build
with `TARGET_PATH_UNSUPPORTED` (no silent fallback to `apps/<id>`). Factory
internals (registry, logs, seed staging) always stay in the repo.

---

## 3. Command reference

All commands are `bin/crazy-admin <command>` (a thin wrapper over
`scripts/crazy_admin.py`).

| Command | Purpose |
|---------|---------|
| `startproject <id> [path]` | Scaffold a new app workbench and register it. `path` defaults to `./<id>`; omit it or use `apps/<id>` for embedded. `--force` overwrites scaffold files. `--path KEY=VALUE` (repeatable) overrides a workbench folder for this project, e.g. `--path reports_dir=out`. |
| `set-path <id> KEY=VALUE...` | Set/update a registered project's workbench folder overrides (persisted in the registry). Re-points where the factory reads/writes; it does not move existing files. |
| `attachproject <id> <path>` | Register an existing codebase without scaffolding or modifying it. `--write-config` drops a `crazy_project.yaml` marker. |
| `add-context <id> <source>` | Ingest a file, directory, or archive (`zip`/`tar`/`tar.gz`/`tgz`/`gz`) into the project's context store. |
| `migrate-project-runtime <id>` | Bring a pre-relocation project forward: non-destructively copy legacy root `state/`, `factory_state/projects/<id>/`, and `reports/` into the workbench, and materialize `config/factory.yaml` if missing. Leaves the old root folders in place. |
| `status [id] [--path DIR]` | Show one project: contract validation/authorization, proposal/approval, effective capabilities, current blocker. With no id/path, discover the project from the current workbench. |
| `next [id] [--path DIR]` | Tell you exactly what to do next for a project. With no id/path, discover the project from the current workbench. |
| `advance [id] [--path DIR] [--all]` | Run one factory advance for a targeted project, discovered workbench, or every registered project. |

Owner-control commands (the normal way to drive the safety gates — no manual
JSON editing). Each takes an optional `<id>` or `--path DIR`; without either,
the command discovers the project from the current workbench:

| Command | Purpose |
|---------|---------|
| `authorize-task [id]` | Authorize the current planned task. Refuses unless its contract currently validates. |
| `revoke-task [id]` | Reverse task authorization. |
| `approve-proposal [id]` | Approve the current coder proposal for application (records its `proposal_id`). |
| `revoke-proposal [id]` | Clear proposal approval. |
| `enable-apply` / `disable-apply [id]` | Toggle whether approved patch plans may be applied. |
| `enable-validation` / `disable-validation [id]` | Toggle running the allow-listed validation checks. |
| `enable-commit` / `disable-commit [id]` | Toggle checkpoint auto-commit (never push/merge). |

These edit the project-local control file `apps/<id>/crazy_project.yaml` (and
mirror the runtime artifacts the advance reads). They never relax a safety
boundary — `authorize-task` refuses a rejected contract, `approve-proposal`
refuses a missing/rejected proposal, and capabilities still default OFF.

Other entry points:

- `bin/factory-advance` — run a advance directly (same as `crazy-admin advance`).
- `bin/factory-status` / `bin/factory-report` / `bin/factory-watch` — inspect state and reports.
- `scripts/mission_loop.py` — the guarded, cron-friendly continuous entry point (Section 6).
- `scripts/context_growth.py start|grow|promote` — grow a project from a seed and promote it into the pipeline (see SEED_GROWN_CONTEXT.md).

---

## 4. Execution flow (one advance)

A advance is a single planning-and-proposal pass. Stages run in order; each later
stage only escalates if the matching owner switch is on.

```text
crazy-admin advance <id>
  │
  ├─ resolve target project (id/path/cwd)      # no target → prints guidance, exits 0
  ├─ honor control flags (stop/pause/blocked)  # owner can halt a run
  │
  ├─ LOAD CONTEXT      context_loader           # aggregate supported context files
  │                                             #   → "Loaded N context file(s) into planning"
  ├─ THINK             Architect role           # task expansion  → TASK_EXPANSION.md
  ├─ PLAN              Planner role             # next action     → NEXT_ACTION.md
  │                                             #   (both prompts include the context bundle)
  ├─ CONTRACT          contract_stage           # planned_task.json  (authorized: FALSE)
  ├─ CODE (propose)    coder_proposal           # skipped unless task is authorized+valid
  ├─ APPLY (preview)   proposal_applier         # patch_plan.json  (preview unless approved+enabled)
  ├─ TEST BUILDER      test_builder             # test_plan.json
  ├─ VALIDATE          validation_runner        # runs checks ONLY if validation.allow_run
  ├─ CHECKPOINT        checkpoint_commit        # git commit ONLY if git.allow_auto_commit
  │
  └─ write report → apps/<id>/factory_reports/, update apps/<id>/state/
```

The hard invariant chain:

> No authorization → no coder action. No owner approval → no apply. No
> validation → no checkpoint. No checkpoint → no auto-commit. No owner policy →
> no push/merge.

`is_contract_actionable` = the contract is `authorized: true` **and**
re-validates as valid on this advance (a cached "valid" is never trusted).

---

## 5. Driving a build: the owner control points

The factory escalates only when you act. Drive it with `crazy-admin` commands —
**you never hand-edit generated JSON in normal use.** When in doubt, run
`crazy-admin next` and it tells you the single next command.

```bash
crazy-admin next todo_app              # what should I do?
crazy-admin authorize-task todo_app    # Step 1
crazy-admin advance todo_app           # Coder now proposes
crazy-admin approve-proposal todo_app  # Step 2
crazy-admin enable-apply todo_app      # Step 3 (then validation, then commit)
crazy-admin advance todo_app           # applies within app/, docs/, tests/
```

### Step 1 — Authorize the planned task
`crazy-admin authorize-task <id>` reviews the contract and authorizes it. It
**refuses** if the contract's validation is not `valid` (e.g. a rejected
contract) — fix the plan or run another advance first. On the next advance the Coder
activates and produces a proposal.

### Step 2 — Approve applying the proposal
`crazy-admin approve-proposal <id>` records approval of the current proposal and
writes the matching approval artifact. The recorded `proposal_id` must match the
current proposal, so a stale approval can never authorize a freshly generated
one. Undo with `revoke-proposal`.

### Step 3 — Enable capabilities, one notch at a time
Each capability is a per-project switch (in `apps/<id>/crazy_project.yaml`),
default OFF. Toggle with a command — no global edits:

| Command | Effect when enabled |
|---------|--------------------|
| `enable-apply <id>` | Apply the approved patch plan to `app/`, `docs/`, `tests/`. |
| `enable-validation <id>` | Run the allow-listed validation commands (shell-free). |
| `enable-commit <id>` | Commit the checkpoint to git (staged paths only; never push/merge). |

A capability set in the control file is authoritative for that project;
otherwise the `config/factory.yaml` global default (OFF) applies. Writes are
always confined to `app/`, `docs/`, `tests/`. Protected paths (root
`README.md`, `factory/`, `config/`, `.git/`, `state/`, secrets, …) are rejected.

### Advanced / debug fallback
The control plane is still file-backed, so for debugging you *can* hand-edit
`apps/<id>/factory_tasks/planned_task.json` (`"authorized": true`) or
`approved_proposal.json` (`{"application_approved": true, "proposal_id": "…"}`),
or flip project-local switches in `apps/<id>/crazy_project.yaml`. The
`crazy-admin` commands are the supported path; manual editing is a fallback only.

### What stays OFF no matter what
`git.allow_auto_push`, `git.allow_auto_merge`, force pushes, history rewrites,
`sudo`, global installs, writes outside the repo. These are not owner switches —
they are not implemented as automated actions.

---

## 6. Running continuously (optional)

`scripts/mission_loop.py` wraps a advance with guards so it can be scheduled
(e.g. cron) without runaway behavior:

- **Lock** — `apps/<id>/state/mission.lock` prevents overlapping runs (stale
  after `mission.lock_stale_seconds`, default 3600s).
- **Control flags** — drop a file to steer the loop:
  `apps/<id>/state/stop.flag`, `pause.flag`, `blocked.flag`,
  `satisfied.flag` (JSON `stop_requested` / `pause_requested` in
  `apps/<id>/state/factory_state.json` are also honored).
- **Stall + satisfaction** — the loop detects no-progress stalls and a
  satisfied checklist and stops on its own.

There is no infinite in-process loop and no background daemon: each invocation
does one guarded beat and exits.

---

## 7. Where output goes

| Location | Contents |
|----------|----------|
| `apps/<id>/factory_tasks/` | planned task, proposals, patch plan, approval, planning records |
| `apps/<id>/factory_reports/` | per-advance reports, activity/daily blog, `CHECKPOINT_HISTORY.md` |
| `apps/<id>/context/catalog.yaml` | imported-context catalog |
| `apps/<id>/config/factory.yaml` | project-local active config (capability switches) |
| `apps/<id>/state/` | `factory_state.json`, `project_state.json`, `active_run.json`, flags, lock |
| `apps/<id>/factory_state/` | factory memory (seed-grown context, checkpoints) |
| `config/factory.yaml` (root) | default config *template* only — copied into each project |
| `checkpoints/`, `logs/` | engine-level commit ledger and logs |

`apps/` is gitignored — workbenches are runtime, created by
`startproject`/`promote`, and each owns its full runtime tree. Use
`bin/crazy-admin status <id>` or `bin/factory-status <id>` to inspect progress
at any time.

---

## 8. Two ways to seed a project

You can start a project from either direction; both end at a registered
workbench with an unauthorized planned task you then authorize.

1. **Direct** — `startproject` + `add-context`, as in the Quick start.
2. **Seed-grown** — `context_growth.py start --seed examples/seeds/<x>.md
   --project-id <id>`, then `grow` repeatedly, then `promote --project-id <id>`
   to register the workbench and stage an `authorized: false` planned task.

From there the execution flow (Section 4) and control points (Section 5) are
identical.
