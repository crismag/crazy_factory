# Workflow: Commit

## Purpose

Create a traceable local checkpoint for reviewed work.

## Preconditions

- task acceptance criteria are addressed
- required validation is complete or gaps are disclosed and approved
- review has no unresolved blocking finding
- staged scope contains only intended work

## Procedure

1. Inspect repository status and diff.
2. Confirm changed files belong to the reviewed task.
3. Stage only intended files.
4. Create a meaningful local commit message referencing the task.
5. Record the commit reference in the session report.

## Restrictions

Push, merge, and branch deletion require explicit owner approval. Force push, history rewrite, and destructive cleanup are forbidden.

## Failure Handling

Stop when unrelated changes cannot be separated safely or a restricted action appears necessary.

