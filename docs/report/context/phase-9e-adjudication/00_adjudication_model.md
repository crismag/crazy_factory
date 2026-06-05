# 00 — Adjudication model (dispositions + the LLM director)

Replaces the binary "valid/rejected" patch/proposal verdict with a graded,
seed-grounded **disposition** plus an **action plan** the LLM directs.

## Disposition taxonomy

| Disposition | Meaning | Who can decide | Effect |
|---|---|---|---|
| `accept` | Aligned with the seed/contract intent; defects (if any) are none/auto-fixed | LLM (above floor) | proceed to apply/checkpoint |
| `fix` | Trivially repairable defects (lint, unused imports, formatting, import order) | LLM or deterministic floor | run repair skills on the **kept** content, then re-adjudicate |
| `scope_down` | Over-reaches the current focus/seed scope (extra modules, premature files, stubs) | LLM | drop/defer extras to their own items; keep the in-focus part |
| `redirect` | **Directional divergence** from the seed/sub-contexts (wrong architecture, forbidden tech, missing required behavior, building the wrong thing) | LLM | revise contract/plan/context and re-plan via skills |
| `escalate` | Genuinely ambiguous or an owner-policy call | LLM | park with a specific owner question |
| `reject_unsafe` | Safety-floor hit (forbidden ops, secrets, path/contract-safety) | **deterministic floor ONLY** | hard reject; LLM can neither override nor fabricate |

There is no blunt "reject that discards work." The nearest are `reject_unsafe`
(floor) and `escalate` (owner) — both keep the artifacts.

## The decision ladder (mirrors contract_review, generalized)

```
1. Deterministic safety floor (non-negotiable)
   forbidden ops / secrets / path escape / contract-safety  -> reject_unsafe
2. Deterministic fixable scan (cheap, model-free)
   lint(F401, formatting), out-of-focus files, no-content    -> proposes fix/scope_down skills
3. LLM adjudicator (above the floor) — the DIRECTOR
   reads seed + sub-contexts + contract/proposal/patch(content) + findings
   -> disposition + rationale + ordered skill calls (+ optional new context)
4. Deterministic fallback (LLM down/malformed)
   apply step-2 fixes if safe; otherwise escalate. NEVER fake accept.
```

The floor is first and wins; the LLM operates strictly above it and can only
choose among **allowed skills** (see 01). Step 2 gives a model-free path so the
common fixables resolve even when Ollama is down.

## The Adjudicator / Director role

New module `scripts/adjudicator.py`. Uses the **reviewer** model.

Inputs (the evidence it reasons over — reuses the 9D `DiagnosisPacket` + adds
seed grounding):

- **seed summary + sub-context expansions** (the basis of direction)
- the **seed-derived project contract** (required tree, behaviors, forbidden
  tech, persistence target — see 02)
- the current **contract / proposal / patch** *including file content*
- deterministic **findings** (lint results, out-of-focus files, missing-required,
  rejection reasons, validation output)
- **attempt history** + failure-class trail (#37)

Output (validated structured object):

```yaml
disposition: accept | fix | scope_down | redirect | escalate | reject_unsafe
rationale: string                      # why, referencing the seed/contract
direction_findings:                    # what (if anything) diverges from intent
  - string
actions:                               # ordered skill calls (see 01)
  - skill: string
    args: {}
new_context:                           # optional: a sub-context the LLM authors
  topic: string
  body: string
confidence: low | medium | high
```

The adjudicator **never executes**. It returns skill calls; the runtime
validates each against the allow-list + floor and executes only the permitted
ones (01).

## How it replaces today's gate

`proposal_applier.run_application_stage` today: `request_patch_plan` →
`validate_patch_plan` (binary) → apply. New flow:

```
request_patch_plan  (content kept, see 02)
  -> deterministic floor  (reject_unsafe stops here)
  -> deterministic fixable scan -> candidate fix/scope_down skills
  -> adjudicate(seed, contract, patch, findings) -> disposition + actions
  -> execute allowed skills (autofix/scope-down/revise) on the KEPT content
  -> if disposition in {accept} and floor clean -> apply
     if {fix, scope_down} -> repair then re-adjudicate (bounded)
     if {redirect} -> route through recovery (revise contract/plan/context)
     if {escalate, reject_unsafe} -> park with reason
```

## Safety invariants

- Floor is deterministic and wins; LLM cannot produce or override
  `reject_unsafe`.
- LLM proposes skills only; Python validates (allow-list + schema + floor) and
  executes.
- Bounded re-adjudication (a `fix` that doesn't clear the issue escalates, via
  the #37 attempt budget + no-progress monitor).
- LLM down/malformed → deterministic fallback; never a fake accept.
