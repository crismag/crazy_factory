# 01 — The Skill Library (what the LLM is fed and may direct)

A **skill** is a deterministic, schema'd, safety-bounded operation the LLM may
*request by name*. The LLM is **fed the catalog** (name, when-to-use, params) so
it can make proper decisions and direct the script; Python validates every
requested call against an allow-list + the floor and executes only the permitted
ones. This is local, curated function-calling — and it generalizes the existing
`recovery_router.ACTION_TYPES` allow-list (already this pattern, smaller).

## Skill contract

```python
@dataclass(frozen=True)
class Skill:
    name: str
    description: str          # what it does
    when_to_use: str          # guidance rendered into the adjudicator prompt
    params: dict              # JSON-schema of args
    category: str             # repair | scope | redirect | context | evidence | owner
    run: Callable             # deterministic impl (path-confined, bounded)
```

```python
@dataclass(frozen=True)
class SkillCall:
    skill: str
    args: dict
```

Registry: `scripts/skills/` (or `scripts/skill_library.py`) exposing
`SKILLS: dict[str, Skill]`, `render_catalog()` (the text fed to the LLM),
`validate_call(call) -> reasons`, and `execute(call, ctx) -> SkillResult`.

## Feeding the catalog to the LLM

`render_catalog()` produces a compact block injected into the adjudicator
prompt:

```text
You may direct ONLY these skills (choose by name, fill args per schema):

- autofix_lint(files=[...]) — repair: remove unused imports / fix safe lint
  (ruff F401, import order, formatting). USE WHEN: defects are trivial,
  auto-fixable lint, not behavior changes.
- keep_only_files(files=[...]) — scope: drop files outside the current focus
  item. USE WHEN: the patch over-reaches the focus (extra/premature modules).
- revise_contract(fields={...}) — redirect: amend objective/scope/acceptance to
  match the seed. USE WHEN: the contract drifted from seed intent.
- generate_subcontext(topic, body) — context: author a derived context doc that
  becomes part of the grounding. USE WHEN: a behavior needs an explicit spec.
- request_new_proposal(constraints) — redirect: re-propose within constraints.
- ...
```

The LLM returns `actions: [SkillCall]`; the runtime maps them through the
registry. **Unknown skill name or schema-invalid args → that call is dropped
(logged), never executed.**

## Initial skill set (by category)

### repair (keep + fix the work)
| Skill | Args | Does |
|---|---|---|
| `autofix_lint` | `files[]` | `ruff check --fix` safe rules (F401 unused imports, import order) + `ruff format` on the **kept patch content** in-memory; re-check |
| `strip_unused_imports` | `files[]` | AST removal fallback when ruff unavailable |
| `format_code` | `files[]` | formatter only |

### scope (defer over-reach, don't reject)
| `keep_only_files` | `files[]` | retain only in-focus files in the patch; the rest become **deferred items**, not failures |
| `defer_files` | `files[]`, `reason` | record dropped files as future checklist items |

### redirect (fix the *direction*, via the recovery path)
| `revise_contract` | `fields{}` | amend contract objective/scope/acceptance/validation_plan toward the seed |
| `update_focus` | `file` | re-point the current checklist focus |
| `split_task` | `into[]` | break an over-broad item into seed-aligned sub-items |
| `request_new_proposal` | `constraints` | clear approval + re-propose within stated constraints |
| `add_required_file` | `path` | add a seed-required file the contract omitted (e.g. `data/tasks.json`) |

### context (LLM authors grounding the factory then reuses)
| `generate_subcontext` | `topic`, `body` | write a derived context doc under `factory_context/derived/` and catalog it |
| `expand_focus_contract` | `file` | (re)run the 9D requirement expander for a file |

### evidence (read-only / safe IO)
| `run_validation` | — | run the coherence gate (owner-gated) |
| `read_workbench` | `files[]` | return current file contents to the LLM |
| `persist_patch_content` | — | save generated content so it's not discarded (see 02) |

### owner
| `record_owner_question` | `question` | park with a specific question |

## Validation & safety (Python enforces, every call)

`validate_call` rejects a call unless ALL hold:
- `skill` is in `SKILLS` (allow-list).
- `args` satisfy the skill's `params` schema.
- every path arg is **inside the project workbench** (reuse
  `resolve_workbench_path` / repo-confinement); never factory runtime dirs,
  `.git`, config, or outside the project.
- the skill's own bound holds (e.g. `autofix_lint` only changes lint, never
  semantics; `revise_contract` re-runs the deterministic contract floor after).
- destructive git / secrets / network are **not skills at all** — not in the
  catalog, so not expressible.

`execute` runs the deterministic impl, returns `SkillResult{changed, detail,
ok}`, and records it for the report + the #37 history.

## Why skills (not free-form LLM action)

- **Bounded surface:** the LLM can only do what the catalog allows; safety is a
  property of the catalog + validator, independent of the prompt.
- **Deterministic + testable:** each skill is unit-tested without a model.
- **Composable direction:** the LLM sequences skills (fix → keep_only_files →
  request_new_proposal) to *deliver the right task*, which is exactly the
  "direct the script and generate new contexts/actions" the phase calls for.
- **Auditable:** every executed skill is logged with args + result.
