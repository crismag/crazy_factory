# Crazy Factory — default web stack

Lovable-style generation needs **one** opinionated, previewable stack,
not every framework. This file records the first default and the
recorded successor.

## First default: `stdlib-web`

**Why this first.** The runtime observer, validation allowlist, and
path confinement already understand `python3 -m …` and a localhost
HTTP probe. A Python 3 standard-library HTTP app (HTML/CSS/JS, JSON
file persistence, port 8765) can be started, probed, and judged
without expanding the safety floor.

| Field | Value |
| --- | --- |
| id | `stdlib-web` |
| start | `python3 -m src.app` |
| listen | `8765` |
| executable | **yes** |
| constraints | stdlib only; no npm; persist under `data/` |

The prompt compiler writes this stack into `architecture.json` so
EXECUTE, the observer, and the evaluator share one start command.
Without a coding-plugin key, `StdlibWebExecutor` writes a generic
stdlib HTTP preview (`src/app.py`) so the observer can probe it.
Each probe persists `factory_tasks/preview.json` with the localhost
URL. The process is still killed after the probe — this is evidence,
not a long-running dev server.

A follow-up owner prompt on a specified product is a conversational
delta (`factory_tasks/deltas.jsonl`, `docs/deltas.md`). It does not
recompile Goal or architecture. The stdlib preview reads
`data/change_requests.json` so the HTTP page can show the requested
change without a coding-plugin key.

Evidence: `scripts/web_stack.py`, `scripts/prompt_compiler.py`,
`scripts/stdlib_preview.py`, `scripts/conversation_delta.py`.

## Recorded successor: `vite-react`

A Vite + React SPA is the Lovable-like preview target. It is **not
executable** in this factory yet: `npm` / `node` are still forbidden
by the validation and runtime floors (P1-07). `resolve_stack` falls
back to `stdlib-web` if asked for a non-executable stack so a prompt
cannot emit `npm run dev`.

Do not allowlist npm from this document. That is a later slice with
the same confine/kill/probe shape `python3 -m` has today.

## What this is not

- Not a multi-framework picker.
- Not a license to invent stacks per prompt.
- Not KAE-Memory, LangChain, or a new MCP server.
- Not a rewrite of P1–P3.

## Next stack work (not this slice)

1. Confine `npm install` / `npm run dev` the way `python3 -m` is confined.
2. Probe the Vite port.
3. Flip `vite-react.executable` to true and let the compiler emit it.
