#!/usr/bin/env python3
"""Product intelligence kernel for Crazy Factory 2.0 (Slice A).

This module is the missing center of gravity: compare the *intended*
product (seed / architecture) with the *observable* workbench, derive
module maturity from evidence, score independent readiness dimensions,
and emit Director objectives. It does not call a model, does not apply
patches, and does not replace the execution kernel.

Python is the rail. Evidence comes from artifacts the kernel already
owns (seed, architecture.json, checklist, workbench files, acceptance,
validation). Percentages are never invented; unmeasured dimensions are
marked ``unknown``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from acceptance_check import evaluate_acceptance, is_stub_source
from architecture import load_contract, missing_required
from completion import open_items, parse_checklist
from project_contract import contract_from_seed, parse_seed
from workbench_growth import workbench_metrics

PRODUCT_MODEL_FILE = "product_model.json"
CONVERGENCE_FILE = "convergence.json"
OBJECTIVES_FILE = "objectives.json"

MATURITY_ORDER: tuple[str, ...] = (
    "UNKNOWN",
    "DISCOVERED",
    "SPECIFIED",
    "DESIGNED",
    "CONTRACTED",
    "PLANNED",
    "IMPLEMENTED",
    "VERIFIED",
    "INTEGRATED",
    "DEMO_READY",
)

# Nested module loop: a module is closed only when verified (or later)
# and it has no remaining gaps. Mixed VERIFIED+stub still needs work.
_CLOSED_MATURITY = frozenset({"INTEGRATED", "DEMO_READY"})

DIMENSIONS: tuple[str, ...] = (
    "product_completeness",
    "requirements_coverage",
    "architecture_coherence",
    "contract_completeness",
    "implementation_completeness",
    "automated_validation",
    "integration_completeness",
    "demo_readiness",
    "documentation_readiness",
)

_PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "describe what",
    "describe what 'done' looks like",
    "none yet",
)
_CHECKLIST = "MASTER_CHECKLIST.md"
_VALIDATION = "validation_result.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_path(value: object, root: Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (root / path)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _is_placeholder(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return True
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


def _is_test_path(path: str) -> bool:
    name = Path(path).name.lower()
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "tests" in Path(path).parts
    )


def _module_id(path: str) -> str:
    name = Path(path).stem
    if name.startswith("test_"):
        name = name[5:]
    elif name.endswith("_test"):
        name = name[:-5]
    slug = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").lower()
    return slug or "module"


def _workbench_py_files(app: Path) -> list[str]:
    skip = {
        "config",
        "state",
        "factory_state",
        "factory_reports",
        "factory_tasks",
        "factory_context",
        "context",
        "docs",
        ".git",
        "__pycache__",
    }
    out: list[str] = []
    if not app.is_dir():
        return out
    for path in sorted(app.rglob("*.py")):
        rel = path.relative_to(app)
        if any(part in skip for part in rel.parts):
            continue
        if rel.name == ".gitkeep":
            continue
        out.append(str(rel).replace("\\", "/"))
    return out


@dataclass
class Module:
    """One product capability / file-group treated as a convergence unit."""

    id: str
    name: str
    paths: list[str] = field(default_factory=list)
    test_paths: list[str] = field(default_factory=list)
    behaviors: list[str] = field(default_factory=list)
    maturity: str = "UNKNOWN"
    evidence: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


@dataclass
class ProductModel:
    """Intended product plus the derived module graph."""

    project_id: str
    intended_goal: str
    constraints: list[str]
    success_criteria: list[str]
    placeholder_intent: bool
    modules: list[Module]
    source: str
    assessed_at: str


@dataclass
class Dimension:
    """One independent readiness dimension with evidence, not a score."""

    name: str
    status: str  # missing | partial | ready | unknown
    evidence: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


@dataclass
class Objective:
    """Director work unit: a gap to close, not a coding task."""

    id: str
    title: str
    gap: str
    why: str
    required_roles: list[str]
    required_capabilities: list[str]
    expected_evidence: list[str]
    blocking: bool
    related_modules: list[str] = field(default_factory=list)


@dataclass
class ConvergenceReport:
    """Product-level comparison of intended vs observable software."""

    project_id: str
    demo_ready: bool
    blocking_question: str
    dimensions: list[Dimension]
    material_gaps: list[str]
    assessed_at: str
    source_files: int = 0
    test_files: int = 0
    lines_of_code: int = 0


@dataclass
class Assessment:
    """Full inspect/assess result."""

    model: ProductModel
    convergence: ConvergenceReport
    objectives: list[Objective]


def _load_seed_text(app: Path, project: dict[str, Any]) -> str:
    seed_rel = str(project.get("seed_file") or "docs/seed.md")
    seed = _read(app / seed_rel)
    if seed.strip() and not _is_placeholder(seed):
        return seed
    goal = _read(app / "factory_context" / "PROJECT_GOAL.md")
    return seed if seed.strip() else goal


def _group_modules(
    required: list[str], extra: list[str], behaviors: list[str]
) -> list[Module]:
    groups: dict[str, Module] = {}

    def bucket(path: str, *, required_hit: bool) -> Module:
        mid = _module_id(path)
        mod = groups.get(mid)
        if mod is None:
            mod = Module(id=mid, name=mid.replace("_", " "))
            groups[mid] = mod
        if _is_test_path(path):
            if path not in mod.test_paths:
                mod.test_paths.append(path)
        elif path not in mod.paths:
            mod.paths.append(path)
        if required_hit:
            mod.evidence.append(f"declared in architecture: {path}")
        else:
            mod.evidence.append(f"observed on disk: {path}")
        return mod

    for path in required:
        bucket(path, required_hit=True)
    declared = set(required)
    for path in extra:
        if path not in declared:
            bucket(path, required_hit=False)
    if not groups and behaviors:
        groups["product"] = Module(
            id="product",
            name="product",
            behaviors=list(behaviors),
            evidence=["derived from seed success criteria"],
        )
    elif behaviors and len(groups) == 1:
        only = next(iter(groups.values()))
        only.behaviors = list(behaviors)
    return list(groups.values())


def _derive_maturity(mod: Module, app: Path, planned: set[str]) -> None:
    existing = [p for p in mod.paths if (app / p).is_file()]
    tests = [p for p in mod.test_paths if (app / p).is_file()]
    stubs = [p for p in existing if is_stub_source(str(app), p)]
    real = [p for p in existing if p not in stubs]
    mentioned = {Path(p).name.lower() for p in mod.paths + mod.test_paths}
    in_plan = bool(planned & mentioned) or any(
        mod.id.replace("_", " ") in item or mod.id in item for item in planned
    )

    if not mod.paths and not mod.behaviors:
        mod.maturity = "UNKNOWN"
        mod.gaps.append("module has no paths or behaviors")
        return
    if not mod.paths:
        mod.maturity = "DISCOVERED"
        mod.gaps.append("no implementation path identified yet")
        return
    if not existing:
        if in_plan:
            mod.maturity = "PLANNED"
        elif mod.behaviors:
            mod.maturity = "SPECIFIED"
        else:
            mod.maturity = "CONTRACTED"
        mod.gaps.append("declared files are missing: " + ", ".join(mod.paths))
        return
    if stubs and not real:
        mod.maturity = "IMPLEMENTED"
        mod.gaps.append("source is a stub: " + ", ".join(stubs))
        return
    if real and tests:
        mod.maturity = "VERIFIED"
        mod.evidence.append("source and tests exist on disk")
        if stubs:
            mod.gaps.append("mixed with stubs: " + ", ".join(stubs))
        return
    mod.maturity = "IMPLEMENTED"
    mod.evidence.append("real source exists: " + ", ".join(real or existing))
    if not tests:
        mod.gaps.append("no tests on disk for this module")


def module_is_open(mod: Module) -> bool:
    """True when the nested module loop should still sit on this module."""
    if mod.maturity in _CLOSED_MATURITY and not mod.gaps:
        return False
    if mod.maturity == "VERIFIED" and not mod.gaps:
        return False
    return True


def select_focus_module(model: ProductModel) -> Module | None:
    """First incomplete module in declaration order.

    Nested module loop: finish this module (paths, non-stub body, tests)
    before opening the next. Product-level gaps (placeholder seed, no
    code, missing architecture) still outrank this selection in EXECUTE.
    """
    for mod in model.modules:
        if module_is_open(mod):
            return mod
    return None


def focus_module_payload(mod: Module | None) -> dict[str, Any] | None:
    """JSON-ready snapshot of the module currently in the inner loop."""
    if mod is None:
        return None
    return {
        "id": mod.id,
        "name": mod.name,
        "maturity": mod.maturity,
        "gaps": list(mod.gaps),
        "paths": list(mod.paths),
        "test_paths": list(mod.test_paths),
        "open": module_is_open(mod),
    }


def build_product_model(project: dict[str, Any], root: Path) -> ProductModel:
    """Build the intended+observable product model (no I/O besides reads)."""
    app = _as_path(project["app_path"], root)
    pid = str(project.get("name") or app.name)
    seed_text = _load_seed_text(app, project)
    seed = parse_seed(seed_text) if seed_text.strip() else None
    goal = (seed.goal if seed else "").strip()
    constraints = list(seed.constraints) if seed else []
    success = list(seed.success) if seed else []
    placeholder = _is_placeholder(goal) and _is_placeholder(" ".join(success))
    contract = load_contract(str(app)) or {}
    required = [
        str(p)
        for p in (contract.get("required_files") or [])
        if isinstance(p, str)
    ]
    extra = _workbench_py_files(app)
    if seed and not success:
        derived = contract_from_seed(seed, required_tree=required)
        success = list(derived.required_behaviors)
    modules = _group_modules(required, extra, success)
    task_root = _as_path(project["task_root"], root)
    checklist = parse_checklist(_read(task_root / _CHECKLIST))
    planned = {item.text.lower() for item in open_items(checklist)}
    planned.update(item.text.lower() for item in checklist if item.done)
    for mod in modules:
        if required and any(p in required for p in mod.paths):
            if "DESIGNED" not in " ".join(mod.evidence):
                mod.evidence.append("present in architecture.json")
        _derive_maturity(mod, app, planned)
    source = (
        "seed+architecture"
        if required and seed_text
        else (
            "architecture" if required else ("seed" if seed_text else "empty")
        )
    )
    return ProductModel(
        project_id=pid,
        intended_goal=goal or "(unspecified)",
        constraints=constraints,
        success_criteria=success,
        placeholder_intent=placeholder,
        modules=modules,
        source=source,
        assessed_at=_now(),
    )


def _dim(
    name: str, status: str, evidence: list[str], gaps: list[str]
) -> Dimension:
    return Dimension(name=name, status=status, evidence=evidence, gaps=gaps)


def build_convergence(
    project: dict[str, Any],
    root: Path,
    model: ProductModel,
) -> ConvergenceReport:
    """Score independent readiness dimensions from evidence."""
    app = _as_path(project["app_path"], root)
    task_root = _as_path(project["task_root"], root)
    growth = workbench_metrics(str(app))
    arch = load_contract(str(app))
    missing = missing_required(str(app), arch) if arch else []
    acceptance = evaluate_acceptance(project, root)
    validation_raw = _read(task_root / _VALIDATION)
    validation_status = ""
    try:
        record = json.loads(validation_raw) if validation_raw else {}
        if isinstance(record, dict):
            validation_status = str(record.get("status") or "")
    except json.JSONDecodeError:
        validation_status = ""
    checklist = parse_checklist(_read(task_root / _CHECKLIST))
    stubs = list(acceptance.stub_files)
    implemented = [
        m for m in model.modules if m.maturity in {"IMPLEMENTED", "VERIFIED"}
    ]
    verified = [m for m in model.modules if m.maturity == "VERIFIED"]

    dims: list[Dimension] = []

    pc_gaps: list[str] = []
    if growth.source_files == 0:
        pc_gaps.append("ZERO_CODE_OUTPUT: no real source files")
    if missing:
        pc_gaps.append("missing required files: " + ", ".join(missing))
    if stubs:
        pc_gaps.append("stub sources: " + ", ".join(stubs))
    dims.append(
        _dim(
            "product_completeness",
            "ready"
            if not pc_gaps and growth.source_files
            else ("missing" if growth.source_files == 0 else "partial"),
            [
                f"{growth.source_files} source / {growth.test_files} test "
                f"file(s), {growth.lines_of_code} LOC"
            ],
            pc_gaps,
        )
    )

    req_gaps: list[str] = []
    if model.placeholder_intent:
        req_gaps.append("intended product is still a scaffold placeholder")
    if not model.success_criteria:
        req_gaps.append("no success criteria in the seed")
    uncovered = [
        m.id
        for m in model.modules
        if m.maturity in {"UNKNOWN", "DISCOVERED"} and m.gaps
    ]
    if uncovered:
        req_gaps.append(
            "undiscovered/unspecified modules: " + ", ".join(uncovered)
        )
    dims.append(
        _dim(
            "requirements_coverage",
            "missing"
            if model.placeholder_intent or not model.success_criteria
            else ("ready" if not req_gaps else "partial"),
            [
                f"goal: {model.intended_goal}",
                f"{len(model.success_criteria)} success criterion(s)",
            ],
            req_gaps,
        )
    )

    if arch is None:
        dims.append(
            _dim(
                "architecture_coherence",
                "missing",
                ["architecture.json absent"],
                ["no architecture contract on disk"],
            )
        )
    else:
        dims.append(
            _dim(
                "architecture_coherence",
                "ready" if not missing else "partial",
                [f"{len(arch.get('required_files') or [])} required files"],
                [f"missing: {', '.join(missing)}"] if missing else [],
            )
        )

    planned_exists = (task_root / "planned_task.json").is_file()
    dims.append(
        _dim(
            "contract_completeness",
            "ready"
            if planned_exists
            else ("partial" if checklist else "missing"),
            [
                "planned_task.json present"
                if planned_exists
                else "no planned_task.json"
            ],
            [] if planned_exists else ["no current task contract"],
        )
    )

    impl_gaps: list[str] = []
    if growth.is_greenfield:
        impl_gaps.append("greenfield: no source or tests")
    for mod in model.modules:
        impl_gaps.extend(f"{mod.id}: {g}" for g in mod.gaps)
    dims.append(
        _dim(
            "implementation_completeness",
            "missing"
            if growth.is_greenfield
            else ("ready" if implemented and not impl_gaps else "partial"),
            [f"{len(implemented)} module(s) implemented or verified"],
            impl_gaps,
        )
    )

    if validation_status == "passed":
        val_status, val_gaps = "ready", []
    elif validation_status:
        val_status, val_gaps = (
            "partial",
            [f"last validation status: {validation_status}"],
        )
    else:
        val_status, val_gaps = (
            "missing",
            ["no validation_result.json (or unreadable)"],
        )
    dims.append(
        _dim(
            "automated_validation",
            val_status,
            [f"status={validation_status or 'absent'}"],
            val_gaps,
        )
    )

    integ_gaps: list[str] = []
    if missing:
        integ_gaps.append("required files still missing")
    if growth.test_files == 0:
        integ_gaps.append("no tests on disk")
    if len(verified) < len(model.modules) and model.modules:
        integ_gaps.append(
            f"{len(verified)}/{len(model.modules)} modules verified"
        )
    dims.append(
        _dim(
            "integration_completeness",
            "ready"
            if not integ_gaps and model.modules
            else ("missing" if not model.modules else "partial"),
            [f"{len(verified)} verified module(s)"],
            integ_gaps,
        )
    )

    demo_gaps = list(acceptance.reasons)
    dims.append(
        _dim(
            "demo_readiness",
            "ready"
            if acceptance.accepted
            else ("missing" if growth.is_greenfield else "partial"),
            [
                "acceptance.accepted=true"
                if acceptance.accepted
                else "acceptance.accepted=false"
            ],
            demo_gaps,
        )
    )

    readme = (app / "README.md").is_file() or (
        app / "docs" / "seed.md"
    ).is_file()
    docs_placeholder = _is_placeholder(_read(app / "docs" / "seed.md"))
    dims.append(
        _dim(
            "documentation_readiness",
            "ready"
            if readme and not docs_placeholder
            else ("partial" if readme else "missing"),
            ["docs/seed.md or README.md present"] if readme else [],
            ["seed/goal still placeholder"]
            if docs_placeholder
            else ([] if readme else ["no README.md or docs/seed.md"]),
        )
    )

    material: list[str] = []
    for dim in dims:
        if dim.status in {"missing", "partial"}:
            material.extend(dim.gaps)
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for gap in material:
        if gap not in seen:
            seen.add(gap)
            unique.append(gap)

    blocking = _blocking_question(
        model, growth.is_greenfield, unique, acceptance.accepted
    )
    return ConvergenceReport(
        project_id=model.project_id,
        demo_ready=bool(acceptance.accepted),
        blocking_question=blocking,
        dimensions=dims,
        material_gaps=unique,
        assessed_at=_now(),
        source_files=growth.source_files,
        test_files=growth.test_files,
        lines_of_code=growth.lines_of_code,
    )


def _blocking_question(
    model: ProductModel,
    greenfield: bool,
    gaps: list[str],
    accepted: bool,
) -> str:
    if accepted:
        return (
            "No material gap currently blocks a demo: acceptance evidence "
            "is complete."
        )
    if model.placeholder_intent:
        return (
            "What currently prevents a viable product is missing intent: "
            "the seed/goal is still a scaffold placeholder."
        )
    if greenfield:
        return (
            "What currently prevents a viable product is ZERO_CODE_OUTPUT: "
            "the workbench has no real source or tests."
        )
    if gaps:
        return "What currently prevents a viable product: " + gaps[0]
    return (
        "What currently prevents a viable product is incomplete evidence "
        f"for '{model.intended_goal}'."
    )


def propose_objectives(
    model: ProductModel, convergence: ConvergenceReport
) -> list[Objective]:
    """Deterministic Director: gaps become objectives, not patches."""
    objs: list[Objective] = []
    n = 1

    def add(
        title: str,
        gap: str,
        why: str,
        roles: list[str],
        caps: list[str],
        evidence: list[str],
        *,
        blocking: bool,
        modules: list[str] | None = None,
    ) -> None:
        nonlocal n
        objs.append(
            Objective(
                id=f"OBJ-{n:03d}",
                title=title,
                gap=gap,
                why=why,
                required_roles=roles,
                required_capabilities=caps,
                expected_evidence=evidence,
                blocking=blocking,
                related_modules=modules or [],
            )
        )
        n += 1

    if model.placeholder_intent:
        add(
            "Specify the intended product",
            "placeholder seed/goal",
            "The factory cannot converge on an unspecified product.",
            ["director", "architect"],
            ["filesystem"],
            ["non-placeholder Goal and Success in docs/seed.md"],
            blocking=True,
        )
    if convergence.source_files == 0:
        add(
            "Reach code birth",
            "ZERO_CODE_OUTPUT",
            "A factory that produces no software has not started the product.",
            ["coder", "test_builder"],
            ["filesystem", "apply"],
            ["at least one real source file and one real test file"],
            blocking=True,
        )
    arch_dim = next(
        (
            d
            for d in convergence.dimensions
            if d.name == "architecture_coherence"
        ),
        None,
    )
    if arch_dim and arch_dim.status == "missing":
        add(
            "Produce an architecture / module graph",
            "architecture.json absent",
            "Modules cannot mature past DISCOVERED without a design.",
            ["architect"],
            ["filesystem"],
            ["architecture.json with required_files grounded in the seed"],
            blocking=True,
        )
    for mod in model.modules:
        if any("stub" in g for g in mod.gaps):
            add(
                f"Replace stub implementation of {mod.name}",
                "; ".join(mod.gaps),
                "Placeholder bodies are not product behavior.",
                ["coder", "test_builder"],
                ["filesystem", "apply", "validation"],
                [f"non-stub source for {mod.id}", f"tests for {mod.id}"],
                blocking=True,
                modules=[mod.id],
            )
        elif any("missing" in g for g in mod.gaps):
            add(
                f"Implement module {mod.name}",
                "; ".join(mod.gaps),
                "Declared module files are not on disk.",
                ["coder"],
                ["filesystem", "apply"],
                [f"files exist: {', '.join(mod.paths)}"],
                blocking=True,
                modules=[mod.id],
            )
        elif any("no tests" in g for g in mod.gaps):
            add(
                f"Verify module {mod.name}",
                "; ".join(mod.gaps),
                "Implementation without tests is not independently verified.",
                ["test_builder"],
                ["filesystem", "apply", "validation"],
                [f"tests exist and pass for {mod.id}"],
                blocking=False,
                modules=[mod.id],
            )
    val = next(
        (
            d
            for d in convergence.dimensions
            if d.name == "automated_validation"
        ),
        None,
    )
    if val and val.status == "partial":
        add(
            "Repair automated validation failures",
            "; ".join(val.gaps),
            "A product that does not validate is not demoable.",
            ["coder", "test_builder"],
            ["validation", "remediation"],
            ["validation_result.json status=passed"],
            blocking=True,
        )
    if convergence.demo_ready:
        return []
    return objs


def inspect_project(project: dict[str, Any], root: Path) -> Assessment:
    """Live product intelligence (no persistence)."""
    model = build_product_model(project, root)
    convergence = build_convergence(project, root, model)
    objectives = propose_objectives(model, convergence)
    return Assessment(
        model=model, convergence=convergence, objectives=objectives
    )


def _factory_state_dir(project: dict[str, Any], root: Path) -> Path:
    raw = project.get("factory_state_dir")
    if raw:
        return _as_path(raw, root)
    return _as_path(project["app_path"], root) / "factory_state"


def persist_assessment(
    assessment: Assessment, project: dict[str, Any], root: Path
) -> Path:
    """Write product/convergence/objectives JSON into the workbench."""
    dest = _factory_state_dir(project, root)
    dest.mkdir(parents=True, exist_ok=True)
    payload = {
        PRODUCT_MODEL_FILE: {
            **asdict(assessment.model),
            "modules": [asdict(m) for m in assessment.model.modules],
        },
        CONVERGENCE_FILE: {
            **asdict(assessment.convergence),
            "dimensions": [
                asdict(d) for d in assessment.convergence.dimensions
            ],
        },
        OBJECTIVES_FILE: {
            "project_id": assessment.model.project_id,
            "assessed_at": assessment.convergence.assessed_at,
            "objectives": [asdict(o) for o in assessment.objectives],
        },
    }
    for name, data in payload.items():
        (dest / name).write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
    return dest


def load_persisted(
    project: dict[str, Any], root: Path
) -> dict[str, Any] | None:
    """Load the last assess artifacts, or None if never assessed."""
    dest = _factory_state_dir(project, root)
    model_path = dest / PRODUCT_MODEL_FILE
    if not model_path.is_file():
        return None
    out: dict[str, Any] = {}
    for name in (PRODUCT_MODEL_FILE, CONVERGENCE_FILE, OBJECTIVES_FILE):
        raw = _read(dest / name)
        try:
            out[name] = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            out[name] = {}
    return out


def assess_project(project: dict[str, Any], root: Path) -> Assessment:
    """Inspect, persist, and return the assessment."""
    assessment = inspect_project(project, root)
    persist_assessment(assessment, project, root)
    return assessment


def assessment_to_dict(assessment: Assessment) -> dict[str, Any]:
    """JSON-ready snapshot for MCP / CLI."""
    return {
        "project_id": assessment.model.project_id,
        "intended_goal": assessment.model.intended_goal,
        "placeholder_intent": assessment.model.placeholder_intent,
        "source": assessment.model.source,
        "demo_ready": assessment.convergence.demo_ready,
        "blocking_question": assessment.convergence.blocking_question,
        "workbench": {
            "source_files": assessment.convergence.source_files,
            "test_files": assessment.convergence.test_files,
            "lines_of_code": assessment.convergence.lines_of_code,
        },
        "modules": [asdict(m) for m in assessment.model.modules],
        "dimensions": [asdict(d) for d in assessment.convergence.dimensions],
        "material_gaps": assessment.convergence.material_gaps,
        "objectives": [asdict(o) for o in assessment.objectives],
        "success_criteria": assessment.model.success_criteria,
        "constraints": assessment.model.constraints,
        "assessed_at": assessment.convergence.assessed_at,
        "focus_module": focus_module_payload(
            select_focus_module(assessment.model)
        ),
    }


def render_assessment(assessment: Assessment) -> str:
    """Owner-facing Markdown for inspect/assess."""
    c = assessment.convergence
    lines = [
        f"# Product intelligence — {assessment.model.project_id}",
        "",
        f"Intended: {assessment.model.intended_goal}",
        f"Source: {assessment.model.source}",
        f"Demo ready: {str(c.demo_ready).lower()}",
        f"Workbench: {c.source_files} source + {c.test_files} test "
        f"file(s), {c.lines_of_code} LOC",
        "",
        "## Blocking question",
        c.blocking_question,
        "",
        "## Modules",
    ]
    if not assessment.model.modules:
        lines.append("(none discovered)")
    for mod in assessment.model.modules:
        lines.append(
            f"- `{mod.id}` maturity={mod.maturity} "
            f"paths={', '.join(mod.paths) or '—'} "
            f"tests={', '.join(mod.test_paths) or '—'}"
        )
        for gap in mod.gaps:
            lines.append(f"  - gap: {gap}")
    lines.extend(["", "## Readiness dimensions"])
    for dim in c.dimensions:
        lines.append(f"- {dim.name}: {dim.status}")
        for gap in dim.gaps:
            lines.append(f"  - {gap}")
    lines.extend(["", "## Objectives"])
    if not assessment.objectives:
        lines.append("(none — no material Director work queued)")
    for obj in assessment.objectives:
        flag = "blocking" if obj.blocking else "follow-up"
        lines.append(f"- {obj.id} [{flag}] {obj.title}")
        lines.append(f"  gap: {obj.gap}")
        lines.append("  evidence: " + "; ".join(obj.expected_evidence))
    lines.extend(["", "## Material gaps"])
    if not c.material_gaps:
        lines.append("(none)")
    for gap in c.material_gaps:
        lines.append(f"- {gap}")
    return "\n".join(lines) + "\n"
