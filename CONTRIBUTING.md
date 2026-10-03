# Contributing

[简体中文](CONTRIBUTING.zh-CN.md)

Contributions should keep Robot Workflow reusable across robot projects and keep impact conclusions within their evidence scope.

## Contents

- [Setup and checks](#setup-and-checks)
- [Coding and review standards](#coding-and-review-standards)
- [Repository and documentation hygiene](#repository-and-documentation-hygiene)

## Setup and checks

Run from the project root using Python 3.11+:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
python scripts/check_docs.py
```

Use the minimal example in the README for an integration smoke check. Generated files belong outside the project.

## Coding and review standards

- Keep the runtime standard-library-only; justify any new dependency.
- Discovery, monitoring and default verification never execute/import inspected repository code; use parsers and explicit source contracts. Declared commands run only with explicit `verify --run-checks --root DIR`; preserve snapshot binding, output limits, timeouts and owned-process cleanup.
- Preserve directed facet propagation, version provenance and unknown coverage. Do not label lack of a graph path as verified compatibility.
- Bind evidence to source inputs and state its scope. A source assertion cannot establish simulator, hardware or Sim2Real success.
- Use focused modules and descriptive names. Avoid speculative abstractions and duplicated graph logic.
- Add behavior tests for graph traversal, parser semantics, evidence validity or user-visible CLI changes.
- Render external data through text nodes and escape embedded JSON. Keep reports offline by default.
- Review changes on both Standards and Spec axes against these rules and [the scope](docs/spec.md).

## Repository and documentation hygiene

Every authored Markdown document needs matching complete English/Chinese files with aligned sections, facts, commands and caveats. Preserve standard English entrypoints. Use one title, ordered heading levels and a clickable contents list for at least three main sections.

Keep only delivery/build/runtime sources, required examples, tests and concise conclusions. Do not commit upstream source copies, historical assets, backups, screenshots, intermediate reports or logs. Record source commits and hashes instead. Before publishing, check tracked files, ignore rules, links and a clean install.
