# Escalation Rules

## Purpose

Escalation protects the owner from hidden risk and protects the factory from guessing beyond its authority.

## Escalate When

- approval is required
- a task cannot remain within scope
- a consequential architectural choice is unresolved
- repository state conflicts with safe progress
- validation is required but unavailable
- a critical risk cannot be mitigated
- a stall repeats without a meaningfully different next action
- external access or data transfer is proposed

## Escalation Format

Include:

- what is blocked
- evidence observed
- actions already attempted
- risk of proceeding
- smallest owner decision needed
- safe default while waiting

## Safe Default

When waiting for input, stop the affected work, preserve state, update memory, and avoid restricted actions.

