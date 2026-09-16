# P4a completion baseline

Recorded 2026-09-16. P4a engine acceptance is met: a bounded seed
becomes a runnable, validated application through the existing
P0–P3 loop plus a minimal AgentExecutor.

Later providers (Cursor / Codex / Claude) and specialized roles
stay deferred. P5 / UI / extra MCP / multi-agent org are not next.

## What P4a proved

```text
objective + seed + failures
  → AgentExecutor
  → confined workbench files
  → existing validation / runtime observation
  → existing evaluation
```

| Piece | Evidence |
| --- | --- |
| Provider-neutral contract | `ExecutorRequest` / `ExecutorResult` / `AgentExecutor` |
| Optional LLM backend | `LlmFileExecutor` (skips when Ollama is down) |
| Capable proof backend | `StdlibWebExecutor` copies `examples/actuators/stdlib_task_board/` |
| Safety | no engine `scripts/` / `factory/` writes |
| Benchmark | `examples/seeds/task_board_web.md` → COMPLETE + runtime |

`tests/test_agent_executor.py::TaskBoardBenchmarkTests` is the
acceptance record.

## What remains after this baseline

The happy path is closed for the first seed. Ordinary owner
invocation (`crazy-admin run --seed`, MCP `start_mission`) and a
failed workbench recovering on the next beat must not require a
human. Those are P4b automation proofs, not new architecture.
