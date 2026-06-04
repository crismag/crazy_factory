# Phase 9A — Context-Aware Project Bootstrapping

> For the hands-on end-to-end guide (quick start, execution flow, owner
> switches) see [USAGE.md](USAGE.md). This document covers the 9A design.


Crazy Factory can receive project knowledge and make it available to the
existing Think → Plan → Build pipeline. This phase proves one loop end to end:

```text
Receive Context → Store Context → Expose Context To AI → Influence Planning
```

It is intentionally small. The ingestion layer performs **no intelligence** —
only file validation, archive extraction, and catalog maintenance. All
understanding stays with the AI workflow. There is no knowledge graph, no RAG,
no embeddings, no document processing, no classification engine, and no Archon
or CIE integration (those are later phases).

## The context store

Every project gets a context store inside its workbench:

```text
<app_path>/context/
  imports/<import_id>/      preserved originals (file, directory tree, archive)
  extracted/<import_id>/    safe extraction output for archives
  catalog.yaml              what was imported + which files are supported
```

This is separate from `factory_context/` (the project goal and seed-grown
context). The build target remains `app/` (the coder's only write target) — the
context store never holds generated code.

## Supported vs. stored

Files the AI actively consumes (flagged `supported: true` in the catalog and
injected into planning):

```text
.md  .txt  .yaml  .yml  .json  .csv  .sql
```

Every other file (`.pdf`, `.docx`, `.xlsx`, `.png`, `.jpg`, `.svg`, …) is
**stored, cataloged, and preserved** but never parsed, converted, or
interpreted. Secret-like files (`.env*`, `id_rsa`, `*.pem`/`*.key`/…) are
refused — never copied into the repository.

## Commands

```bash
# Create a project (scaffolds the workbench + an empty context store).
crazy-admin startproject todo_app apps/todo_app

# Import context — a single file, a directory, or an archive.
crazy-admin add-context todo_app ./seed/
crazy-admin add-context todo_app requirements.md
crazy-admin add-context todo_app package.zip
crazy-admin add-context todo_app bundle.tar.gz

# Target the project and run one context-aware advance.
crazy-admin status todo_app        # shows context file count, last advance, last contract
crazy-admin advance todo_app
```

Supported archive kinds: `zip`, `tar`, `tar.gz` / `tgz`, and single-file `gz`.

## How context reaches the AI

On each advance, before planning:

1. `context_loader` reads the supported files recorded in the catalog.
2. It aggregates them into one plain-text **context bundle**:

   ```text
   Project Context

   ===== <path> =====
   <file contents>
   ...
   ```

3. The bundle is injected into the Architect and Planner prompts under a
   `## Project Imported Context` heading.

This is simple file aggregation — no chunking, ranking, embedding, or search.

### Volume guard

So a large import cannot overflow the model context window:

- each file is line-capped on read (`max_lines_per_file`),
- the bundle is bounded by a total file-count and byte budget
  (`DEFAULT_MAX_CONTEXT_FILES`, `DEFAULT_MAX_CONTEXT_BYTES`).

When the budget is exceeded the loader includes what fits and **logs exactly
what it dropped** — never a silent truncation.

## Safety

- The admin CLI is owner-driven. It stores files and updates the catalog; it
  never generates, applies, commits, pushes, or merges code. Every capability
  switch stays off by default — importing context enables nothing.
- All writes stay inside approved roots. Context ingestion is supported for
  embedded apps under the repo and for external apps under the owner-approved
  apps base; other external paths are rejected rather than written to.
- Archive extraction refuses path traversal, absolute member paths, overwrites,
  and non-regular tar members (symlinks/hardlinks/devices). Originals are
  preserved.
- Secret-like files are never ingested.

## Architecture

| Module | Responsibility |
|--------|----------------|
| `scripts/archive_utils.py` | Safe stdlib extraction of zip/tar/tar.gz/gz |
| `scripts/context_manager.py` | `add_context`, classification (supported flag), the `catalog.yaml` read/write |
| `scripts/context_loader.py` | Build the context bundle + volume guard |
| `scripts/project_registry.py` | Resolves `context_*` store paths per project |
| `scripts/crazy_admin.py` | `startproject` (scaffold store), `add-context`, `status` |
| `scripts/planning_roles.py` | Injects the bundle into Architect/Planner prompts |
| `scripts/factory_advance.py` | Loads the bundle once per advance and passes it to planning |

## Catalog format

`catalog.yaml` uses synthetic ids as keys (so it round-trips through the
factory's small YAML subset, which does not parse lists of mappings):

```yaml
imports:
  import_001:
    source: "package.zip"
    source_type: "archive"
    imported_at: "2026-06-02T12:00:00Z"
    extracted_to: "apps/todo_app/context/extracted/import_001"
    extracted: true
    file_count: 3
files:
  f0001:
    path: "apps/todo_app/context/extracted/import_001/requirements.md"
    import_id: "import_001"
    type: "md"
    supported: true
```

The catalog tracks imports and files only — it is not a search index or graph.

## Success metric

A project supplied with different context files produces different planning
output. The advance logs `Loaded N context file(s) (… bytes) into planning.`, and
the Architect/Planner prompts contain the imported material — verified by
`tests/test_context_ingestion.py` (the planner receives the bundle; different
context yields different prompts) and by the live workflow above.
