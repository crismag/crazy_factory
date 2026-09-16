# Crazy Factory MCP surface — featured vs inventory

Living map of what an external client should call. Transport stays
stdio JSON-RPC (`crazy-admin serve-mcp`). Network MCP and auth remain
deferred (P3-04). Worker-role tools (`call_architect`, `call_coder`,
…) stay unpublished.

The **Director** is the owner conversation. Featured tools are the
commands that conversation uses. Inventory tools expose the same
engine for power users and for clients that already know the internals.
They are not a second product.

Evidence: `scripts/director.py`, `scripts/mcp_server.py` (`FEATURED_TOOLS`
listed first), `tests/test_director.py`, `tests/test_mcp_server.py`.

---

## How a client should talk

```text
list_projects            → what workbenches exist
director_brief [id]      → intended product + mission + one next command
                           (the Director names the tool; the client calls it)
start_mission            → prompt or bounded context in, autonomous
                           loop until COMPLETE / HUMAN_REQUIRED / BUDGET
continue_mission         → keep going after MORE_WORK / budget;
                           optional prompt is a follow-up delta
stop_mission             → owner halt (never auto-recommended)
get_status               → pipeline + mission snapshot without a brief
```

`director_brief` does **not** run workers. Its `next.action` is one of:

| Action | When | Featured tool to call |
| --- | --- | --- |
| `import_project` | Nothing registered, or unknown id | `import_project` then `start_mission` |
| `pick_project` | Several workbenches; no id given | `list_projects`, then brief one |
| `provide_context` | Placeholder seed (“describe what”) | `start_mission` with `prompt` / `seed` / `context` |
| `start` | Real context, no mission yet | `start_mission` |
| `continue` | `MORE_WORK`, recoverable, or `BUDGET_EXHAUSTED` | `continue_mission` |
| `done` | Mission `COMPLETE` | none — do not re-crank |
| `human` | `HUMAN_REQUIRED` | none — do not continue blindly; `get_status` to read the blocker |

`stop_mission` is featured because the owner must be able to halt. The
Director never recommends it as the next autonomous step.

When the mission is `COMPLETE` but product intelligence still lists
gaps, those gaps are **caveats** on `done`, not a reason to call
`continue_mission` (that would no-op: already-accepted workbenches
exit with zero beats).

---

## Featured tools

| Tool | Read-only | Role |
| --- | --- | --- |
| `director_brief` | yes | The thing the owner talks to |
| `list_projects` | yes | Discovery (registry + last mission outcome) |
| `start_mission` | no | Create-if-needed + prompt/seed + closed loop |
| `continue_mission` | no | Resume without re-applying the profile |
| `stop_mission` | no | Owner halt |
| `get_status` | yes | Thin pipeline + mission snapshot |

Initialize `instructions` tell clients to start here. Featured tools
are listed first in `tools/list` and carry `annotations.featured: true`.

---

## Inventory tools

Same engine, not the conversation. Use when a client already has a
reason to inspect raw product intelligence, persist an assessment, or
run a single beat.

| Tool | Notes |
| --- | --- |
| `import_project` | Scaffold or attach; `start_mission` also create-if-needed |
| `provide_context` | Extra files/archives; seed-in-one-call is featured via `start_mission` |
| `inspect_project` | Live product kernel + mission; no persist |
| `assess_project` | Persist `product_model.json` / `convergence.json` / `objectives.json` |
| `advance_project` | One `factory_advance` beat — owner should prefer `start`/`continue` |
| `get_findings` | Material gaps only |
| `get_objectives` | Director objective queue (execution still uses P2 `current_objective`) |
| `reconcile_project` | Alias of assess after external edits |

Read-only resources under `crazy://projects/...` remain. They are
inventory, not featured commands.

---

## Deliberately not MCP tools

- Worker dispatch: `call_architect` / `call_planner` / `call_coder` /
  `call_reviewer` — EXECUTE owns those roles.
- Dashboards, UI, notifications.
- Network listen + auth (P3-04).
- Dynamic team / skill registry (P5-02).
- Factory self-improvement that writes `scripts/` (P5-03).
- Cursor / Codex as named tools (P4-09 adapters, not MCP verbs).
  Claude/OpenAI are coding plugins behind `AgentExecutor`, not MCP
  tools.

---

## CLI mirrors

| MCP featured | CLI |
| --- | --- |
| `director_brief` | `crazy-admin brief [id] [--json]` |
| `list_projects` | `crazy-admin brief` with no id (catalog / pick) |
| `start_mission` | `crazy-admin run [id] --prompt TEXT` or `--seed FILE` |
| `continue_mission` | `crazy-admin run [id] [--prompt TEXT]` |
| `stop_mission` | `crazy-admin stop [id]` |
| `get_status` | `crazy-admin status [id]` |

Inspect/assess stay as `crazy-admin inspect` / `assess`.
