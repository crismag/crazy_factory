# Crazy Factory Message Quality Standard

Messages are communication between the factory and humans, not logs. Every
message should help someone (1) understand what happened, (2) why, (3) the
impact, (4) what to do next, and (5) debug quickly. A message that doesn't help
a human make a decision is noise.

A useful message answers: **WHAT happened · WHY · WHERE · WHAT is affected ·
WHAT to do next.**

> Tired-engineer-at-2AM test: would they understand it, and know how to debug
> from this message alone? If not, improve it.

## API mapping (`scripts/factory_messaging.py`)

Ordinary lines — single tagged lines, verbosity-gated:

| Helper | Tag | Use |
|---|---|---|
| `iprint` | `[INFO]` | progress/state (Action · Target · Result) |
| `wprint` | `[WARN]` (stderr) | unexpected but continuable |
| `eprint` | `[ERROR]` (stderr) | operation failed |
| `dprint` | `[DEBUG]` | operation · inputs · outputs · decision |
| `cprint` | `[CMD]` | command / path / execution detail |
| `nprint` | `[NOTE]` | notice / guidance / narrative |
| `sprint` | `[OK]` | success confirmation |

Structured human data — `key_value_print(mapping, title=)` (indents pairs under
the title), `table_print(rows, headers=)`, `json_print(data, title=)`,
`section_print(title)`.

Emphasized attention checkpoints — `post_message(type, title, **fields)`. Pass
actionable fields (`reason=`, `impact=`, `evidence=`, `recommendation=`,
`action=`, or any custom key → Title-Case label); they render in the order
given as indented `Label:` blocks. Frame char by severity: `=` errors/blocks,
`-` warnings, `+` success/approval. **Reserve banners for genuine attention
events** — not ordinary progress.

## Required fields by message kind

- **Info** — Action, Target, Result.
- **Warning** — Reason, Impact, Recommendation.
- **Error** — Operation, Reason, Location, Impact, Resolution.
- **Fatal** — Failure, Reason, Impact, Required Action.
- **Validation failure** — Check, Failure, Evidence, Recommendation.
- **Contract rejection** — Proposal, Rule Violated, Impact, Recommended Fix.
- **Debug** — Operation, Inputs, Outputs, Decision.

## Examples

Fatal (banner, `=`):

```text
================================================================================
[FATAL] Factory startup aborted
================================================================================

Reason:
    No active project configured

Impact:
    Factory cannot continue

Required Action:
    Select an active project

================================================================================
```

```python
post_message("FATAL", "Factory startup aborted",
             reason="No active project configured",
             impact="Factory cannot continue",
             required_action="Select an active project")
```

Validation failure (banner, `=`):

```python
post_message("VALIDATION_FAILED", "Validation failed",
             check="Python Syntax Validation", file="storage.py", line=43,
             evidence="// This is a valid comment",
             recommendation="Replace JS-style comment with Python #")
```

Info (structured line block):

```python
key_value_print({"Project": "tic-tac-toe", "Context": "project_context.md"},
                title="Loading active project:")
```

Exception handling — never `eprint("Failed")`; include the cause and next step:

```python
except Exception as exc:
    post_message("ERROR", "Unable to load project configuration",
                 reason=str(exc), context=file_path,
                 action="Verify the configuration file exists")
```

## Message smells (expand these)

Bare words that are incomplete and must carry context:
`Failed · Error · Exception · Invalid · Done · Complete · Rejected · Accepted ·
Running · Loading · Checking`.

## Author checklist

Before adding a message: does it explain **what / why / impact / next action**,
and could a tired engineer debug from it alone? If not, improve it. See
[reports/factory_messaging_migration_plan.md](../reports/factory_messaging_migration_plan.md)
for the per-site migration plan.
