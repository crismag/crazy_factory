# Slice 7 / 9D.5 — Layer 3: acceptance-based item retirement

**Goal:** stop ticking checklist items on coherence-green alone. An item retires
only on **acceptance evidence**: required files exist, criteria implemented,
required tests exist, validation passes, no blocking reviewer findings.

**Depends on:** per-file contracts (Slice 3) and the completeness reviewer
(Slice 6) for the strongest form; the `missing_required` half can land
independently and earlier.

## The current gap (verified)

`factory_advance.py:688` ticks the first open item when:

```python
application_result.applied
and application_result.source != "preserved"
and validation_status_label(validation_result) == "passed"
```

`validation` is whole-project coherence (compile+pytest+ruff). So "done" =
"compiles, lints, the tests that exist pass" — **not** "the file satisfies its
contract." A `pass`-stub with one trivial test that passes would tick (the
placeholder gate now blocks the worst of this, but minimal-but-real code still
slips). And `architecture.missing_required` (architecture.py:198) has **zero
callers** — required-file coverage is never enforced at completion.

## Change

Gate retirement on an explicit acceptance check:

```python
def item_acceptance(*, app_path, contract, file_spec, validation_result,
                    reviewer_verdict) -> ItemAcceptance:
    """Deterministic: do the evidence facts support retiring this item?"""
    missing_files = missing_required(app_path, contract)          # must be []
    coherence_passed = validation_status_label(validation_result) == "passed"
    tests_present = all_required_tests_exist(file_spec, app_path) # from Slice 3 spec
    no_blocking_review = reviewer_verdict in (None, "valid")      # from Slice 6
    complete = (not missing_files and coherence_passed
                and tests_present and no_blocking_review)
    return ItemAcceptance(complete, missing_files, tests_present, ...)
```

Replace the tick condition with `... and item_acceptance(...).complete`. Keep the
existing `applied and source != "preserved"` guards.

## Per-item evidence record

Persist evidence so status/reports can show *why* an item is/ isn't done:

```yaml
item_id:
  status: pending | in_progress | blocked | complete
  acceptance_criteria: [string]
  evidence:
    files: [{path, exists}]
    tests: [test_name]
    validation: {compileall: passed, pytest: passed, ruff: passed}
    reviewer: valid | revise_proposal | reject | none
```

Store alongside `MASTER_CHECKLIST.md` (e.g.
`factory_tasks/checklist_evidence.json`).

## Incremental landing

1. **Now-ish (cheap, no LLM):** wire `missing_required` into the tick condition —
   an item can't retire while its required files are absent. This alone kills the
   "ready while files missing" incoherence.
2. **After Slice 3/6:** add tests-present + reviewer-verdict to the gate for full
   acceptance.

## Tests

- An item with `missing_required != []` does **not** retire even when validation
  passes.
- A `pass`-stub that somehow passes coherence does **not** retire (no
  required-tests-present / reviewer blocks).
- A genuinely complete slice retires and the evidence record is written.
- `completion.is_complete` (project-level) only true when every item is
  acceptance-complete.

## Acceptance

- "Thin-but-green" no longer counts as done; retirement requires acceptance
  evidence; status/reports can explain the gap. `ruff`+`mypy` clean; suite green.
