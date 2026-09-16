#!/usr/bin/env python3
"""Owner-facing Director: product intelligence + mission + next command.

P5-01. The Director is what the owner talks to. It does not run workers,
does not apply patches, and does not invent a multi-agent org. It reads
the live product kernel and the latest mission snapshot, then names one
recommended next action.

Recommended actions:

* ``import_project`` — nothing is registered yet
* ``pick_project`` — several projects exist; the owner must choose
* ``provide_context`` — placeholder intent; start needs a prompt or seed
* ``start`` — bounded context exists; no mission has run
* ``continue`` — MORE_WORK / recoverable / budget / runnable preview
* ``done`` — evaluator COMPLETE (remaining product gaps are caveats)
* ``human`` — HUMAN_REQUIRED; do not continue blindly
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from control_intelligence import load_decision
from mission_runner import (
    BUDGET_EXHAUSTED,
    COMPLETE,
    HUMAN_REQUIRED,
    MORE_WORK,
    RECOVERABLE,
    RUNNABLE_PREVIEW,
    load_mission_snapshot,
)
from product_kernel import (
    assessment_to_dict,
    focus_module_payload,
    inspect_project,
    select_focus_module,
)
from project_registry import (
    RegistryError,
    all_project_ids,
    load_registry,
    resolve_project,
)

ACTION_IMPORT = "import_project"
ACTION_PICK = "pick_project"
ACTION_PROVIDE_CONTEXT = "provide_context"
ACTION_START = "start"
ACTION_CONTINUE = "continue"
ACTION_DONE = "done"
ACTION_HUMAN = "human"

CONTINUE_OUTCOMES = frozenset(
    {MORE_WORK, RECOVERABLE, BUDGET_EXHAUSTED, RUNNABLE_PREVIEW}
)

FEATURED_MCP = (
    "director_brief",
    "list_projects",
    "start_mission",
    "continue_mission",
    "stop_mission",
    "get_status",
)

INVENTORY_MCP = (
    "import_project",
    "provide_context",
    "inspect_project",
    "assess_project",
    "advance_project",
    "get_findings",
    "get_objectives",
    "reconcile_project",
)


@dataclass
class NextAction:
    """One recommended owner move, plus the MCP/CLI handles for it."""

    action: str
    why: str
    mcp_tool: str | None = None
    cli: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)


def mcp_surface() -> dict[str, Any]:
    """Featured vs inventory MCP map (see factory/CF2_MCP_SURFACE.md)."""
    return {
        "featured": list(FEATURED_MCP),
        "inventory": list(INVENTORY_MCP),
        "never_expose": [
            "call_architect",
            "call_planner",
            "call_coder",
            "call_reviewer",
        ],
        "deferred": ["network_mcp", "auth"],
    }


def list_registered_projects(root: Any) -> list[dict[str, Any]]:
    """Cheap catalog: registry id, path, and last mission outcome."""
    registry = load_registry(root)
    rows: list[dict[str, Any]] = []
    for pid in all_project_ids(registry):
        try:
            project = resolve_project(registry, pid)
        except RegistryError:
            continue
        snap = load_mission_snapshot(project, root)
        rows.append(
            {
                "project_id": pid,
                "app_path": project.get("app_path"),
                "mission_outcome": snap.get("outcome"),
                "mission_reason": snap.get("reason"),
            }
        )
    return rows


def _next_for_assessment(
    project_id: str,
    assessment: Any,
    mission: dict[str, Any],
) -> NextAction:
    outcome = mission.get("outcome")
    placeholder = bool(assessment.model.placeholder_intent)
    pid = project_id

    if outcome == HUMAN_REQUIRED:
        return NextAction(
            action=ACTION_HUMAN,
            why=(
                mission.get("reason")
                or assessment.convergence.blocking_question
                or "A genuine human decision is required."
            ),
            mcp_tool="get_status",
            cli=f"crazy-admin status {pid}",
            arguments={"project_id": pid},
        )
    if outcome in CONTINUE_OUTCOMES:
        why = mission.get("reason") or "Work remains; continue the mission."
        if outcome == BUDGET_EXHAUSTED:
            why = (
                f"{why} Raise --max-beats if the budget was the only stop."
            )
        if outcome == RUNNABLE_PREVIEW:
            why = (
                f"{why} Configure a coding plugin to implement the "
                "outstanding product claims; do not treat the preview "
                "as COMPLETE."
            )
        return NextAction(
            action=ACTION_CONTINUE,
            why=why,
            mcp_tool="continue_mission",
            cli=f"crazy-admin run {pid}",
            arguments={"project_id": pid},
        )
    if outcome == COMPLETE:
        extra = ""
        if not assessment.convergence.demo_ready:
            extra = (
                " Product intelligence still reports gaps; they are "
                "caveats, not a reason to re-crank a completed mission."
            )
        return NextAction(
            action=ACTION_DONE,
            why=(
                (mission.get("reason") or "Acceptance evidence is complete.")
                + extra
            ),
            mcp_tool=None,
            cli=None,
            arguments={"project_id": pid},
        )
    if placeholder:
        return NextAction(
            action=ACTION_PROVIDE_CONTEXT,
            why=(
                "Intended product is still a placeholder. Pass a prompt, "
                "a real seed, or inline context with start_mission; do "
                "not run workers on 'describe what'."
            ),
            mcp_tool="start_mission",
            cli=f"crazy-admin run {pid} --prompt '<what to build>'",
            arguments={"project_id": pid, "prompt": "<what to build>"},
        )
    return NextAction(
        action=ACTION_START,
        why=(
            "Bounded context exists and no mission has run. "
            "start_mission takes seed/context and target in one call."
        ),
        mcp_tool="start_mission",
        cli=f"crazy-admin run {pid} --seed <seed.md>",
        arguments={"project_id": pid},
    )


def build_director_brief(
    project: dict[str, Any], root: Any
) -> dict[str, Any]:
    """Live inspect + mission snapshot + recommended next command."""
    assessment = inspect_project(project, root)
    mission = load_mission_snapshot(project, root)
    pid = str(project.get("name") or "")
    nxt = _next_for_assessment(pid, assessment, mission)
    control_payload = None
    task_root = project.get("task_root")
    if task_root:
        decision = load_decision(Path(str(task_root)))
        if decision is not None:
            control_payload = {
                "outcome": decision.outcome,
                "kind": decision.kind,
                "stance": decision.stance,
                "source": decision.source,
                "rationale": decision.rationale,
                "quality_ok": decision.quality_ok,
            }
            if decision.source == "model" and decision.director_why:
                nxt.why = decision.director_why
    snap = assessment_to_dict(assessment)
    focus = focus_module_payload(select_focus_module(assessment.model))
    modules = [
        {
            "id": m["id"],
            "maturity": m["maturity"],
            "gaps": m.get("gaps") or [],
        }
        for m in snap.get("modules") or []
    ]
    return {
        "project_id": pid,
        "intended_goal": snap["intended_goal"],
        "placeholder_intent": snap["placeholder_intent"],
        "demo_ready": snap["demo_ready"],
        "blocking_question": snap["blocking_question"],
        "material_gaps": snap["material_gaps"],
        "objectives": [
            {
                "id": o["id"],
                "title": o["title"],
                "blocking": o["blocking"],
            }
            for o in snap.get("objectives") or []
        ],
        "modules": modules,
        "focus_module": focus,
        "mission": {
            "outcome": mission.get("outcome"),
            "reason": mission.get("reason"),
            "beats": mission.get("beats"),
            "artifact": mission.get("artifact"),
            "trace": mission.get("trace"),
            "objective": mission.get("objective"),
            "preview": mission.get("preview"),
        },
        "next": asdict(nxt),
        "control": control_payload,
        "surface": mcp_surface(),
    }


def unregistered_brief(project_id: str | None) -> dict[str, Any]:
    """Director reply when the named project is not in the registry."""
    pid = project_id or "<id>"
    nxt = NextAction(
        action=ACTION_IMPORT,
        why=(
            f"Project '{pid}' is not registered. Import or scaffold it, "
            "then start_mission with a seed."
        ),
        mcp_tool="import_project",
        cli=f"crazy-admin startproject {pid}",
        arguments={"project_id": pid},
    )
    return {
        "project_id": project_id,
        "intended_goal": None,
        "placeholder_intent": True,
        "demo_ready": False,
        "blocking_question": "No registered workbench for this id.",
        "material_gaps": ["project is not registered"],
        "objectives": [],
        "modules": [],
        "focus_module": None,
        "mission": {
            "outcome": None,
            "reason": None,
            "beats": None,
            "artifact": None,
            "trace": None,
            "objective": None,
        },
        "next": asdict(nxt),
        "surface": mcp_surface(),
    }


def catalog_brief(root: Any) -> dict[str, Any]:
    """Director reply when no project is selected."""
    rows = list_registered_projects(root)
    if not rows:
        nxt = NextAction(
            action=ACTION_IMPORT,
            why=(
                "No projects are registered. Import a workbench, then "
                "start_mission with context + target in one call."
            ),
            mcp_tool="import_project",
            cli="crazy-admin startproject <id> [path]",
            arguments={},
        )
        why_block = "No registered projects."
    elif len(rows) == 1:
        registry = load_registry(root)
        project = resolve_project(registry, str(rows[0]["project_id"]))
        return build_director_brief(project, root)
    else:
        nxt = NextAction(
            action=ACTION_PICK,
            why=(
                f"{len(rows)} projects are registered. Pass project_id "
                "to director_brief, or pick from list_projects."
            ),
            mcp_tool="list_projects",
            cli="crazy-admin brief <id>",
            arguments={},
        )
        why_block = "Multiple projects; choose one."
    return {
        "project_id": None,
        "projects": rows,
        "intended_goal": None,
        "placeholder_intent": False,
        "demo_ready": False,
        "blocking_question": why_block,
        "material_gaps": [],
        "objectives": [],
        "modules": [],
        "focus_module": None,
        "mission": {
            "outcome": None,
            "reason": None,
            "beats": None,
            "artifact": None,
            "trace": None,
            "objective": None,
        },
        "next": asdict(nxt),
        "surface": mcp_surface(),
    }


def director_brief(
    root: Any,
    *,
    project_id: str | None = None,
    project: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Entry point used by CLI and MCP."""
    if project is not None:
        return build_director_brief(project, root)
    if project_id:
        try:
            resolved = resolve_project(load_registry(root), project_id)
        except RegistryError:
            return unregistered_brief(project_id)
        return build_director_brief(resolved, root)
    return catalog_brief(root)


def render_brief(payload: dict[str, Any]) -> str:
    """Owner-facing Markdown for ``crazy-admin brief``."""
    pid = payload.get("project_id") or "(none selected)"
    nxt = payload.get("next") or {}
    mission = payload.get("mission") or {}
    lines = [
        f"# Director brief — {pid}",
        "",
        f"Intended: {payload.get('intended_goal') or '(none)'}",
        f"Demo ready: {str(bool(payload.get('demo_ready'))).lower()}",
        f"Mission: {mission.get('outcome') or '(none)'}",
        f"Preview: {(mission.get('preview') or {}).get('url') or '(none)'}",
        "",
        "## Blocking question",
        str(payload.get("blocking_question") or "(none)"),
        "",
        "## Next",
        f"- Action: `{nxt.get('action')}`",
    ]
    if nxt.get("mcp_tool"):
        lines.append(f"- MCP: `{nxt['mcp_tool']}`")
    else:
        lines.append("- MCP: (none — do not start or continue)")
    if nxt.get("cli"):
        lines.append(f"- CLI: `{nxt['cli']}`")
    lines.append(f"- Why: {nxt.get('why') or ''}")
    focus = payload.get("focus_module")
    if focus:
        lines.extend(
            [
                "",
                "## Focus module",
                f"- `{focus.get('id')}` maturity={focus.get('maturity')}",
            ]
        )
        for gap in focus.get("gaps") or []:
            lines.append(f"  - gap: {gap}")
    if payload.get("projects"):
        lines.extend(["", "## Projects"])
        for row in payload["projects"]:
            outcome = row.get("mission_outcome") or "no mission"
            lines.append(
                f"- `{row.get('project_id')}` "
                f"path={row.get('app_path')} mission={outcome}"
            )
    lines.extend(["", "## Material gaps"])
    gaps = payload.get("material_gaps") or []
    if not gaps:
        lines.append("(none)")
    for gap in gaps:
        lines.append(f"- {gap}")
    objs = payload.get("objectives") or []
    lines.extend(["", "## Objectives"])
    if not objs:
        lines.append("(none)")
    for obj in objs:
        flag = "blocking" if obj.get("blocking") else "follow-up"
        lines.append(f"- {obj.get('id')} [{flag}] {obj.get('title')}")
    modules = payload.get("modules") or []
    if modules:
        lines.extend(["", "## Modules"])
        for mod in modules:
            lines.append(f"- `{mod.get('id')}` maturity={mod.get('maturity')}")
    return "\n".join(lines) + "\n"
