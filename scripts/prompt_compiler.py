#!/usr/bin/env python3
"""Compile a raw owner prompt into a factory seed and architecture.

Lovable-style entry: one sentence becomes an intended product. The
compiler writes ``docs/seed.md`` and ``architecture.json`` so the
existing loop has Goal, Success, required files, and a start command.

Claude/OpenAI fill in screens and wording when a key is present.
Without a key (and under pytest unless opted in) a deterministic
default-stack compile still produces a non-placeholder seed — the
factory proceeds instead of parking on ``specify_intent``.

Empty or already-specified seeds are left alone. The startproject
scaffold is not compiled until the owner supplies a prompt.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from coding_llm import resolve_coding_backend
from control_intelligence import control_model_enabled
from llm_interaction import structured_call
from project_contract import parse_seed
from web_stack import DEFAULT_STACK_ID, WebStack, resolve_stack, stack_record

COMPILE_FILE = "prompt_compile.json"
SEED_REL = "docs/seed.md"
ARCH_REL = "architecture.json"

_PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "describe what",
    "describe what 'done' looks like",
    "none yet",
)

_SYSTEM = (
    "You are Crazy Factory's prompt compiler. Turn a short human "
    "prompt into a bounded web application intent. Do not write "
    "application source. Stay on the given default stack. Respond "
    "with ONLY JSON."
)
_PRIMING = (
    "JSON keys: title, goal, constraints (array of strings), "
    "known_context, success (array of strings), screens (array), "
    "data (string), required_files (array), start_command, "
    "listen_port (int), stack. Constraints must keep Python 3 "
    "stdlib only. start_command must begin with python3."
)


@dataclass
class CompiledProduct:
    """Intended product derived from a raw prompt."""

    title: str
    goal: str
    constraints: list[str]
    success: list[str]
    known_context: str
    screens: list[str]
    data: str
    required_files: list[str]
    start_command: str
    listen_port: int
    stack: str
    source: str
    original_prompt: str
    provider: str = ""


def _is_placeholder_text(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return True
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


def needs_compile(text: str) -> bool:
    """True when the text is not yet a specified factory seed."""
    body = (text or "").strip()
    if not body:
        return False
    seed = parse_seed(body)
    goal = (seed.goal or "").strip()
    success = [s for s in seed.success if str(s).strip()]
    specified = (
        goal
        and success
        and not _is_placeholder_text(goal)
        and not any(_is_placeholder_text(s) for s in success)
    )
    return not specified


def _title_from_prompt(prompt: str) -> str:
    line = (prompt or "").strip().splitlines()[0] if prompt.strip() else ""
    words = [
        w.strip(".,:;!?\"'") for w in line.split() if w.strip(".,:;!?\"'")
    ]
    skip = {
        "build",
        "make",
        "create",
        "a",
        "an",
        "the",
        "me",
        "my",
        "please",
        "app",
        "application",
        "for",
    }
    kept = [w for w in words if w.lower() not in skip][:6]
    if not kept:
        kept = words[:4] or ["app"]
    title = " ".join(kept)
    return title[:80] if title else "App"


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def render_seed(product: CompiledProduct) -> str:
    constraints = "\n".join(f"- {c}" for c in product.constraints)
    success = "\n".join(f"- {s}" for s in product.success)
    screens = ", ".join(product.screens) or "primary UI"
    return (
        "# Factory Seed\n\n"
        f"Goal:\n{product.goal.strip()}\n\n"
        f"Constraints:\n{constraints}\n\n"
        "Known Context:\n"
        f"{product.known_context.strip() or 'Single-user local app.'}\n"
        f"Screens: {screens}.\n"
        f"Data: {product.data or 'JSON file under data/'}.\n\n"
        f"Success:\n{success}\n"
    )


def architecture_payload(product: CompiledProduct, stack: WebStack) -> dict:
    files = product.required_files or list(stack.required_files)
    return {
        "src_dirs": ["src"],
        "test_dirs": ["tests"],
        "extra_allowed": list(stack.extra_allowed),
        "forbidden_imports": list(stack.forbidden_imports),
        "required_files": files,
        "start_command": product.start_command or stack.start_command,
        "listen_port": product.listen_port or stack.listen_port,
        "stack": stack.id,
        "source": "prompt-compiler",
        "title": product.title,
    }


def fallback_product(prompt: str, stack: WebStack) -> CompiledProduct:
    title = _title_from_prompt(prompt)
    goal = prompt.strip()
    if not goal.lower().startswith("build"):
        goal = f"Build {title}: {goal}"
    success = [
        f"A person can use the {title} UI in a browser on localhost.",
        "Core create / list / update / delete flows work without placeholders.",
        "Data persists across process restart (JSON under data/).",
        "python3 -m compileall and pytest pass.",
        f"`{stack.start_command}` starts and answers HTTP.",
    ]
    screens = ["home", "list", "detail"]
    return CompiledProduct(
        title=title,
        goal=goal,
        constraints=list(stack.constraints),
        success=success,
        known_context="Single-user local app. No accounts, no cloud.",
        screens=screens,
        data="JSON file under data/",
        required_files=list(stack.required_files),
        start_command=stack.start_command,
        listen_port=stack.listen_port,
        stack=stack.id,
        source="fallback",
        original_prompt=prompt.strip(),
    )


def _sanitize(
    data: dict[str, Any], prompt: str, stack: WebStack, provider: str
) -> CompiledProduct:
    base = fallback_product(prompt, stack)
    files = [
        name
        for name in _str_list(data.get("required_files"))
        if not name.startswith("/")
        and ".." not in name
        and not name.startswith("scripts/")
        and not name.startswith("factory/")
    ]
    start = str(data.get("start_command") or base.start_command).strip()
    rewritten_start = not start.startswith("python3")
    if rewritten_start:
        start = stack.start_command
    port = data.get("listen_port")
    if (
        rewritten_start
        or not isinstance(port, int)
        or not (1 <= port <= 65535)
    ):
        port = stack.listen_port
    goal = str(data.get("goal") or base.goal).strip() or base.goal
    success = _str_list(data.get("success")) or base.success
    constraints = _str_list(data.get("constraints")) or base.constraints
    title = str(data.get("title") or base.title).strip() or base.title
    return CompiledProduct(
        title=title[:80],
        goal=goal,
        constraints=constraints,
        success=success,
        known_context=str(
            data.get("known_context") or base.known_context
        ).strip(),
        screens=_str_list(data.get("screens")) or base.screens,
        data=str(data.get("data") or base.data).strip(),
        required_files=files or base.required_files,
        start_command=start,
        listen_port=port,
        stack=stack.id,
        source="model",
        original_prompt=prompt.strip(),
        provider=provider,
    )


def compile_prompt(
    prompt: str, *, stack_id: str | None = None
) -> CompiledProduct:
    """Turn a raw prompt into an intended product."""
    text = (prompt or "").strip()
    stack = resolve_stack(stack_id or DEFAULT_STACK_ID)
    if not text:
        return fallback_product("Build a small local web app.", stack)
    product = fallback_product(text, stack)
    if not control_model_enabled():
        return product
    pack = resolve_coding_backend()
    if pack is None:
        return product
    provider, client, model = pack
    user = json.dumps(
        {
            "prompt": text,
            "default_stack": stack_record(stack),
            "required_start_prefix": "python3",
            "required_files_hint": list(stack.required_files),
        },
        indent=2,
    )
    data, _note = structured_call(
        client=client,
        model=model,
        system=_SYSTEM,
        user=user[:8000],
        priming=_PRIMING,
        required_keys=("goal", "success"),
        retries=1,
    )
    if data is None:
        return product
    return _sanitize(data, text, stack, provider)


def _app_dir(project: dict[str, Any], root: Path) -> Path:
    path = Path(str(project["app_path"]))
    return path if path.is_absolute() else (root / path)


def _task_dir(project: dict[str, Any], root: Path) -> Path:
    raw = project.get("task_root") or "factory_tasks"
    path = Path(str(raw))
    return path if path.is_absolute() else (root / path)


def _may_write_architecture(path: Path) -> bool:
    """Overwrite only when missing or previously written by this compiler."""
    if not path.is_file():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return True
    return isinstance(data, dict) and data.get("source") == "prompt-compiler"


def persist_compiled(
    product: CompiledProduct, project: dict[str, Any], root: Path
) -> dict[str, str]:
    """Write seed, architecture, and compile record into the workbench."""
    app = _app_dir(project, root)
    stack = resolve_stack(product.stack)
    seed_path = app / SEED_REL
    arch_path = app / ARCH_REL
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_text(render_seed(product), encoding="utf-8")
    if _may_write_architecture(arch_path):
        arch_path.write_text(
            json.dumps(architecture_payload(product, stack), indent=2) + "\n",
            encoding="utf-8",
        )
    task_root = _task_dir(project, root)
    task_root.mkdir(parents=True, exist_ok=True)
    record = {
        "source": product.source,
        "provider": product.provider,
        "stack": stack.id,
        "title": product.title,
        "original_prompt": product.original_prompt,
        "start_command": product.start_command,
        "listen_port": product.listen_port,
    }
    compile_path = task_root / COMPILE_FILE
    compile_path.write_text(
        json.dumps({**record, "product": asdict(product)}, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "seed": str(seed_path),
        "architecture": str(arch_path),
        "record": str(compile_path),
    }


def compile_into_workbench(
    project: dict[str, Any],
    root: Path,
    prompt: str,
    *,
    stack_id: str | None = None,
) -> dict[str, str]:
    """Compile an owner prompt and persist it on the workbench."""
    product = compile_prompt(prompt, stack_id=stack_id)
    return persist_compiled(product, project, root)


def maybe_compile_workbench(
    project: dict[str, Any],
    root: Path,
    *,
    prompt: str | None = None,
) -> dict[str, str] | None:
    """Compile when the owner supplied a prompt or an unspecified seed.

    The startproject placeholder (Goal/Success still say "describe what")
    is not compiled. The owner must pass a prompt or a real seed.
    """
    text = (prompt or "").strip()
    explicit = bool(text)
    if not text:
        app = _app_dir(project, root)
        try:
            text = (app / SEED_REL).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
    if not needs_compile(text):
        return None
    if not explicit:
        seed = parse_seed(text)
        placeholder = (
            seed.goal
            and seed.success
            and _is_placeholder_text(seed.goal)
            and all(_is_placeholder_text(s) for s in seed.success)
        )
        if placeholder:
            return None
    return compile_into_workbench(project, root, text)


def compiled_stack_id(project: dict[str, Any], root: Path) -> str:
    raw = _task_dir(project, root) / COMPILE_FILE
    try:
        data = json.loads(raw.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return DEFAULT_STACK_ID
    if isinstance(data, dict) and data.get("stack"):
        return str(data["stack"])
    return DEFAULT_STACK_ID
