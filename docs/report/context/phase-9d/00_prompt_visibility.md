# Slice 1 / 9D.0 — Prompt Visibility Fixes

**Goal:** stop the coder from coding blind. Smallest, highest-ROI change; no new
modules, no LLM round-trips, low risk. Ship this first — it improves every
generation immediately and makes later slices more effective.

## 9D.0.1 — Feed acceptance criteria into the patch-plan (code) prompt

**Problem (verified):** `scripts/proposal_applier.py` `request_patch_plan` builds
`proposal_summary` from `proposal_id, task_id, files_to_create/modify/delete,
implementation_steps` — it omits `objective`, `scope`, and `acceptance_criteria`.
The model writing the *actual file contents* never sees the success definition.

**Edit:** thread the authorized `contract` (already a param of
`request_patch_plan`, `contract: dict | None`) into the summary:

```python
contract = contract or {}
proposal_summary = json.dumps(
    {
        "proposal_id": proposal_record.get("proposal_id"),
        "task_id": proposal_record.get("task_id"),
        "objective": contract.get("objective"),
        "scope": contract.get("scope"),
        "acceptance_criteria": contract.get("acceptance_criteria"),
        "validation_expectations": contract.get("validation_plan"),
        "files_to_create": proposal_record.get("files_to_create"),
        "files_to_modify": proposal_record.get("files_to_modify"),
        "files_to_delete": proposal_record.get("files_to_delete"),
        "implementation_steps": proposal_record.get("implementation_steps"),
    },
    indent=2,
)
```

Confirm the caller (`run_application_stage` → `request_patch_plan`) passes the
loaded contract; `coder_proposal`/`factory_advance` already load it for the
proposal stage, so plumb the same record through.

## 9D.0.2 — Add an explicit quality bar

**Problem:** neither the coder instruction (`coder_proposal.py:1016`) nor the
patch-plan instruction asks for completeness. We *reject* stubs after the fact
(`_is_placeholder_body`) but never *ask* for full behavior. Prevent > reject.

**Edit:** append to BOTH instruction strings a shared quality clause (extract a
constant, e.g. `QUALITY_BAR` in `prompt_builder.py`, and append to each):

```text
QUALITY BAR — your output is rejected if it violates any of these:
- Implement EVERY acceptance criterion fully; no partial/happy-path-only work.
- Every required behavior must have a corresponding test that exercises it.
- NO placeholder bodies: no bare `pass`, no `...`, no `TODO`, no
  `raise NotImplementedError`, no "implement here" comments, no empty tests.
- No unused imports; no tests that assert nothing or always pass.
- Do NOT add notes admitting the implementation is incomplete.
- If you cannot satisfy a criterion, say so explicitly in `notes` rather than
  emitting a stub — an honest gap is recoverable; a hidden stub is not.
```

This pairs with the deterministic `_is_placeholder_body` gate: the prompt asks
for completeness, the gate enforces it.

## 9D.0.3 — Fix `TEST_BUILDER_RULES.md` drift

**Problem (verified):** `factory/instructions/TEST_BUILDER_RULES.md` says *"Scope
checks to ONLY the files the current task creates… Never validate the whole
project for an incremental task."* This directly contradicts the current
**whole-project coherence gate** (`architecture.coherence_commands`) and the
recently tightened path checks. The prompt is fighting the gate.

**Edit:** replace that bullet with:

```text
- Run focused task validation when useful, but whole-project coherence gates
  remain mandatory before checkpoint, item retirement, or autopilot success:
    python3 -m compileall -q src tests
    python3 -m pytest tests
    ruff check src tests
  A task is not "done" until the whole project still compiles, lints, and
  passes — an incremental change that breaks a sibling file is not complete.
```

## 9D.0.4 — Give the planner an acceptance-criteria spec

**Problem:** `PLANNER_RULES.md` says only "Write measurable acceptance criteria"
— no format, minimum, or example, so criteria come out thin and propagate
everywhere.

**Edit:** add to `PLANNER_RULES.md`:

```text
## Acceptance Criteria Format
- Write ONE criterion per observable behavior (not per file).
- Each criterion must be a testable assertion: a reader must be able to write a
  test that passes iff the criterion holds.
- Bad:  "storage works"
- Good: "load_tasks() returns [] when data/tasks.json is missing"
- Good: "save_tasks() then load_tasks() round-trips id, title, and done"
- Cover the unhappy paths the goal implies (missing input, malformed input).
```

## Tests

- `tests/test_proposal_applier.py`: assert the patch-plan `proposal_summary`
  includes `acceptance_criteria` and `objective` when a contract is passed
  (inspect the request payload via the existing Ollama mock).
- `tests/test_coder_proposal.py`: assert the quality-bar text appears in the
  coder instruction.
- A doc/lint check (or a tiny unit test reading the file) asserting
  `TEST_BUILDER_RULES.md` no longer contains "Never validate the whole project".

## Acceptance for this slice

- Patch-plan prompt provably contains acceptance criteria + objective.
- Both generation prompts contain the quality bar.
- `TEST_BUILDER_RULES.md` matches the coherence-gate policy.
- `ruff` + `mypy` clean; full suite green under the clean-config stash.

## Why first

This is a lighter-weight version of "full expansion" that needs **no new LLM
role** — feeding the success definition to the code prompt is the single biggest
win per line changed, and it de-risks measuring the later slices.
