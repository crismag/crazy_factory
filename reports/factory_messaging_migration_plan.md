# Factory Messaging Migration Plan

Sweep of `scripts/*.py` output usages, classified for migration to the
`factory_messaging` layer.

## Classification key

| Class | API | When |
|---|---|---|
| NORMAL_INFO | `iprint()` | ordinary status |
| NORMAL_WARNING | `wprint()` | recoverable warning |
| NORMAL_ERROR | `eprint()` | error (stderr) |
| NORMAL_DEBUG | `dprint()` | debug detail |
| NORMAL_COMMAND | `cprint()` | command / path / execution detail |
| NORMAL_NOTICE | `nprint()` | notice / guidance / narrative |
| NORMAL_SUCCESS | `sprint()` | success confirmation |
| STRUCTURED | `json_print()` / `table_print()` / `key_value_print()` / `section_print()` | structured human data |
| SPECIAL_BANNER | `post_message()` | emphasized attention checkpoint only |
| KEEP_RAW | `print()` | machine-readable payload / test-asserted contract / the emitter itself |

**`post_message()` is reserved** for attention banners (fatal, hard rejection,
security/path block, contract rejected, validation pass/fail checkpoint, owner
action required) — never ordinary progress.

## Status: executed (content + API sweep done)

This plan has been carried out. The sweep improved **message content** (context,
reason, impact, next action, debuggability — not just presentation) and routed
each emitted message through the right `factory_messaging` helper:

- `crazy_admin.py` — owner-capability confirmations now state the *consequence*
  of the switch (`_CAPABILITY_IMPACT`); task/proposal confirmations name the
  project and what it unblocks; `--all` sweep, skips, and CLI errors carry
  reason + continuation; `status` report kept verbatim (shell-asserted payload),
  blocker `None` → "(none — not blocked)".
- `mission_loop.py` — no-target / missing-workbench / unapproved-location /
  lock-contention / end-of-beat messages now carry project, reason, impact, fix.
- `context_growth.py` — seed/promote/grow confirmations name the project, the
  next command, and the safety guarantee; stale "Active project is now" wording
  removed (no global active project).
- `factory_advance.py` — entry-guard refusals routed to `eprint`/`wprint` with
  reason + fix; bare phase headers (`contract`/`coder`/`application`/
  `validation`) now describe what the phase does and for which project.
- `project_paths.py` — config-fallback warning explains the impact (runs on
  engine defaults, not project settings).
- `git_guard.py` — status header → `section_print`, body → `cprint`, policy →
  `nprint` with the "owner's to run" rationale.

`scripts/factory_log.py` (the back-compat shim) and `tests/test_factory_log.py`
were **removed**; `factory_advance.py` and `crazy_admin.py` now import
`factory_messaging as msg` directly. No `factory_log` references remain.

`watcher.py` activity dump and `report_writer.py` blog body stay `KEEP_RAW`
(they are payloads the user asked to read, not factory messages).

## Sweep totals (pre-execution inventory)

- 77 `print()` sites across 9 files. **No** `logging`, `sys.stdout.write`, or
  `sys.stderr.write` usage.

| File | print sites | dominant class |
|---|---:|---|
| crazy_admin.py | 46 | CLI results → NORMAL_* + STRUCTURED |
| mission_loop.py | 9 | NORMAL_INFO/NOTICE + one SPECIAL_BANNER candidate |
| context_growth.py | 9 | NORMAL_SUCCESS/INFO + 1 NORMAL_ERROR |
| git_guard.py | 5 | STRUCTURED header + KEEP_RAW body |
| factory_advance.py | 4 | KEEP_RAW (test-asserted entry guards) + 1 banner candidate |
| watcher.py | 1 | KEEP_RAW (payload) |
| report_writer.py | 1 | KEEP_RAW (blog payload) |
| project_paths.py | 1 | NORMAL_WARNING |
| factory_messaging.py | 1 | KEEP_RAW (the emitter) |

---

## scripts/crazy_admin.py (CLI command output)

These are user-facing command results. Most are simple lines; the `status`
display is structured. Low risk, but note: migrating to `iprint`/etc means
`-q` (verbosity 0) silences them — desired. None are asserted by the shell flow
scripts (those grep `factory_advance` output, not crazy-admin status).

```
Area: _print_status header + paths/contract/proposal/capabilities (lines 649-683)
Current Output: print("Active project: ..."); print("  apply: ..."); section labels
Recommended API: section_print("Status") + key_value_print({...}) ; capabilities via table_print/key_value
Reason: structured human data — a status report reads better as titled key/value blocks
Risk: low

Area: status "none"/select guidance (649-650)
Current Output: print("Active project: (none)"); print("Select one: ...")
Recommended API: nprint(...)
Reason: guidance/notice
Risk: low

Area: success confirmations (568 migrated, 866 "State:", 874/876 path overrides,
      968 "Task authorized", 973 "revoked", 987 "approval cleared", 993 "X = true")
Current Output: print("Task authorized.\n\nNext: ...") etc.
Recommended API: sprint(<confirmation>) + nprint(<next-step hint>)
Reason: success line + a follow-up guidance line; the "Next:" hint is a notice
Risk: low

Area: created/migrated/skipped notices (574/579/581/583 migrate-runtime, 885/899/905 add-context,
      923 "No registered projects", 930 "Skipping '{pid}'")
Current Output: print("  config: materialized ..."), print("Skipped (secret-like): ...")
Recommended API: iprint(...) ; "Skipping"/"No registered projects" -> wprint(...)
Reason: ordinary info; skip/empty conditions are warnings
Risk: low

Area: --all sweep header (926)
Current Output: print(f"\n=== advance: {pid} ===")
Recommended API: section_print(f"advance: {pid}")
Reason: a per-project section divider
Risk: low

Area: CLI top-level error (845)
Current Output: print(f"crazy-admin error: {exc}", file=sys.stderr)
Recommended API: eprint(f"{exc}")  (or post_message for fatal aborts)
Reason: error already routed to stderr; eprint standardizes it
Risk: low
```

---

## scripts/mission_loop.py

```
Area: no-project / not-usable / missing workbench (224, 228, 234)
Current Output: print(f"No project to run: {exc}") + guidance
Recommended API: eprint(<reason>) + nprint(<guidance>)
Reason: error + guidance
Risk: low

Area: lock contention (268, 269)
Current Output: print("...action=locked"); print("Another mission run in progress...")
Recommended API: iprint("mission iteration: action=locked") + wprint("another run in progress; skipping")
Reason: status + a warning
Risk: low

Area: iteration status (312, 313, 314, 317)
Current Output: print(f"...action={action}"); print(f"Active project: {project_name}")
Recommended API: iprint(...) or key_value_print({"action":..,"project":..,"task":..})
Reason: per-beat status; key/value reads cleanly
Risk: low

Area: stalled/abort condition (within the stalled branch)
Current Output: print(...) describing a stall
Recommended API: SPECIAL_BANNER post_message("ACTION_REQUIRED", "Mission stalled", reason=..., action=...)
Reason: a stall is an attention checkpoint needing owner action
Risk: medium (confirm exact wording; keep machine-readable "action=stalled" line as KEEP_RAW if a watcher greps it)
```

---

## scripts/context_growth.py

```
Area: seed / promote confirmations (678, 679, 683, 685, 689)
Current Output: print(f"Seeded project '{...}'."); print(f"Promoted '{...}' ...")
Recommended API: sprint(<confirmation>) + iprint(<detail>)
Reason: success + info
Risk: low

Area: "Active project is now: {id}" (684)
Current Output: print(f"Active project is now: {summary['project_id']}")
Recommended API: iprint(...) — AND fix stale wording (no global active project anymore)
Reason: ordinary info; also a content bug to correct separately
Risk: low

Area: post-promote guidance (700, 704)
Current Output: print(<next steps>)
Recommended API: nprint(...)
Reason: guidance
Risk: low

Area: top-level error (710)
Current Output: print(f"context_growth error: {exc}", file=sys.stderr)
Recommended API: eprint(f"{exc}")
Reason: error to stderr
Risk: low
```

---

## scripts/git_guard.py (status command)

```
Area: status header (88, 89, 91)
Current Output: print("Crazy Factory status"); print("===================="); print()
Recommended API: section_print("Crazy Factory status")  (or banner_print)
Reason: a manual banner -> use the structured helper
Risk: low

Area: git status body (90)
Current Output: print(status())
Recommended API: cprint(status())  OR  KEEP_RAW
Reason: command/VCS output; cprint tags it as console output, raw keeps it verbatim
Risk: low

Area: trailing guidance (92)
Current Output: print(<hint>)
Recommended API: nprint(...)
Reason: guidance
Risk: low
```

---

## scripts/factory_advance.py

The run stream + summary are already migrated to `factory_messaging` (via the
`flog` shim). Four entry-guard prints remain:

```
Area: no-target notice (173, 174)
Current Output: print("No project to advance: ..."); print(<how to target>)
Recommended API: KEEP_RAW for the first line (asserted by tests) OR eprint + nprint with test update
Reason: test_app_builder asserts "No project to advance" on stdout
Risk: medium (migrating to stderr/eprint breaks the stdout assertion — update the test if migrating)

Area: workbench-missing (204)
Current Output: print(f"Workbench for '{...}' is missing ...")
Recommended API: eprint(...)
Reason: an error condition
Risk: low

Area: TARGET_PATH_UNSUPPORTED (213)
Current Output: print(f"TARGET_PATH_UNSUPPORTED: ... unapproved location ...")
Recommended API: SPECIAL_BANNER post_message("SECURITY_BLOCK"/"ACTION_REQUIRED", "Unapproved build location", reason=..., action=...)
Reason: a refusal to build outside approved roots — an attention/security checkpoint
Risk: medium (test_app_builder asserts "TARGET_PATH_UNSUPPORTED" on stdout; banner goes to stderr — update the test, or keep the token in the banner title and capture stderr)
```

---

## scripts/watcher.py

```
Area: activity summary output (85)
Current Output: print(activity_summary().rstrip())
Recommended API: KEEP_RAW
Reason: the summary is the payload the user asked to read, not a factory message
Risk: none
```

## scripts/report_writer.py  (DONE)

```
Area: no-project / no-blog (migrated)
Current Output: was print(...) -> now wprint(...) / nprint(...)
Recommended API: wprint / nprint  (applied)
Reason: message vs guidance
Risk: none

Area: blog content (579)
Current Output: print(safe_read_text(blog, root).rstrip())
Recommended API: KEEP_RAW
Reason: the blog content is the payload
Risk: none
```

## scripts/project_paths.py

```
Area: missing project config warning (150)
Current Output: print("WARNING: no project config at ...; using the default template ...")
Recommended API: wprint("no project config at ...; using the default template ...")
Reason: a warning (drop the manual "WARNING:" prefix — the tag supplies it)
Risk: low
```

## scripts/factory_messaging.py

```
Area: the emitter (_write -> print)
Current Output: print(line, file=stream)
Recommended API: KEEP_RAW
Reason: this IS the implementation that all helpers route through
Risk: none
```

---

## Execution order (suggested)

1. **Low-risk, high-value first**: `crazy_admin.py` status block → `section_print`/`key_value_print`; confirmations → `sprint`/`iprint`; CLI error → `eprint`. `project_paths.py` warning → `wprint`. `context_growth.py` confirmations/errors.
2. **mission_loop.py**: status → `iprint`/`key_value_print`; lock → `wprint`; stall → `post_message("ACTION_REQUIRED")`.
3. **git_guard.py**: header → `section_print`; body decision (cprint vs raw).
4. **Banners last (need wording + test review)**: `factory_advance` TARGET → `post_message`; `mission_loop` stall → `post_message`. Update the two `test_app_builder` stdout assertions if those entry-guard lines move to stderr/banners.

## Notes / out of scope

- Do **not** migrate the `factory_advance` end-of-advance summary lines away from
  verbatim `report()` — downstream flow scripts (`tests/generation_flow.sh`) grep
  their exact text.
- `context_growth.py` "Active project is now" wording is stale (no global active
  project) — a separate content fix, flagged here.
- Banners (`post_message`) should remain rare: only the few genuine attention
  checkpoints above, so the console doesn't become "a dramatic factory siren".
