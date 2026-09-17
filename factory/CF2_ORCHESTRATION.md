# Crazy Factory — Orchestration current state

Slice 1 audit for the Orchestration Readiness + Pattern Intelligence
track. This document records what the kernel actually does today, what
can be extended, and the minimal primitives this slice introduces.
It does not rewrite the proven product loop.

Plan of record: [CF2_ARCHITECTURE.md](CF2_ARCHITECTURE.md).
Task graph primitive: `scripts/task_graph.py`.

**Last updated:** 2026-09-17

---

## Proven baseline (do not regress)

```text
prompt
  → product claims
  → Codex / AgentExecutor
  → real implementation
  → Factory-owned behavioral verification
  → claim verification
  → owner-delta verification
  → COMPLETE
```

Invariants:

- Codex is recognized through `default_executor().can_implement()`,
  not provider-name special casing.
- Owner deltas reopen accepted work.
- COMPLETE requires product evidence.
- Habit-class evidence is behavioral, not identifier matching.
- Persistence can be verified across restart.
- Visible output can verify product behavior.
- `planned_task.json` does not block AgentExecutor paths.
- The inner Ollama Coder authorization chain remains independently
  gated.
- An already-satisfied habit workbench can COMPLETE with zero extra
  coding beats.

This slice does not rewrite product evidence, Codex integration, or
the inner Coder gate.

---

## Step 1 — Current path (exact points)

```text
owner prompt / seed / delta
        │
        ▼
prompt_compiler / conversation_delta     product_intent.json
        │                                (revision + claims)
        ▼
mission_runner.evaluate_mission
        │
        ├─ acceptance_check              mechanical evidence
        ├─ product_intent.score_claims   product_evidence.json
        ├─ conversation_delta            deltas.json (lifecycle)
        └─ runtime_observer              runtime_result.json
        │
        ▼
objective_generator.next_execute_objective
        │  priority:
        │    runtime > validation > owner_delta
        │    > product_claims > product_kernel > growth
        │
        ▼
current_objective.json                   ONE ExecuteObjective
current_module.json                      nested module focus
task_graph.json                          THIS SLICE (side-effect)
        │
        ▼
execution_assignment.compile_assignment  bounded AgentExecutor packet
        │
        ▼
AgentExecutor.execute                    files under ALLOWED_TOPS
        │
        ▼
validation_runner + runtime_observer
        │
        ▼
evaluate_mission                         COMPLETE / MORE_WORK / …
```

| Stage | Implementation | Artifact |
| --- | --- | --- |
| Owner prompt | `scripts/prompt_compiler.py`, `crazy-admin run --prompt` | `docs/seed.md`, `architecture.json` |
| Intent / claims | `scripts/product_intent.py` | `factory_tasks/product_intent.json` |
| Owner delta | `scripts/conversation_delta.py` | `deltas.jsonl`, `deltas.json` |
| Objective | `scripts/objective_generator.py` `ExecuteObjective` | `current_objective.json` |
| Product gaps | `scripts/product_kernel.py` `Objective` | inspect/assess (not a DAG) |
| Assignment | `scripts/execution_assignment.py` | `execution_assignment.md` |
| Inner-Coder packet | `scripts/diagnosis_packet.py` | `diagnosis/current_packet.json` |
| Inner-Coder gate | `scripts/contract_stage.py` | `planned_task.json` (optional on AgentExecutor) |
| Executor | `scripts/agent_executor.py` | `executor_result.json` |
| Validation | `scripts/validation_runner.py` | `validation_result.json` |
| Runtime | `scripts/runtime_observer.py` | `runtime_result.json` |
| Evidence | `scripts/product_evidence.py` | `product_evidence.json` |
| Acceptance | `scripts/acceptance_check.py` | `product_acceptance.json` |
| Mission | `scripts/mission_runner.py` | `mission_result.json`, `MISSION_TRACE.md` |
| Planning prose | Architect/Planner | `TASK_EXPANSION.md`, `NEXT_ACTION.md` |
| Checklist | completion parser | `MASTER_CHECKLIST.md` (flat list) |

There is one current objective. There is no durable dependency graph.
`MASTER_CHECKLIST.md` is a filename-oriented list. Product-kernel
`Objective` is a Director gap (title, why, expected_evidence,
related_modules), not a task DAG.

---

## Step 2 — Context flow

| Context | Producer | Consumer | Authority | Stale-sensitive | Used for |
| --- | --- | --- | --- | --- | --- |
| Owner intent | prompt compiler / seed | assignment, claims, Director | **highest** for requested behavior | yes (revision) | what the product must do |
| Owner delta | `conversation_delta` | objective, claims, COMPLETE | **highest** for change; invalidates prior acceptance | yes | reopen work; extra claims |
| Product claims | `product_intent` | objective, assignment, evaluator | high (compiled from intent) | yes | remaining work; COMPLETE |
| Verified / unsatisfied claims | `product_evidence` + `score_claims` | evaluator, `_from_product_claims` | high (Factory-owned) | yes | skip already-satisfied work |
| Architecture | `architecture.json` via `architecture.load_contract` | patch/coherence gates, assignment excerpt | high for structure | yes | forbid contradicting the system |
| Project contract | `project_contract.py` from seed | architecture derivation | high when present | yes | forbidden tech, required behaviors |
| File contracts | `factory_context/file_contracts` | `acceptance_check` | medium-high | yes | declared interfaces |
| Repo state | workbench files + `workbench_growth` | assignment inventory, evidence probes | high for what exists | yes | ground abstract requirements |
| Mission state | `mission_runner` | Director, MCP status | operational | yes | continuation / stop |
| Task expansion | Architect (`TASK_EXPANSION.md`) | Planner (legacy inner path) | **low** | **yes — often stale** | generated plan only |
| Next action | Planner (`NEXT_ACTION.md`) | inner Coder prompt | **low** | **yes** | generated plan only |
| Planned task | `contract_stage` / Ollama | inner Coder authorization | high *only* for inner Coder; skipped on AgentExecutor | yes | owner-authorized bounded coding task |
| Execution assignment | `execution_assignment` | AgentExecutor | medium (projection of higher authorities) | yes | bounded worker context |
| Validation | `validation_runner` | objective repair, assignment | high for mechanical health | yes | repair vs implement |
| Product evidence | `product_evidence` | evaluator COMPLETE | high | yes | claim satisfaction |
| Executor result | AgentExecutor | `_annotate_with_executor`, judgment | low (self-report, not proof) | yes | avoid repeating identical files |
| Control decision | `control_intelligence` | kind/stance overlay | medium; rails veto COMPLETE | yes | beat decision |
| Historical attempts | attempt log / executor_result | assignment previous_executor | diagnostic | yes | stagnation later |

---

## Step 3 — Context authority (desired)

Generated planning prose must never outrank current authoritative
state. Audited desired order:

```text
current owner intent (incl. open deltas)
        ↓
current product state / evidence
        ↓
current architecture / project / file contracts
        ↓
current repo state
        ↓
current execute objective / task graph (derived)
        ↓
execution assignment / diagnosis packet (projections)
        ↓
executor self-report
        ↓
historical / stale planning prose
        (TASK_EXPANSION.md, NEXT_ACTION.md, leftover planned_task.json)
```

Reconciliation example from the kickoff:

- Owner delta: add feature X
- Old `TASK_EXPANSION.md`: X is out of scope
- Repo: partial X exists
- Evidence: half of X is verified

Factory behavior today: the delta bumps `intent_revision`, prior
COMPLETE is stale, `_from_owner_delta` / unsatisfied claims drive
the next `ExecuteObjective`. The old expansion file is not consulted
on the AgentExecutor path. **Keep that.** The task graph is rebuilt
from current intent/evidence each beat, not from the previous graph
or from `TASK_EXPANSION.md`.

---

## Step 3 — Assess existing structures

| Question | Finding |
| --- | --- |
| Can objectives become graph nodes? | **Extend, do not replace.** `ExecuteObjective` remains the single scheduled unit. Graph nodes are a durable projection of the same sources (runtime, validation, deltas, claims). Product-kernel `Objective` stays a Director gap. |
| Can `execution_assignment` become ContextPacket? | **Yes, later (Slice 3).** It already answers the nine intelligence questions, prepends unsatisfied claims, and bounds excerpts. Do not add a parallel packet this slice. `DiagnosisPacket` stays the inner-Coder FACTS packet. |
| Can workbench support isolated task workspaces? | **Not yet.** One `app_path` workbench; AgentExecutor writes through `ALLOWED_TOPS`; no git worktree per task. Factory-owned integration. Slice 4. |
| Can product evidence supply task evidence targets? | **Yes, now.** `Capability.evidence` and `ClaimScore.kind` become `evidence_targets` / claim linkage on each node. |

No parallel orchestration subsystem.

---

## Step 4 — Minimal schema (only fields with consumers)

### TaskNode

| Field | Consumer |
| --- | --- |
| `task_id` | persist/load, dependency edges, tests |
| `parent_objective_id` | link to current `ExecuteObjective` |
| `intent_revision` | reject/flag stale graphs |
| `title` | debug, future assignment slice |
| `purpose` | why this task exists |
| `status` | ready set, metrics, future scheduler |
| `kind` | `implement` / `repair` / `verify` / `delta` / `birth` / `specify`; metrics |
| `dependencies` | ready-set, cycle check, future scheduler |
| `blocked_by` | repair outstanding vs claim work |
| `claim_ids` | task↔claim linkage; skip satisfied work |
| `evidence_targets` | what product truth should change |
| `context_refs` | bounded, attributable pointers (not blobs) |
| `affected_scope` | future file-conflict / parallel safety |

Not stored (no consumer this slice):

- `parallelizable` — **derived** (`is_parallelizable`)
- `executor_requirements` — routing still uses `can_implement()`
- `risk`, `expected_outputs` blobs, `RUNNING`/`FAILED` — no scheduler yet

### Status vs existing transitions

| Graph status | Existing CF meaning |
| --- | --- |
| `pending` | deps unmet (new; not scheduled today) |
| `ready` | would be eligible if the scheduler consulted the graph |
| `verified` | claim/delta/evidence already satisfied |
| `blocked` | runtime/validation repair outstanding |
| `superseded` | node identity from an older revision no longer present |

Not adopted yet: `RUNNING`, `IMPLEMENTED`, `VALIDATING`, `FAILED`.
Those would conflate “executor wrote files” with “product verified”
if introduced without a consumer. Task completion ≠ claim verification.

### ContextPacket (Slice 3)

`ExecutionAssignment` **is** the bounded packet. A selected `TaskNode`
is optional. Legacy `compile_assignment(project, root, objective)`
still builds a valid objective-oriented assignment (`task_id` empty).

When `task=` is supplied and `task.intent_revision` matches current
intent:

- identity: `task_id`, `parent_objective_id`, `intent_revision`
- `claim_ids` / `evidence_targets` from that node only
- `context_refs` (provenance pointers, not blobs)
- `repo_scope` as `file:…` paths from `affected_scope`
- architecture **key subset** (stack, start, forbidden imports,
  intersecting `required_files`) — the file is still monolithic
- owner intent as a short original-prompt slice
- owner deltas only when the node is a delta task
- prior executor writes only if they intersect scope or the stance
  is repair/investigate

Stale tasks (`task.intent_revision != current`): the returned packet
keeps the **old** revision, sets `stale=True`, and does **not** copy
current owner intent. `build_request` regenerates from the current
objective instead of executing the stale packet. Persisted
`execution_assignment.json` is never rewritten to pretend it was
built under a newer revision.

Completing the assignment does not verify claims. Factory evidence
remains independent.

Bounded selection friction (do not paper over with huge packets):

- `architecture.json` has no domain/module addresses
- many graph nodes still have empty `affected_scope`
- claims do not map to modules except via `Capability.files`
- executor history is a file-list note, not structured attempts
- the live AgentExecutor path still compiles the **objective** packet
  (no auto-selected graph node) so current Codex behavior is unchanged

### Context refs (this slice)

Examples actually written:

- `product_intent@revision-2`
- `claim:define_habits`
- `architecture:architecture.json`
- `owner_delta:delta-1`
- `objective:OBJ-PRODUCT`
- `evidence:runtime`

---

## How the graph is derived (no invented domain DAG)

The graph is a **deterministic projection** of current Factory truth:

1. Runtime/validation failures → `repair` nodes (`ready`).
2. Each compiled claim → `implement` node. Status `verified` if
   persisted evidence says so; `blocked` while a repair is outstanding;
   otherwise `ready`. **No claim-to-claim dependencies** (the Factory
   does not know domain topology yet).
3. Each owner delta → `delta` node (open = ready/blocked; verified
   deltas stay visible as `verified`).
4. Greenfield with no claims → `birth`.
5. `specify_intent` objective → `specify`.
6. One `verify` node depending on claim/delta implement nodes —
   Factory evidence step, not a hard-coded product-management graph.

The scheduler is unchanged: `next_execute_objective` still returns
one `ExecuteObjective` with the same priority. Persisting
`factory_tasks/task_graph.json` is a side-effect.

---

## A6 — Stagnation prep

`task_graph.json` stores:

- `fingerprint` of task ids + statuses + claims + revision
- `repo_fingerprint` of workbench `src/` / `tests/` / `data/` paths
- `prior_*` fingerprints
- `churn_without_progress` when tasks/evidence are unchanged and
  repo paths changed

No diagnosis policy engine. No automatic “stop coding.”

---

## A7 — Executor capability vocabulary (current consumers only)

Existing:

- `AgentExecutor.can_implement()` — evaluator MORE_WORK vs
  `RUNNABLE_PREVIEW`
- `coding_executor_available()` — same question, no vendor branch

Do not add `can_review`, `can_use_browser`, cost/latency classes
until something reads them. Future routing should stay capability-
based.

---

## A8 — Specialist roles (conceptual only)

A role is instructions + context projection + task + tools, not a
service or persistent chat.

| Role | Today | Later |
| --- | --- | --- |
| Director / Decomposer | `product_kernel` + `director.py` + this graph projection | true decomposition |
| Architecture / Repo Analyst | `architecture.json`, inspect | bounded analyst packet |
| Implementation Worker | AgentExecutor | isolated worktree |
| Product / UX Reviewer | not a worker; evidence kinds | advisory patterns |
| Verification Worker | `product_evidence` (Factory-owned) | stays Factory-owned |

Do not expose agent topology to end users.

---

## A9 — Workspace isolation

Today's live path still writes one `app_path` workbench.

Slice 4 adds an opt-in primitive (`scripts/task_workspace.py`):

- Location: `factory_workspaces/<project>/<workspace_id>/tree`
  (gitignored; never mixed into customer source).
- `worktree` when `<app>/.git` exists (detached HEAD at recorded SHA).
- `copy` of allowed application tops otherwise. A workbench that only
  lives inside the Factory repo is **not** treated as a Git base.
- Record: task_id, intent_revision, base_revision or explicit
  `git_base_available=False`, changed files from Git/filesystem.
- `bind_project_to_workspace` points `app_path` at the tree without
  rewriting `config/projects.yaml`.
- Stale intent marks the workspace `stale` and refuses reuse.
- Cleanup removes only that workspace (worktree-aware). No merge.

Live AgentExecutor does not auto-create workspaces.

Slice 4 friction (informs integration):

- Embedded `apps/*` workbenches are gitignored and usually **not** Git
  repos; isolation is a bounded copy and `base_revision` is empty.
- Workbenches routinely have uncommitted files; a worktree is HEAD
  only (`canonical_dirty`).
- `config/projects.yaml` still has one canonical `app_path`. Binding
  is ephemeral and must not be persisted as the registry path.
- Runtime `listen_port` / data files live in the workbench; two
  workspaces would collide if started. Not started in this slice.
- `repo_scope` is advisory. AgentExecutor can still write other
  allowed tops *inside* the isolated tree. Enforcing scope needs a
  later apply filter. Existing ALLOWED_TOPS confinement is unchanged.
- Validation/runtime still assume the project mapping's `app_path`
  and `task_root`. Canonical `factory_tasks` is not remapped.
- `.env` / secret names are not copied. No secret inheritance.

## A10 — File conflict prep

`scopes_overlap` / `is_parallelizable` detect:

- explicit file overlap
- shared top-level / module path
- package/config files (`requirements.txt`, `architecture.json`)
- schema/data/migration overlap

Unknown `affected_scope` on a writing task is **not** treated as
safe-to-parallelize. Dependency independence alone is insufficient.

---

## Track B — Pattern intelligence (not this slice)

Slice 5 will add archetypes, feature patterns, UX patterns, and
reference entries with a small schema, loader, and search. Patterns
are advisory. Owner intent and architecture remain authoritative.
Do not couple runtime to external repositories. Slice 6 may let one
benchmark’s task expansion *read* pattern metadata.

---

## Non-goals (still in force)

No multi-agent parallel writes, auto-merge, agent git push, agent-
decided COMPLETE, persistent specialist chats, LLM-per-task router,
LLM judge replacing deterministic validation, VS Code/Cursor as a
runtime dependency, or rewrite of Codex / product evidence / inner
Coder.

User-facing surface stays: describe software → context → Factory
works → preview + repository. Task DAGs and worktrees belong in
debug tooling only.

---

## Recommended next slice

**Safe task-result integration:** take one isolated workspace result
and apply it to the canonical workbench under Factory authority
(changed-file list, path confinement, no worker merge/push). Still
one worker at a time. Pattern library remains a separate slice.
