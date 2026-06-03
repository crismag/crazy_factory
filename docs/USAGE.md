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

> **Validate your install:** `tests/manual_run_flow.sh` runs this whole flow
> against a throwaway project and asserts the safety invariants (context
> loaded, secrets skipped, planned task `authorized: false`, no code
> generated). It backs up and restores your tracked config/state, so it is
> safe to run anytime.

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
  crazy_project.yaml        # owner-control file: metadata, owner decisions,
                            #   per-project capability switches (driven by CLI)
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
| `status` | Show the active project: contract validation/authorization, proposal/approval, effective capabilities, current blocker. |
| `next [id]` | Tell you exactly what to do next for a project (defaults to the active one). |
| `tick` | Run one factory tick on the active project. |

Owner-control commands (the normal way to drive the safety gates — no manual
JSON editing). Each takes an optional `<id>`, defaulting to the active project:

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
mirror the runtime artifacts the tick reads). They never relax a safety
boundary — `authorize-task` refuses a rejected contract, `approve-proposal`
refuses a missing/rejected proposal, and capabilities still default OFF.

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

The factory escalates only when you act. Drive it with `crazy-admin` commands —
**you never hand-edit generated JSON in normal use.** When in doubt, run
`crazy-admin next` and it tells you the single next command.

```bash
crazy-admin next                       # what should I do?
crazy-admin authorize-task todo_app    # Step 1
crazy-admin tick                       # Coder now proposes
crazy-admin approve-proposal todo_app  # Step 2
crazy-admin enable-apply todo_app      # Step 3 (then validation, then commit)
crazy-admin tick                       # applies within app/, docs/, tests/
```

### Step 1 — Authorize the planned task
`crazy-admin authorize-task <id>` reviews the contract and authorizes it. It
**refuses** if the contract's validation is not `valid` (e.g. a rejected
contract) — fix the plan or run another tick first. On the next tick the Coder
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
or flip the global switches in `config/factory.yaml`. The `crazy-admin` commands
are the supported path; manual editing is a fallback only.

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
