# Robot Workflow

[简体中文](README.zh-CN.md)

Robot Workflow is an open-source engineering workflow tool for robot teams. Register the relationships between robot models, reference data, training, perception and deployment; compare versioned source snapshots; inspect downstream impact and the evidence needed to adopt a change.

Version 0.1.0 provides a local CLI and an offline interactive report. Runtime dependencies: Python 3.11+ and Git for checkout provenance. No AI service, ROS installation or simulator is required.

## Contents

- [Capabilities](#capabilities)
- [Quick start](#quick-start)
- [Your own workflow](#your-own-workflow)
- [Commands and status](#commands-and-status)
- [Boundaries and roadmap](#boundaries-and-roadmap)
- [Development and license](#development-and-license)

## Capabilities

| Capability | Behavior |
|---|---|
| Engineering graph | Components, repositories, typed dependency facets, ownership, implementation readiness and requirements |
| Source snapshots | Git commits, dirty state, file SHA-256, registered source coverage and out-of-contract Git inventory |
| Semantic changes | URDF kinematics/dynamics/visuals, Python AST, JSON, TOML, conservative YAML, ROS schemas, text and binary hashes |
| Impact analysis | Directed transitive propagation with source, representative paths, reasons and required checks |
| Evidence | Deterministic source assertions bound to exact snapshot and source fingerprints; stale evidence is explicit |
| Interactive report | Workflow canvas, scenario selection, component inspector, search, status filter, zoom, changes, requirements and version bundle |
| Offline use | Standalone HTML with English/Chinese controls, JSON import/export and no network requests |
| Integration gate | Optional nonzero exit status for source changes, incomplete coverage or unregistered changes |

## Quick start

Run from the project root. The minimal example contains two small source contracts, so no external repositories are needed.

1. Install in an isolated environment:

   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   python -m pip install .
   ```

2. Capture and verify the example:

   ```bash
   robot-workflow snapshot --config examples/minimal/workflow.json \
     --root examples/minimal/repositories --output /tmp/robot-baseline.json
   robot-workflow verify --snapshot /tmp/robot-baseline.json \
     --output /tmp/robot-evidence.json
   robot-workflow compare --before /tmp/robot-baseline.json \
     --after /tmp/robot-baseline.json --evidence /tmp/robot-evidence.json \
     --output /tmp/robot-report.json --html /tmp/robot-workflow.html
   ```

3. Open `/tmp/robot-workflow.html` in a browser. The joint-order requirement should be verified; source impact should be absent.
4. To try a change, modify `joint_order` in the example robot's `model.json`, capture a new snapshot as `/tmp/robot-candidate.json`, and compare the baseline against that candidate. Re-run `verify` to check the new joint-order relationship. Restore your example edit afterwards.

Generated reports, source snapshots and logs must stay outside the repository.

## Your own workflow

Start with [the minimal configuration](examples/minimal/workflow.json). Each node owns declared source globs; every edge states which source facets it watches and which target facets may become invalidated.

```json
{
  "from": "robot",
  "to": "policy",
  "watch": ["kinematics", "joint_order"],
  "emits": ["data"],
  "reason": "Policy FK and joint mapping consume the robot model"
}
```

1. Add repositories with paths relative to your checkout root.
2. Add components and source globs using the supported parsers.
3. Declare dependency edges and review their reasons. Relationships are explicit and maintained by the team.
4. Add requirements with source assertions where deterministic equality is useful.
5. Capture baseline/candidate snapshots with the same graph; compare and review the candidate before updating your version bundle.

See [architecture and configuration](docs/architecture.md) for parser facets, assertions, coverage and evidence semantics. Configuration changes require their own review: comparing two different graph configurations is rejected to avoid silently dropping dependencies.

## Commands and status

| Command | Purpose |
|---|---|
| `fetch --config FILE --root DIR` | Create new sparse GitHub clones for declared source globs; existing directories are never replaced |
| `snapshot --config FILE --root DIR --output FILE [--label NAME]` | Capture actual local source state and provenance |
| `verify --snapshot FILE --output FILE` | Run declared equality assertions and record bound evidence |
| `compare --before FILE --after FILE --output FILE [--evidence FILE] [--html FILE] [--fail-on-impact]` | Analyze candidate change and optionally generate HTML / CI gate |
| `report --input FILE --output FILE` | Render an existing impact-report JSON as standalone HTML |

Exit codes: `0` completed; `1` invalid input or operational failure; `2` a failed assertion or an activated impact gate. The impact gate is conservative: semantic source changes, unknown coverage and unregistered changes require review. It is not an incompatibility classifier.

| State | Meaning |
|---|---|
| `changed` | Registered semantic source changed |
| `potential_impact` | A declared dependency path connects this candidate change to the component |
| `no_registered_impact` | No matching path in the current graph; compatibility remains unproven |
| `unknown` | Required source missing/invalid, or a change is outside registered contracts |
| `verified` / `failed` | The recorded source assertion passed/failed for this exact snapshot |
| `stale` | Supplied evidence belongs to another snapshot or source fingerprint |
| `unverified` | No current evidence is recorded |

## Boundaries and roadmap

- This is an engineering workflow and review tool. It does not run training, ROS nodes, simulators or hardware commands.
- Graph extraction is declarative. Python AST changes are conservative semantic-change signals, not proof that behavior changes. YAML is a lexical extractor rather than a full YAML parser.
- H5, checkpoint tensor layouts, external calibration, timing behavior and actual physical actuator mappings need additional extractors or external verification. The example uses source manifests and explicitly leaves physics/hardware requirements unverified.
- No automatic webhook listener, notification delivery, graph editor, CAD/PLM integration or AI agent is implemented in 0.1.0. CLI invocations can be integrated into your own CI.
- Evidence is a source assertion record, not a signed attestation or proof of simulation, hardware safety or Sim2Real success. Reports may contain source snippets: review them before external sharing.
- Existing pinned deployments are unchanged. Reports analyze candidate adoption across declared engineering relationships, including planned interfaces.
- Future development should prioritize richer contract extractors, reviewed dependency discovery and external evidence adapters before adding task execution.

## Development and license

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python scripts/check_docs.py
```

See [contribution standards](CONTRIBUTING.md) and [implementation scope](docs/spec.md). The tool is licensed under [Apache-2.0](LICENSE). Upstream repositories remain separately licensed; their source, models, screenshots, training logs and historical backups are not redistributed in this project.

The engineering-record direction is informed by [Flow Systems Graph](https://www.flowengineering.com/product/systems-graph). This is an independent implementation, without affiliation with Flow Engineering.
