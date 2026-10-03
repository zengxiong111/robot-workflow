# Architecture and Configuration

[简体中文](architecture.zh-CN.md)

This document specifies the 0.5.0 engineering graph, snapshot, impact and evidence boundaries. Configuration is JSON; runtime dependencies are Python 3.11+ and optional Git provenance.

## Contents

- [Data flow](#data-flow)
- [Configuration](#configuration)
- [Extractors](#extractors)
- [Impact and version semantics](#impact-and-version-semantics)
- [Evidence and coverage](#evidence-and-coverage)
- [Integration and extension](#integration-and-extension)

- [Discovery and monitoring](#discovery-and-monitoring)

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

Sources are parsed as data. Python files are never imported; default analysis does not execute robot code, training entry points or ROS nodes. Explicit declared command checks can execute repository code. `fetch` and explicit console repository import create checkouts; the snapshot/compare/report commands do not modify repository inputs.

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

### Engineering objects and ports

Optional `nodes[].kind` accepts `component`, `model`, `dataset`, `calibration`, `test`, `requirement` or `artifact`. Ports declare `id`, `direction` (`input`/`output`), optional label and contract. Supported contract fields are `type`, `unit`, `frame`, `joint_order` and positive finite `rate_hz`. An edge with ports must declare both `from_port` and `to_port`, connecting an existing output to an existing input.

```json
{
  "id": "robot",
  "kind": "model",
  "ports": [{
    "id": "joint-state",
    "direction": "output",
    "contract": {"type": "joint_state", "unit": "rad", "joint_order": ["j1", "j2"]}
  }]
}
```

The report compares declarations field by field; absent declarations are unknown. No unit conversion or frame transform is inferred. A matching declaration is separate from source or execution evidence.

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

`verify` records provenance plus `evidence_scope` check signatures. Source assertions and interface checks bind selected extracted values, their availability, source specifications and check definitions. Unrelated inputs may change without expiring these records. Command checks conservatively bind the selected repository content inventory, command definitions tool implementation, environment-variable digest, and Python/command executable identity. This does not capture every external dependency or hardware state. Legacy records without a scope still require the exact snapshot and source fingerprints. Missing coverage remains unknown.

Snapshot IDs hash the graph, repository provenance and captured source state. They detect accidental alteration; they are not signatures or trusted attestations. Evidence JSON can be authored externally and therefore must be reviewed before relying on it.

### Explicit contracts, commands and cases

`interface_contracts` compares extracted fields between components named by a requirement, returning pass/fail/unknown. `validation_checks` runs argv with `shell=False` in the selected repository; default verification skips commands and records unknown. `verify --run-checks --root DIR` checks full snapshot identity before and after execution; timeout, missing executable, source drift or missing coverage is unknown. Output is truncated to 4000 bytes per stream; default timeout is 60 seconds, maximum 3600 seconds. POSIX timeout terminates the owned process group; Windows terminates only the main owned process.

Checks for one requirement are combined: any fail remains fail, otherwise any unknown remains unknown, and only all-pass checks verify it. Scoped evidence identifies reusable results; old evidence remains snapshot-bound. Case state lives separately outside the source root, updates through file locking and atomic replacement, and appears only for matching candidate identities.

## Integration and extension

CI can invoke `snapshot`, `verify` and `compare --fail-on-impact`, then attach the JSON/HTML output for human review. Version 0.5.0 provides polling and outbound notifications; no inbound GitHub webhook receiver is implemented.

To add a parser, implement it in `contracts.py`, register its name, add behavior-focused tests and document its facets. Domain-neutral graph propagation stays in `engine.py`. External simulator or hardware evidence needs a future adapter with explicit input/version bindings and validation scope; no external execution is inferred from source assertions.

The HTML renderer escapes embedded JSON, inserts source values with DOM text nodes, restricts source links to HTTPS GitHub URLs and disables network connections through its content policy. Reports intentionally contain selected source differences; keep them local unless their content is approved for sharing.

## Discovery and monitoring

`init` discovers existing local Git checkouts; `start` saves a configuration once and starts polling. Repository/package references create conservative inferred provider-to-consumer edges with file evidence. This is dependency assistance, not complete static analysis. Edit owners, review the graph and add precise contracts before treating it as a release gate. Adding repositories requires generating and reviewing a new configuration and using fresh monitor state.

`sync` never stashes, resets or merges divergent branches. `watch` observes local source state, optionally synchronizes, compares snapshots and writes reports outside the source root. The polling interval defaults to 30 seconds; network operations and analysis add latency. State-directory locks support Unix and Windows; the automated monitoring tests currently run on Linux.

Notifications use `notifications.webhook_env` for a default endpoint and `notifications.recipients` for owner-to-environment-variable routing. The environment holds URLs; configuration holds only variable names. The JSON POST includes event identity, owners, impacts, source commits and the local report path. A receiver should deduplicate by `event_id`: durable retry provides at-least-once delivery, not exactly-once delivery across crashes. Redirects are refused. Local state contains reports and event history and must remain private when sources are private.
