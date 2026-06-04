# Slice 2 / 9D.1 — DiagnosisPacket foundation

**Goal:** one deterministic, bounded, role-sliceable object holding *verified*
project/task state — the single source of curated truth every later slice
consumes. No LLM here; pure assembly from artifacts + state.

## Module

```
scripts/diagnosis_packet.py
tests/test_diagnosis_packet.py
```

## Dataclasses (mirror the direction-doc schema, typed)

```python
@dataclass(frozen=True)
class FailingTest:
    test_name: str
    file: str
    message: str
    traceback_excerpt: str = ""

@dataclass(frozen=True)
class LintError:
    file: str
    line: int
    code: str
    message: str

@dataclass(frozen=True)
class CheckOutcome:
    command: str
    status: str               # passed | failed | not_run
    output_excerpt: str = ""

@dataclass(frozen=True)
class Rejection:
    reason: str
    severity: str = "blocker"  # blocker | warning

@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    task_id: str
    action: str               # contract | proposal | patch | remediation
    result: str               # accepted | rejected | validation_failed | validation_passed
    rejection_reasons: list[str]
    validation_summary: str
    files_touched: list[str]

@dataclass(frozen=True)
class SourceFile:
    path: str
    content: str
    truncated: bool

@dataclass(frozen=True)
class DiagnosisPacket:
    packet_id: str
    project_id: str
    project_path: str
    generated_at: str
    # freshness
    session_id: str
    task_id: str
    attempt_window: int
    # current task
    checklist_item: str
    focus_file: str
    objective: str
    scope: str
    acceptance_criteria: list[str]
    validation_expectations: list[str]
    required_files: list[str]
    files_in_scope: list[str]
    # architecture
    forbidden_dirs: list[str]
    forbidden_names: list[str]
    forbidden_imports: list[str]
    missing_required_files: list[str]
    existing_required_files: list[str]
    # workbench reality
    source_snapshot: list[SourceFile]
    # last validation (ground truth)
    compileall: CheckOutcome
    pytest: CheckOutcome
    pytest_failures: list[FailingTest]
    ruff: CheckOutcome
    ruff_errors: list[LintError]
    # last rejections (ground truth, from JSON not prose)
    contract_rejections: list[Rejection]
    proposal_rejections: list[Rejection]
    patch_rejections: list[Rejection]
    # trajectory
    attempt_history: list[Attempt]
    # recovery
    remediation_enabled: bool
    attempt_number: int
    attempt_budget: int
    repeated_failure_patterns: list[str]
    expansion_status: str = "none"   # none | expanded | fallback
```

## Data sources (verified — read structured artifacts, NOT `.md` prose)

| Field | Source |
|---|---|
| acceptance_criteria / objective / scope / validation_expectations | `factory_tasks/planned_task.json` (contract record) |
| required_files / forbidden_* | `architecture.json` via `architecture.load_contract` |
| missing_required_files / existing_required_files | `architecture.missing_required(app_path, contract)` + its complement |
| checklist_item / focus_file | `factory_tasks/MASTER_CHECKLIST.md` via `completion.checklist_focus` + first open item |
| source_snapshot / files_in_scope | workbench read (reuse `coder_proposal.read_workbench_source`), limited to files_in_scope |
| pytest/ruff/compile outcomes + failures | `factory_tasks/validation_result.json` (the `ValidationResult` the run persists) — parse `CheckResult` rows by command |
| contract_rejections | `planned_task.json` validation block (`ValidationVerdict.reasons`) |
| proposal_rejections | `factory_tasks/coder_proposal.json` verdict reasons |
| patch_rejections | application result / `patch_plan` verdict reasons |
| remediation_enabled / attempt_number / attempt_budget | `factory_config["validation"]["allow_remediation"]`, `project_state["remediation_attempt"]`, `remediation_settings()` |
| session_id / task_id | `project_state` (+ a per-run session id — see Freshness) |

**`attempt_history` does not exist yet.** `project_state` tracks
`failure_count`, `remediation_attempt`, `last_*_status` — but no per-attempt log.
Two options:
1. **Add it** — append one `Attempt` record per beat in
   `mission_state.update_success_state` (cheap, authoritative). **Preferred.**
2. **Reconstruct** — best-effort from the latest artifacts (only the most recent
   attempt is reliable). Acceptable for a minimal first version.

Start with option 2 (single most-recent attempt) so the packet ships without a
state-shape change; add option 1 in the same slice if budget allows.

## Determinism, freshness, budget

- **Deterministic:** no `Date.now()`-style nondeterminism in tests — accept
  `now: str` (ISO) as a param, like `add_context`. `packet_id` derived from
  `project_id + task_id + attempt_number` (stable), not a random uuid.
- **Freshness:** `session_id` stamps the current run; **exclude any artifact
  from a prior session/task** (the context-wedge run proved stale data poisons
  decisions). Default `attempt_window = 3` (last N attempts for this task only).
- **Budget:** reuse the `context_loader` pattern — per-file line cap +
  total-byte cap on `source_snapshot`; truncate with `truncated=True`.
- **Dedup:** collapse identical rejection/failure strings (the same lint error
  repeated across attempts appears once, with a count).
- **No raw reports:** never read `*_REPORT.md` / session prose. (Enforced by a
  test asserting the builder opens no `report` files.)

## Output location

```
factory_state/projects/<project_id>/diagnosis/current_packet.json
```

Matches the per-project state convention (`factory_state/projects/<id>/`). Write
via `safe_write_json` confined to that root. (Keep it out of the workbench
`src/tests` so it never trips the coherence gate or required-file checks.)

## API

```python
def build_packet(
    *, project: dict, root: Path, factory_config: dict,
    project_state: dict, session_id: str, now: str,
    attempt_window: int = 3,
) -> DiagnosisPacket: ...

def packet_to_dict(packet: DiagnosisPacket) -> dict: ...   # JSON-serializable
def write_packet(packet, root, project) -> str: ...        # safe_write_json
```

## Tests (`tests/test_diagnosis_packet.py`, mocked artifacts)

1. Builds from a temp workbench with a planned_task.json + validation_result.json
   + architecture.json → asserts acceptance_criteria, pytest_failures,
   missing_required_files populated.
2. **No-report invariant:** patch `open`/reads to fail on any `*_REPORT.md`;
   builder still succeeds.
3. **Freshness:** an artifact stamped with a different `session_id` is excluded.
4. **Budget:** a huge source file is truncated (`truncated=True`).
5. **Dedup:** duplicated rejection strings collapse.
6. **Determinism:** same inputs + same `now` → byte-identical `packet_to_dict`.
7. Serializable: `json.dumps(packet_to_dict(p))` round-trips.

## Acceptance

- Builder is pure/deterministic, reads only structured artifacts, bounded, and
  excludes prior-session data. Unit-tested. `ruff`+`mypy` clean.
- Nothing consumes it yet (that's Slice 3) — this slice is the foundation only.
