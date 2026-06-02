# Model Strategy

## Phase 1.5 Assignments

| Worker | Ollama model |
| --- | --- |
| Architect | `cogito:14b` |
| Planner | `cogito:14b` |
| Coder | `qwen2.5-coder:14b` |
| Test Builder | `qwen2.5-coder:14b` |
| Reviewer | `gemma4:latest` or `cogito:14b` |
| Fast Helper | `deepseek-coder:latest` |
| Embeddings | `nomic-embed-text:latest` |

## Current Boundary

Phase 1.5 ticks may call the local Architect model for planning-only task
expansion. When Ollama is unavailable or returns an invalid response, the tick
must use deterministic fallback planning and exit cleanly.

The initial configured reviewer is `gemma4:latest`. A later planning phase may
define when to fall back to `cogito:14b`.
