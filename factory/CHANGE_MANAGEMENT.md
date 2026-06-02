# Change Management

## Purpose

Changes to Crazy Factory documentation, governance, architecture, or future implementation must be intentional, reviewable, and traceable.

## Change Classes

| Class | Examples | Required handling |
| --- | --- | --- |
| Editorial | Typo, wording clarification, link repair | Review for meaning preservation |
| Operational | Workflow, role, template, or reporting change | Review affected contracts and update cross-references |
| Architectural | Boundary, component, memory, or integration change | Architecture proposal and decision record |
| Governance | Authority, approval, safety, or git rule change | Owner approval and decision record |
| Implementation | Future source or behavior change | Planned task, validation, review, and local commit |

## Required Record

Every non-editorial change should identify:

- reason for change
- affected documents or components
- risk impact
- required approval
- validation performed
- decision record when applicable

## Protected Meaning

No lower-level document may silently weaken [FACTORY_CONTRACT.md](FACTORY_CONTRACT.md). Governance changes require explicit owner approval.

