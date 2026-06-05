#!/usr/bin/env python3
"""Phase 9D — deterministic run-quality metrics for a project.

A model-free snapshot assembled from a project's artifacts + acceptance verdict,
so the effect of 9D (and future changes) is measurable rather than anecdotal.
Capture a baseline before a change, re-run after, and compare. Reads only
structured artifacts; runs nothing and writes nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from acceptance_check import evaluate_acceptance
from completion import open_items, parse_checklist


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def collect_metrics(project: dict[str, Any], root: Path) -> dict[str, Any]:
    """Return a deterministic quality snapshot for one project."""
    task_root = Path(str(project["task_root"]))

    items = parse_checklist(
        (task_root / "MASTER_CHECKLIST.md").read_text(encoding="utf-8")
        if (task_root / "MASTER_CHECKLIST.md").exists()
        else ""
    )
    open_count = len(open_items(items))
    done_count = len(items) - open_count
    complete_pct = round(100 * done_count / len(items)) if items else 0

    validation = _read_json(task_root / "validation_result.json") or {}
    checks = validation.get("checks") or []
    failing = [
        c
        for c in checks
        if isinstance(c, dict)
        and c.get("status") in {"failed", "blocked", "error"}
    ]

    evidence = _read_json(task_root / "checklist_evidence.json") or {}
    evidence_records = (
        len(evidence.get("items", [])) if isinstance(evidence, dict) else 0
    )

    recovery = _read_json(task_root / "recovery_decision.json") or {}
    last_recovery = (
        recovery.get("decision") if isinstance(recovery, dict) else None
    )

    report = evaluate_acceptance(project, root)

    return {
        "project": str(project.get("name") or project["app_path"]),
        "accepted": report.accepted,
        "acceptance": {
            "required_present": report.required_present,
            "no_stub_sources": report.no_stub_sources,
            "checklist_complete": report.checklist_complete,
            "validation_passed": report.validation_passed,
            "gaps": report.reasons,
        },
        "checklist": {
            "total": len(items),
            "done": done_count,
            "open": open_count,
            "complete_pct": complete_pct,
        },
        "validation": {
            "status": validation.get("status", "not_run"),
            "checks": len(checks),
            "failing": len(failing),
        },
        "stub_source_files": report.stub_files,
        "missing_required_files": report.missing_files,
        "evidence_records": evidence_records,
        "last_recovery_decision": last_recovery,
    }


def render_metrics_md(metrics: dict[str, Any]) -> str:
    """Render metrics as a compact Markdown block."""
    cl = metrics["checklist"]
    val = metrics["validation"]
    lines = [
        f"# Run metrics — {metrics['project']}",
        "",
        f"- Accepted: {'yes' if metrics['accepted'] else 'no'}",
        f"- Checklist: {cl['done']}/{cl['total']} done "
        f"({cl['complete_pct']}%), {cl['open']} open",
        f"- Validation: {val['status']} "
        f"({val['failing']}/{val['checks']} checks failing)",
        f"- Stub source files: {len(metrics['stub_source_files'])}",
        f"- Missing required files: {len(metrics['missing_required_files'])}",
        f"- Acceptance-evidence records: {metrics['evidence_records']}",
        f"- Last recovery decision: {metrics['last_recovery_decision'] or '—'}",
    ]
    if metrics["acceptance"]["gaps"]:
        lines.append("- Gaps:")
        lines.extend(f"  - {g}" for g in metrics["acceptance"]["gaps"])
    return "\n".join(lines)
