# Flow Systems Graph Comparison for Robot Workflow

As of 2026-10-03, this note compares Flow Engineering's publicly described Systems Graph with Robot Workflow 0.5.0 and identifies practical open-source improvements. Flow statements below are vendor-published product claims, not independent verification of private product behavior; Robot Workflow statements are checked against its public README and implementation documentation.

[简体中文](flow-comparison.zh-CN.md)

## Contents

- [Scope and evidence](#scope-and-evidence)
- [What Flow publicly describes](#what-flow-publicly-describes)
- [Robot Workflow today](#robot-workflow-today)
- [Prioritized improvements](#prioritized-improvements)
- [Boundaries and acceptance criteria](#boundaries-and-acceptance-criteria)
- [References](#references)

## Scope and evidence

The comparison is based on the Flow Systems Graph page, Flow's official integrations page and customer API documentation, plus Robot Workflow's checked-in 0.5.0 README and architecture description. The Flow site describes a shared, continuously updated engineering model linking requirements, interfaces, tests, CAD and compliance, with source links, change impact, branch review, parameter references and integrations. These are statements made by Flow; this research did not access an authenticated Flow workspace or verify the advertised workflows in a live UI. [Flow Systems Graph](https://www.flowengineering.com/product/systems-graph) [Flow integrations](https://www.flowengineering.com/integrations)

## What Flow publicly describes

| Product area | Publicly described behavior | Evidence boundary |
|---|---|---|
| Connected graph | Nodes for engineering artifacts and explicit links; source traceability to documents and clauses | Marketing/product-page description; live graph not inspected |
| Change and review | Change proposal, impact analysis, stale/suspect downstream items, branch-based reruns, notifications and review/approval | Illustrative scenario on the product page; not independently verified |
| Requirements and parameters | Cross-project requirement linking and live parameter references consumed through an API | Product-page claims |
| Integrations | GitHub, GitLab, Python, Onshape, spreadsheets, issue trackers, document stores and collaboration tools are listed; individual entries describe distinct read/write abilities | Official integrations catalog; some entries are explicitly marked “Coming Soon” |
| API and automation | Authenticated REST API for projects, entities, relationships and automations; API docs also describe an MCP connection | Official API overview |
| API controls | API supports branch-aware reads/writes; API keys inherit their creator's permissions, including read-only roles and branch restrictions; webhook automation starts asynchronous runs | Official API docs; the webhook response acknowledges acceptance, not completion |

The public integration catalog distinguishes listed integrations from those labeled “Coming Soon”; for example, it describes Python, GitHub, Onshape, Excel and SharePoint, while Ansys and SimScale are marked “Coming Soon” on the page consulted. Do not treat a catalog entry as proof of a particular deployment's enabled access or permissions. The API documentation specifies branch-aware operations, permission inheritance, branch/read-only restrictions, and asynchronous webhook runs; a 202 response means accepted, not completed. [Flow integrations](https://www.flowengineering.com/integrations) [API conventions](https://docs.flowengineering.com/api/conventions) [API authentication](https://docs.flowengineering.com/api/authentication) [Webhook automations](https://docs.flowengineering.com/api/automations/webhooks)

## Robot Workflow today

Robot Workflow 0.5.0 already provides a local, declarative graph of repositories, components, typed dependency facets, requirements, readiness, owners and ports. It captures Git/file snapshots, computes downstream impact, checks source assertions and interface declarations, records scoped evidence, supports explicit command checks, offers polling and outbound owner webhooks, and renders local/offline reports. Its setup flow discovers repositories and inferred edges for human review. [Robot Workflow README](../README.md) [Architecture and configuration](architecture.md)

The key boundary is that it is a local single-user workflow, not a continuously synchronized shared system model. Configuration and relationships are maintained by the team; discovery is conservative assistance. The tool has no general graph editor, authenticated multi-user server, inbound GitHub webhook receiver, CAD/PLM connector, parameter calculation engine, review/approval branches or robot-domain extractors for items such as HDF5 datasets, policy checkpoints, calibration or simulator/hardware evidence. Its source evidence does not establish physical behavior, safety or Sim2Real success. [Robot Workflow README](../README.md) [Architecture and configuration](architecture.md)

## Prioritized improvements

| Priority | Improvement | Concrete robot example | Acceptance criteria |
|---|---|---|---|
| P0 | Build an accepted multi-repository baseline to candidate lifecycle | Bind URDF, policy, calibration and deployment repositories into one approved baseline; propose a candidate changing the wrist camera frame | Flow is: accepted baseline → immutable candidate → impact report → required checks → named human review → explicitly accepted next baseline. Candidates never auto-approve; every repository commit, dirty state, graph version and coverage are recorded; relevant changes invalidate checks and approval |
| P0 | Add source-backed robot contracts and extractors | Build on existing URDF/ROS parsing, bind extracted fields to ports, and extend extraction to checkpoint/dataset/calibration identities and policy dimensions | Exact source paths and fingerprints bind each value; unsupported/missing fields are unknown; diffs show changed values; metadata checks never claim physical validation |
| P1 | Add domain-aware setup templates | Guide a new team through robot model, sensor, hand, dataset, training, evaluation and deployment mappings | Templates create editable proposals with source-based evidence; inferred edges remain unverified; onboarding ends with coverage and ownership review and a reproducible initial baseline |
| P1 | Integrate measured simulation and hardware evidence | Attach a simulator run or bench test to exact model, controller, firmware, calibration and setup versions | Adapter records result source, input fingerprints, environment, test conditions and scope; changed/missing inputs make evidence stale/unknown; evidence cannot automatically accept a candidate or certify safety |
| P1 | Add shared identity, roles and review records | Model, perception and controls owners review a camera-frame change | Authenticated role checks scope reads/writes; review binds immutable candidate and field-level diff; decisions and evidence IDs are auditable; approval remains separate from check results |
| P1 | Integrate GitHub PRs, checks and inbound events | A URDF/policy PR receives an impact report and check status; repository event triggers a refresh | PR displays pass/fail/unknown and evidence links; configured checks can gate merge; inbound/outbound events authenticate, deduplicate and audit retries; no robot command runs implicitly |
| P2 | Add hierarchical views and live parameter propagation | A joint-limit value flows from the robot model to controller constraints and policy contract, visible under arm/wrist subsystems | Formula references bind source field, unit, expression version and result; changes recompute downstream values and impacts; invalid units remain unknown; tree/filter views preserve stable graph identity |
| P3 | Add assisted change and impact suggestions | Suggest checks affected by a sensor-frame or joint-mapping change | Suggestions cite source objects/paths, remain proposals and require human acceptance; they never change baseline, approval or evidence automatically |

Recommended sequence: establish the accepted-baseline/candidate gate and source-backed robot contracts first; add domain-aware onboarding and measured evidence next; then shared review, CI and integrations; add hierarchy and parameter propagation after graph identity and provenance are stable. Assisted AI comes last. These are proposed Robot Workflow improvements, not current capabilities. Flow's public product page motivates shared baselines, impact review, parameter references and integration. Its official API documentation separately describes branch-aware access, permission inheritance and automation triggers; these facts support the comparison without inferring unverified internals. [Flow Systems Graph](https://www.flowengineering.com/product/systems-graph) [API conventions](https://docs.flowengineering.com/api/conventions) [API authentication](https://docs.flowengineering.com/api/authentication) [Webhook automations](https://docs.flowengineering.com/api/automations/webhooks)

## Boundaries and acceptance criteria

Improvements should preserve local-first operation, inspect sources as data by default, and require explicit action before running commands or connecting to robot hardware. Any new evidence record should state what inputs and environment it covers, and changed or missing inputs must invalidate or downgrade the result. Integration should begin with read-only import/export and machine-readable formats; credentials and write permissions should be opt-in and scoped. A reviewed graph, passing source contract or simulation report is not proof of safe deployment or successful physical manipulation.

The Flow evidence in this note comes from public product and API pages only. The local Robot Workflow proposal does not imply that a live Flow tenant or UI was tested.

## References

- [Flow Systems Graph product page](https://www.flowengineering.com/product/systems-graph) — publicly stated graph, impact, parameter, integration and review capabilities.
- [Flow integrations catalog](https://www.flowengineering.com/integrations) — integration descriptions and “Coming Soon” labels.
- [Flow API overview](https://docs.flowengineering.com/api) — REST API coverage and MCP/automation documentation entry points.
- [Flow API conventions](https://docs.flowengineering.com/api/conventions) — branch-aware API reads/writes, pagination and error handling.
- [Flow API authentication](https://docs.flowengineering.com/api/authentication) — API key permissions, read-only roles and branch restrictions.
- [Flow webhook automations](https://docs.flowengineering.com/api/automations/webhooks) — trigger and asynchronous run behavior.
- [Robot Workflow README](../README.md) — current 0.5.0 user-visible scope and limitations.
- [Robot Workflow architecture](architecture.md) — configuration, facets, evidence, impact and extension boundaries.
