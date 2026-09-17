#!/usr/bin/env python3
"""Phase 9D — deterministic acceptance checker.

"Done" must be evidence-based, not a model's say-so or a single green pytest. A
project is *accepted* only when, deterministically:

1. every declared required file exists (``missing_required`` empty),
2. no required source file is a stub (all-placeholder bodies),
3. every checklist item is complete (no open items, and the checklist is real),
4. the last whole-project validation passed (compile + tests + lint).

This is what lets the autopilot exit ``0`` only on a genuinely finished app, and
otherwise report a truthful "partial build" and exit non-zero. It runs no model
and writes nothing — pure inspection of artifacts + workbench reality.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from architecture import load_contract, missing_required
from completion import open_items, parse_checklist
from conversation_delta import open_deltas, refresh_delta_verification
from product_intent import (
    intent_capabilities,
    intent_revision,
    persist_acceptance,
    score_claims,
)
from proposal_applier import _is_placeholder_body
from workbench_growth import workbench_metrics


@dataclass(frozen=True)
class AcceptanceReport:
    """Deterministic acceptance verdict for a project.

    ``accepted`` is product-level: mechanical evidence plus product
    claims for the current intent revision. Mechanical-only success
    is ``mechanical_ok`` and must not be treated as COMPLETE.
    """

    accepted: bool
    required_present: bool
    no_stub_sources: bool
    checklist_complete: bool
    validation_passed: bool
    has_code: bool = True
    contracts_satisfied: bool = True
    mechanical_ok: bool = True
    product_ok: bool = True
    intent_revision: int = 0
    accepted_revision: int | None = None
    unsatisfied_product: list[str] = field(default_factory=list)
    open_delta_ids: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    stub_files: list[str] = field(default_factory=list)
    open_items: list[str] = field(default_factory=list)
    contract_gaps: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _is_test_path(path: str) -> bool:
    name = path.lower().rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py")


def _is_stub_file(path: Path) -> bool:
    """True when a file's functions are all placeholders (a stub module)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return False  # unreadable/syntax issues are caught by other gates
    funcs = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not funcs:
        return False  # a data/constant module is not a stub by this measure
    return all(_is_placeholder_body(f.body) for f in funcs)


def _interface_symbol(interface: str) -> str:
    """Extract the function/class name from a declared interface signature."""
    text = interface.strip()
    match = re.match(r"(?:async\s+)?def\s+([A-Za-z_]\w*)", text) or re.match(
        r"class\s+([A-Za-z_]\w*)", text
    )
    if match:
        return match.group(1)
    leading = re.match(r"([A-Za-z_]\w*)", text)
    return leading.group(1) if leading else ""


def _defined_symbols(path: Path) -> set[str]:
    """Top-level function/class names defined in a Python file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return set()
    return {
        node.name
        for node in tree.body
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
    }


def _contract_interface_gaps(app_path: str, context_root: str) -> list[str]:
    """9E ST9: enforce that each frozen file-contract's declared interfaces are
    actually defined in its target file — the contracts we generate must be met,
    not merely advisory."""
    contracts_dir = Path(context_root) / "file_contracts"
    if not contracts_dir.is_dir():
        return []
    base = Path(app_path)
    gaps: list[str] = []
    for spec_file in sorted(contracts_dir.glob("*.json")):
        try:
            spec = json.loads(spec_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        target = spec.get("file")
        interfaces = spec.get("interfaces") or []
        if not isinstance(target, str) or not isinstance(interfaces, list):
            continue
        target_path = base / target
        if not target_path.exists():
            continue  # absence is covered by the required-files gate
        defined = _defined_symbols(target_path)
        for interface in interfaces:
            name = _interface_symbol(str(interface))
            if name and name not in defined:
                gaps.append(f"contract {target}: missing interface `{name}`")
    return gaps


def interface_gaps_for_file(
    app_path: str, context_root: str, target_rel: str
) -> list[str]:
    """ST9 (per-item, Issue #35): interface gaps for ONE file's contract.

    Returns the interfaces a ``file_contracts`` spec declares for ``target_rel``
    but that are not defined in it. Empty when the file has no contract, does not
    exist (the required-files gate owns absence), or satisfies every interface.
    This lets per-item checklist retirement require acceptance evidence (the
    contracted behaviour exists), not just coherence-green.
    """
    contracts_dir = Path(context_root) / "file_contracts"
    if not contracts_dir.is_dir() or not target_rel:
        return []
    target_path = Path(app_path) / target_rel
    if not target_path.exists():
        return []
    defined = _defined_symbols(target_path)
    gaps: list[str] = []
    for spec_file in sorted(contracts_dir.glob("*.json")):
        try:
            spec = json.loads(spec_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if spec.get("file") != target_rel:
            continue
        for interface in spec.get("interfaces") or []:
            name = _interface_symbol(str(interface))
            if name and name not in defined:
                gaps.append(f"missing interface `{name}`")
    return gaps


def is_stub_source(app_path: str, target_rel: str) -> bool:
    """True when ``target_rel`` exists but is an all-placeholder stub module."""
    if not target_rel:
        return False
    path = Path(app_path) / target_rel
    return path.exists() and _is_stub_file(path)


def _resolved(value: object, root: Path) -> Path:
    """Join a repository-relative workbench path to ``root``.

    ``evaluate_acceptance`` must not depend on process CWD. Registry paths
    such as ``apps/demo`` are relative to the factory root, not to wherever
    the owner (or a unit test) happened to invoke the CLI.
    """
    path = Path(str(value))
    return path if path.is_absolute() else (root / path)


def evaluate_acceptance(
    project: dict[str, Any], root: Path
) -> AcceptanceReport:
    """Return the deterministic acceptance verdict for a project."""
    app = _resolved(project["app_path"], root)
    app_path = str(app)
    task_root = _resolved(project["task_root"], root)
    arch = load_contract(app_path) or {}

    # Issue #38 #6: a run cannot be ACCEPTED if the application is empty. A
    # contract-less project would otherwise pass vacuously; require real source
    # code to exist (paths resolve against root, not process CWD).
    has_code = workbench_metrics(app_path).source_files >= 1

    # 1. required files present
    missing = missing_required(app_path, arch) if arch else []
    required_present = not missing

    # 2. no required source file is a stub
    base = Path(app_path)
    required = [
        f
        for f in (arch.get("required_files") or [])
        if isinstance(f, str) and not _is_test_path(f)
    ]
    stub_files = [
        f for f in required if (base / f).exists() and _is_stub_file(base / f)
    ]
    no_stub_sources = not stub_files

    # 3. checklist complete (and real — an empty checklist is not "done")
    checklist_md = ""
    try:
        checklist_md = (task_root / "MASTER_CHECKLIST.md").read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeDecodeError):
        checklist_md = ""
    items = parse_checklist(checklist_md)
    open_now = [i.text for i in open_items(items)]
    checklist_complete = bool(items) and not open_now

    # 4. last whole-project validation passed
    validation_passed = False
    try:
        record = json.loads(
            (task_root / "validation_result.json").read_text(encoding="utf-8")
        )
        validation_passed = (
            isinstance(record, dict) and record.get("status") == "passed"
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        validation_passed = False

    # 5. the file-contracts we generated are met (declared interfaces present)
    context_root = str(
        _resolved(
            project.get("context_root") or (app / "factory_context"),
            root,
        )
    )
    contract_gaps = _contract_interface_gaps(app_path, context_root)
    contracts_satisfied = not contract_gaps

    reasons: list[str] = []
    if not has_code:
        reasons.append("application has no real source files (empty project)")
    if not required_present:
        reasons.append(f"missing required files: {', '.join(missing)}")
    if not no_stub_sources:
        reasons.append(
            f"stub (placeholder) source files: {', '.join(stub_files)}"
        )
    if not checklist_complete:
        if not items:
            reasons.append("no checklist (project goal not decomposed)")
        else:
            reasons.append(f"{len(open_now)} checklist item(s) still open")
    if not validation_passed:
        reasons.append("last whole-project validation did not pass")
    if not contracts_satisfied:
        reasons.append(
            f"unmet file-contract interfaces: {', '.join(contract_gaps)}"
        )

    mechanical_ok = (
        has_code
        and required_present
        and no_stub_sources
        and checklist_complete
        and validation_passed
        and contracts_satisfied
    )

    scores = score_claims(project, root)
    unsatisfied_ids = {s.cap.id for s in scores if not s.ok}
    refresh_delta_verification(project, root, unsatisfied_ids=unsatisfied_ids)
    product_gaps = [s.cap for s in scores if not s.ok]
    delta_open = open_deltas(project, root)
    rev = intent_revision(project, root)
    claims = intent_capabilities(project, root)
    # No compiled claims and no open deltas: vacuous product_ok so
    # pre-L0 workbenches (and _make_accepted fixtures) still complete.
    product_ok = not product_gaps and not delta_open
    if claims and product_gaps:
        reasons.append(
            "product claims unsatisfied: "
            + ", ".join(c.id for c in product_gaps[:6])
        )
    if delta_open:
        reasons.append(
            "open owner deltas: "
            + ", ".join(str(d.get("id") or "?") for d in delta_open[:6])
        )

    accepted = mechanical_ok and product_ok
    accepted_rev = rev if accepted and rev else None
    persist_acceptance(
        project,
        root,
        {
            "intent_revision": rev,
            "accepted_revision": accepted_rev,
            "implementation_revision": rev if mechanical_ok else None,
            "stale": not product_ok,
            "mechanical_ok": mechanical_ok,
            "product_ok": product_ok,
            "accepted": accepted,
            "unsatisfied": [c.id for c in product_gaps],
            "open_deltas": [str(d.get("id") or "") for d in delta_open],
            "evidence": [
                {
                    "id": s.cap.id,
                    "ok": s.ok,
                    "kind": s.kind,
                    "detail": s.detail,
                }
                for s in scores
            ],
        },
    )

    return AcceptanceReport(
        accepted=accepted,
        required_present=required_present,
        no_stub_sources=no_stub_sources,
        checklist_complete=checklist_complete,
        validation_passed=validation_passed,
        has_code=has_code,
        contracts_satisfied=contracts_satisfied,
        mechanical_ok=mechanical_ok,
        product_ok=product_ok,
        intent_revision=rev,
        accepted_revision=accepted_rev,
        unsatisfied_product=[c.claim for c in product_gaps],
        open_delta_ids=[str(d.get("id") or "") for d in delta_open],
        missing_files=missing,
        stub_files=stub_files,
        open_items=open_now,
        contract_gaps=contract_gaps,
        reasons=reasons,
    )


def render_acceptance(report: AcceptanceReport) -> str:
    """Render a short human-readable acceptance report."""
    mark = "✓" if report.accepted else "✗"
    lines = [
        f"Acceptance: {mark} {'ACCEPTED' if report.accepted else 'NOT YET'}"
    ]
    checks = [
        ("real code exists", report.has_code),
        ("required files present", report.required_present),
        ("no stub source files", report.no_stub_sources),
        ("checklist complete", report.checklist_complete),
        ("validation passed", report.validation_passed),
        ("file-contracts satisfied", report.contracts_satisfied),
        ("mechanical evidence", report.mechanical_ok),
        ("product claims satisfied", report.product_ok),
    ]
    lines.extend(f"  [{'x' if ok else ' '}] {label}" for label, ok in checks)
    if report.reasons:
        lines.append("Gaps:")
        lines.extend(f"  - {r}" for r in report.reasons)
    return "\n".join(lines)
