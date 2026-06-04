# Slice 5 / 9D.3 — Layer 1: seed-derived requirement expansion

**Goal:** turn the generic per-file checklist item into a concrete, frozen
**file contract** of behaviors + tests + interfaces, derived from the seed. This
is the root fix for shallow output: the deterministic skeleton stays (good for
convergence), the LLM supplies the per-file flesh (good for quality).

**Depends on:** the packet (Slice 2) carries `expansion_status`. Composes with
the seed actually reaching planning (context-wedge fix, already landed).

## The tension it resolves

`completion.items_from_required_files` is deliberately generic ("Implement
`src/storage.py` with the functionality the project goal assigns to it") — that
determinism fixed run-to-run non-convergence. But it strips every behavior. We
keep the deterministic **order/count** and enrich the **content**.

## New role: `requirement_expander` (a.k.a. `focus_expander`)

```
scripts/requirement_expander.py
tests/test_requirement_expander.py
factory/instructions/REQUIREMENT_EXPANDER_RULES.md
```

```python
@dataclass(frozen=True)
class FocusRequirementSpec:
    file: str
    purpose: str
    required_behaviors: list[str]
    required_tests: list[str]
    interfaces: list[str]
    dependencies: list[str]
    done_definition: list[str]
    source: str                  # "ollama" | "fallback"

def expand_focus_requirements(
    *, seed_context: str, focus_file: str, architecture: dict,
    models_config: dict, factory_config: dict,
) -> FocusRequirementSpec: ...
```

Uses the **planner/architect-tier model** (interpretation, not codegen). Output
JSON-validated; on malformed/timeout → deterministic fallback (below).

### Example output

```yaml
file: src/storage.py
purpose: JSON persistence layer for the task-board app
required_behaviors:
  - save tasks to data/tasks.json
  - load tasks from data/tasks.json on startup
  - return empty list when the file is missing
  - handle corrupt JSON without crashing
  - preserve task id, title, and done fields
required_tests:
  - test_save_load_roundtrip
  - test_missing_file_returns_empty
  - test_corrupt_json_returns_empty
  - test_task_serialization_shape
interfaces:
  - save_tasks(tasks, path=DEFAULT_TASKS_PATH)
  - load_tasks(path=DEFAULT_TASKS_PATH)
dependencies: [src/task_model.py]
done_definition:
  - required behaviors implemented
  - required tests exist
  - compileall + pytest + ruff pass
```

## Persistence — freeze the contract (critical for convergence)

```
factory_context/file_contracts/<slugified_path>.yaml   # e.g. src_storage.yaml
```

**Rule:** expand a file ONCE, when its checklist item first becomes the focus;
freeze it. Do **not** regenerate every beat — regeneration reintroduces the
run-to-run variance the deterministic decomposition removed. Re-expand only on
explicit request (e.g. a recovery decision `revise_acceptance`).

## Wiring (`factory_advance.py:356-359`)

Today: `planning_context = context_bundle + arch_brief + focus` (focus = generic
item). Change: when the focus file has a frozen contract, load it; else expand +
freeze it; then fold the spec into `focus` **and** into the contract's
`acceptance_criteria`/`validation_plan` so it flows to planner → contract →
coder → patch-plan automatically.

```python
spec = load_or_expand_file_contract(focus_file, seed=goal_text, arch=arch_contract, ...)
focus = render_focus_with_spec(focus_md, spec)   # behaviors + acceptance + tests
# carry spec.required_behaviors -> contract acceptance_criteria during contract stage
```

The deterministic item list in `MASTER_CHECKLIST.md` is **unchanged** (same
order/count); only the per-beat focus + contract get richer.

## Fallback (degrade, never regress)

If expansion fails (Ollama down / unparseable):
- use today's generic focus text,
- set the packet/contract `expansion_status: fallback`,
- continue. The flow is never worse than current behavior.

## Tests

1. Mocked expander returns a spec → `planning_context` + contract
   `acceptance_criteria` contain the behaviors.
2. Frozen contract on disk → second beat does **not** call the model (load,
   don't re-expand). Assert no Ollama call.
3. Expander raises `OllamaConnectionError` → `expansion_status == "fallback"`,
   generic focus used, no crash.
4. Spec schema validation rejects malformed model output.

## Acceptance

- A focus file gains a concrete behavior/test spec from the seed, frozen once.
- Deterministic checklist order/count preserved (convergence intact).
- Ollama-down degrades to today's behavior, flagged. `ruff`+`mypy` clean; suite
  green.
