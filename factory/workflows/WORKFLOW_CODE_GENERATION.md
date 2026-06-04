# Workflow: Code Generation

## Status

This workflow applies when an owner-approved planned task activates the Coder.
It remains gated by contract validation, owner authorization, proposal approval,
and the current project capability switches.

## Purpose

Implement one approved planned task with minimal scope.

## Required Inputs

- approved planned task
- relevant architecture and decisions
- repository state
- coding and safety rules

## Procedure

1. Read acceptance criteria and exclusions.
2. Inspect relevant existing patterns.
3. Identify the smallest necessary change set.
4. Implement only the approved scope.
5. Record changed files, assumptions, and deviations.
6. Stop when new architecture, broader scope, or restricted actions are needed.
7. Hand off to validation.

## Outputs

- bounded implementation change set
- implementation notes
- validation handoff

## Escalation

Return to planning if implementation cannot remain within the approved task.
