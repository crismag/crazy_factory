# P0 — Why Crazy Factory cannot go prompt → working output

Generated: 2026-09-16. Traced from `scripts/factory_advance.py`,
`scripts/mission_loop.py`, `scripts/crazy_admin.py`,
`config/factory.yaml`, `crazy_project.yaml` defaults, and
`tests/autopilot_taskboard.sh`.

This supersedes Slice A as the **development priority**. Product
intelligence and MCP remain useful, but they are P3/P5. The factory
fails today because it is a **single-beat pipeline the owner must
crank**, not a closed execution engine.

---

## 1. Exact current execution path

There is no `start()` that works until done. The real path is:

```text
owner: crazy-admin startproject <id>
owner: crazy-admin add-context <id> <seed>
owner: crazy-admin advance <id>          # ONE beat, then process exits
owner: crazy-admin authorize-task <id>   # typing
owner: crazy-admin advance <id>          # coder may propose
owner: crazy-admin approve-proposal <id> # typing
owner: crazy-admin enable-apply
owner: crazy-admin enable-validation
owner: crazy-admin enable-remediation
owner: crazy-admin enable-autonomous     # optional
owner: crazy-admin advance <id>          # maybe apply + validate
owner: crazy-admin advance <id>          # maybe next checklist item
…repeat until owner gives up or parks…
owner: (outside the factory) pytest / compileall / launch the app
```

`scripts/mission_loop.py` is **also one beat**. It is cron-shaped:
lock → maybe one `factory_advance.main` → unlock → **exit**. Nothing
in-process returns to work.

`tests/autopilot_taskboard.sh` is a **human replacement**: it loops
`advance` + `authorize-task` + `approve-proposal` in bash, then runs
acceptance **outside** the factory. That script is the proof that the
engine does not own continuation.

One `advance` beat (when not parked):

```text
load context → Architect → Planner → planned_task.json (authorized:false)
→ Coder [SKIP unless authorized+valid]
→ Apply [SKIP unless approved+allow_apply]
→ Test plan
→ Validation [SKIP unless allow_run; SKIP if apply rejected]
→ Checkpoint [SKIP unless allow_auto_commit]
→ maybe tick checklist
→ maybe recovery_router [ONLY application_rejected AND allow_remediation]
→ print report → exit 0
```

---

## 2. Every point where execution stops

| Stop | Where | What happens |
| --- | --- | --- |
| Process exit | end of `factory_advance.main` / `mission_loop.main` | **The loop is the missing arrow.** Success and failure both exit. |
| No target | `advance` with no id/path/cwd | prints guidance, exit 0 |
| Missing workbench | `workbench_exists` | refuse, exit 0 |
| Unapproved path | `app_is_buildable` | `TARGET_PATH_UNSUPPORTED` |
| stop/pause | `requested_control_action` | persist WAIT, exit 0 |
| Park | `self_rejection`, `remediation_exhausted` | warn, **do not work**, exit 0 |
| Contract unauthorized | coder stage | Coder not activated |
| Contract invalid | contract_review | no coder |
| Proposal unapproved | applier | preview only, no writes |
| `allow_apply=false` | default | no writes |
| `mode: preview_only` | default until enable-apply | no writes |
| Apply rejected | path/secret/lint/contract | no files; validation skipped |
| `allow_run=false` | default | validation recorded as skipped |
| Command not allowlisted | `validation_runner` | blocked, never executed |
| Checkpoint off | default | no commit (not a product stop) |
| Checklist tick refused | stubs / missing file / interface gaps | item stays open; **still exits** |
| `NO_PROGRESS` (5 beats) | `progress_blocker` | park; next advance no-ops |
| `recovery_exhausted` | router budget | park |
| `needs_owner_decision` | adjudicator escalate | park |
| Satisfaction flag | mission_loop | next cron beat is `satisfied`, not run |
| Ollama down | every role | deterministic **planning** fallback; **no real implementation** |

The dominant stop is not a safety floor. It is **the process ending
after one pipeline pass**, plus **defaults that skip implement /
validate**.

---

## 3. Manual interventions currently required

From USAGE.md + autopilot script + owner_controls:

1. Create the project.
2. Supply/import context (and notice when the catalog is empty).
3. Invoke `advance` the first time.
4. `authorize-task` every new checklist item (unless autonomy).
5. `advance` again to propose.
6. `approve-proposal` every new proposal (unless autonomy/remediation).
7. `enable-apply` / `enable-validation` / `enable-remediation`.
8. Invoke `advance` after every gate.
9. `revoke-task` to unstick `self_rejection`.
10. Interpret pytest/ruff failures when validation is off.
11. Launch the application (factory never starts it).
12. Decide the next product gap when the checklist is a filename list.
13. Re-run the bash autopilot when the factory parks.

Autonomy mode (`allow_autonomous`) removes **typing** for authorize +
approve **inside one beat**. It does **not** create a persistent
mission. The owner still has to call `advance` (or cron) forever.

---

## 4. Configuration restrictions — classified

From `config/factory.yaml` + `default_control()` + `CAPABILITY_BRIDGE`
+ `validation_runner.ALLOWED_COMMANDS` + `git_guard`.

### SAFETY REQUIREMENTS (keep)

| Restriction | Why |
| --- | --- |
| No auto-push / auto-merge / force-push / history rewrite | repo integrity |
| Path confinement to workbench | isolation |
| Secret/credential path blocks | data |
| `sudo`, `rm -rf`, shell metacharacters in validation | host safety |
| Deletes default OFF | accidental destruction |
| Model cannot self-authorize a contract | governance floor |
| Factory must not write engine source | identity |

### DEVELOPMENT SCAFFOLDING (legitimate while debugging the *kernel*)

| Restriction | Why it existed | For a product run |
| --- | --- | --- |
| `factory.mode: dry_run` | observe without side effects | obsolete for `run` |
| `proposal_application.mode: preview_only` | inspect patches | **blocker** for output |
| `allow_apply: false` | same | **blocker** |
| `validation.allow_run: false` | don't exec yet | **blocker** |
| `allow_remediation: false` | don't auto-fix | **blocker** for recover |
| `autonomy.enabled` absent/false | require typing | **blocker** for unattended |
| `max_files_per_run: 5` | bound a beat | **product limiter** |
| `max_lines_per_file: 300` | bound a beat | limiter |

These are **not** safety. They are "the apprentice is not allowed to
build yet." A workbench **execution profile** should flip them ON for
one isolated project without weakening other projects or the floor.

### OBSOLETE LIMITATIONS

| Item | Reality |
| --- | --- |
| Docs claiming documentation-only factory | runtime exists |
| `mission_loop` as "continuous operation" | one beat |
| Reviewer as a lifecycle phase | not invoked as a phase |
| Test Builder plan | ignored when `architecture.json` exists |

### DIRECT BLOCKERS TO THE PRODUCT

1. **No continuation controller** — the missing `while not done`.
2. **Default-off implement/validate** — a beat that cannot write or
   test cannot produce software.
3. **Per-item owner authorize/approve** unless autonomy is on.
4. **Validation allowlist has no install/build/start** — no `npm`,
   `pip install`, `node`, `python app.py`. A web app cannot be built
   or launched by the Observer today.
5. **Recovery is not a continue** — it rewrites artifacts then
   **exits**; the next beat is a separate process.
6. **`NO_PROGRESS` / park** without a new objective — stuck.
7. **No running-output inspection** — files ≠ runnable.
8. **In-process Coder + Ollama** as the only implementer — if the
   model is down or starved, fallbacks plan but do not ship a product.
9. **Checklist-as-progress** — "Implement src/storage.py" is not
   "users can complete a task in the UI."

---

## 5. Missing feedback loops

```text
HAVE:     implement? → (maybe) pytest/ruff on disk
MISSING:  execute beat → observe → evaluate → NEXT beat automatically

HAVE:     validation_failed → remediation in THE NEXT owner advance
MISSING:  validation_failed → recover → execute → observe (in-process)

HAVE:     application_rejected → recovery_router (end of beat) → exit
MISSING:  rejected → revise objective → execute again

HAVE:     checklist tick on file evidence
MISSING:  "did the app start and do X?"

HAVE:     DiagnosisPacket for situational facts (good)
MISSING:  feeding that into a persistent mission controller

HAVE:     autonomy auto-approve inside a beat
MISSING:  mission that keeps calling beats
```

The old factory has **phases**. It lacks the **arrows that return to
work**.

---

## 6. Redundant machinery that can be simplified

Keep as rails: workbench isolation, contracts floor, apply engine,
validation allowlist, state JSON, DiagnosisPacket.

Do not grow: another recovery module, more reviewer phases, MCP
resource trees, role registries, dashboards.

Fold later: `remediation.py` + `recovery_manager.py` +
`recovery_router.py` (three vocabularies for "try again").

`mission_loop.py` (cron one-shot) stays for scheduling; **P0 is an
in-process mission runner**.

---

## 7. Delegate vs own

| Own (Crazy Factory) | Delegate (coding agent) |
| --- | --- |
| Mission + continuation | Token-level code edits |
| Isolated workbench + safety floor | Multi-file implementation |
| Objective + acceptance contract | Framework/idiom knowledge |
| Tool execution (tests, later build/start) | Generating the patch |
| Independent evaluate (pass / more / blocked) | Self-talk about quality |
| Trace / report | — |
| Stop for genuine human authority | — |

Today the in-process Coder **is** a weak coding agent (JSON patch
plan → apply). Keep it as the default executor so `run` works with
Ollama. Add an **agent executor interface** so a future Cursor/Codex
adapter can replace that step without rewriting the loop.

---

## 8. Minimum architecture for autonomous completion

```text
run(seed)
  apply WORKBENCH_AUTONOMOUS profile   # apply+validate+remediate+autonomy
  loop until COMPLETE | HUMAN_REQUIRED | BUDGET:
      EVALUATE (acceptance, growth, blocker)
      if not terminal:
          OBJECTIVE = current gap (checklist focus for now)
          EXECUTE   = one factory_advance beat (existing kernel)
          OBSERVE   = validation_result + workbench_metrics + blocker
          TRACE     append
  report artifact or justified blocker
```

State machine:

`ASSESS → OBJECTIVE → EXECUTE → VALIDATE → EVALUATE`
→ `COMPLETE` | `OBJECTIVE` | `RECOVER→OBJECTIVE` | `HUMAN_REQUIRED`

Existing Architect/Planner/Coder/Test live **under EXECUTE**. They
must not be the thing the owner cranks.

---

## 9. Benchmark (first proof)

Seed: `examples/seeds/task_board_web.md`

Python stdlib-only task board (so today's pytest/compileall allowlist
can eventually validate it without npm). Acceptance is behavioral, not
"files exist."

A passing P0 **engine** test (no Ollama required): `crazy-admin run`
keeps invoking the kernel until COMPLETE / HUMAN / BUDGET and writes
a mission trace. A passing P1 **product** test (needs a coding agent):
the same command on that seed yields a runnable app.

---

## 10. Ordered plan (priority)

| Pri | Meaning | This branch |
| --- | --- | --- |
| **P0** | Closed loop: context → work → observe → continue | `mission_runner` + `crazy-admin run` |
| **P1** | Runnable output (build/start/install tools) | observer landed |
| **P2** | Convergence (objectives from remaining gaps) | `objective_generator` wired into EXECUTE |
| **P3** | MCP exposes `start/status/continue/stop` | thin wrap of P0; seed-in-start open |
| **P4** | Better agents / executor adapter | later |
| **P5** | Broader product intelligence | postpone |

---

## 11. Concrete P0 tasks

1. ~~Workbench execution profile (capabilities ON, floor intact).~~
2. ~~Mission runner loop + evaluator + `MISSION_TRACE.md`.~~
3. ~~`crazy-admin run` / `stop`.~~
4. ~~Tests: continues, stops on complete, stops on human blocker,
   stops on budget, writes trace, does not push/merge.~~
5. ~~Benchmark seed with explicit acceptance.~~
6. ~~MCP `start_mission` / `continue_mission` / `stop_mission` as
   wrappers, not the engine.~~

Landed on this branch. Acceptance evaluation now resolves workbench
paths against the factory root (CWD-independent).

P1 observer and P2 objective generator landed on this branch (see
`factory/CF2_TASK_CHECKLIST.md`). Remaining: P3 seed-in-start, P4
coding-agent adapter for a live task-board build.
