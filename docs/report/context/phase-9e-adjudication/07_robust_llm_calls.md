# 07 — 9E.7 Robust LLM role calls (prime · classify · iterate · never use a refusal)

The planner stored a **model refusal as the next action**:

> `{"response": "I'm sorry, I can't complete the request as it appears to be a
> task contract and validation report… feel free to ask!"}`

## Why it happened (root cause)

`request_planner_result` is the **only** role still on free-form chat:

- **No output contract** — plain `client.chat(...)`, no `response_format="json"`,
  no schema, vague instruction ("Create one concise planning-only next action").
  The coder/contract/test roles all use `response_format="json"` + "Return ONLY
  a JSON object…".
- **Document-dump context** — the user message is the Architect expansion **plus
  every `factory_tasks/` file as "Task Source"** (incl. `VALIDATION_REPORT.md`,
  `RECOVERY_DECISION.md`). An instruction-tuned model handed a wall of "here are
  a contract and a validation report" with a weak ask replies *conversationally*
  — its refusal literally names what it saw.
- **No response analysis** — the reply is stored verbatim; a refusal becomes
  "the plan." The deterministic fallback only triggers on Ollama *errors*, not
  on a *successful-but-non-actionable* reply.

## The capability: robust structured role interaction

Every LLM role call gets four things (a shared helper, reused across roles):

1. **Pre-prompt priming** — a preamble that conditions the model on *how to
   respond and what is expected* before the task: the exact JSON shape, "do not
   ask questions, do not refuse; if information is missing, choose the smallest
   safe next step." Sets the contract up front.
2. **Enforced output format** — `response_format="json"` + a required-keys
   schema, like the coder/contract roles.
3. **Response analysis (classification)** — inspect what came back and **know
   not to use a bad one**: classify as `empty | refusal | malformed | valid`.
   Refusal/empty/missing-keys → **rejected, never stored**.
4. **Iterate to harden** — on a bad response, a bounded reframe-retry loop feeds
   the model its own bad output + a correction ("That was not a valid action.
   Output ONLY the JSON with keys …"), converging to a **final/consolidated**
   response. After N tries → deterministic fallback (never a fake/garbage plan).

```text
prime → call(json) → classify → if bad: reframe with the bad output → retry (bounded)
                              → if good: parse + validate keys → use
      → exhausted: deterministic fallback (never store a refusal)
```

5. **Curated context** — feed the role only what it needs (seed/goal, architect
   expansion, current focus, current blocker/diagnosis) — **not** the raw
   `factory_tasks/` dump. The irrelevant validation/recovery reports are what
   tipped the model into "this is just a pile of documents."

## Shared helper

`scripts/llm_interaction.py`:

```python
REFUSAL_MARKERS = ("i'm sorry", "i cannot", "i can't", "unable to",
                   "cannot complete", "feel free to ask", "as an ai", ...)

def classify_response(text) -> str   # "empty" | "refusal" | "json" | "prose"

def structured_call(*, client, model, system, user, priming,
                    required_keys, retries=2) -> tuple[dict | None, str]:
    """Prime + json call + classify + reframe-retry. Returns (data|None, note).
    None => no usable structured response; caller uses its deterministic fallback."""
```

## Subtasks (9E.7)

| ST | What | Touches | Risk |
|---|---|---|---|
| **L1** | `llm_interaction.py` — `classify_response` + `structured_call` (prime · json · classify · bounded reframe-retry) | new module | low |
| **L2** | **Planner** uses `structured_call` (schema `{next_action, rationale, target_file, kind}`) + priming; render the action into `RoleResult.content`; **fall back on non-actionable** (never store a refusal) | `planning_roles.py` | med |
| **L3** | **Architect** uses the same helper (the other laggard) | `planning_roles.py` | med |
| **L4** | **Curated planner/architect context** — focus + architect expansion + blocker, not the full `factory_tasks` dump | `factory_advance.py`, `planning_roles.py` | med |
| **L5** | **Generalize** — route coder/contract/test/adjudicator through the same prime+classify+iterate wrapper so refusal handling is uniform | those modules | med |
| **L6** | Tests + re-run — classify cases; planner falls back on a mocked refusal (refusal NOT stored); planner hardens (refusal→valid on retry); valid JSON accepted | tests | — |

## Execution slices

- **Slice 1 = L1 + L2 (surgical fix):** the helper + planner wiring. This alone
  prevents the exact failure — a refusal is classified, retried, and if still
  bad, replaced by the deterministic fallback, never stored as the plan.
- **Slice 2 = L3 + L4:** architect on the helper + context curation.
- **Slice 3 = L5 + L6:** uniform rollout + tests.

## Invariants (tested)

- A refusal/empty/malformed reply is **never used** — it's rejected and either
  hardened by retry or replaced by the deterministic fallback.
- Bounded retries (no infinite reframe loop); LLM-down → fallback, never fake.
- Output is schema-validated before use.
- Pure-ish + deterministic where possible: `classify_response` unit-tested;
  `structured_call` tested with a mocked client (refusal-then-valid, all-refusal,
  immediate-valid).

## Definition of done

The planner (then architect, then all roles) **primes** the model, **enforces**
a JSON action, **analyzes** the reply, **iterates** to harden it, and **never
stores a refusal/garbage** — falling back deterministically when the model won't
produce a usable action. The exact `NEXT_ACTION` refusal cannot recur.
