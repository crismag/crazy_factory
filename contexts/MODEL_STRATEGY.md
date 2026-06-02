# Model Strategy

## Phase 1 Assignments

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

The model assignments are documented and configurable, but Phase 1 ticks do
not call Ollama. The bootstrap must remain useful when Ollama is not running.

The initial configured reviewer is `gemma4:latest`. A later planning phase may
define when to fall back to `cogito:14b`.
