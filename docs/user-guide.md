# Robot Workflow User Manual

[简体中文](user-guide.zh-CN.md)

Version 0.4.0. A practical guide to setting up, reviewing and monitoring a team engineering workflow.

## Contents

- [Purpose and collaboration](#purpose-and-collaboration)
- [Install and prepare directories](#install-and-prepare-directories)
- [Guided setup](#guided-setup)
- [First run with the bundled example](#first-run-with-the-bundled-example)
- [Create your own workflow](#create-your-own-workflow)
- [Review dependencies and source contracts](#review-dependencies-and-source-contracts)
- [Monitor and synchronize repositories](#monitor-and-synchronize-repositories)
- [Configure owner Webhooks](#configure-owner-webhooks)
- [Notification payload and delivery](#notification-payload-and-delivery)
- [Read reports and state files](#read-reports-and-state-files)
- [Add repositories or change configuration](#add-repositories-or-change-configuration)
- [Fixed comparisons and CI](#fixed-comparisons-and-ci)
- [Contracts, command checks and change cases](#contracts-command-checks-and-change-cases)
- [Troubleshooting and boundaries](#troubleshooting-and-boundaries)
- [Further reading](#further-reading)

## Purpose and collaboration

Robot Workflow v0.4.0 is a Git-backed engineering dependency and change-impact tool. It connects robot models, data, training, perception and deployment through a reviewed graph. It reads local source, captures fingerprints, compares versions and identifies components requiring review. Git supplies commits and synchronization; the JSON graph supplies engineering relationships.

Use it to answer who should review a change, why their component may be affected, and which source checks have evidence. Discovery and monitoring do not execute inspected code by default; explicit command checks require `--run-checks`. A compatible source assertion is not proof of physical task success.

| Role | Responsibility |
| --- | --- |
| Workflow maintainer | Review dependencies, coverage and configuration changes |
| Component owner | Maintain source contracts, owner name and required checks |
| Integration owner | Review reports and arrange simulation/hardware verification |
| Notification service owner | Receive JSON events, deduplicate them and route messages |

## Install and prepare directories

Requires Python 3.11+ and Git for discovery/synchronization. No AI service, ROS or simulator is required. The commands below use a POSIX shell; replace `$HOME/robot-workflow-lab` if needed, using the same paths throughout.

Keep tool source, inspected checkouts and workflow state separate. State must be outside the entire `repos` root, not merely outside one checkout. Authentication for private remotes uses your existing Git configuration.

1. Clone the tool and install into an external virtual environment.
2. These instructions describe `0.4.0`. Check the installed version; the default branch may change in the future.
3. Continue using the activated environment for all subsequent commands.

```bash
mkdir -p "$HOME/robot-workflow-lab"
cd "$HOME/robot-workflow-lab"
git clone https://github.com/zengxiong111/robot-workflow.git tool
python3 -m venv env
. env/bin/activate
python -m pip install ./tool
python -c 'import robot_workflow; print(robot_workflow.__version__)'
robot-workflow --help
```

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

## First run with the bundled example

From `$HOME/robot-workflow-lab`, collect a snapshot, verify the declared joint-order equality and render a report. Outputs stay outside the tool repository. No external repository or notification endpoint is needed.

Open `demo/workflow.html` in a browser. Expected result: no source changes, and the joint-order requirement is verified. This checks the declared JSON source relationship, not robot behavior.

```bash
mkdir -p demo
robot-workflow snapshot --config tool/examples/minimal/workflow.json   --root tool/examples/minimal/repositories --output demo/baseline.json
robot-workflow verify --snapshot demo/baseline.json --output demo/evidence.json
robot-workflow compare --before demo/baseline.json --after demo/baseline.json   --evidence demo/evidence.json --output demo/report.json --html demo/workflow.html
```

## Create your own workflow

Work from `$HOME/robot-workflow-lab`. Place existing Git checkouts below `repos`, for example `repos/robot-description` and `repos/policy-runtime`. Checkouts may be nested; the `--root` argument is the parent directory, not a single checkout. Select each repository branch with Git before monitoring. No clone command with invented remotes is needed: use your actual repositories.

1. Generate configuration without synchronizing sources.
2. Review `state/workflow.json`: owners, artifacts, inferred edge direction and `discovery.notes`.
3. Run one local observation cycle using `--no-update`.
4. Read the generated JSON/HTML before enabling synchronization.

The initial observation establishes a baseline. `init` refuses existing output files. It currently generates one node per repository; split a repository into multiple components by editing configuration when needed.

```bash
mkdir -p repos state
robot-workflow init --root "$PWD/repos" --output "$PWD/state/workflow.json"   --project "My Robot Workflow" --owner robotics
robot-workflow watch --config "$PWD/state/workflow.json"   --root "$PWD/repos" --state-dir "$PWD/state" --once --no-update
```

## Review dependencies and source contracts

### Understand the configuration

| Field | Meaning |
| --- | --- |
| `repositories[].id` / `path` | Stable identifier / checkout path relative to `--root` |
| `nodes[].repository` / `owner` | Repository identifier / routing name of the responsible team |
| `nodes[].artifacts[]` | File glob and parser, relative to that repository |
| `edges[].from` / `to` | Provider → consumer; upstream change may affect downstream |
| `edges[].watch` / `emits` | Incoming semantic facets watched / facets propagated onward |
| `edges[].reason` / `basis` | Engineering rationale / evidence or inferred relationship basis |
| `nodes[].checks` | Review reminders; these commands are not automatically executed |
| `requirements[]` | Named requirements with optional deterministic equality assertions |

Automatic discovery considers explicit GitHub identities, local paths, package declarations and submodules. A README link may reverse or overstate an engineering relationship. Review every edge with the component owners.

### Choose coverage deliberately

Discovery selects up to 80 supported artifacts per repository, scans up to 20,000 files per checkout and skips files over 1,000,000 bytes. Some generated, test and vendor directories are excluded. Discovery limits differ from snapshot artifact `max_bytes` (default 4,000,000).

Register actual files that define the contract. Supported manual parsers: `urdf`, `python`, `json`, `toml`, `yaml`, `ros`, `markdown`, `text`, `binary`. YAML extraction is conservative lexical analysis; binary extraction is hash-only. Documentation-only repositories now use a real document when available; repositories without supported source or documentation may receive a missing placeholder: replace it with a real document using `markdown` and select the intended facet. Missing files must remain visible as unknown until corrected.

The complete example below describes two components and an equality requirement. It can be saved as a separate configuration using the bundled example's repository root; it also illustrates the structure to adapt to your own source paths. Both assertion paths must be registered artifacts.

```json
{
  "schema_version": 1,
  "project": "Joint mapping workflow",
  "repositories": [
    {"id": "robot", "path": "robot"},
    {"id": "policy", "path": "policy"}
  ],
  "nodes": [
    {"id": "robot", "label": "Robot model", "repository": "robot", "owner": "model-team",
     "artifacts": [{"glob": "model.json", "parser": "json"}]},
    {"id": "policy", "label": "Policy runtime", "repository": "policy", "owner": "policy-team",
     "artifacts": [{"glob": "input.json", "parser": "json"}],
     "checks": ["Validate named actuator mapping"]}
  ],
  "edges": [
    {"from": "robot", "to": "policy", "watch": ["data"], "emits": ["data"],
     "reason": "Policy input consumes robot joint order"}
  ],
  "requirements": [
    {"id": "joint-order", "title": "Joint orders match", "nodes": ["robot", "policy"],
     "assertions": [
       {"id": "order", "source": {"node": "robot", "path": "model.json", "pointer": "/data/joint_order"},
        "equals_source": {"node": "policy", "path": "input.json", "pointer": "/data/joint_order"}}
     ]}
  ]
}
```

## Monitor and synchronize repositories

After reviewing configuration, run continuous monitoring from the lab directory. Ctrl+C stops the foreground process. To resume, run the same command with the same root, configuration and state directory. The default interval is 30 seconds; network and analysis time add latency. There is no background service or inbound GitHub push receiver in this version.

`watch` snapshots sources, optionally fetches/fast-forwards eligible checkouts, compares, verifies source assertions, writes reports/events, then updates its baseline. It compares each cycle with the previous cycle, not permanently with the first approved release. Preserve an explicit snapshot for fixed release comparisons.

`--once` runs one cycle; `--no-update` observes local changes without fetching. `start` is the shortcut that creates `state-dir/workflow.json` only if absent, then watches; existing configuration is reused, so initialization flags do not replace its owners/routes.

| Sync status | Action |
| --- | --- |
| `current` / `updated` | No new remote commit / fast-forward completed |
| `dirty` | Local modifications; tool does not stash or reset |
| `detached` | No active branch; select the intended branch yourself |
| `diverged` | Local history is not an ancestor of remote; resolve with your normal Git review process |
| `no_upstream` | Configure the intended tracking branch; a declared `ref` only helps when a branch remote is available |
| `error` | Inspect remote authentication, network or checkout availability |

Synchronization follows the current branch upstream when present; configuration `ref` does not force a branch switch or pin. Skipped/failed synchronization makes affected coverage unknown. Run `sync` separately when you want only an update result.

```bash
robot-workflow watch --config "$PWD/state/workflow.json"   --root "$PWD/repos" --state-dir "$PWD/state" --interval 30

robot-workflow sync --config "$PWD/state/workflow.json" --root "$PWD/repos"
```

## Configure owner Webhooks

Stop monitoring before editing configuration. Add the following `notifications` object at top level and assign matching strings to each node's `owner`. Use a fresh state directory after reviewing the configuration change. URL secrets stay in environment variables, not JSON.

The default endpoint receives all event owners; owner routes receive the owners mapped to that endpoint. Endpoints sharing the same URL are grouped. A generic webhook is an HTTP JSON receiver; Slack, Feishu or other service-specific formats need your adapter. No built-in custom authentication headers or payload templates are provided.

Configure the environment before starting the process. Replace `https://notify.example.org/...` with your own receiver URL; those are placeholders, not functioning services. If no endpoint is configured, events stay local. If an endpoint variable is configured but unset, delivery remains queued for retry.

```json
{
  "notifications": {
    "webhook_env": "WORKFLOW_WEBHOOK_URL",
    "recipients": {
      "model-team": "MODEL_TEAM_WEBHOOK_URL",
      "policy-team": "POLICY_TEAM_WEBHOOK_URL"
    }
  }
}
```

```bash
export WORKFLOW_WEBHOOK_URL='https://notify.example.org/workflow'
export MODEL_TEAM_WEBHOOK_URL='https://notify.example.org/model'
export POLICY_TEAM_WEBHOOK_URL='https://notify.example.org/policy'
robot-workflow watch --config "$PWD/state/workflow.json"   --root "$PWD/repos" --state-dir "$PWD/state-notify" --interval 30
```

## Notification payload and delivery

| Payload field | Meaning |
| --- | --- |
| `event_id` / `created_at` | Deduplication identifier / UTC creation time |
| `owners` / `impacts` | Routed owners / component status and representative paths |
| `source_commits` | Actual captured repository commits |
| `baseline` / `candidate` | Compared snapshot identities |
| `summary` | Change, unknown and unregistered-change counts |
| `sync_errors` / `sync_warnings` | Failed or skipped synchronization |
| `report` | Local JSON report path, not a remote download URL |

Events are triggered by semantic changes, unknown coverage, unregistered changes or sync warnings. A commit that only changes ignored formatting may produce no event. A failed requirement alone is not an independent notification trigger. Check the report requirements as well as notifications.

The receiver should return HTTP 2xx and deduplicate by `event_id`. Redirects are refused, requests time out after 8 seconds, and failed deliveries retry on later cycles. Delivery is at least once across crashes; it is not guaranteed to be exactly once. Same-state events are deduplicated locally.

`pending_notifications=0` can mean local-only handling, not receipt by an external service. To validate your receiver, make a reviewed reversible change in a disposable checkout, confirm the receiver's event ID, and restore it. Do not test by modifying a running robot's source.

## Read reports and state files

Open the HTML path corresponding to the latest `report-*.json`. Each cycle creates a new report; an already-open report does not refresh live. Use the browser to open the next report or import an updated report JSON. The offline UI provides graph selection, search/filter, zoom, component inspector, changes, requirements and versions; it does not edit workflow configuration.

| Status | Interpretation |
| --- | --- |
| `changed` | Registered semantic source changed |
| `potential_impact` | A declared path requires review or revalidation |
| `no_registered_impact` | No matching path in this graph; compatibility is not established |
| `unknown` | Required coverage or remote freshness cannot be established |
| `verified` / `failed` | Source equality assertion passed / failed on this snapshot |
| `stale` | Supplied evidence no longer matches current identity |
| `unverified` | No valid evidence recorded |

| State file | Purpose |
| --- | --- |
| `baseline.json` | Last captured cycle, updated after durable report/event writes |
| `root-identity.json` | Binding to the inspected root |
| `report-*.json` / `.html` | Per-cycle analysis / offline view |
| `events.jsonl` | Locally recorded meaningful events; may be absent before any event |
| `notification-queue.json` | Pending delivery state |
| `.watch.lock` | State directory process lock |
| `workflow.json` | Created by `start`, or placed there by your `init` command |

Reports can include selected source differences. Keep private reports private. Monitor output grows with cycles: stop monitoring, retain required evidence outside repositories, and manage storage according to team retention policy. Do not remove active baseline or queue files to clear warnings.

The graph fits its canvas to node positions. By default it shows the selected component's connections; use Connection view to switch to current impact paths or all dependencies. Select a component to read paths and required checks first, then expand Source and registered files for the file list. Layout lanes, when supplied by a report, are presentation groups rather than proof of runtime order. Lines distinguish input and output dependencies. Larger arrowheads point at the receiving component. Long connections use separate lanes and a white outline to keep crossings readable.
Input and output views are relative to the selected component: blue lines trace upstream dependencies, orange lines trace downstream dependencies, and gray dashed lines show other relationships. Thick lines indicate paths implicated in the current change. Dependency direction can show both sides or filter to inputs or outputs. The inspector separates direct input dependencies and output impacts; expandable path lists use the existing analysis results. Registered dependencies are potential impact relationships, not proof that an interface failed or passed. In dependency cycles, a relationship may be reachable on both sides; the input view takes precedence for coloring indirect relationships.

## Add repositories or change configuration

1. Stop the running monitor with Ctrl+C.
2. Place the new checkout below the same root, with its intended branch/upstream.
3. Run `init` to a new filename, then reconcile its discoveries with your reviewed graph. Preserve manually defined owners, edges, assertions and contracts.
4. Review direction, artifact existence and coverage with owners.
5. Start `watch` with the revised configuration and a fresh state directory.

The same procedure applies to changing owners/routes, artifacts or dependencies: configuration identity is part of snapshot binding. Existing state rejects configuration changes before synchronization. New state establishes a new baseline and does not automatically compare the old graph against the new graph. Do not delete old state until pending deliveries and needed evidence are handled.

```bash
robot-workflow init --root "$PWD/repos" --output "$PWD/workflow-proposed.json"   --project "My Robot Workflow" --owner robotics
# Review and reconcile workflow-proposed.json before running the next command.
robot-workflow watch --config "$PWD/workflow-proposed.json"   --root "$PWD/repos" --state-dir "$PWD/state-revised" --once --no-update
```

## Fixed comparisons and CI

For release review, use explicit baseline/candidate snapshots with exactly the same reviewed configuration. First capture the approved baseline; then make or check out the intended source change separately, capture the candidate and verify it. The commands below assume the reviewed configuration at `state/workflow.json`; they do not perform that source change.

`--fail-on-impact` returns 2 for semantic changes, unknown coverage or unregistered changes. It is a conservative review gate, not a compatibility classifier. `verify` separately returns 2 for failed equality assertions; `compare --fail-on-impact` is not a general assertion-failure gate. Capture and inspect both results in CI.

| Exit code | Meaning |
| --- | --- |
| 0 | Command completed; still inspect report states |
| 1 | Input/operation error |
| 2 | `verify` assertion failure, `compare` impact gate or `sync` protective skip |

`watch` may finish with code 0 while its cycle contains sync warnings. Inspect its printed `sync` results and reports.

```bash
mkdir -p release-review
robot-workflow snapshot --config state/workflow.json --root "$PWD/repos"   --output release-review/baseline.json --label approved
# Apply or check out the intended source change separately before continuing.
robot-workflow snapshot --config state/workflow.json --root "$PWD/repos"   --output release-review/candidate.json --label candidate
robot-workflow verify --snapshot release-review/candidate.json   --output release-review/evidence.json
robot-workflow compare --before release-review/baseline.json   --after release-review/candidate.json --evidence release-review/evidence.json   --output release-review/report.json --html release-review/report.html --fail-on-impact
```

## Contracts, command checks and change cases

Add contracts and checks to an existing graph. This is a configuration fragment: first register the `camera` and `pose` components and the `pose` repository, add a `pose-contract` requirement covering both components, and register the two real `contract.json` files as `json` artifacts. `/data` is the JSON extractor root; field pointers are relative to it. Field names imply no unit conversion or coordinate transformation.

```json
{
  "interface_contracts": [{
    "id": "pose-fields", "requirement": "pose-contract",
    "producer": {"node": "camera", "path": "contract.json", "pointer": "/data"},
    "consumer": {"node": "pose", "path": "contract.json", "pointer": "/data"},
    "fields": [{"name": "frame", "pointer": "/frame"}, {"name": "units", "pointer": "/units"}]
  }],
  "validation_checks": [{
    "id": "pose-tests", "requirement": "pose-contract", "repository": "pose",
    "argv": ["python3", "-B", "-m", "unittest", "discover", "-s", "tests"],
    "timeout_seconds": 60
  }]
}
```

1. Source assertions and contract comparisons run by default; missing fields are unknown and mismatches fail.
2. Commands run only with `--run-checks`, requiring `--root`. Configured tests must already exist; the runner is not a sandbox, so configure reviewed check commands only. Default timeout is 60 seconds, maximum 3600; each output stream displays at most 4000 bytes. A nonzero command exit fails; timeout, missing executable, source drift or missing coverage is unknown.
3. All declared checks for a requirement combine: any fail stays fail, otherwise any unknown stays unknown. A skipped command cannot become verified through passing source assertions. `verify` returns 2 for fail or unknown, and 1 for configuration/invocation errors.
4. Monitoring maintains `cases.json` outside the source root; existing reports can also be synchronized manually. Case IDs bind candidate snapshot and component. Resync preserves ownership, status, notes and actor/timestamp transition history.
5. Claim or resolve with the CLI. Take `CASE_ID` from list output and replace `OWNER` with the acting person. Closing needs a note; reopen with `--status open`. `resolved` is a human disposition and does not change verification state; `dismissed` also needs a reason. Offline reports display state and cannot write it back.

```bash
robot-workflow snapshot --config "$HOME/robot-workflow-lab/state/workflow.json" \
  --root "$HOME/robot-workflow-lab/repos" --output /tmp/candidate.json
robot-workflow verify --snapshot /tmp/candidate.json \
  --root "$HOME/robot-workflow-lab/repos" --run-checks --output /tmp/evidence.json
robot-workflow compare --before /tmp/candidate.json --after /tmp/candidate.json \
  --evidence /tmp/evidence.json --output /tmp/verified-report.json
robot-workflow cases sync --input /tmp/verified-report.json \
  --state "$HOME/robot-workflow-lab/state/cases.json"
robot-workflow cases list --state "$HOME/robot-workflow-lab/state/cases.json"
robot-workflow cases update --state "$HOME/robot-workflow-lab/state/cases.json" \
  --id CASE_ID --status claimed --actor OWNER
robot-workflow cases update --state "$HOME/robot-workflow-lab/state/cases.json" \
  --id CASE_ID --status resolved --actor OWNER --note "Reviewed evidence and recorded disposition"
robot-workflow report --input /tmp/verified-report.json \
  --cases "$HOME/robot-workflow-lab/state/cases.json" --output /tmp/verified-report.html
```

The compare command above uses the same snapshot to display candidate check results; use a real baseline for change analysis. Reports without changed/unknown components create no cases. Report state is captured at generation time; regenerate after CLI updates.

Use the following command when installing from a local checkout; the source path is a placeholder. Existing schema 1 configurations remain valid; omitting `validation_checks` declares no command checks.

```bash
python -m pip install /path/to/local/robot-workflow
python -c 'import robot_workflow; print(robot_workflow.__version__)'
```

## Troubleshooting and boundaries

| Symptom | Resolution |
| --- | --- |
| No Git checkouts found | Use the parent root; ensure actual checkouts are below it, not only URLs |
| Configuration exists | Initialize to a new filename; preserve reviewed configuration |
| Configuration changed since baseline | Review the new graph, then use fresh state |
| State bound to another root | Use a separate state directory for each source root |
| State directory rejected | Move it outside the entire source root |
| Unknown artifact coverage | Check glob, parser, file size, syntax, sparse checkout and unresolved LFS pointers |
| Documentation-only repository unknown | Replace placeholder glob with a real `markdown`/`text` contract |
| Commit updated but no event | Inspect semantic changes and unregistered files; formatting alone may not trigger |
| Notifications pending | Check configured environment names, process environment, HTTP receiver and queue errors |
| No notification and pending=0 | Confirm an event occurred and an actual endpoint was configured |
| Old HTML still shows a previous state | Open the newly generated HTML; reports are static |

The tool cannot fully discover runtime/data/hardware dependencies, interpret checkpoint tensors or H5 semantics, approve a deployment, or prove Sim2Real safety. Binary hashes can detect identity changes but not behavior. Use source contracts and explicit external tests for those decisions.

Current discovery needs review, especially artifact caps, documentation-only coverage and reference direction. Start with critical dependencies, precise contracts and agreed owners before adding broader coverage. A report's known graph is the limit of its conclusions.

## Further reading

- [Quick start and command reference](../README.md).
- [Architecture, parsers and assertion semantics](architecture.md).
- [Bundled complete minimal configuration](../examples/minimal/workflow.json).
- [Contribution guidelines](../CONTRIBUTING.md).

This manual is generic and contains no private robot-team repository configuration or validation output. Those cases should remain in their local workspace unless separately authorized for sharing.
