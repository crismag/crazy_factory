# Crazy Factory — Intelligence-first direction

North star for P4+ work. Companion to
[CF2_ARCHITECTURE.md](CF2_ARCHITECTURE.md). This document describes
capabilities that exist now and the near-term boundary — not a
wishlist of infrastructure.

## North star

Crazy Factory is not a clone of Lovable or any other app builder.
It is a software-creation system that takes incomplete human intent
and turns it into coherent, demonstrable working software through
reasoning, investigation, planning, execution, observation,
criticism, verification, and iterative improvement.

Governing principle:

> **Capability first. Architecture second. Technology third.**

Do not acquire infrastructure and then invent reasons to use it.
Claude/OpenAI/other plugins are workers. MCP is machinery. Crazy
Factory is the factory: it owns mission, understanding, context,
planning, capability selection, observation, evidence, judgment,
recovery, and outcome.

## Capability-first adoption

An external technology is allowed only when a concrete capability
requires it and it is demonstrably preferable to what already
exists. Deferred until a demonstrated need:

- KAE-Memory
- LangChain / LangGraph
- n8n
- Cline
- vector databases as “AI memory”
- message queues
- multi-agent frameworks

## Provider independence

```text
Crazy Factory
     | objective, curated context, acceptance, constraints
     v
AgentExecutor
     +-- Claude / Anthropic
     +-- OpenAI
     +-- stdlib proof actuator
     +-- future specialist
```

The factory compiles the assignment. The plugin writes files. The
factory independently inspects and judges. Crazy Factory is not
synonymous with Claude.

## Context engineering

More tokens are not better context. Context is relevant, structured,
attributable, compact, and sufficient. `execution_assignment.py`
assembles it from artifacts the factory already writes (seed,
architecture, workbench inventory, DiagnosisPacket, validation
checks, runtime, prior executor writes). It does not dump the
entire repo into the prompt.

## Evidence-based observation

Process exit status is not success. Evidence today:

- `validation_result.json` (compile / pytest / lint checks)
- `runtime_result.json` (confined start probe)
- workbench inventory and architecture
- `executor_result.json` (what the plugin wrote, plus stance)
- `judgment.json` (outcome vs acceptance vs validation vs runtime)

Browser/visual journeys remain deferred.

## Judgment vs execution success

`ExecutorResult.ok` means the plugin produced files. Acceptance
means the product is demonstrable. `judgment.json` records both so
the next beat cannot confuse them. Tests passing is one evidence
gate, not product quality.

## Recovery / reconsideration

The assignment stance is not “fix the errors”:

| Stance | When |
| --- | --- |
| `birth` | greenfield / code birth |
| `implement` | product gap |
| `repair` | first validation/runtime failure |
| `investigate` | previous executor wrote files and the failure remains |
| `need_context` | placeholder / unspecified product |

## Intelligence loop mapping (current)

| Capability | Implementation | Strength | This slice |
| --- | --- | --- | --- |
| UNDERSTAND | `product_kernel`, seed parse, Director | strong owner view | executor now receives a slice |
| INVESTIGATE | DiagnosisPacket, validation, runtime observer | facts not prose | failing checks reach the assignment |
| REASON | objective generator, convergence | repair vs product | stance from kind + prior write |
| PLAN | `next_execute_objective`, factory_advance | one objective per beat | assignment names that objective |
| EQUIP | workbench profile, capability gates | isolated | no new tools; confinement in assignment |
| EXECUTE | `AgentExecutor` + Claude/OpenAI | provider-neutral | quality assignment, not a thin prompt |
| OBSERVE | validation + runtime + metrics | structured | assignment + judgment artifacts |
| JUDGE | `evaluate_acceptance`, `evaluate_mission` | multi-gate | `judgment.json`; executor ok ≠ accepted |
| RECONSIDER | repair objectives, no-progress retry | kinds exist | `investigate` vs blind rewrite |
| DELIVER | mission trace, Director, MCP | owner-facing | no new MCP verbs |

## Near-term boundary (not this slice)

- KAE-Memory / durable memory (discover need first)
- specialized tool plugins (browser, security, a11y)
- runtime observe every beat (not only on acceptance)
- reading `executor_result.json` into objective selection
- Cursor/Codex IDE adapters
- network MCP
