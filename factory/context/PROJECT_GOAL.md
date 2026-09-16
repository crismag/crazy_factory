# Project Goal

## Primary Goal

Crazy Factory must take a bounded application context and keep
working until there is a runnable, validated application, or a
clearly justified blocker that genuinely requires human intervention.

Product intelligence, MCP, and specialized agents exist to support
that capability. They are not a substitute for it.

## Required Qualities

- local-first operation
- closed execution loop (work → observe → recover → continue)
- bounded autonomy inside an isolated workbench
- non-negotiable safety floor (no push/merge/delete/engine writes)
- inspectable mission traces
- evidence-based acceptance (not "files were generated")
- MCP as a wrapper around the working engine, not the engine itself

## Current Goal

P0: closed autonomous loop via `crazy-admin run`. See
[CF2_ARCHITECTURE.md](../CF2_ARCHITECTURE.md) and
[P0_AUTONOMOUS_LOOP.md](../../docs/report/context/crazy-factory-2.0/P0_AUTONOMOUS_LOOP.md).
