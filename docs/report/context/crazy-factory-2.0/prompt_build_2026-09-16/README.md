# Prompt-build evidence (2026-09-16)

Live no-key run of `--prompt "build a habit tracker"` then follow-up
`"add a streak counter and a weekly view"`.

Parent analysis:
[POST_L0_CAPABILITY_ASSESSMENT.md](../POST_L0_CAPABILITY_ASSESSMENT.md).

| File | What it shows |
| --- | --- |
| `summary.json` | Outcomes, beats, HTTP, seed-unchanged, delta count |
| `docs/seed.md` | Fallback compiled Goal (generic CRUD success) |
| `architecture.json` | `stdlib-web`, port 8765, title “habit tracker” |
| `factory_reports/MISSION_TRACE.md` | 1 beat to COMPLETE |
| `factory_tasks/executor_result.json` | `stdlib_web` wrote 9 files; inner contract rejected |
| `factory_tasks/preview.json` | `http://127.0.0.1:8765/` HTTP 200 |
| `factory_tasks/judgment.json` | COMPLETE / accepted / runtime running |
| `factory_tasks/deltas.jsonl` | Follow-up prompt persisted |
| `preview_first_prompt.html` | Generic CRUD, no streak |
| `preview_after_delta.html` | Same CRUD plus “Requested changes” banner |
| `inspect.json` | `demo_ready: true` despite generic UI |
