#!/usr/bin/env python3
"""Stdio MCP server for Crazy Factory.

Crazy Factory is the *server*. External AIs (Cursor, Claude, other
orchestrators) are clients. The public surface is intent-shaped.

Featured tools (owner / Director conversation):

    director_brief, list_projects,
    start_mission, continue_mission, stop_mission, get_status

Inventory tools (power-user; same engine, not the conversation):

    import_project, provide_context, inspect_project, assess_project,
    advance_project, get_findings, get_objectives, reconcile_project

``start_mission`` accepts a seed/context and target in one call.
``inspect_project`` / ``get_status`` include mission outcome, artifact,
and trace. ``director_brief`` is the owner-facing combination of
product intelligence, mission snapshot, and one recommended next
command.

It does not expose call_architect / call_coder. Resources under
``crazy://projects/...`` are read-only project intelligence.

Transport: MCP stdio (Content-Length framing, protocol 2024-11-05),
plus newline-delimited JSON for tests. No vendor SDK.

See factory/CF2_MCP_SURFACE.md for the featured vs inventory map.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

sys.dont_write_bytecode = True

import factory_advance  # noqa: E402
from context_manager import ContextError, add_context  # noqa: E402
from crazy_admin import (  # noqa: E402
    AdminError,
    attachproject,
    ensure_project,
    ingest_start_context,
    startproject,
    status as admin_status,
)
from director import (  # noqa: E402
    FEATURED_MCP,
    INVENTORY_MCP,
    director_brief,
    list_registered_projects,
    mcp_surface,
)
from owner_controls import gather_status  # noqa: E402
from product_kernel import (  # noqa: E402
    assessment_to_dict,
    assess_project,
    inspect_project,
    load_persisted,
)
from mission_runner import (  # noqa: E402
    load_mission_snapshot,
    run_mission as run_closed_mission,
    stop_mission as request_stop,
)
from project_paths import load_project_factory_config  # noqa: E402
from project_registry import (  # noqa: E402
    RegistryError,
    all_project_ids,
    load_registry,
    resolve_project,
)
from repo_tools import find_repo_root  # noqa: E402

PROTOCOL = "2024-11-05"
SERVER_NAME = "crazy-factory"
SERVER_VERSION = "2.0.0-p5a"
FEATURED_TOOLS = list(FEATURED_MCP)
INVENTORY_TOOLS = list(INVENTORY_MCP)

_INSTRUCTIONS = (
    "Talk to the Director. Featured tools: director_brief, "
    "list_projects, start_mission, continue_mission, stop_mission, "
    "get_status. director_brief names the one next command. "
    "Do not call advance_project unless the owner wants a single "
    "beat. Never call worker roles."
)


def _ann(
    title: str, *, read_only: bool, featured: bool = True
) -> dict[str, Any]:
    return {
        "title": title,
        "readOnlyHint": read_only,
        "destructiveHint": False,
        "openWorldHint": False,
        "featured": featured,
    }


TOOLS: list[dict[str, Any]] = [
    {
        "name": "director_brief",
        "description": (
            "Owner-facing Director: intended vs observable product, "
            "latest mission, and one recommended next command "
            "(start, continue, done, human, provide_context, "
            "import, or pick a project). Does not run workers. "
            "Omit project_id to catalog registered workbenches."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": (
                        "Optional. When omitted, briefs the sole "
                        "project or lists all registered projects."
                    ),
                },
            },
        },
        "annotations": _ann("Director brief", read_only=True),
    },
    {
        "name": "list_projects",
        "description": (
            "List registered workbenches with last mission outcome. "
            "Does not inspect product intelligence."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _ann("List projects", read_only=True),
    },
    {
        "name": "start_mission",
        "description": (
            "Start a persistent autonomous mission from context + target "
            "in one call: create the workbench if needed, ingest a seed, "
            "enable the isolated profile, and keep executing until "
            "accepted, blocked, or the beat budget is spent."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Target project id (created if missing).",
                },
                "context": {
                    "type": "string",
                    "description": (
                        "Inline seed markdown, or a path to a context "
                        "source (file, directory, or archive)."
                    ),
                },
                "seed": {
                    "type": "string",
                    "description": (
                        "Path to a seed markdown file copied to "
                        "docs/seed.md and ingested as context."
                    ),
                },
                "target": {
                    "type": "string",
                    "description": (
                        "Optional workbench path when creating the project."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "Alias for target.",
                },
                "max_beats": {"type": "integer"},
            },
            "required": ["project_id"],
        },
        "annotations": _ann("Start mission", read_only=False),
    },
    {
        "name": "continue_mission",
        "description": (
            "Resume an existing mission without re-applying the profile."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "max_beats": {"type": "integer"},
            },
            "required": ["project_id"],
        },
        "annotations": _ann("Continue mission", read_only=False),
    },
    {
        "name": "stop_mission",
        "description": "Request the mission runner to halt.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
        "annotations": _ann("Stop mission", read_only=False),
    },
    {
        "name": "get_status",
        "description": (
            "Pipeline status, owner capabilities, and the latest mission "
            "outcome, artifact, and trace."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
        "annotations": _ann("Mission status", read_only=True),
    },
    {
        "name": "import_project",
        "description": ("Create or attach a Crazy Factory project workbench."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "path": {
                    "type": "string",
                    "description": "Optional workbench path.",
                },
                "attach": {
                    "type": "boolean",
                    "description": (
                        "Attach an existing tree instead of scaffolding."
                    ),
                },
            },
            "required": ["project_id"],
        },
        "annotations": _ann(
            "Import project", read_only=False, featured=False
        ),
    },
    {
        "name": "provide_context",
        "description": (
            "Import a file, directory, or archive as project context."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "source": {"type": "string"},
            },
            "required": ["project_id", "source"],
        },
        "annotations": _ann(
            "Provide context", read_only=False, featured=False
        ),
    },
    {
        "name": "inspect_project",
        "description": (
            "Live product intelligence plus the latest mission outcome, "
            "artifact, and trace. Does not run workers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
        "annotations": _ann(
            "Inspect project", read_only=True, featured=False
        ),
    },
    {
        "name": "assess_project",
        "description": (
            "Recompute product intelligence, persist it, and return "
            "Director objectives."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
        "annotations": _ann(
            "Assess project", read_only=False, featured=False
        ),
    },
    {
        "name": "advance_project",
        "description": (
            "Run one execution-kernel beat for the project. Honors owner "
            "capability switches; does not bypass safety."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
        "annotations": _ann(
            "Advance one beat", read_only=False, featured=False
        ),
    },
    {
        "name": "get_findings",
        "description": (
            "Material product gaps from the latest/live assessment."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
        "annotations": _ann("Get findings", read_only=True, featured=False),
    },
    {
        "name": "get_objectives",
        "description": "Director objective queue.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
        "annotations": _ann(
            "Get objectives", read_only=True, featured=False
        ),
    },
    {
        "name": "reconcile_project",
        "description": (
            "Reassess after human or external-agent edits. Recomputes "
            "the product model from disk (same as assess)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
            },
            "required": ["project_id"],
        },
        "annotations": _ann(
            "Reconcile project", read_only=False, featured=False
        ),
    },
]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resource(uri: str, name: str, description: str) -> dict[str, Any]:
    return {
        "uri": uri,
        "name": name,
        "description": description,
        "mimeType": "application/json",
    }


def list_resources(root: Path) -> list[dict[str, Any]]:
    """MCP resources for every registered project plus the index."""
    resources = [
        _resource(
            "crazy://projects",
            "projects",
            "Registered Crazy Factory projects",
        )
    ]
    try:
        ids = all_project_ids(load_registry(root))
    except (RegistryError, OSError, ValueError):
        ids = []
    for pid in ids:
        base = f"crazy://projects/{pid}"
        resources.extend(
            [
                _resource(base, pid, f"Project {pid} summary"),
                _resource(
                    f"{base}/product",
                    f"{pid} product",
                    "Intended product model",
                ),
                _resource(
                    f"{base}/modules",
                    f"{pid} modules",
                    "Module graph and maturity",
                ),
                _resource(
                    f"{base}/objectives",
                    f"{pid} objectives",
                    "Director objectives",
                ),
                _resource(
                    f"{base}/findings",
                    f"{pid} findings",
                    "Material gaps",
                ),
                _resource(
                    f"{base}/status",
                    f"{pid} status",
                    "Pipeline and capability status",
                ),
                _resource(
                    f"{base}/demo",
                    f"{pid} demo",
                    "Demo readiness",
                ),
            ]
        )
    return resources


def _project(root: Path, project_id: str) -> dict[str, Any]:
    return resolve_project(load_registry(root), project_id)


def _text_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = (
        payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    )
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def call_tool(
    name: str, arguments: dict[str, Any], root: Path
) -> dict[str, Any]:
    """Dispatch an MCP tool call to existing factory operations."""
    try:
        return _call_tool(name, arguments or {}, root)
    except (
        RegistryError,
        OSError,
        ValueError,
        KeyError,
        AdminError,
        ContextError,
    ) as exc:
        return _text_result({"error": str(exc)}, is_error=True)


def _call_tool(
    name: str, arguments: dict[str, Any], root: Path
) -> dict[str, Any]:
    if name == "director_brief":
        pid = arguments.get("project_id")
        payload = director_brief(
            root, project_id=str(pid) if pid else None
        )
        return _text_result(payload)
    if name == "list_projects":
        return _text_result(
            {"projects": list_registered_projects(root), **mcp_surface()}
        )
    if name == "import_project":
        pid = str(arguments["project_id"])
        path = arguments.get("path")
        if arguments.get("attach"):
            if not path:
                raise ValueError("attach requires path")
            info = attachproject(pid, str(path), root=root)
        else:
            info = startproject(pid, str(path) if path else None, root=root)
        return _text_result(info)
    if name == "provide_context":
        project = _project(root, str(arguments["project_id"]))
        result = add_context(
            project=project,
            source=str(arguments["source"]),
            root=root,
            now=_stamp(),
        )
        return _text_result(result)
    if name == "inspect_project":
        project = _project(root, str(arguments["project_id"]))
        payload = assessment_to_dict(inspect_project(project, root))
        payload["mission"] = load_mission_snapshot(project, root)
        return _text_result(payload)
    if name in {"assess_project", "reconcile_project"}:
        project = _project(root, str(arguments["project_id"]))
        return _text_result(assessment_to_dict(assess_project(project, root)))
    if name == "advance_project":
        project = _project(root, str(arguments["project_id"]))
        code = factory_advance.main(project)
        return _text_result({"exit_code": code, "project": project["name"]})
    if name == "start_mission":
        pid = str(arguments["project_id"])
        target = arguments.get("target") or arguments.get("path")
        project = ensure_project(
            pid, root, path=str(target) if target else None
        )
        ingested = ingest_start_context(
            project,
            root,
            seed=(str(arguments["seed"]) if arguments.get("seed") else None),
            context=(
                str(arguments["context"]) if arguments.get("context") else None
            ),
        )
        max_beats = int(arguments.get("max_beats") or 12)
        result = run_closed_mission(
            project, root, max_beats=max_beats, apply_profile=True
        )
        return _text_result(
            {
                "outcome": result.outcome,
                "reason": result.reason,
                "beats": result.beats,
                "trace": result.trace_path,
                "artifact": result.artifact,
                "ingested": ingested,
            }
        )
    if name == "continue_mission":
        project = _project(root, str(arguments["project_id"]))
        max_beats = int(arguments.get("max_beats") or 12)
        result = run_closed_mission(
            project, root, max_beats=max_beats, apply_profile=False
        )
        return _text_result(
            {
                "outcome": result.outcome,
                "reason": result.reason,
                "beats": result.beats,
                "trace": result.trace_path,
                "artifact": result.artifact,
            }
        )
    if name == "stop_mission":
        project = _project(root, str(arguments["project_id"]))
        rel = request_stop(project, root)
        return _text_result({"stop_flag": rel, "project": project["name"]})
    if name == "get_status":
        project = _project(root, str(arguments["project_id"]))
        cfg = load_project_factory_config(str(project["app_path"]), root)
        info = admin_status(project, root)
        info["owner"] = gather_status(project, root, cfg)
        return _text_result(info)
    if name == "get_findings":
        project = _project(root, str(arguments["project_id"]))
        snap = load_persisted(project, root)
        if snap and isinstance(snap.get("convergence.json"), dict):
            gaps = snap["convergence.json"].get("material_gaps") or []
            question = snap["convergence.json"].get("blocking_question")
        else:
            assessment = inspect_project(project, root)
            gaps = assessment.convergence.material_gaps
            question = assessment.convergence.blocking_question
        return _text_result(
            {"blocking_question": question, "material_gaps": gaps}
        )
    if name == "get_objectives":
        project = _project(root, str(arguments["project_id"]))
        snap = load_persisted(project, root)
        if snap and isinstance(snap.get("objectives.json"), dict):
            objs = snap["objectives.json"].get("objectives") or []
        else:
            objs = [
                assessment_to_dict(inspect_project(project, root))[
                    "objectives"
                ]
            ][0]
        return _text_result({"objectives": objs})
    raise ValueError(f"Unknown tool: {name}")


def _read_resource_body(uri: str, root: Path) -> dict[str, Any]:
    if uri == "crazy://projects":
        return {"projects": all_project_ids(load_registry(root))}
    prefix = "crazy://projects/"
    if not uri.startswith(prefix):
        raise ValueError(f"Unknown resource: {uri}")
    rest = uri[len(prefix) :]
    parts = rest.split("/")
    pid = parts[0]
    project = _project(root, pid)
    leaf = parts[1] if len(parts) > 1 else ""
    persisted = load_persisted(project, root) or {}
    live = assessment_to_dict(inspect_project(project, root))
    if leaf == "":
        return {
            "project_id": pid,
            "assessed": bool(persisted),
            "demo_ready": live["demo_ready"],
            "blocking_question": live["blocking_question"],
        }
    if leaf == "product":
        return persisted.get("product_model.json") or {
            "status": "not_assessed",
            "live": {
                "intended_goal": live["intended_goal"],
                "modules": live["modules"],
            },
        }
    if leaf == "modules":
        return {"modules": live["modules"]}
    if leaf == "objectives":
        return {"objectives": live["objectives"]}
    if leaf == "findings":
        return {
            "blocking_question": live["blocking_question"],
            "material_gaps": live["material_gaps"],
        }
    if leaf == "status":
        return admin_status(project, root)
    if leaf == "demo":
        demo = next(
            (d for d in live["dimensions"] if d["name"] == "demo_readiness"),
            {},
        )
        return {
            "demo_ready": live["demo_ready"],
            "dimension": demo,
        }
    raise ValueError(f"Unknown resource: {uri}")


def handle_message(
    message: dict[str, Any], root: Path
) -> dict[str, Any] | None:
    """Handle one JSON-RPC MCP message. Notifications return None."""
    method = str(message.get("method") or "")
    msg_id = message.get("id")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    if method in {"notifications/initialized", "initialized"}:
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"listChanged": False},
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
                "instructions": _INSTRUCTIONS,
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": TOOLS},
        }
    if method == "tools/call":
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        result = call_tool(name, args, root)
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    if method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"resources": list_resources(root)},
        }
    if method == "resources/read":
        uri = str(params.get("uri") or "")
        try:
            body = _read_resource_body(uri, root)
            contents = [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(body, indent=2),
                }
            ]
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"contents": contents},
            }
        except (RegistryError, ValueError, KeyError, OSError) as exc:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32002, "message": str(exc)},
            }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if msg_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def _write_framed(payload: dict[str, Any], out: TextIO) -> None:
    body = json.dumps(payload)
    out.write(f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}")
    out.flush()


def serve(
    *,
    root: Path | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    jsonl: bool = False,
) -> int:
    """Run the stdio MCP loop until stdin closes."""
    root = root or find_repo_root()
    inp = stdin or sys.stdin
    out = stdout or sys.stdout
    if jsonl:
        for line in inp:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            reply = handle_message(message, root)
            if reply is not None:
                out.write(json.dumps(reply) + "\n")
                out.flush()
        return 0
    # Content-Length framing (MCP stdio).
    while True:
        headers: dict[str, str] = {}
        while True:
            header = inp.readline()
            if header == "":
                return 0
            if header in ("\r\n", "\n"):
                break
            if ":" in header:
                key, value = header.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        length = int(headers.get("content-length") or "0")
        if length <= 0:
            continue
        raw = inp.read(length)
        if not raw:
            return 0
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        reply = handle_message(message, root)
        if reply is not None:
            _write_framed(reply, out)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    jsonl = "--jsonl" in args
    return serve(jsonl=jsonl)


if __name__ == "__main__":
    raise SystemExit(main())
