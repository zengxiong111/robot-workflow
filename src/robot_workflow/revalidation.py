"""Dependency-scoped validity rules for saved verification records."""

from copy import deepcopy
import hashlib
import inspect
import os
import platform
import shutil
import sys
import robot_workflow.contracts as contracts_module
import robot_workflow.verification as verification_module
import robot_workflow.interface_contracts as interfaces_module
import robot_workflow.checks as checks_module

from .contracts import digest, extract
from pathlib import Path


def _req_semantics(snapshot, requirement):
    config = snapshot["config"]
    req = next(item for item in config.get("requirements", []) if item["id"] == requirement)
    node_repositories = {node["id"]: node["repository"] for node in config["nodes"]
                         if node["id"] in req["nodes"]}
    repository_paths = {repo["id"]: repo["path"] for repo in config["repositories"]
                        if repo["id"] in node_repositories.values()}
    return {"nodes": sorted(req["nodes"]), "node_repositories": node_repositories,
            "repository_paths": repository_paths}


def _requirement_checks(config, requirement):
    return {
        "assertions": next((r.get("assertions", []) for r in config.get("requirements", [])
                             if r["id"] == requirement), []),
        "interfaces": [item for item in config.get("interface_contracts", [])
                       if item["requirement"] == requirement],
        "commands": [item for item in config.get("validation_checks", [])
                     if item["requirement"] == requirement],
    }


def _source_dep(snapshot, source, pointer):
    try:
        node = snapshot["nodes"][source["node"]]
        artifact = node["files"][source["path"]]
        repo = snapshot["repositories"][node["repository"]]
        matching_specs = [spec for spec in node.get("artifacts", [])
                          if Path(source["path"]).match(spec["glob"])]
        from .verification import pointer as resolve
        value = resolve(artifact["facets"], pointer)
        return {"node": source["node"], "path": source["path"], "available": True,
                "repository": node["repository"], "repository_path": repo["path"],
                "parser": artifact["parser"], "matching_specs": matching_specs,
                "pointer": pointer, "digest": digest(value)}
    except (KeyError, IndexError, TypeError, ValueError):
        return {"node": source.get("node"), "path": source.get("path"), "available": False,
                "pointer": pointer, "digest": None}


def _parser_identity():
    # Extractor implementation changes can alter pointer results without changing inputs.
    return hashlib.sha256(inspect.getsource(contracts_module).encode()).hexdigest()


def _implementation_identity(module):
    return hashlib.sha256(inspect.getsource(module).encode()).hexdigest()


def scopes(snapshot):
    """Map each requirement to exact check definitions and only their dependencies."""
    config = snapshot["config"]
    result = {}
    for req in config.get("requirements", []):
        rid = req["id"]
        checks = []
        for assertion in req.get("assertions", []):
            deps = [_source_dep(snapshot, assertion["source"], assertion["source"].get("pointer", ""))]
            if "equals_source" in assertion:
                src = assertion["equals_source"]
                deps.append(_source_dep(snapshot, src, src.get("pointer", "")))
            checks.append({"id": assertion["id"], "kind": "source_assertion",
                           "signature": digest({"definition": assertion, "dependencies": deps,
                                                "parser_identity": _parser_identity(),
                                                "checker_identity": _implementation_identity(verification_module),
                                                "runtime": current_runtime(),
                                                "requirement": _req_semantics(snapshot, rid)}),
                           "dependencies": deps})
        for contract in config.get("interface_contracts", []):
            if contract["requirement"] != rid:
                continue
            for field in contract.get("fields", []) or [{"name": "value", "pointer": ""}]:
                check_id = f"{contract['id']}:{field['name']}"
                deps = []
                for endpoint in (contract["producer"], contract["consumer"]):
                    base = endpoint.get("pointer", "")
                    tail = field.get("pointer", "")
                    resolved_pointer = base + tail if tail else base
                    deps.append(_source_dep(snapshot, endpoint, resolved_pointer))
                checks.append({"id": check_id, "kind": "interface_contract",
                               "signature": digest({"definition": contract, "field": field,
                                                    "dependencies": deps, "parser_identity": _parser_identity(),
                                                    "checker_identity": _implementation_identity(interfaces_module),
                                                    "runtime": current_runtime(),
                                                    "requirement": _req_semantics(snapshot, rid)}),
                               "dependencies": deps})
        repo_by_id = snapshot["repositories"]
        for spec in config.get("validation_checks", []):
            if spec["requirement"] != rid:
                continue
            repo = repo_by_id[spec["repository"]]
            repo_inventory = repo.get("command_inventory", {"coverage": "unknown", "files": {},
                                                               "problems": [{"reason": "command inventory unavailable"}]})
            checks.append({"id": spec["id"], "kind": "command",
                           "signature": digest({"definition": spec,
                                                "inventory": repo_inventory,
                                                "available": repo["available"],
                                                "runner_identity": _implementation_identity(checks_module),
                                                "runtime": {**current_runtime(),
                                                            "command": command_identity(spec["argv"][0])},
                                                "requirement": _req_semantics(snapshot, rid),
                                                "requirement_checks": _requirement_checks(config, rid)}),
                           "dependencies": [{"repository": spec["repository"],
                                             "inventory_digest": digest(repo_inventory),
                                             "available": repo["available"],
                                             "coverage": repo_inventory["coverage"]}]})
        result[rid] = {"version": 1, "checks": checks}
    return result


def annotate(records, snapshot):
    by_req = scopes(snapshot)
    for record in records:
        complete = by_req.get(record["requirement"], {"version": 1, "checks": []})
        ids = {item.get("id") for item in record.get("checks", [])}
        record["evidence_scope"] = {"version": 1, "checks": deepcopy(
            [item for item in complete["checks"] if item["id"] in ids])}
    return records


def reusable(record, snapshot, current_scope, check_runtime=True):
    """Return (valid, reason); pre-scope evidence stays exact-snapshot-bound."""
    requirement = next((req for req in snapshot["config"].get("requirements", [])
                        if req["id"] == record.get("requirement")), None)
    if requirement is None or any(snapshot["nodes"].get(node, {}).get("coverage") != "declared_sources_scanned" or
                                  snapshot["nodes"].get(node, {}).get("problems")
                                  for node in requirement["nodes"]):
        return False, "requirement_source_coverage_unknown"
    if not isinstance(record.get("evidence_scope"), dict):
        expected = ({node: snapshot["nodes"][node]["fingerprint"] for node in requirement["nodes"]}
                    if requirement else {})
        valid = (record.get("snapshot_id") == snapshot["snapshot_id"] and
                 record.get("fingerprints") == expected)
        return valid, "legacy_exact_snapshot" if valid else "legacy_snapshot_changed"
    if record["evidence_scope"].get("version") != 1:
        return False, "unsupported_evidence_scope"
    prior = {item["id"]: item for item in record["evidence_scope"].get("checks", [])}
    current = {item["id"]: item for item in current_scope.get("checks", [])}
    if prior.keys() != current.keys():
        return False, "check_coverage_changed"
    for check_id in prior:
        if prior[check_id].get("signature") != current[check_id].get("signature"):
            return False, f"dependency_or_definition_changed:{check_id}"
        if any(dep.get("coverage", "complete") != "complete"
               for dep in current[check_id].get("dependencies", [])):
            reason = "command_inventory_incomplete" if current[check_id].get("kind") == "command" else "source_coverage_unknown"
            return False, f"{reason}:{check_id}"
        if any(dep.get("available") is False for dep in current[check_id].get("dependencies", [])):
            return False, f"source_unavailable:{check_id}"
    # Any observed command runtime mismatch invalidates the aggregate record.
    if check_runtime and any(check.get("kind") == "command" for check in prior.values()):
        command_evidence = {item.get("id"): item.get("environment") for item in record.get("checks", [])
                            if item.get("environment")}
        expected_ids = {check_id for check_id, item in prior.items() if item.get("kind") == "command"}
        expected_runtime = {check_id: {**current_runtime(), "command": command_identity(
            next(item["argv"][0] for item in snapshot["config"].get("validation_checks", [])
                 if item["id"] == check_id))} for check_id in expected_ids}
        if set(command_evidence) != expected_ids or any(
                env != expected_runtime[check_id] for check_id, env in command_evidence.items()):
            return False, "runtime_identity_changed"
    return True, "scoped_dependencies_unchanged"


def current_runtime():
    return {"python": platform.python_version(), "platform": sys.platform,
            "executable": sys.executable,
            "environment_digest": digest(dict(sorted(os.environ.items())))}


def command_identity(argv0):
    candidate = Path(argv0)
    resolved = candidate.resolve() if candidate.is_absolute() else Path(shutil.which(argv0) or "")
    if not resolved.is_file():
        return {"path": str(resolved) if str(resolved) else None, "sha256": None}
    hasher = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return {"path": str(resolved), "sha256": hasher.hexdigest()}


def prepare_previous(previous, snapshot):
    """Copy reusable records and explain decisions per requirement."""
    current_scopes = scopes(snapshot)
    valid_records, decisions = [], []
    all_records = (previous or {}).get("records", [])
    for requirement, scope in current_scopes.items():
        matching = [record for record in all_records if record.get("requirement") == requirement]
        # Reuse the requirement result only as one complete, passing record.
        valid = []
        reasons = []
        for record in matching:
            ok, reason = reusable(record, snapshot, scope)
            if record.get("result") != "pass":
                ok, reason = False, "prior_result_not_passing"
            if ok:
                copied = deepcopy(record)
                copied["evidence_reused"] = True
                copied["from_snapshot_id"] = record.get("snapshot_id")
                copied["snapshot_id"] = snapshot["snapshot_id"]
                valid.append(copied)
            else:
                reasons.append(reason)
        # More than one competing candidate record is ambiguous; require exactly one complete pass.
        if len(valid) == 1:
            valid_records.extend(valid)
        configured = bool(scope["checks"])
        decisions.append({"requirement": requirement,
                          "action": "reuse" if len(valid) == 1 else
                                    "run" if configured else "not_configured",
                          "reason": "scoped evidence remains valid" if len(valid) == 1
                                    else "; ".join(reasons) if reasons else
                                    "no prior evidence" if configured else "no verification checks configured",
                          "relevant_check_ids": [check["id"] for check in scope["checks"]]})
    return valid_records, decisions
