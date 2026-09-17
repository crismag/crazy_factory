# Crazy Factory — post-L0 capability assessment

Generated: 2026-09-16  
Branch: `cursor/l0-conversational-deltas-3f2d` (L0-01…L0-05 landed)  
Supersedes [ASSESSMENT.md](ASSESSMENT.md) as the **current** product
reading. The 2026-09-16 Slice A audit remains the historical
repository map; it is not the live capability ceiling.

Evidence pack:
[prompt_build_2026-09-16/](prompt_build_2026-09-16/).

---

## 1. How far a prompt actually goes

This environment had **no** `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
and **no** Ollama. That is the no-plugin path owners hit in CI and
on a fresh machine.

| Step | Command / event | Result |
| --- | --- | --- |
| 1 | `--prompt "build a habit tracker"` | Compiler wrote a specified `docs/seed.md` + `architecture.json` (`stdlib-web`, `python3 -m src.app`, port 8765). Fallback compiler (no model). |
| 2 | `run` beat 1 | Inner Architect/Planner/contract **rejected** (Ollama connection refused). `StdlibWebExecutor` still wrote 9 preview files. |
| 3 | Validation | compileall, pytest, ruff, `pip install -r` all **passed**. |
| 4 | Runtime | HTTP **200** at `http://127.0.0.1:8765/`. Process killed after the probe. |
| 5 | Evaluator | **`COMPLETE` in 1 beat.** Reason: `acceptance evidence is complete (runtime running)`. |
| 6 | Product on the page | Generic item CRUD titled “habit tracker”. Add / edit / done / delete. **No habits, dates, or streaks.** |
| 7 | Follow-up `--prompt "add a streak counter and a weekly view"` | Goal and architecture **unchanged**. Delta written to `deltas.jsonl` + `docs/deltas.md`. Banner appears on the HTML page. |
| 8 | Second `run` | **`COMPLETE`, 0 beats.** Already-accepted workbenches do not execute. The streak/weekly request was recorded, not built. |

Trace (beat 0 → beat 1):

```text
beat 0: MORE_WORK  src=0 tests=0  runtime=missing  OBJ-001 code_birth
beat 1: COMPLETE   src=2 tests=2  runtime=running  OBJ-RUNTIME repair_runtime
        blocker=planning_contract_rejected
```

Inspect after the run still reported `demo_ready: true` and
“No material gap currently blocks a demo.”

**Ceiling without a coding plugin:** a reachable generic stdlib
CRUD preview, labeled with words from the prompt, that the factory
believes is done. **Not** a habit tracker. **Not** conversational
editing of the running product.

**Not measured here:** Claude/OpenAI applying a purpose-built
assignment. Keys were absent. That path is wired (`CloudCodingExecutor`
first in the default chain) and unproven on this host.

---

## 2. What is now true (L0 + P0–P5)

The September 16 Slice A audit (“no MCP, no Director, no closed
loop, Ollama-only”) is obsolete. The factory **can**:

- Keep working without the owner cranking `advance` (`crazy-admin run`).
- Compile a one-liner into Goal/Success + a default executable stack.
- Stand up a localhost HTTP preview and persist `preview.json`.
- Treat a follow-up prompt as a delta instead of recompiling the product.
- Wrap start/continue/stop in MCP; Director names the next featured tool.
- Prefer Claude, then OpenAI, as coding plugins when a key exists.
- Compile a purpose-built execution assignment from evidence.
- Observe runtime every evaluation beat.
- Persist attempts / control memory (model control is off without a key).

Safety floor still holds: no auto-push/merge, path confinement,
deletes off, factory must not write engine source.

---

## 3. Capability scorecard (Lovable-like “any prompt → working app”)

| Capability | Status | Evidence / enablement |
| --- | --- | --- |
| Raw sentence → specified intent | **YES** | Fallback compiler; `prompt_compile.json` source=`fallback` |
| Default executable web stack | **YES** | `stdlib-web` only. `vite-react` recorded, not executable |
| Reachable preview without a vendor key | **YES** | HTTP 200, `preview.json` |
| Preview is the *requested* product | **NO** | Generic CRUD; success criteria are CRUD+HTTP, not habit semantics |
| Closed loop until COMPLETE | **YES** (process) | 1 beat to COMPLETE |
| COMPLETE means the software is good | **NO** | `judgment.json` admits executor ok ≠ acceptance; evaluator still COMPLETE’d a generic preview |
| Follow-up prompt does not clobber Goal | **YES** | `seed_unchanged`, `arch_unchanged` |
| Follow-up prompt changes the running app | **NO** | Banner only; 0-beat COMPLETE; `StdlibWebExecutor` skips overwrite on `implement` |
| Coding plugin writes product-specific code | **UNMEASURED** | Requires `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` |
| Inner Architect/Planner without Ollama | **FALLBACK** | Contract rejected; executor bypassed the inner coder |
| MCP `start_mission.prompt` | **YES** (unit) | Not re-run live in this probe |
| MCP drop-in “any prompt” product | **NO** (L0-06) | stdio only; client must already know featured tools |
| Long-lived preview (Vite-style) | **NO** | Probe then kill |
| npm / React / browser journeys | **NO** | Safety floor forbids npm; P1-07 / L0-07 / P1-08 |
| Durable AI memory (KAE-Memory, vectors) | **DEFERRED** | File artifacts are the memory; no demonstrated need to add infra |
| Cursor / Codex IDE adapters | **DEFERRED** | P4-09 |

---

## 4. Missing features (product, not architecture)

These are capability holes the live run actually hit.

1. **Product-intent acceptance.** Success criteria from the fallback
   compiler are generic (“CRUD works”, “HTTP answers”). Acceptance
   + inspect `demo_ready` treat that as a habit tracker. The factory
   cannot tell “labeled CRUD” from “the software the owner asked for.”
2. **Delta execution after COMPLETE.** L0-05 persists the follow-up.
   The mission runner treats COMPLETE as terminal, so
   `continue_mission` / second `run` is a 0-beat no-op. The banner
   can look like the change landed.
3. **No-key implement path.** After `src/app.py` exists, the stdlib
   actuator refuses to overwrite. Without a coding plugin, a delta
   cannot become behavior.
4. **Prompt compiler without a model is stack-shaped, not
   domain-shaped.** Title = “habit tracker”; screens = home/list/detail;
   no streak, schedule, or check-in in the seed.
5. **Inner kernel still assumes Ollama.** Contract review failed
   loudly; the P4 executor saved the beat. Dual writers remain a
   coherence risk when a key *or* Ollama is present.
6. **Preview is evidence, not a product session.** No long-running
   URL for the owner to click while chatting.
7. **Drop-in MCP packaging (L0-06).** Featured tools exist; there is
   no “paste this server into Claude/Cursor and type a prompt”
   productization.
8. **`vite-react` (L0-07).** Blocked on npm confine + probe (P1-07).

---

## 5. Required enablements (to go further than this run)

Ordered by what would have changed **this** probe’s outcome.
Do not start KAE-Memory, LangChain, n8n, Cline, UI, or network MCP
to fix these.

| Enablement | Why | Kind |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | Only way the default chain writes product-specific files instead of the generic preview | **Operator** (key). Unmeasured until set. |
| Re-open / continue on new owner delta | Second prompt must produce beats with stance `implement`, even if the last outcome was COMPLETE | **Factory** (L0-08) |
| Intent vs preview in acceptance | COMPLETE must fail when the running UI does not cover compiled success *meaning* (or an explicit “generic preview, not the product” caveat) | **Factory** (L0-09) |
| Domain-shaped compile when a key is present | Screens/success should mention streaks, check-ins, etc. Fallback may stay generic | **Already wired** if `control_model_enabled()`; needs a key |
| Optional: allow stdlib preview to apply *small* HTML/data deltas without a plugin | No-key follow-ups could do more than a banner | **Factory**, only if L0-08 still has no key |
| `npm` confine + HTTP probe | Required before `vite-react.executable = true` | P1-07 / L0-07 |
| Network MCP + auth | Only if a remote client must attach | P3-04, later |

Operator keys are not a substitute for L0-08/L0-09: a plugin that
never runs because the mission is already COMPLETE still cannot
apply the follow-up.

---

## 6. Pipeline (do not skip ahead)

**Done:** P0 closed loop, P1 observer, P2 remaining-gap EXECUTE,
P3 stdio MCP, P4a–P4f executor + assignment + control, P5a Director,
P5b module loop, L0-01…L0-05 compiler / stack / preview / deltas.

**Empirical next (from this run), then recorded L0:**

1. **L0-08** — New owner delta re-opens work (COMPLETE is not a
   tombstone for conversation).
2. **L0-09** — Acceptance/inspect must distinguish generic preview
   from the intended product (or refuse COMPLETE on preview-only).
3. **Measure with a live Claude/OpenAI key** — same habit-tracker
   prompt; compare files and HTTP body to this no-key baseline.
4. **L0-06** — Drop-in MCP packaging once 08/09 (or a keyed run)
   show a prompt can become the *asked-for* app.
5. **L0-07 / P1-07** — `vite-react` after npm is confined.

Still deferred on purpose: P5-02 dynamic teams, P5-03 factory
self-writes `scripts/`, P4-09 Cursor/Codex, P1-08 browser journeys,
KAE-Memory, LangChain.

---

## 7. Honest product sentence

Crazy Factory can take a one-line prompt, compile it onto
`stdlib-web`, and in one autonomous beat serve a passing, reachable
generic CRUD page titled after that prompt. It will then declare the
mission complete. A second sentence is remembered as a delta and
shown as a banner; it is not built. Turning that into coherent
working software still requires a coding-plugin key **and** the
factory to keep working after the preview looks “done.”
