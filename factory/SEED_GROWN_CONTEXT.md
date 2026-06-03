# Seed-Grown Context (Phase 9)

A Crazy Factory project does not start from a fixed Phase 1 → Phase 2 → Phase 3
script. It starts from one small **seed** document and grows its context one
artifact at a time. Each grow cycle reads the seed and the most recent
artifacts, asks the model for the single next most useful artifact, writes
exactly that one artifact, records it in a ledger, and stops. The model decides
the order; the engine only bounds what is allowed.

## Layout

```text
factory_state/projects/<project_id>/
  seed.md                  # the human-written seed (copied at start)
  context_ledger.json      # ordered index of grown artifacts
  contexts/                # the growing chain: 000_seed.md, 001_*.md, ...
  proposals/ contracts/ runs/ reflections/   # reserved siblings
```

`factory_state/projects/` is runtime output and is gitignored.

## No default project

The repository ships with **no active project and no committed app
workbench** — `apps/` is gitignored (workbenches are runtime, created by
`promote`). The factory never picks a project for you; an app to work on must
be **explicitly selected**, either by promoting a seed-grown project or by
setting `active_project` in config to a registered workbench. Running
`factory_tick.py` / `mission_loop.py` with nothing selected prints guidance and
exits cleanly. Sample seeds for different app types live in `examples/seeds/`
and are only used when you pass them explicitly.

## Commands

```bash
# Initialize a project from a seed (writes 000_seed and the ledger).
python3 scripts/context_growth.py start \
    --seed examples/seeds/sqlite_project_manager.md \
    --project-id sqlite_project_manager

# Grow one artifact per invocation (no internal loop).
python3 scripts/context_growth.py grow --project-id sqlite_project_manager

# Promote a grown task proposal into the build pipeline (owner-driven).
python3 scripts/context_growth.py promote --project-id sqlite_project_manager
```

## Two separate "projects"

The context engine and the build pipeline use different notions of project,
and they are NOT auto-wired:

- A **context project** lives in `factory_state/projects/<id>/` and is selected
  by `--project-id`. `grow` only touches it.
- The **build pipeline's active project** is `active_project` in
  `config/projects.yaml` (default `demo_app`); its workbench is
  `apps/<active_project>/`. `factory_tick.py` only touches that.

So growing context for `my_app` does not change what `factory_tick.py` builds.
`promote` is the explicit, owner-driven bridge between the two.

## promote

`promote --project-id <id>` is the one command that connects the layers. It is
owner-driven and never builds:

- registers the app workbench `apps/<id>/` and adds it to
  `config/projects.yaml`,
- makes `<id>` the active project (in both config files) and repoints
  `state/*.json` (so the next tick does not fail the project-mismatch check),
- copies the **latest valid** grown `task_proposal` into
  `apps/<id>/factory_tasks/planned_task.json`, forced to `authorized: false`,
- materializes the seed as `apps/<id>/factory_context/PROJECT_GOAL.md`.

It does NOT activate the coder, apply, validate, commit, push, or merge. After
`promote`, the owner reviews the planned task and sets `authorized: true` to
begin building through the normal pipeline. Promoting a project with no valid
task proposal fails safely.

## Growth decision

Each cycle the model returns a structured decision plus the artifact body:

```json
{
  "next_artifact_type": "requirements",
  "reason": "The seed defines the goal but not feature boundaries.",
  "requires_user_input": false,
  "safe_to_continue": true,
  "content": "..."
}
```

`next_artifact_type` is bounded to: `observation`, `questions`, `requirements`,
`architecture`, `task_proposal`, `reflection`, `validation_summary`,
`next_action`. The **order** is the model's choice; the set is fixed so a stray
type cannot create arbitrary files. An unknown type degrades to `observation`;
an unavailable or malformed model falls back to a deterministic placeholder
(it never crashes and never proposes an implementation).

## Safety boundaries

The context layer is deliberately weak by design:

- It writes **only** under `factory_state/projects/<id>/`. It never writes
  application code, applies a patch, runs a command, or touches git.
- When the model decides the next artifact is an implementation task
  (`task_proposal`), it does **not** modify files. It emits a *planned task
  contract* shaped for the existing Phase 3–8 pipeline, always with
  `authorized: false`. The owner must authorize it through the normal flow
  (`is_contract_actionable`) before anything is built, applied, validated, or
  committed.
- No autonomous loop, no background execution, no auto-apply, no auto-commit,
  no push or merge. All existing capability switches stay off by default.

## Handoff to the build pipeline

```text
context growth (seed → artifacts)
  → task_proposal contract (authorized: false)
  → owner authorizes (sets authorized: true in the pipeline's planned_task.json)
  → coder proposal → owner approval → controlled apply
  → validation → optional checkpoint auto-commit
```

The growth engine produces a pipeline-compatible, unauthorized contract; the
owner promotes and authorizes it. Nothing downstream runs without the owner's
explicit switches.
