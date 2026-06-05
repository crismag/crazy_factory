#!/usr/bin/env python3
"""Seed-derived project contract (Phase 9E.ST6, foundational slice).

The structural gate today is a hand-authored ``architecture.json`` that can
**diverge from the seed** (the task-board run dropped ``README.md`` and
``data/tasks.json`` and let the required UI be stubbed). ST6's fix: derive the
contract *from the seed* so structure, acceptance, and forbidden-tech all trace
back to what the owner actually asked for.

Per the governing principle (scripts are rails, not a brain): this module is the
**deterministic rail**. From a seed it derives — with no model —

- ``forbidden_tech`` / ``allowed_tech`` (the directional safety guard): a baseline
  tech catalog is forbidden *unless* the seed's constraints name it,
- ``required_behaviors`` (from the seed's Success section),
- ``validation`` (a baseline verification recipe).

``required_tree`` is the one part a seed does not state literally — it is the
*design*, which the architect role proposes (and a later slice feeds in here).
So ``contract_from_seed`` accepts an optional proposed tree; the deterministic
derivation + validation work with or without it. ``to_architecture_contract``
renders the contract into the existing ``architecture.json`` schema so the
already-built patch/coherence gates consume it unchanged.

This module decides nothing and writes nothing; it derives + validates. Wiring it
into the live advance path (generate ``architecture.json`` from the seed, feed
``required_behaviors`` into acceptance, ``forbidden_tech`` into the floor and the
adjudicator) is the next ST6 slice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Baseline catalog of heavyweight tech the small-app seeds generally forbid.
# Each group is forbidden *as a whole* unless the seed's constraints name any of
# its markers (naming "SQLite" allows the whole database group). Allowing is the
# lenient direction — it only weakens the guard, never causes a false rejection;
# over-forbidding would wrongly block valid work, so we err toward allow.
_TECH_CATALOG: dict[str, tuple[str, ...]] = {
    "database": (
        "sqlite",
        "sqlite3",
        "postgres",
        "psycopg",
        "mysql",
        "mongodb",
        "sqlalchemy",
        "redis",
    ),
    "web": ("flask", "django", "fastapi", "aiohttp", "bottle", "tornado"),
    "auth": ("oauth", "jwt", "passlib", "bcrypt"),
    "cloud": ("boto3", "google.cloud", "azure", "gcloud"),
    "ai": ("openai", "anthropic", "torch", "tensorflow", "transformers"),
    "packaging": ("setuptools", "poetry", "twine"),
}

_SECTION_KEYS = ("goal", "constraints", "known context", "success")


@dataclass(frozen=True)
class Seed:
    """A parsed factory seed (Goal / Constraints / Success sections)."""

    goal: str
    constraints: list[str]
    success: list[str]
    raw: str = ""


@dataclass(frozen=True)
class ProjectContract:
    """A seed-grounded contract: the basis of direction + acceptance.

    ``required_tree`` is the architect's design (empty until proposed); the rest
    is derived deterministically from the seed.
    """

    goal: str
    required_behaviors: list[str]
    forbidden_tech: list[str]
    allowed_tech: list[str]
    validation: list[str]
    required_tree: list[str] = field(default_factory=list)
    persistence_target: str = ""
    source: str = "seed"


def _strip_bullet(line: str) -> str:
    return line.lstrip("-*•").strip()


def parse_seed(text: str) -> Seed:
    """Parse a factory seed's labelled sections deterministically.

    Recognises ``Goal:``, ``Constraints:``, ``Known Context:``, and ``Success:``
    (case-insensitive). A section's body is the lines until the next known
    header; bullet markers are stripped. Missing sections yield empty values —
    never an error (degrade, don't guess).
    """
    sections: dict[str, list[str]] = {key: [] for key in _SECTION_KEYS}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower().rstrip(":")
        header = next(
            (key for key in _SECTION_KEYS if lowered == key), None
        )
        if header is not None:
            current = header
            # A header may carry an inline value: "Goal: build X".
            inline = line.split(":", 1)
            if len(inline) == 2 and inline[1].strip():
                sections[header].append(inline[1].strip())
            continue
        if line.startswith("#"):
            continue  # markdown title, not a section
        if current is not None:
            body = _strip_bullet(line)
            if body and body.lower() != "none yet.":
                sections[current].append(body)
    goal = " ".join(sections["goal"]).strip()
    return Seed(
        goal=goal,
        constraints=sections["constraints"],
        success=sections["success"],
        raw=text,
    )


def derive_tech(seed: Seed) -> tuple[list[str], list[str]]:
    """Return ``(forbidden_tech, allowed_tech)`` grounded in the seed.

    A tech group is *allowed* when the constraints name any of its markers; all
    other catalog markers are *forbidden*. So "SQLite" in the constraints allows
    the database group, while a "standard library only" seed (naming no tech)
    forbids every group.
    """
    text = " ".join(seed.constraints).lower()
    allowed: set[str] = set()
    for markers in _TECH_CATALOG.values():
        if any(marker in text for marker in markers):
            allowed.update(markers)
    forbidden = {
        marker
        for markers in _TECH_CATALOG.values()
        for marker in markers
        if marker not in allowed
    }
    return sorted(forbidden), sorted(allowed)


def _derive_validation(required_tree: list[str]) -> list[str]:
    """Baseline verification recipe; add an entrypoint launch when discernible."""
    recipe = ["pytest the test suite"]
    # Conventional entrypoint names only — stay conservative so we never emit a
    # false "launch" step when the entrypoint is genuinely ambiguous.
    _entry_stems = ("main", "__main__", "app", "cli", "run", "board", "gui")
    entry = next(
        (
            path
            for path in required_tree
            if path.endswith(".py")
            and not path.split("/")[-1].startswith("test_")
            and Path(path).stem in _entry_stems
        ),
        "",
    )
    if entry:
        recipe.append(f"launch {entry}")
    return recipe


def _derive_persistence(required_tree: list[str]) -> str:
    """Best-effort persistence target: the first data file in the tree."""
    return next(
        (
            path
            for path in required_tree
            if path.endswith((".json", ".db", ".sqlite", ".csv"))
        ),
        "",
    )


def contract_from_seed(
    seed: Seed,
    *,
    required_tree: list[str] | None = None,
    required_behaviors: list[str] | None = None,
) -> ProjectContract:
    """Derive a :class:`ProjectContract` from a seed (+ an optional design).

    ``required_tree``/``required_behaviors`` are the architect's proposals when
    available; without them the contract still carries the deterministically
    derived ``forbidden_tech`` and the seed's Success criteria as behaviors.
    """
    tree = list(required_tree or [])
    behaviors = list(
        required_behaviors if required_behaviors is not None else seed.success
    )
    forbidden, allowed = derive_tech(seed)
    return ProjectContract(
        goal=seed.goal,
        required_behaviors=behaviors,
        forbidden_tech=forbidden,
        allowed_tech=allowed,
        validation=_derive_validation(tree),
        required_tree=tree,
        persistence_target=_derive_persistence(tree),
    )


def validate_contract(contract: ProjectContract) -> list[str]:
    """Return deterministic coherence problems with a derived contract.

    Empty list == coherent. Catches a missing goal, a persistence target absent
    from the required tree, ill-formed tree paths, and any tech that is somehow
    both allowed and forbidden.
    """
    reasons: list[str] = []
    if not contract.goal.strip():
        reasons.append("Contract has no goal (seed Goal section missing/empty)")
    for path in contract.required_tree:
        if path.startswith("/") or ".." in path.split("/"):
            reasons.append(f"required_tree path is not workbench-relative: {path}")
    if (
        contract.persistence_target
        and contract.required_tree
        and contract.persistence_target not in contract.required_tree
    ):
        reasons.append(
            f"persistence_target {contract.persistence_target!r} is not in "
            "required_tree"
        )
    overlap = sorted(set(contract.allowed_tech) & set(contract.forbidden_tech))
    if overlap:
        reasons.append(
            "tech is both allowed and forbidden: " + ", ".join(overlap)
        )
    return reasons


def _infer_dir_buckets(
    tree: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Split a required tree into (src_dirs, test_dirs, extra_allowed tops)."""
    src_dirs: set[str] = set()
    test_dirs: set[str] = set()
    extra: set[str] = set()
    for path in tree:
        parts = path.split("/")
        if len(parts) == 1:
            extra.add(path)  # a root file like README.md
            continue
        top = parts[0]
        if top in ("tests", "test"):
            test_dirs.add(top)
        elif top in ("src", "app", "lib"):
            src_dirs.add(top)
        else:
            extra.add(top)
    return sorted(src_dirs), sorted(test_dirs), sorted(extra)


def to_architecture_contract(contract: ProjectContract) -> dict[str, Any]:
    """Render the contract into the existing ``architecture.json`` schema.

    So the already-built patch + coherence gates (``architecture.py``) enforce a
    *seed-derived* structure instead of a hand-authored one. Only positively
    derived keys are emitted; ``forbidden_dirs``/``forbidden_names`` are left to
    the project (not invented here).
    """
    src_dirs, test_dirs, extra = _infer_dir_buckets(contract.required_tree)
    return {
        "src_dirs": src_dirs,
        "test_dirs": test_dirs,
        "extra_allowed": extra,
        "forbidden_imports": contract.forbidden_tech,
        "required_files": list(contract.required_tree),
        "source": "seed-derived",
    }


def seed_to_dict(seed: Seed) -> dict[str, Any]:
    return {
        "goal": seed.goal,
        "constraints": seed.constraints,
        "success": seed.success,
    }


def contract_to_dict(contract: ProjectContract) -> dict[str, Any]:
    return {
        "goal": contract.goal,
        "required_tree": contract.required_tree,
        "required_behaviors": contract.required_behaviors,
        "forbidden_tech": contract.forbidden_tech,
        "allowed_tech": contract.allowed_tech,
        "persistence_target": contract.persistence_target,
        "validation": contract.validation,
        "source": contract.source,
    }
