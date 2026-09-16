# Technical Debt

## Current State

Implementation exists. Debt is concentrated in pipeline thickness and
doc drift, not in "we have not started."

## Debt To Track

| ID | Item | Impact | Suggested review point |
| --- | --- | --- | --- |
| TD-101 | `factory_advance.py` still always runs the full linear beat | Product objectives cannot steer work yet | P2 |
| TD-108 | Validation allowlist has no install/build/start | Mission can loop but cannot launch an app | P1 |
| TD-109 | In-process Coder is the only implementer | No live model → planning fallbacks, no product | P4 |
| TD-102 | Three recovery vocabularies (remediation, manager, router) | Duplicate control paths | Slice D |
| TD-103 | `architecture.json` vs seed vs checklist as competing truth | Workers get compressed intent | Slice C |
| TD-104 | `app/` vs `src/` scaffold mismatch | False contract conflicts | MISC-1 |
| TD-105 | Phase 9D/9E packages vs CF 2.0 plan of record | Prompt/context pollution if both ingested | prompt curation |
| TD-106 | Lint autofix looks up bare `ruff` on PATH | Tests fail in minimal images | packaging |
| TD-107 | Test Builder plans ignored when architecture.json exists | Dead worker output | later verification slice |

Bootstrap-era TD-001…TD-004 (storage, locking, oversight unspecified)
are superseded: those subsystems now exist in some form.
