# Flow Integration

## Explicit Command

Add:

```bash
crazy-admin recover <project>
```

Purpose:

- read the latest failure/rejection/acceptance gap,
- run deterministic recovery rules,
- ask the LLM recovery planner only when deterministic rules do not apply or
  escalation is needed,
- validate the decision,
- apply allowed runtime/artifact actions,
- write recovery reports,
- update `resume_from`.

Useful options later:

```bash
crazy-admin recover <project> --stage application
crazy-admin recover <project> --reason application_rejected
crazy-admin recover <project> --dry-run
```

## Embedded Recovery In `advance`

`advance` should call recovery automatically when safe and owner-enabled:

- after `application_status == rejected`,
- after validation failed,
- after seed acceptance failed,
- after self-rejection,
- after repeated contract/proposal rejections.

In the first cut, embed only application rejection, validation failure, and
self-rejection. Acceptance recovery should wait until the acceptance gate is
wired and producing structured gaps.

This should not require the shell script to run special logic. The script can
call `advance`; the factory decides whether the next internal action is normal
planning, remediation, recovery, or parking.

## Future High-Level Build Command

After explicit recovery and embedded recovery are stable, add:

```bash
crazy-admin build <project> --until accepted --max-steps 20
```

This command should be thin orchestration over factory-native primitives:

- advance,
- recover,
- validate,
- acceptance check,
- status/report.

It should not duplicate recovery intelligence in shell.

## Task-Board Example

Observed failure:

```text
Application rejected:
- Implementation patch does not include or declare validation tests.
```

Expected recovery decision:

```json
{
  "decision": "revise_proposal",
  "target_stage": "coder",
  "actions": [
    {
      "type": "clear_approval",
      "path": "factory_tasks/approved_proposal.json",
      "detail": "stale approval targets a proposal that cannot pass application"
    },
    {
      "type": "request_new_proposal",
      "detail": "new proposal must include source and corresponding tests"
    }
  ]
}
```

Expected next advance:

- coder receives application rejection reasons,
- coder proposes source plus tests,
- application gate validates the patch,
- validation runs,
- checklist progresses only if the slice satisfies gates.

This example should be deterministic and model-free in the first cut. It does
not need LLM recovery because the rejection reason directly maps to the fix.
