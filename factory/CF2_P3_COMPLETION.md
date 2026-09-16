# P3 completion baseline

Recorded 2026-09-16. P3 engine acceptance is met. Network MCP/auth
(`CF2-P3-04`) stays deferred on purpose.

## What P3 proved

External invocation wraps the **working** P0–P2 engine. It does not
re-implement the incomplete workflow remotely.

| Call | Engine |
| --- | --- |
| `start_mission` | create-if-needed + seed/context ingest + `run_mission` |
| `continue_mission` | `run_mission` without re-applying the profile |
| `stop_mission` | owner stop flag |
| `get_status` / `inspect_project` | pipeline + **mission outcome, artifact, trace** |

Transport remains stdio JSON-RPC. Evidence:
`scripts/mcp_server.py`, `tests/test_mcp_server.py`,
`load_mission_snapshot` in `scripts/mission_runner.py`.

## What P0–P3 now provide together

```text
persistent mission
  → continuation
  → runtime observation
  → remaining-gap objective selection
  → external MCP invocation
```

The missing actuator is implementation: objective → workbench files.
That is P4a, not further MCP/P5/UI work.

## Explicitly not started from this baseline

- Network MCP / auth
- Broader MCP surface (dashboards, extra tools)
- P5 product intelligence / dynamic teams
- Multi-agent role organization
