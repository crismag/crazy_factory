# Git Rules

## Purpose

Git operations must preserve owner control and repository history.

## Allowed Local Operations

- `status`
- `diff`
- `add`
- `commit`
- `log`

These operations remain subject to task scope and review. A local commit should contain only reviewed intended changes.

## Restricted Operations

The following require explicit owner approval:

- push
- merge
- branch deletion

## Forbidden Operations

- force push
- history rewrite
- destructive cleanup
- removal of unrelated owner changes
- any operation designed to bypass review or conceal repository state

See [../governance/ALLOWED_ACTIONS.md](../governance/ALLOWED_ACTIONS.md) and [../governance/APPROVAL_RULES.md](../governance/APPROVAL_RULES.md).

