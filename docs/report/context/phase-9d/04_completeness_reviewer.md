# Slice 6 / 9D.4 — Layer 2: acceptance-completeness reviewer

**Goal:** reject thin-but-valid proposals **before** they become files. The
deterministic placeholder gate catches `pass` stubs; this catches "technically
implemented but doesn't satisfy the contract" (e.g. a `Task` that's constructor-
only, one happy-path test). Mirrors the proven `contract_review` pattern: model
proposes, reviewer judges, Python enforces.

**Depends on:** real per-file acceptance criteria (Slice 3) and the packet
(Slice 2). Without rich criteria there is nothing to review against.

## Module

```
scripts/completeness_review.py
tests/test_completeness_review.py
factory/instructions/REVIEWER_RULES.md   # already exists; tighten for this use
```

## Where it runs

Between proposal acceptance and the patch-apply, inside the application stage
(or just before `request_patch_plan`). It reviews the **proposal** (and, if you
prefer post-codegen review, the generated patch) against the file contract.
Recommended: review the **patch plan** (actual file contents) — that's where
thinness is concrete.

## Inputs / output

Inputs: file contract (Slice 3 spec) + acceptance_criteria, the proposed
patch/diff, current workbench state, validation_expectations.

```yaml
verdict: valid | revise_proposal | reject
missing_behaviors: [string]
missing_tests: [string]
quality_findings: [string]
recommended_revision: string
```

**Reject / revise when:** the patch doesn't satisfy the file contract; tests
don't map 1:1 to required behaviors; placeholder logic; happy-path only;
generated notes admit incompleteness; criteria ignored.

## Layered with the deterministic floor (do not replace it)

- **Floor (deterministic, already present):** `_is_placeholder_body`, path/
  import/name contract gate, syntax compile, required-file presence. A floor hit
  → `reject` regardless of the reviewer (LLM can never override the floor).
- **Reviewer (LLM, above the floor):** behavioral completeness vs the contract.
  Use the **stronger reviewer model** (`models.yaml: reviewer`) — diversity from
  the coder model catches what the generator missed.

## Decision → flow

- `valid` → proceed to apply.
- `revise_proposal` → do **not** apply; record `missing_behaviors` into the
  packet's rejection list and the next beat's coder slice; route via the
  recovery_router (`revise_proposal`) with a per-trigger budget.
- `reject` → terminal for this attempt; park or escalate per recovery ladder.

## Loop safety

Bounded by a per-trigger budget (reuse the recovery_router accounting). Enforce
an **escalation ladder** deterministically: repeated `revise_proposal` on the
same file with the same missing behaviors must escalate (→ `replan`/`ask_owner`/
park), not loop. The packet's `repeated_failure_patterns` feeds this.

## Fallback

Ollama down / malformed reviewer output → **do not fake a pass**; fall back to
the deterministic floor only and flag `review_status: floor_only` in the report.
Never let an unavailable reviewer auto-approve.

## Tests (mocked reviewer)

1. Constructor-only `Task` vs a contract requiring toggle/edit → `revise_proposal`
   with `missing_behaviors` listing toggle + edit.
2. Floor wins: placeholder body → `reject` even when the mocked reviewer says
   `valid`.
3. Complete proposal satisfying the contract → `valid`.
4. Reviewer raises → `floor_only`, no fake pass.
5. Escalation: 3rd identical `revise_proposal` → escalates (no infinite loop).

## Acceptance

- Thin-but-green code is blocked before it is written, with explicit missing
  behaviors fed back. Floor remains authoritative. Bounded + escalating.
  `ruff`+`mypy` clean; suite green.
