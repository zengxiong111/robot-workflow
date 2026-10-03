# Architecture and Configuration

[简体中文](architecture.zh-CN.md)

This document specifies the 0.1.0 engineering graph, snapshot, impact and evidence boundaries. Configuration is JSON; runtime dependencies are Python 3.11+ and optional Git provenance.

## Contents

- [Data flow](#data-flow)
- [Configuration](#configuration)
- [Extractors](#extractors)
- [Impact and version semantics](#impact-and-version-semantics)
- [Evidence and coverage](#evidence-and-coverage)
- [Integration and extension](#integration-and-extension)

## Data flow

```text
workflow.json + local checkouts
              │
           snapshot
              │
      baseline / candidate JSON
              │
     compare ← source assertions (verify)
              │
     impact JSON → offline HTML
```

Sources are parsed as data. Python files are never imported; robot code, training entry points and ROS nodes are never executed. Only `fetch` creates checkouts; the snapshot/compare/report commands do not modify repository inputs.

## Configuration

| Field | Meaning |
|---|---|
| `schema_version` | Must be `1` |
| `project` | Report title |
| `repositories[]` | Unique `id`, relative `path`, optional GitHub HTTPS `.git` URL and branch/tag `ref` |
| `nodes[]` | Unique `id`, `repository`, `label`, optional `label_zh`, `description`, `description_zh`, `stage`, `position`, `owner`, `readiness`, `checks` |
| `nodes[].artifacts[]` | Repository-relative `glob`, supported `parser`, optional `facet` override and `max_bytes` (default 4,000,000) |
| `edges[]` | `from`, `to`, nonempty `watch` and `emits` arrays, explanatory `reason`, optional relationship `basis` |
| `requirements[]` | Unique `id`, `title`, affected `nodes`, optional source equality `assertions` |

`readiness` is a record with `state` (`implemented`, `partial`, `planned`, `unknown`), `summary`, optional `summary_zh`, and source-review bindings `reviewed_commit` / `reviewed_fingerprint`. Missing bindings produce `unverified`; a changed binding produces `stale`. It is a maintainer source review, separate from execution evidence.

Repository paths and artifact globs cannot use absolute paths or `..`. Source symlinks cannot escape their repository or point into `.git`. Unmatched globs, oversized files, invalid syntax and unresolved LFS pointers produce unknown coverage.

The same file can be registered in separate components. Avoid overlapping globs with different parsers inside one component; the final matching specification currently determines its representation.

## Extractors

| Parser | Facets | Notes |
|---|---|---|
| `urdf` | `joint_order`, `kinematics`, `dynamics`, `visuals`, `extensions` | Joint/link definitions, limits, inertial/collision elements and root extensions; conservative XML values |
| `python` | `implementation`, `symbols` | AST without module/class/function docstrings; comments and formatting ignored; code never imported |
| `json` | `data` | Parsed structure; object key order ignored, list order preserved |
| `toml` | `config` | Standard-library TOML parser |
| `yaml` | `config` | Conservative lines; ignores blank and standalone comment lines, preserves indentation and inline content |
| `ros` | `interface` | `.msg` / `.srv` / `.action` field lines, separators and constants; comments ignored |
| `markdown` | `documentation` | Normalized line endings; changes propagate only if that facet is watched |
| `text` | `content` | Normalized line endings |
| `binary` | `artifact` | SHA-256 only; no structural or tensor interpretation |

An artifact's `facet` override nests all extracted values under the named facet. For example, an architecture README can be registered as `interface`, but every edit then conservatively needs interface review. This is useful for planned contracts and less precise than a structured schema.

Raw file SHA-256 and semantic facet hashes are stored separately. Out-of-contract working files larger than 4,000,000 bytes use size/mtime metadata and are explicitly marked `unhashed_large_file`; register them with an increased `max_bytes` for content coverage. Numeric textual variants in URDF can trigger review even if physically equal. Generic AST differences cannot establish a behavioral regression.

## Impact and version semantics

1. Compare registered artifacts using the same configuration.
2. Start a propagation seed for each changed semantic facet.
3. Traverse an edge when its `watch` contains that facet or `*`.
4. At the consumer, propagate its `emits` facets through later edges.
5. Record representative paths and reasons; a visited node/facet set bounds traversal and cycles terminate.
6. Propagate incomplete source coverage through downstream declared dependencies as unknown.
7. List tracked and nonignored untracked Git/file inventory changes outside registered artifacts as unclassified changes. They are not silently treated as compatible.

The tool produces candidate upgrade analysis. Dependencies describe engineering relationships; they do not imply that a running deployment follows the upstream default branch. Existing pinned bundles remain unchanged. Vendored policies have their own lineage and should not be assumed to adopt every upstream training commit.

`potential_impact` means review or revalidation is needed. A failed equality assertion is a confirmed source-contract mismatch, not automatically a failed physical task. `no_registered_impact` is bounded by graph coverage. The UI does not claim that every possible path has been enumerated.

## Evidence and coverage

A requirement may declare an equality assertion using a source node, artifact path and JSON Pointer into extracted facets:

```json
{
  "id": "actor-input",
  "source": {
    "node": "policy",
    "path": "models/manifest.json",
    "pointer": "/data/actor/layers/0"
  },
  "equals": 134
}
```

Use `equals_source` instead of `equals` to compare with another extracted source. JSON Pointer supports list indices and `~0` / `~1` escapes.

`verify` emits records containing requirement ID, result, check details, exact snapshot ID and fingerprints of every requirement component. `compare --evidence` accepts them as current only when all bindings match. A change anywhere in the candidate snapshot conservatively expires old records. Requirements without assertions remain unverified; absent source coverage overrides any passing assertion with unknown.

Snapshot IDs hash the graph, repository provenance and captured source state. They detect accidental alteration; they are not signatures or trusted attestations. Evidence JSON can be authored externally and therefore must be reviewed before relying on it.

## Integration and extension

CI can invoke `snapshot`, `verify` and `compare --fail-on-impact`, then attach the JSON/HTML output for human review. Version 0.1.0 has no webhook listener or automatic notification service.

To add a parser, implement it in `contracts.py`, register its name, add behavior-focused tests and document its facets. Domain-neutral graph propagation stays in `engine.py`. External simulator or hardware evidence needs a future adapter with explicit input/version bindings and validation scope; no external execution is inferred from source assertions.

The HTML renderer escapes embedded JSON, inserts source values with DOM text nodes, restricts source links to HTTPS GitHub URLs and disables network connections through its content policy. Reports intentionally contain selected source differences; keep them local unless their content is approved for sharing.
