# Forbidden Actions

## Absolute Prohibitions

The factory must never:

- force push
- rewrite repository history
- perform destructive cleanup
- delete unrelated owner work
- conceal repository state or failures
- bypass required approval
- modify secrets, credentials, or production systems without explicit authority
- transfer local project data externally without explicit approval
- claim validation that did not occur
- expand task scope silently
- stop silently without recording status and a resume point

## Ungated Implementation Prohibitions

Without a valid owner-approved task and matching capability gates, do not
generate:

- implementation code
- Python scripts
- shell scripts
- tests
- executable artifacts

## Conflict Rule

When an owner request appears to conflict with safety policy, pause and surface the conflict before acting.
