# Robot Workflow

[简体中文](README.zh-CN.md)

Robot Workflow is an open-source engineering workflow tool for robot teams. Register the relationships between robot models, reference data, training, perception and deployment; compare versioned source snapshots; inspect downstream impact and the evidence needed to adopt a change.

Version 0.4.0 provides a local CLI and an offline interactive report. Runtime dependencies: Python 3.11+ and Git for checkout provenance. No AI service, ROS installation or simulator is required.

## Contents

- [Guided setup](#guided-setup)
- [Capabilities](#capabilities)
- [Create and monitor your workflow](#create-and-monitor-your-workflow)
- [Quick start](#quick-start)
- [Your own workflow](#your-own-workflow)
- [Commands and status](#commands-and-status)
- [Boundaries and roadmap](#boundaries-and-roadmap)
- [Contracts, command checks and change cases](#contracts-command-checks-and-change-cases)
- [Development and license](#development-and-license)

Read the [User Manual](docs/user-guide.md) for setup, dependency review, monitoring, owner Webhooks and troubleshooting.

## Guided setup

After installation, run one command in an interactive terminal:

```bash
robot-workflow setup
```

The wizard asks for the parent directory containing existing Git checkouts, a state directory outside that root, a workflow name and component owners. For inferred relationships, choose keep (`k`), delete (`d`) or reverse (`r`). It checks coverage, generates a first local report and asks the system browser to open it. Sources are not fetched during setup. Existing saved configuration is reused rather than overwritten.

For an unattended first report, supply the root explicitly. Defaults retain inferred relationships as unreviewed; `--yes` does not prove dependencies correct.

```bash
robot-workflow setup --root /tmp/my-robot-repos --owner robotics --yes --no-open
robot-workflow doctor --config /tmp/my-robot-repos-workflow/workflow.json --root /tmp/my-robot-repos
robot-workflow open --state-dir /tmp/my-robot-repos-workflow
```

The default state location is a sibling directory named `<root-name>-workflow`. `setup --lang en` uses English prompts; Chinese is the default. Diagnostics report source coverage, unassigned owners, local Git issues and inferred dependencies requiring review. `doctor` returns 2 for error findings; warnings still require review. A documentation-only repository uses a real document if available, which covers documentation rather than runtime behavior. A missing browser leaves the report path available.

Setup prints a continuous local-observation command. Remove `--no-update` to enable Git fetching and fast-forward synchronization. Notification routes remain configured through `init` or JSON; this wizard does not configure Webhook secrets, add missing dependencies, or implement graphical editing.

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

## Create and monitor your workflow

Place your existing Git checkouts under one directory. Configuration, reports and monitor state must stay outside those checkouts. No inspected project code is executed.

1. Start a workflow with automatic repository and dependency discovery:

   ```bash
   robot-workflow start --root /tmp/my-robot-repos \
     --state-dir /tmp/my-robot-workflow --owner robotics \
     --webhook-env ROBOT_WORKFLOW_WEBHOOK_URL --interval 30
   ```

2. The first start creates `/tmp/my-robot-workflow/workflow.json`. Review inferred edges and their source evidence, edit component owners and add explicit contracts where needed. Stop with Ctrl+C before editing configuration; restart to load the reviewed configuration.
3. Set `ROBOT_WORKFLOW_WEBHOOK_URL` in your environment to enable delivery to your notification service. Never put webhook secrets in configuration or version control. With no notification configuration, events are recorded locally only. A configured environment variable with no URL keeps delivery pending for retry.
4. Use a separate route for each owner when initializing a new workflow:

   ```bash
   robot-workflow init --root /tmp/my-robot-repos \
     --output /tmp/workflow.json --owner robotics \
     --route robotics=ROBOTICS_WEBHOOK_URL
   robot-workflow watch --config /tmp/workflow.json \
     --root /tmp/my-robot-repos --state-dir /tmp/my-robot-monitor \
     --interval 30
   ```

The monitor polls at the requested interval; it is not a GitHub push webhook receiver. It fetches and fast-forwards clean existing branches, reports skipped or failed synchronization, compares source snapshots, writes impact HTML/JSON and routes events to owners. The first source snapshot establishes the baseline. Use `--once` for one cycle or `--no-update` to observe local changes without pulling.

Automatic discovery uses explicit repository/package references and records them as inferred relationships, not proven behavior dependencies. Review the generated graph: hidden runtime, hardware and data dependencies still need manual contracts. Re-run `init` to a new file when adding repositories or refreshing inferred relationships; initialization refuses to overwrite a reviewed configuration.

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
| `setup [--root DIR] [--state-dir DIR] [--yes] [--no-open]` | Guided local setup, edge review and first report |
| `doctor --config FILE --root DIR` | Explain local setup and coverage problems |
| `open --state-dir DIR` | Open the latest monitor report |
| `init --root DIR --output FILE [--owner NAME] [--webhook-env ENV] [--route OWNER=ENV]` | Discover existing checkouts and create a new editable configuration |
| `start --root DIR --state-dir DIR [--interval 30] [--once] [--no-update]` | Initialize once, then monitor using the saved configuration |
| `sync --config FILE --root DIR` | Fetch and fast-forward eligible existing checkouts |
| `watch --config FILE --root DIR --state-dir DIR [--interval 30] [--once] [--no-update]` | Persist impact reports and route change events to owners |
| `fetch --config FILE --root DIR` | Create new sparse GitHub clones for declared source globs; existing directories are never replaced |
| `snapshot --config FILE --root DIR --output FILE [--label NAME]` | Capture actual local source state and provenance |
| `verify --snapshot FILE --output FILE [--run-checks --root DIR]` | Run declared equality assertions and record bound evidence |
| `compare --before FILE --after FILE --output FILE [--evidence FILE] [--html FILE] [--fail-on-impact]` | Analyze candidate change and optionally generate HTML / CI gate |
| `cases sync/list/update --state FILE` | Synchronize, inspect, claim or dispose of candidate-bound change cases |
| `report --input FILE --output FILE` | Render an existing impact-report JSON as standalone HTML |

Exit codes: `0` completed; `1` invalid input or operational failure; `2` a failed assertion, activated impact gate or protected synchronization skip. The impact gate is conservative: semantic source changes, unknown coverage and unregistered changes require review. It is not an incompatibility classifier.

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

- Discovery, monitoring and source verification do not execute inspected code by default. `verify --run-checks --root DIR` explicitly executes configured commands; the runner is not a sandbox and does not automatically schedule ROS, training or hardware jobs.
- Graph extraction is declarative. Python AST changes are conservative semantic-change signals, not proof that behavior changes. YAML is a lexical extractor rather than a full YAML parser.
- H5, checkpoint tensor layouts, external calibration, timing behavior and actual physical actuator mappings need additional extractors or external verification. Source manifests establish declared source contracts; physical requirements need external evidence.
- Version 0.4.0 adds discovery, polling, safe synchronization and generic outbound webhooks. It does not provide a GitHub webhook receiver, graph editor, CAD/PLM integration or AI agent.
- Evidence records the actual scope of declared checks, including source assertions, interface equality and explicit command results. It is not a signed attestation and does not automatically establish simulation, hardware safety or Sim2Real success. Reports may contain source snippets: review them before external sharing.
- Existing pinned deployments are unchanged. Reports analyze candidate adoption across declared engineering relationships, including planned interfaces.
- The current version adds explicit interface contracts, command checks and local change cases; richer domain extractors, verification scope and shared team services remain follow-up work.

## Contracts, command checks and change cases

0.4.0 keeps interface checks and case state on configuration schema 1; existing configurations work without adding fields. `interface_contracts` compares explicit producer and consumer fields; `validation_checks` declares commands requiring explicit execution. Skipped commands remain unknown and cannot be overridden by other passing source checks.

`cases sync/list/update` manages open, claimed, resolved and dismissed states; closing requires a note. Monitoring creates local cases automatically, and reports can embed case state. Claiming or closing uses the CLI; offline pages only display state. Resolved does not certify compatibility. See the [user manual](docs/user-guide.md#contracts-command-checks-and-change-cases) for configuration and commands.

## Development and license

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python scripts/check_docs.py
```

See [contribution standards](CONTRIBUTING.md) and [implementation scope](docs/spec.md). The tool is licensed under [Apache-2.0](LICENSE). Upstream repositories remain separately licensed; their source, models, screenshots, training logs and historical backups are not redistributed in this project.

The engineering-record direction is informed by [Flow Systems Graph](https://www.flowengineering.com/product/systems-graph). This is an independent implementation, without affiliation with Flow Engineering.
