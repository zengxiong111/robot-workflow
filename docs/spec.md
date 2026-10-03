# Version 0.4.0 Scope

[简体中文](spec.zh-CN.md)

Robot Workflow is a reusable open-source engineering dependency and evidence tool informed by Flow's living engineering-record approach. This specification covers the generic tool and minimal example.

## Contents

- [Required behavior](#required-behavior)
- [Validation acceptance](#validation-acceptance)
- [Delivery boundaries](#delivery-boundaries)

## Required behavior

1. Provide a domain-neutral local CLI and declarative graph configuration; project-specific repositories must not be hardcoded into engine logic.
2. Capture exact Git/file provenance and distinguish baseline from candidate sources.
3. Detect relevant semantic source changes and propagate through explicit typed dependency edges with reasons and representative paths.
4. Track component implementation readiness separately from requirements and bound evidence; show unknown, unverified and stale states explicitly.
5. Provide an interactive engineering workflow report with source changes, component inspection, version bundle, requirements/evidence, scenario selection and English/Chinese controls.
6. Include reusable examples, license, build metadata, automated tests, CI and full paired English/Chinese structured documentation.

7. Discover existing checkouts and concrete cross-repository references without executing inspected code; inferred edges must preserve provider-to-consumer direction and evidence.
8. Provide simple initialization and start commands without overwriting reviewed configuration.
9. Poll existing checkouts, fetch and fast-forward eligible clean branches; preserve dirty, divergent and detached checkouts.
10. Route meaningful events to owner webhooks configured by environment variable; persist delivery retries and avoid repeated successful deliveries.

11. Compare explicit producer/consumer fields; missing data is unknown, with no inferred unit or frame conversions.
12. Execute declared commands only with explicit opt-in, check snapshot identity before/after, bound timeout/output, and combine all declared checks.
13. Persist owner claims, disposition notes and reopening; case state is separate from verification results.
14. Display check details, current-snapshot cases and input/output direction in reports.

## Validation acceptance

- Exercise the generic minimal example with versioned source snapshots.
- Test parser facets, transitive dependency propagation, nonsemantic comments, missing sources and unregistered changes.
- Verify minimal installation, CLI/report behavior, source assertion expiry and clean restoration of disposable inputs.
- State usability strengths, manual registration cost and unimplemented capabilities; do not infer hardware or complete-repository compatibility from these checks.

## Delivery boundaries

0.4.0 does not execute inspected code by default; declared commands require explicit `verify --run-checks`. The runner is not a sandbox, and monitoring does not automatically execute physical jobs. GitHub push webhook receivers, graph authoring UI, CAD/PLM integrations and model-backed autonomous agents are not included. Monitoring uses polling and generic outbound notifications. Sources, logs and historical snapshots used during validation remain outside the project. Public publication requires an accessible repository creation/push path; local packaging must not be described as an already published GitHub release.
