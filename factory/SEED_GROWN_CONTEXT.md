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

## Commands

```bash
# Initialize a project from a seed (writes 000_seed and the ledger).
python3 scripts/context_growth.py start \
    --seed examples/seeds/sqlite_project_manager.md \
    --project-id sqlite_project_manager

# Grow one artifact per invocation (no internal loop).
python3 scripts/context_growth.py grow --project-id sqlite_project_manager
```

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
