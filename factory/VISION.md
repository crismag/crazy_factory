# Vision

Crazy Factory should become a calm, observable background collaborator for local software projects. It should periodically inspect state, select a modest next action, make or propose progress within its authority, validate the result, and preserve memory for the next run.

## Desired Experience

The owner should be able to:

- understand what the factory is doing and why
- observe incremental progress without supervising every step
- intervene before consequential or external actions
- trace decisions and failures across sessions
- pause, redirect, or narrow the factory at any time
- operate primarily with local models and local project data

## Immediate Direction

The owner should be able to hand Crazy Factory a bounded application
context and walk away. It should keep working until there is a
runnable, validated application or a justified human blocker.

MCP, specialized agents, and product-level intelligence support that
loop. They come after the loop exists. See
[CF2_ARCHITECTURE.md](CF2_ARCHITECTURE.md) and [ROADMAP.md](ROADMAP.md).

Ollama-backed local models, scheduled sessions, and multi-project
operation already have runtime support. `crazy-admin run` is the P0
continuation controller. Codex/Claude as implementation providers
remain P4.

