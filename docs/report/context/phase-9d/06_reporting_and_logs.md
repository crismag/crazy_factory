# Slice 8 / 9D.6 + 9D.7 — Reporting truthfulness & fresh debug logs

**Goal:** make the operator able to trust what the factory says happened, and
stop stale logs from poisoning interpretation. Two related fixes.

---

## 9D.6 — Reporting truthfulness

### The verified lie

`scripts/report_writer.py:475` emits, unconditionally, inside the dry-run
report's Safety Record:

```python
+ "- No application code was modified.\n"
```

This is boilerplate from before apply mode existed. After any apply it is false.
There are likely sibling overstatements ("context was read" while the catalog is
empty).

### Changes

1. **Make write claims conditional on facts.** Replace the static line with the
   real outcome from `application_result`:
   - applied → list `application_result.applied_files` ("Files written: …").
   - activated-but-rejected → "Patch rejected; no files written. Reasons: …".
   - not activated → "No application stage ran (no approved proposal)."
2. **Required factual report fields** (structured sections, not prose):
   task id · current checklist item · files proposed/created/modified/skipped/
   rejected · validation commands run · validation status · exact blockers ·
   context packet id · acceptance-criteria coverage · item-retirement decision.
3. **Forbidden report statements** (add a test asserting they never appear when
   false):
   - "No application code was modified." when files were written.
   - "context was read" / nonzero context when the catalog is empty or import
     failed (cross-check `catalog.yaml` supported count).
   - any success line when final validation failed.

### Suggested approach

Build the report from the same structured results the packet uses
(`application_result`, `validation_result`, catalog status) — single source of
truth. The report becomes a *projection of facts*, mirroring the
"feed facts not prose" principle but for the human side. (Downstream flow scripts
grep some `factory_advance` summary lines — keep those exact tokens; change only
the report-writer body.)

### Tests

- Apply that writes `src/x.py` → report lists `src/x.py`, never says "No
  application code was modified".
- Rejected application → report says rejected + reasons, no write claim.
- Empty catalog → report does not claim context was read.
- Failed validation → no success line.

---

## 9D.7 — Fresh per-run debug logs

### Problem

`CRAZY_FACTORY_LOGFILE` is a single append-only file (the autopilot scripts set
one path). Across runs it accumulates, so `grep` surfaces **stale failures** and
the operator misreads old errors as current. (The debug log the user opened is
exactly this.)

### Change

Per-run log directory with a `latest` symlink:

```
logs/autopilot/<project>/<timestamp>/debug.log
logs/autopilot/<project>/<timestamp>/summary.md
logs/autopilot/<project>/latest -> <timestamp>
```

- The autopilot scripts compute `<timestamp>` once at start and export
  `CRAZY_FACTORY_LOGFILE` into that dir (timestamp passed in by the shell, since
  scripts own run identity — keep the engine deterministic).
- `summary.md` = the final structured outcome (exit status, checklist progress,
  blockers) — the shareable artifact.
- Optional: prune old run dirs beyond N.

### Why it matters for 9D

The DiagnosisPacket already excludes prior-session artifacts; per-run logs apply
the same freshness discipline to the human/debug surface. Together they remove
stale-data misinterpretation on both sides.

### Acceptance

- Reports never assert a write/context/success claim that the structured results
  contradict (tested).
- Each autopilot run writes to its own log dir; `latest` points at the current
  run. `ruff`+`mypy` clean; suite green.
