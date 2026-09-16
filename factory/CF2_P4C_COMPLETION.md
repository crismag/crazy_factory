# P4c completion baseline

Recorded 2026-09-16. Productization target is Lovable-like:
bounded prompt/seed → Crazy Factory keeps working → runnable
validated application. Coding intelligence is a **plugin**, not a
local-Ollama-first path.

Claude (Anthropic) and OpenAI are the starting coding models behind
`AgentExecutor`. Other intelligence plugins can join the same
contract later. The factory still owns mission, observation,
evaluation, confinement, and continuation.

## What P4c proved

```text
objective + seed + failures
  → CloudCodingExecutor (Claude or OpenAI)
  → confined workbench files
  → existing validation / runtime observation
  → existing evaluation
```

No API key → skip immediately (no network) → stdlib task-board
actuator still closes the known proof seed.

| Piece | Evidence |
| --- | --- |
| Cloud clients | `scripts/coding_llm.py` (`AnthropicClient`, `OpenAIClient`) |
| Skip without keys | `no_coding_api_key`; `urlopen` not called |
| Prefer Claude | both keys → Anthropic |
| Default chain | `CloudCodingExecutor` then `StdlibWebExecutor` |
| Ollama | opt-in only (`CRAZY_FACTORY_EXECUTOR=ollama`) |
| Path filter | blocked tops (`scripts/`, `factory/`, …) dropped |
| Tests | `tests/test_coding_llm.py`, cloud cases in `test_agent_executor.py` |

CI never calls a live vendor. Keys:
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` (or `CRAZY_FACTORY_*` aliases).
Force a plugin with `CRAZY_FACTORY_EXECUTOR=anthropic|openai` or
`CRAZY_FACTORY_CODING_PROVIDER`.

## What remains after this baseline

- Cursor / Codex IDE adapters (P4-09)
- Specialized roles (P4-04)
- Live Ollama as a coding model (P1-09) — not the starting path
- In-process Architect/Planner stay on the local Ollama client
- P5-02/P5-03, UI, network MCP
