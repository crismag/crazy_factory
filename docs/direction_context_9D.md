# Crazy Factory Direction Context and Implementation Plan

## Title

Phase 9D — Situational Context, Prompt Fidelity, and Acceptance-Driven Convergence

## Purpose

Crazy Factory has improved from an unsafe or unreliable prototype into a guarded iterative build loop. It can plan, authorize, propose, reject bad patches, remediate, and eventually produce a passing first slice.

However, generated output quality remains shallow because the LLM is not consistently receiving the right information at the right time. The problem is no longer simply “the model writes mediocre code.” The deeper issue is information loss across the factory pipeline.

The factory currently starves the LLM of:

* concrete acceptance criteria
* exact prior failures
* exact rejection reasons
* current task trajectory
* what was already attempted
* current workbench reality
* file-specific behavioral expectations

At the same time, feeding raw generated reports would create a self-poisoning loop because reports may contain boilerplate, stale claims, or inaccurate factory prose.

The next direction is to create a deterministic, curated, role-sliced situational context system that feeds models ground truth, not noise.

---

# Core Direction

## Guiding Principle

Feed facts. Do not feed factory prose.

The model should not be reminded of what the factory claimed happened.
The model should be shown what actually happened.

## Good Context To Feed

Feed ground truth generously:

* exact pytest failures
* exact ruff errors
* exact compile errors
* exact patch rejection reasons
* exact proposal rejection reasons
* exact contract rejection reasons
* current checklist item
* current acceptance criteria
* required files
* missing files
* existing source files in scope
* previous attempts for the same task
* recovery decisions
* validation command output
* architecture constraints
* seed-derived file requirements

## Bad Context To Avoid

Do not feed raw generated narrative reports:

* session reports
* APPLICATION_REPORT prose
* safety boilerplate
* long narrative summaries
* stale prior-run reports
* inaccurate claims such as “No application code was modified”
* duplicate report fragments
* unverified factory commentary

Reports may be used later only after they become truthful, structured, and distilled.

---

# Main New Artifact

## DiagnosisPacket / SituationalContextPacket

Create a deterministic context builder that produces a bounded packet of verified project/task state.

Recommended module:

```text
scripts/situational_context.py
```

or:

```text
scripts/diagnosis_packet.py
```

The packet should be generated from current workbench state, validation artifacts, rejection records, task records, architecture files, and checklist state.

It should not depend on raw narrative reports.

---

# DiagnosisPacket Schema

Recommended structure:

```yaml
packet_id: string
project_id: string
project_path: string
generated_at: iso_timestamp
freshness_scope:
  session_id: string
  task_id: string
  attempt_window: integer
  exclude_prior_sessions: true

current_task:
  task_id: string
  checklist_item_id: string
  focus_file: string
  objective: string
  scope: string
  acceptance_criteria:
    - string
  validation_expectations:
    - string
  required_files:
    - string
  files_in_scope:
    - string

architecture:
  required_files:
    - string
  forbidden_dirs:
    - string
  forbidden_names:
    - string
  forbidden_imports:
    - string
  missing_required_files:
    - string
  existing_required_files:
    - string

workbench_reality:
  existing_files:
    - path: string
      role: source | test | data | doc
      status: exists | missing
  source_snapshot:
    - path: string
      content: string
      truncated: boolean

last_validation:
  compileall:
    command: string
    status: passed | failed | not_run
    output_excerpt: string
  pytest:
    command: string
    status: passed | failed | not_run
    failing_tests:
      - test_name: string
        file: string
        message: string
        traceback_excerpt: string
  ruff:
    command: string
    status: passed | failed | not_run
    errors:
      - file: string
        line: integer
        code: string
        message: string

last_rejections:
  contract:
    - reason: string
      severity: blocker | warning
  proposal:
    - reason: string
      severity: blocker | warning
  patch:
    - reason: string
      severity: blocker | warning

attempt_history:
  - attempt_id: string
    task_id: string
    action: contract | proposal | patch | remediation
    result: accepted | rejected | validation_failed | validation_passed
    rejection_reasons:
      - string
    validation_summary: string
    files_touched:
      - string

recovery:
  remediation_enabled: boolean
  attempt_number: integer
  attempt_budget: integer
  repeated_failure_patterns:
    - string
  recommended_next_action: string
  stop_condition: string

excluded_context:
  raw_reports_excluded: true
  stale_reports_excluded: true
  narrative_reports_excluded: true
```

---

# Role-Sliced Context

The same packet should not be dumped into every prompt. Each role should receive only the slice it needs.

## Architect Slice

Purpose: understand project structure and missing pieces.

Include:

* project seed summary
* architecture constraints
* required files
* missing files
* checklist state
* current milestone
* seed-derived requirements if available

Exclude:

* full pytest logs unless architecture-relevant
* patch rejection details
* raw reports

## Planner Slice

Purpose: choose the next smallest valuable task and define a measurable contract.

Include:

* checklist state
* current target file
* required files
* missing files
* seed-derived behaviors
* previous completed items
* current architecture constraints

Must produce:

* objective
* scope
* exclusions
* dependencies
* acceptance criteria
* validation expectations

Acceptance criteria must be one criterion per observable behavior.

## Contract Role Slice

Purpose: freeze the planned task into an enforceable contract.

Include:

* planner output
* architecture constraints
* files in scope
* required validation commands
* current acceptance criteria

Must ensure:

* criteria are concrete
* criteria are testable
* task scope is small but valuable
* no generic “implement file” contracts unless expanded

## Coder Slice

Purpose: produce implementation proposal or code consistent with current task reality.

Include:

* objective
* scope
* acceptance criteria
* files to create/modify
* current source in scope
* exact prior rejection reasons
* exact prior validation failures
* attempt history for current task only
* architecture constraints

Exclude:

* raw reports
* unrelated task history
* stale failures from previous sessions

## Patch-Plan Slice

Purpose: generate exact file contents.

Include:

* approved proposal
* objective
* scope
* acceptance criteria
* validation expectations
* current file contents
* last failed command
* exact rejection reasons
* required tests
* no-placeholder quality rules

The patch-plan prompt must see what “done” means.

## Reviewer Slice

Purpose: judge completeness and safety.

Include:

* acceptance criteria
* generated patch summary
* files changed
* validation evidence
* missing required behavior
* quality gate results

Must return:

* valid
* revise_proposal
* reject

With explicit missing behaviors.

## Recovery Router Slice

Purpose: decide what to do after failure.

Include:

* last N attempts
* repeated failure patterns
* exact validation failures
* exact rejection reasons
* current task state
* remaining remediation budget

Must return:

* retry same task
* revise proposal
* regenerate patch
* escalate to planner
* stop as unrecoverable

---

# Immediate Implementation Plan

## Phase 9D.0 — Prompt Visibility Fixes

This is the smallest high-impact change.

### 9D.0.1 Feed Acceptance Criteria Into Patch Plan

Patch-plan generation currently receives file lists and implementation steps, but not enough success definition.

Update patch-plan prompt input to include:

* objective
* scope
* acceptance_criteria
* validation_expectations
* required_tests if available
* current failure/rejection context if available

The code generator must never be asked to write files without seeing the criteria used to judge success.

### 9D.0.2 Add Explicit Quality Bar

Add operational quality requirements to coder and patch-plan prompts:

* implement every acceptance criterion
* every behavior must have a test
* no placeholder `pass`
* no TODO-only implementation
* no `NotImplementedError`
* no empty tests
* no unused imports
* no fake green tests
* no notes admitting incomplete implementation
* do not declare completion if any criterion is missing

### 9D.0.3 Fix Test Builder Rule Drift

Current test builder guidance must match actual factory policy.

Replace any instruction saying:

```text
Never validate the whole project for an incremental task.
```

with:

```text
Run focused task validation when useful, but whole-project coherence gates remain mandatory before checkpoint, item retirement, or autopilot success.
```

Required coherence gates:

```bash
python3 -m compileall -q src tests
python3 -m pytest tests
ruff check src tests
```

---

# Phase 9D.1 — Build DiagnosisPacket Foundation

Implement deterministic packet creation.

## Files To Add

```text
scripts/diagnosis_packet.py
tests/test_diagnosis_packet.py
```

or equivalent names.

## Responsibilities

The builder should collect:

* current project id
* current task id
* current checklist item
* acceptance criteria
* architecture constraints
* required files
* missing files
* current source files in scope
* latest validation result
* latest rejection reasons
* current attempt history

## Requirements

* deterministic output
* JSON/YAML serializable
* bounded by token budget
* excludes raw reports
* excludes stale prior-run data
* deduplicates repeated failure text
* includes only current session/task attempt history by default
* unit tested with mocked records

## Output Location

Recommended:

```text
factory_state/projects/<project_id>/diagnosis/current_packet.json
```

or inside the active workbench:

```text
factory_diagnostics/current_packet.json
```

depending on existing state conventions.

---

# Phase 9D.2 — Wire Packet Into Coder and Patch-Plan

Update coder proposal and patch-plan generation to consume role-specific packet slices.

## Coder Proposal Must Receive

* current objective
* acceptance criteria
* files in scope
* current workbench state
* previous rejection reasons
* previous validation failures

## Patch-Plan Must Receive

* approved proposal
* acceptance criteria
* exact expected behavior
* current source contents
* last rejection reasons
* last validation errors

## Expected Improvement

The model should stop repeating thin proposals after rejection.

Instead of:

```python
def save_data(data):
    pass
```

It should receive:

```text
Previous patch was rejected because save_data/load_data were placeholders.
Acceptance criteria require JSON round-trip persistence, missing-file handling, and corrupt JSON handling.
Implement those behaviors and add tests.
```

---

# Phase 9D.3 — Layer 1 Requirement Expansion

After the packet exists, add seed-derived file requirement expansion.

## Purpose

Deterministic decomposition is good for convergence but too generic for quality.

Keep deterministic file order/count, but enrich each focus file with seed-derived requirements.

## New Role

```text
requirement_expander
```

or:

```text
focus_expander
```

## Function

```python
expand_focus_requirements(seed_context, focus_file, architecture) -> FocusRequirementSpec
```

## Example Output

```yaml
file: src/storage.py
purpose: JSON persistence layer for task-board app
required_behaviors:
  - save tasks to data/tasks.json
  - load tasks from data/tasks.json on startup
  - return empty list when file is missing
  - handle corrupt JSON without crashing
  - preserve task id, title, and done fields
required_tests:
  - test_save_load_roundtrip
  - test_missing_file_returns_empty
  - test_corrupt_json_returns_empty
  - test_task_serialization_shape
interfaces:
  - save_tasks(tasks, path=DEFAULT_TASKS_PATH)
  - load_tasks(path=DEFAULT_TASKS_PATH)
dependencies:
  - src/task_model.py
done_definition:
  - required behaviors implemented
  - required tests exist
  - compileall passes
  - pytest passes
  - ruff passes
```

## Persistence

Freeze expansion output.

Recommended:

```text
factory_requirements/file_contracts/src_storage.yaml
```

or:

```text
factory_context/file_contracts/storage.yaml
```

Important rule:

Do not regenerate expansion every beat unless explicitly requested. Frozen file contracts preserve convergence.

## Fallback

If LLM expansion fails:

* use deterministic generic fallback
* mark packet field `expansion_status: fallback`
* do not make the flow worse than today

---

# Phase 9D.4 — Layer 2 Acceptance Completeness Reviewer

Add a reviewer before apply.

## Purpose

Reject thin proposals before they become files.

## Inputs

* current file contract
* acceptance criteria
* proposed patch
* current workbench state
* validation expectations

## Output

```yaml
verdict: valid | revise_proposal | reject
missing_behaviors:
  - string
missing_tests:
  - string
quality_findings:
  - string
recommended_revision: string
```

## Reject When

* proposal does not satisfy file contract
* tests do not map to required behaviors
* patch contains placeholder logic
* implementation is only happy-path
* generated notes admit incompleteness
* criteria are ignored

---

# Phase 9D.5 — Layer 3 Acceptance-Based Item Retirement

Do not retire checklist items merely because compile/pytest/ruff passed.

A checklist item retires only when:

* required files exist
* acceptance criteria are implemented
* required tests exist
* validation passes
* no blocking reviewer findings remain

## Required Completion Check

Add or activate:

```python
missing_required(...)
```

and ensure it is called before item retirement.

## For Each Item

Track:

```yaml
item_id:
  status: pending | in_progress | blocked | complete
  acceptance_criteria:
    - string
  evidence:
    tests:
      - string
    validation:
      compileall: passed
      pytest: passed
      ruff: passed
    files:
      - path: string
        exists: true
```

---

# Phase 9D.6 — Reporting Truthfulness

Reports should be restructured into factual sections.

## Required Report Fields

* task id
* current checklist item
* files proposed
* files created
* files modified
* files skipped
* files rejected
* validation commands run
* validation status
* exact blockers
* context packet id
* acceptance criteria coverage
* item retirement decision

## Forbidden Report Behavior

Never say:

```text
No application code was modified.
```

if files were created or changed.

Never claim context was read if catalog is empty or context import failed.

Never report success if final validation failed.

---

# Phase 9D.7 — Fresh Debug Logs

Debug logs must be per run, not append-only across unrelated runs.

Recommended:

```text
logs/autopilot/task-board/<timestamp>/debug.log
logs/autopilot/task-board/<timestamp>/summary.md
logs/autopilot/task-board/latest -> <timestamp>
```

This prevents stale failure interpretation.

---

# Phase 9D.8 — Acceptance Target for Task-Board Demo

The task-board autopilot is successful only when the generated app contains:

Required files:

```text
README.md
src/task_model.py
src/storage.py
src/task_board.py
data/tasks.json
tests/test_task_model.py
tests/test_storage.py
```

Required behaviors:

```text
create task with id, title, done status
edit task title
toggle done status
delete task
serialize tasks to JSON
save tasks to data/tasks.json
load tasks on startup
missing JSON returns empty list
corrupt JSON handled safely
Tkinter UI smoke check does not hang
```

Required validation:

```bash
python3 -m compileall -q src tests
python3 -m pytest tests
ruff check src tests
```

Autopilot must exit `0` only when all of the above are green.

---

# Recommended Work Order

## Slice 1 — Prompt Visibility Patch

Implement:

* acceptance criteria into patch-plan prompt
* objective/scope into patch-plan prompt
* explicit quality bar
* updated test builder instruction

Expected outcome:

The coder stops coding blind.

## Slice 2 — DiagnosisPacket Minimal Version

Implement:

* packet schema
* current task fields
* acceptance criteria
* last validation result
* last rejection reasons
* current source snapshot
* tests with mocked artifacts

Expected outcome:

Every retry can see exact ground-truth failure context.

## Slice 3 — Wire Packet Into Patch-Plan

Implement role slice for patch-plan.

Expected outcome:

Patch generation sees exact failure/rejection and does not repeat previous invalid output.

## Slice 4 — Wire Packet Into Coder Proposal

Implement role slice for coder proposal.

Expected outcome:

Proposal generation becomes less generic and more tied to acceptance criteria.

## Slice 5 — Requirement Expansion

Implement file-specific expansion from seed.

Expected outcome:

Generic checklist items become concrete file contracts.

## Slice 6 — Completeness Reviewer

Implement pre-apply behavioral reviewer.

Expected outcome:

Thin-but-valid code is rejected before writing.

## Slice 7 — Acceptance-Based Retirement

Implement criteria coverage before checklist retirement.

Expected outcome:

Thin-but-green no longer counts as complete.

## Slice 8 — Reporting and Debug Cleanliness

Implement truthful report fields and per-run debug logs.

Expected outcome:

Operator can trust what the factory says happened.

---

# Non-Goals

Do not attempt to solve everything by switching models.

Do not dump larger raw context into prompts.

Do not feed raw generated reports into the model.

Do not relax safety boundaries.

Do not build UI first.

Do not allow push, merge, branch deletion, or destructive git operations.

Do not let the model decide that a task is complete without deterministic validation and acceptance evidence.

---

# Final Architecture Principle

The LLM should remain creative in:

* requirement interpretation
* decomposition
* implementation strategy
* remediation ideas
* code generation

The factory should remain strict in:

* context curation
* workspace cleanliness
* file boundaries
* architecture constraints
* placeholder rejection
* validation execution
* acceptance evidence
* report truthfulness
* final exit status

The correct division is:

```text
LLM = imagination and synthesis
Factory = evidence, enforcement, and truth
```

Phase 9D should therefore build the missing evidence layer between the model and the factory gates.

The next concrete artifact should be the DiagnosisPacket / SituationalContextPacket builder.
