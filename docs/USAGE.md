# Crazy Factory — Usage & Execution Flow

This is the practical "how do I drive it" guide. It covers creating a project,
giving it context, running the tick pipeline, and the owner-controlled switches
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

# 3. Select it as the active project.
bin/crazy-admin activate todo_app

# 4. See where things stand.
bin/crazy-admin status

# 5. Run one planning tick (reads context, plans, proposes — never builds yet).
bin/crazy-admin tick
```

After step 5 the factory has produced a **planned task** and a **coder
proposal**, both unauthorized. Nothing was written to your app, committed, or
pushed. You move it forward by flipping switches (Section 5).

---

## 2. Core concepts

| Concept | What it is |
|---------|-----------|
| **Project registry** | `config/projects.yaml` maps each `project_id` to where its app lives (`app_path`), its factory memory (`state_path`), `repo_mode`, and `seed_file`. The factory never picks a project — you `activate` one. |
| **Embedded vs external** | *Embedded* apps live under `apps/<id>` (build now). *External* apps live anywhere on disk — registerable and inspectable, but building/ingesting into them is a later increment. |
| **Workbench** | The app directory. Holds your code plus the factory's per-tick working files (see layout below). |
| **Context store** | `<app_path>/context/` — imported project knowledge (Phase 9A). Separate from `factory_context/` (the goal + grown context). |
| **Capability switches** | Flags in `config/factory.yaml`. All default OFF. They are the only way actions escalate from "proposed" to "applied". |

### Workbench layout

```text
apps/todo_app/
  crazy_project.yaml        # per-app marker
  README.md
  app/                      # YOUR CODE — the coder's only write target
  docs/                     # docs the coder may write
  tests/                    # tests the coder may write
  context/                  # Phase 9A imported knowledge
    imports/<import_id>/     #   preserved originals
    extracted/<import_id>/   #   safe archive extraction output
    catalog.yaml             #   what was imported + which files feed the AI
  factory_context/          # PROJECT_GOAL.md + seed-grown context (prompt input)
  factory_tasks/            # planned_task.json, TASK_EXPANSION.md, NEXT_ACTION.md,
                            #   coder_proposal.json, patch_plan.json, approved_proposal.json
  factory_reports/          # per-tick reports + CHECKPOINT_HISTORY.md
```

---

## 3. Command reference

All commands are `bin/crazy-admin <command>` (a thin wrapper over
`scripts/crazy_admin.py`).

| Command | Purpose |
|---------|---------|
| `startproject <id> [path]` | Scaffold a new app workbench and register it. `path` defaults to `./<id>`; omit it or use `apps/<id>` for embedded. `--force` overwrites scaffold files. |
| `attachproject <id> <path>` | Register an existing codebase without scaffolding or modifying it. `--write-config` drops a `crazy_project.yaml` marker. |
| `add-context <id> <source>` | Ingest a file, directory, or archive (`zip`/`tar`/`tar.gz`/`tgz`/`gz`) into the project's context store. |
| `activate <id>` | Make `<id>` the active project (updates the registry + `state/*.json`). |
| `status` | Show the active project, its paths, context file count, and last tick/contract. |
| `tick` | Run one factory tick on the active project. |

Other entry points:

- `bin/factory-tick` — run a tick directly (same as `crazy-admin tick`).
- `bin/factory-status` / `bin/factory-report` / `bin/factory-watch` — inspect state and reports.
- `scripts/mission_loop.py` — the guarded, cron-friendly continuous entry point (Section 6).
- `scripts/context_growth.py start|grow|promote` — grow a project from a seed and promote it into the pipeline (see SEED_GROWN_CONTEXT.md).

---

## 4. Execution flow (one tick)

A tick is a single planning-and-proposal pass. Stages run in order; each later
stage only escalates if the matching owner switch is on.

```text
crazy-admin tick
  │
  ├─ resolve active project (registry)         # no project → prints guidance, exits 0
  ├─ honor control flags (stop/pause/blocked)  # owner can halt a run
  │
  ├─ LOAD CONTEXT      context_loader           # aggregate supported context files
  │                                             #   → "Loaded N context file(s) into planning"
  ├─ THINK             Architect role           # task expansion  → TASK_EXPANSION.md
  ├─ PLAN              Planner role             # next action     → NEXT_ACTION.md
  │                                             #   (both prompts include the context bundle)
  ├─ CONTRACT          contract_stage           # planned_task.json  (authorized: FALSE)
  ├─ CODE (propose)    coder_proposal           # coder_proposal.json  (proposes only)
  ├─ APPLY (preview)   proposal_applier         # patch_plan.json  (preview unless approved+enabled)
  ├─ TEST BUILDER      test_builder             # test_plan.json
  ├─ VALIDATE          validation_runner        # runs checks ONLY if validation.allow_run
  ├─ CHECKPOINT        checkpoint_commit        # git commit ONLY if git.allow_auto_commit
  │
  └─ write report → factory_reports/, update state/
```

The hard invariant chain:

> No authorization → no coder action. No owner approval → no apply. No
> validation → no checkpoint. No checkpoint → no auto-commit. No owner policy →
> no push/merge.

`is_contract_actionable` = the contract is `authorized: true` **and**
re-validates as valid on this tick (a cached "valid" is never trusted).

---

## 5. Driving a build: the owner control points

The factory escalates only when you act. Walk it up one notch at a time.

### Step 1 — Authorize the planned task
After a tick, review the plan and authorize it:

```text
apps/todo_app/factory_tasks/planned_task.json   →  set  "authorized": true
```

The factory never sets this itself. On the next tick the Coder activates and
produces a proposal.

### Step 2 — Approve applying the proposal
Review `coder_proposal.json`, then create a **separate** approval file the
factory never overwrites:

```text
apps/todo_app/factory_tasks/approved_proposal.json
  { "application_approved": true, "proposal_id": "<id from coder_proposal.json>" }
```

The `proposal_id` must match the current proposal, so a stale approval can't
authorize a freshly generated one.

### Step 3 — Enable writes, then validation, then commit
Flip these in `config/factory.yaml` as you gain confidence (each defaults OFF):

| Switch | Effect when `true` |
|--------|--------------------|
| `proposal_application.allow_apply` | Apply the approved patch plan to `app/`, `docs/`, `tests/`. |
| `proposal_application.allow_delete` | Allow deletes in a patch plan (otherwise deletes are rejected). |
| `validation.allow_run` | Run the allow-listed validation commands (shell-free). |
| `git.allow_auto_commit` | Commit the checkpoint to git (staged paths only; never push/merge). |

Writes are always confined to `app/`, `docs/`, `tests/`. Protected paths (root
`README.md`, `factory/`, `config/`, `.git/`, `state/`, secrets, …) are rejected.

### What stays OFF no matter what
`git.allow_auto_push`, `git.allow_auto_merge`, force pushes, history rewrites,
`sudo`, global installs, writes outside the repo. These are not owner switches —
they are not implemented as automated actions.

---

## 6. Running continuously (optional)

`scripts/mission_loop.py` wraps a tick with guards so it can be scheduled
(e.g. cron) without runaway behavior:

- **Lock** — `state/mission.lock` prevents overlapping runs (stale after
  `mission.lock_stale_seconds`, default 3600s).
- **Control flags** — drop a file to steer the loop:
  `state/stop.flag`, `state/pause.flag`, `state/blocked.flag`,
  `state/satisfied.flag` (JSON `stop_requested` / `pause_requested` in
  `state/factory_state.json` are also honored).
- **Stall + satisfaction** — the loop detects no-progress stalls and a
  satisfied checklist and stops on its own.

There is no infinite in-process loop and no background daemon: each invocation
does one guarded beat and exits.

---

## 7. Where output goes

| Location | Contents |
|----------|----------|
| `apps/<id>/factory_tasks/` | planned task, proposals, patch plan, approval, planning records |
| `apps/<id>/factory_reports/` | per-tick reports, `CHECKPOINT_HISTORY.md` |
| `apps/<id>/context/catalog.yaml` | imported-context catalog |
| `state/` | `factory_state.json`, `project_state.json`, `active_run.json`, flags, lock |
| `factory_state/projects/<id>/` | seed-grown context (gitignored) |
| `reports/`, `logs/` | global activity/daily reports and logs |

`apps/` and `factory_state/projects/` are gitignored — workbenches are runtime,
created by `startproject`/`promote`. Use `bin/crazy-admin status` or
`bin/factory-status` to inspect progress at any time.

---

## 8. Two ways to seed a project

You can start a project from either direction; both end at a registered,
activated workbench with an unauthorized planned task you then authorize.

1. **Direct** — `startproject` + `add-context`, as in the Quick start.
2. **Seed-grown** — `context_growth.py start --seed examples/seeds/<x>.md
   --project-id <id>`, then `grow` repeatedly, then `promote --project-id <id>`
   to register the workbench and stage an `authorized: false` planned task.

From there the execution flow (Section 4) and control points (Section 5) are
identical.
