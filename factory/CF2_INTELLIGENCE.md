# Crazy Factory — Intelligence-first direction

North star for P4+ work. Companion to
[CF2_ARCHITECTURE.md](CF2_ARCHITECTURE.md). This document describes
capabilities that exist now and the near-term boundary — not a
wishlist of infrastructure.

## North star

Crazy Factory is not a clone of Lovable or any other app builder.
It is a software-creation system that takes incomplete human intent
and turns it into coherent, demonstrable working software through
reasoning, investigation, planning, execution, observation,
criticism, verification, and iterative improvement.

Governing principle:

> **Capability first. Architecture second. Technology third.**

Do not acquire infrastructure and then invent reasons to use it.
Claude/OpenAI are the factory's intelligence plugins: they write
code **and** they supervise continuation, objective, stance, quality,
and recovery. MCP is machinery. Deterministic rails remain vetoes
(stop flag, budget, unsafe start, COMPLETE without evidence). The
factory persists attempts and working memory so the model can keep
going across beats.

## Capability-first adoption

An external technology is allowed only when a concrete capability
requires it and it is demonstrably preferable to what already
exists. Deferred until a demonstrated need:

- KAE-Memory
- LangChain / LangGraph
- n8n
- Cline
- vector databases as “AI memory”
- message queues
- multi-agent frameworks

## Provider independence

```text
Crazy Factory control intelligence (attempts.jsonl + control_memory)
     | monitor packet: runtime, validation, hashes, prior attempts
     v
Claude / OpenAI
     | outcome, kind, stance, quality_ok, recovery, memory_notes
     v
rails (stop / budget / unsafe / evidence) then EXECUTE
```

The factory compiles evidence. The model decides the beat. Rails
can only veto, not plan. Crazy Factory is not synonymous with Claude.

## Context engineering

More tokens are not better context. Context is relevant, structured,
attributable, compact, and sufficient. `execution_assignment.py`
assembles it from artifacts the factory already writes (seed,
architecture, workbench inventory, DiagnosisPacket, validation
checks, runtime, prior executor writes). It does not dump the
entire repo into the prompt.

## Evidence-based observation

Process exit status is not success. Evidence today:

- `validation_result.json` (compile / pytest / lint checks)
- `runtime_result.json` (confined start probe)
- workbench inventory and architecture
- `executor_result.json` (what the plugin wrote, plus stance)
- `judgment.json` (outcome vs acceptance vs validation vs runtime)
- `attempts.jsonl` (append-only beat history + file hashes)
- `control_memory.json` (working notes the model updates)
- `control_decision.json` (latest outcome / kind / stance)

Browser/visual journeys remain deferred.

`ExecutorResult.ok` is still not acceptance. The control model can
block COMPLETE on quality; it cannot declare COMPLETE without
evidence.

## Intelligence loop mapping (current)

| Function | Who decides | Model? |
| --- | --- | --- |
| Continue / stop / budget / stop-flag | `reason_control` + rails | **Yes** (rails veto stop/budget) |
| Next objective | control overlay on `next_execute_objective` | **Yes** |
| Assignment + stance | control stance, else heuristic | **Yes** |
| Acceptance | model `quality_ok` + evidence gates | **Yes** (cannot force COMPLETE) |
| Runtime / validation | observers collect; model interprets | **Yes** (probes stay confined) |
| Product inspect / Director next command | Director reads `control_decision` | **Yes** |
| Safety / stall / recovery routing | `recovery` field + floor | **Yes** (floor never overridden) |
| Write application files | `CloudCodingExecutor` | **Yes** — Claude preferred |
| Inner Architect / Planner | `_chat_backend` cloud then Ollama | **Yes** (Ollama if no key) |
| Prompt → seed + architecture | `prompt_compiler.compile_prompt` | **Yes** (fallback if no key) |
| Follow-up prompt on specified product | `conversation_delta.append_delta` | No extra model call |
| Task-board proof with no keys | `StdlibWebExecutor` | Fixture fallback only |

## Near-term boundary (not this slice)

- KAE-Memory / durable memory (discover need first)
- specialized tool plugins (browser, security, a11y)
- Cursor/Codex IDE adapters
- network MCP
- `vite-react` as an executable stack (npm still forbidden)

Default stack and compiler: [CF2_WEB_STACK.md](CF2_WEB_STACK.md).
