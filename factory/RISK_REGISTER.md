# Risk Register

## Purpose

This register tracks risks that could affect safety, quality, trust, or maintainability. Update it when a risk changes, a mitigation is validated, or a new risk appears.

| ID | Risk | Impact | Likelihood | Mitigation | Escalation trigger | Status |
| --- | --- | --- | --- | --- | --- | --- |
| R-001 | Autonomous scope creep | High | Medium | Bounded planned tasks, explicit exclusions, independent review | Task exceeds acceptance criteria | Open |
| R-002 | Destructive repository operation | Critical | Low | Allowed/restricted/forbidden git policy | Any need for history rewrite or destructive cleanup | Open |
| R-003 | Loss of context across sessions | High | Medium | Required memory updates and reports | Next session cannot resume without guessing | Open |
| R-004 | Unreliable local-model output | High | Medium | Evidence-based review, small tasks, validation gates | Repeated hallucination or ungrounded claims | Open |
| R-005 | Silent validation gaps | High | Medium | Report unavailable checks and residual risk | Completion claimed without evidence | Open |
| R-006 | External data exposure | Critical | Low | Local-first default and approval-gated integrations | Any external transfer not explicitly approved | Open |
| R-007 | Concurrent session conflict | High | Medium | Future session locking and recovery design | Overlapping active work detected | Planned |
| R-008 | Stalled repetitive activity | Medium | Medium | Stall detection and owner escalation | Same blocker or ineffective action repeats | Open |
| R-009 | Multi-project context leakage | Critical | Low | Future project isolation requirements | Data from one project appears in another context | Planned |
| R-010 | Oversight provider ambiguity | High | Medium | Explicit contracts for optional oversight adapters | External oversight planned without data and authority rules | Planned |

