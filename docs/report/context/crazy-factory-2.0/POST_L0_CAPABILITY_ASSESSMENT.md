# Crazy Factory — post-L0 capability assessment

Generated: 2026-09-16  
Branch: `cursor/l0-product-acceptance-3f2d` (L0-01…L0-09 landed)

Supersedes the L0-05 reading on the same date. The 2026-09-16
Slice A audit remains the historical repository map.

Evidence packs:

- Pre-fix (false COMPLETE): [prompt_build_2026-09-16/](prompt_build_2026-09-16/)
- After L0-08/L0-09: [prompt_accept_2026-09-16/](prompt_accept_2026-09-16/)

---

## 1. How far a prompt actually goes (re-run)

This environment still had **no** `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` and **no** Ollama.

| Step | Command / event | Result |
| --- | --- | --- |
| 1 | `--prompt "build a habit tracker"` | Compiler wrote specified seed + architecture **and** `product_intent.json` claims: define habits, record completion, dated completion, persist. |
| 2 | `run` beat 1 | Inner contract rejected (Ollama refused). `StdlibWebExecutor` wrote 9 generic CRUD files. Validation passed. HTTP 200. |
| 3 | Evaluator | **`RUNNABLE_PREVIEW` in 1 beat.** Not COMPLETE. Reason: mechanical and runtime passed; product claims unsatisfied; no coding plugin. Exit code 1. |
| 4 | Product on the page | Generic item CRUD titled “habit tracker”. **No** `add_habit`, dates, or `data/habits.json`. |
| 5 | Inspect | `Demo ready: false`. `demo_readiness` lists the unsatisfied claims. |
| 6 | Follow-up `--prompt "add a streak counter and a weekly view"` | Goal **unchanged**. Architecture **unchanged**. Delta persisted as `PENDING` then `CLAIMED`. Intent revision 1 → 2. Prior acceptance stale. |
| 7 | Second `run` | **1 beat**, objective `OBJ-DELTA-delta-1` / `implement_delta`. Stdlib actuator skipped overwrite. Banner shows the follow-up. Delta **not VERIFIED**. Outcome **`RUNNABLE_PREVIEW`**, not COMPLETE. |

First-prompt trace:

```text
beat 0: MORE_WORK          src=0 tests=0  runtime=missing
beat 1: RUNNABLE_PREVIEW   src=2 tests=2  runtime=running
        product claims unsatisfied; no coding plugin
```

Follow-up trace:

```text
beat 0: MORE_WORK          owner delta delta-1 is unsatisfied product intent
        objective=OBJ-DELTA-delta-1:implement_delta
beat 1: RUNNABLE_PREVIEW   claims still unsatisfied; delta CLAIMED not VERIFIED
```

**Ceiling without a coding plugin:** a reachable generic stdlib
CRUD preview that the factory **does not** call done. Follow-up
intent reopens work. Banner text cannot verify a delta.

**Not measured here:** Claude/OpenAI implementing the compiled
claims. Keys were absent. That is the next empirical step — not a
substitute for these acceptance semantics.

---

## 2. What L0-08 / L0-09 changed

- Natural-language intent compiles into explicit product claims
  with implementation probes (identifiers, data files, JSON fields).
  Title/banner string matching is not an acceptance rule.
- Acceptance is layered: mechanical (files, validation), runtime
  (start/HTTP), product (claims + VERIFIED deltas for the current
  intent revision).
- COMPLETE requires all applicable layers. Generic CRUD may be
  `RUNNABLE_PREVIEW`.
- Owner deltas have a lifecycle (`PENDING` → `CLAIMED` →
  `VERIFIED`). Only VERIFIED deltas contribute to COMPLETE. A new
  actionable delta invalidates prior acceptance and forces at least
  one execute beat.
- Inner `planning_contract_rejected` (Ollama down) no longer
  outranks a truthful preview stop or a pending owner delta.

Unchanged and still valuable: prompt → seed/spec, stack selection,
autonomous mission loop, implementation actuator, validation,
runtime observation, reachable preview, additive deltas, original
Goal/architecture preserved.

---

## 3. Capability scorecard (Lovable-like “any prompt → working app”)

| Capability | Status | Evidence / enablement |
| --- | --- | --- |
| Raw sentence → specified intent | **YES** | Fallback compiler + `product_intent.json` claims |
| Default executable web stack | **YES** | `stdlib-web` only. `vite-react` recorded, not executable |
| Reachable preview without a vendor key | **YES** | HTTP 200, `preview.json` |
| Preview is the *requested* product | **NO** | Generic CRUD; claims unsatisfied |
| Factory knows preview ≠ requested product | **YES** | `RUNNABLE_PREVIEW`; inspect `demo_ready: false` |
| Closed loop until a truthful stop | **YES** | 1 beat to RUNNABLE_PREVIEW (not false COMPLETE) |
| COMPLETE means the software is good | **GATED** | COMPLETE now requires product claims; unmeasured with a plugin |
| Follow-up prompt does not clobber Goal | **YES** | seed + architecture unchanged |
| Follow-up reopens work | **YES** | 1 beat, `implement_delta`, acceptance stale |
| Follow-up becomes product behavior | **NO** (no key) | Banner + CLAIMED; not VERIFIED |
| Coding plugin writes product-specific code | **UNMEASURED** | Requires `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` |
| Inner Architect/Planner without Ollama | **FALLBACK** | Contract rejected; executor still wrote the preview |
| MCP `start_mission.prompt` | **YES** (unit) | Not re-run live in this probe |
| MCP drop-in “any prompt” product | **NO** (L0-06) | stdio only |
| Long-lived preview (Vite-style) | **NO** | Probe then kill |
| npm / React / browser journeys | **NO** | Safety floor forbids npm |
| Durable AI memory (KAE-Memory, vectors) | **DEFERRED** | File artifacts are the memory |

---

## 4. Missing features (product, not architecture)

1. **Product-specific implementation without a coding plugin.**
   Stdlib preview remains generic CRUD. That is now reported
   honestly as `RUNNABLE_PREVIEW`. Closing claims still needs a
   plugin (or a later, bounded stdlib domain actuator — not this
   slice).
2. **Live Claude/OpenAI characterization.** Keys were absent. The
   factory can now ask the plugin for the right claims and reopen
   on deltas; whether the plugin actually writes habit/streak
   behavior is the next measurement.
3. **Inner kernel still assumes Ollama.** Contract review failed;
   the P4 executor saved the beat. Dual writers remain a coherence
   risk when a key *or* Ollama is present.
4. **Prompt compiler without a model is claim-shaped but
   implementation-generic.** Claims are explicit; files are still
   item CRUD.
5. **Preview is evidence, not a product session.** No long-running
   URL for the owner to click while chatting.
6. **Drop-in MCP packaging (L0-06).** Featured tools exist; there is
   no “paste this server into Claude/Cursor and type a prompt”
   productization.
7. **`vite-react` (L0-07).** Blocked on npm confine + probe (P1-07).

---

## 5. Required enablements (to go further than this run)

Ordered by what would change the next probe’s outcome.
Do not start KAE-Memory, LangChain, n8n, Cline, UI, or network MCP
to fix these. Do not infer that a stronger coding model alone
replaces acceptance semantics — those are now in the engine.

| Enablement | Why | Kind |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | Default chain can write product-specific files against compiled claims + deltas | **Operator** (key). Unmeasured until set. |
| Observe whether the plugin satisfies probes | `add_habit` / `complete_habit` / `current_streak` / `weekly_view` vs banner text | **Empirical** next run |
| `npm` confine + HTTP probe | Required before `vite-react.executable = true` | P1-07 / L0-07 |
| Network MCP + auth | Only if a remote client must attach | P3-04, later |

---

## 6. Pipeline (do not skip ahead)

**Done:** P0–P5b as before, plus L0-01…L0-09 (compiler, stack,
preview, deltas, delta reopen, product-intent acceptance).

**Empirical next:**

1. **Measure with a live Claude/OpenAI key** — same two prompts;
   watch reopen → `implement_delta` → plugin with product context
   → validation/runtime → claim evaluation → COMPLETE only if
   revision N+1 is evidenced.
2. **L0-06** — Drop-in MCP packaging once a keyed run shows a
   prompt can become the asked-for app.
3. **L0-07 / P1-07** — `vite-react` after npm is confined.

Still deferred on purpose: P5-02 dynamic teams, P5-03 factory
self-writes `scripts/`, P4-09 Cursor/Codex, P1-08 browser journeys,
KAE-Memory, LangChain.

---

## 7. Honest product sentence

Crazy Factory can take a one-line prompt, compile it into Goal,
architecture, **and explicit product claims**, and in one
autonomous beat serve a passing, reachable generic CRUD preview.
Without a coding plugin it now **stops at `RUNNABLE_PREVIEW`**
instead of declaring the requested product complete. A second
sentence is remembered as a delta, invalidates that acceptance,
reopens the mission, and stays unverified until implementation
probes hit source — not until a banner quotes the request.
Turning the preview into the asked-for habit tracker still
requires a coding-plugin key. The factory finally knows the
difference between running some software and building what the
owner asked for.
