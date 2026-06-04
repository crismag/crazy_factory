# Slices 3–4 / 9D.2 — Wire the packet into Coder and Patch-Plan

**Goal:** make every retry see exact ground-truth failure/rejection context, so
the model stops repeating thin/invalid output. Each role gets only its slice.

**Depends on:** Slice 2 (the packet exists). Composes with Slice 1 (the quality
bar). No new LLM roles — this enriches existing prompts.

## Role slices (project the packet; do not dump it whole)

```python
def coder_slice(p: DiagnosisPacket) -> str: ...
def patch_plan_slice(p: DiagnosisPacket) -> str: ...
```

Each returns a compact, labeled Markdown block. The slice helpers live next to
the packet (`diagnosis_packet.py`) so the projection is tested independently of
the prompt.

### Coder slice (consumed in `coder_proposal.py` `request_coder_stage`)

Include: objective, scope, **acceptance_criteria**, files_in_scope + current
source, **last proposal/patch/contract rejection reasons**, **last validation
failures (exact)**, attempt_history (this task only), architecture constraints.
Exclude: raw reports, unrelated-task history, prior-session failures.

Integration point — `coder_proposal.py:1051-1063` builds `messages`. Add the
slice as a labeled section in the user message:

```python
situational = coder_slice(packet) if packet else ""
... f"## What Happened Last Time (ground truth — do not repeat)\n\n{situational}\n"
```

`request_coder_stage` gains a `packet: DiagnosisPacket | None = None` param;
`factory_advance` builds the packet once per beat and passes it in.

### Patch-plan slice (consumed in `proposal_applier.py` `request_patch_plan`)

Include: approved proposal, objective + scope + **acceptance_criteria** (Slice 1
already adds these), **exact expected behavior**, current source contents, **last
failed command + its output**, **last rejection reasons**, required tests, the
quality bar. The patch-plan prompt must see what "done" means *and* what just
went wrong.

Integration point — append the slice to the patch-plan user message, same shape.

## Expected behavior change (the point of this slice)

Today, after a rejection the next beat re-proposes blind and often re-emits:

```python
def save_data(data):
    pass
```

After wiring, the prompt carries:

```text
Your previous patch was REJECTED: save_data/load_data were placeholder bodies.
Acceptance criteria require: JSON round-trip persistence; missing file -> [];
corrupt JSON handled without crashing. pytest failed: test_save_load_roundtrip
(AssertionError: expected [Task(...)], got None). Implement those behaviors and
add the listed tests. Do not return placeholders.
```

## Tests

- `tests/test_coder_proposal.py`: with a packet carrying a patch rejection +
  pytest failure, assert the rendered coder message contains the exact rejection
  reason and the failing-test name. Assert prior-session data is absent.
- `tests/test_proposal_applier.py`: assert the patch-plan message contains
  acceptance_criteria + the last failed command output.
- Slice helpers unit-tested directly (input packet → expected sections) without
  invoking Ollama.

## Risk / safety

- Pure context enrichment; the deterministic floor + path/placeholder gates are
  unchanged. Worst case if the packet is `None` (e.g. first beat) → behaves like
  today.
- Keep slices inside the token budget (the packet is already bounded; slices
  select, never expand). A slice must never include another task's files or a
  prior session's failures — enforced by building the packet with
  `attempt_window` + `session_id` (Slice 2).

## Acceptance

- Coder + patch-plan prompts provably include the relevant ground-truth slice.
- Re-proposal after a stub rejection no longer repeats the stub in a manual
  task-board beat (qualitative check) — and the deterministic placeholder gate
  fires far less often because the model was told not to.
- `ruff`+`mypy` clean; full suite green.
