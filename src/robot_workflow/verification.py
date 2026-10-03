"""Run explicit source assertions and bind evidence to a candidate snapshot."""

from .engine import validate_snapshot
from .contracts import digest


def pointer(value, path):
    if not path:
        return value
    if not path.startswith("/"):
        raise ValueError("JSON pointer must start with /")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not part.isascii() or not part.isdecimal() or (part != "0" and part.startswith("0")):
                raise ValueError("JSON pointer array index must be a nonnegative canonical integer")
            value = value[int(part)]
        else:
            value = value[part]
    return value


def source_value(snapshot, source):
    artifact = snapshot["nodes"][source["node"]]["files"][source["path"]]
    return pointer(artifact["facets"], source.get("pointer", ""))


def source_assertions(snapshot):
    validate_snapshot(snapshot)
    records = []
    for req in snapshot["config"].get("requirements", []):
        if not req.get("assertions"):
            continue
        results = []
        for assertion in req["assertions"]:
            try:
                left = source_value(snapshot, assertion["source"])
                right = source_value(snapshot, assertion["equals_source"]) if "equals_source" in assertion else assertion["equals"]
                passed = digest(left) == digest(right)
                results.append({"id": assertion["id"], "result": "pass" if passed else "fail",
                                "summary": "Source assertion matches" if passed else "Source assertion mismatch"})
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                results.append({"id": assertion["id"], "result": "unknown", "summary": f"Cannot evaluate assertion: {exc}"})
        records.append({
            "requirement": req["id"], "snapshot_id": snapshot["snapshot_id"],
            "fingerprints": {n: snapshot["nodes"][n]["fingerprint"] for n in req["nodes"]},
            "result": "fail" if any(r["result"] == "fail" for r in results) else
                      "unknown" if any(r["result"] == "unknown" for r in results) else "pass",
            "summary": f"{sum(r['result'] == 'pass' for r in results)}/{len(results)} source assertions passed; "
                       "this does not establish simulation or hardware behavior",
            "checks": results, "method": "deterministic_source_assertions",
        })
    return {"schema_version": 1, "records": records}


def verify(snapshot, root=None, run_commands=False, evidence=None):
    """Combine all declared checks; skipped command checks remain unknown."""
    from .interface_contracts import check
    from .checks import run_checks

    from .revalidation import annotate, prepare_previous, scopes

    reused, decisions = prepare_previous(evidence, snapshot)
    configured = scopes(snapshot)
    decision_by_req = {item["requirement"]: item for item in decisions}
    if run_commands and root is None:
        raise ValueError("--root is required with --run-checks")

    records = []
    reused_ids = set()
    for record in reused:
        if decision_by_req.get(record["requirement"], {}).get("action") == "reuse":
            records.append(record)
            reused_ids.add(record["requirement"])

    stale_ids = {rid for rid, scope in configured.items() if scope["checks"] and rid not in reused_ids}
    fresh_records = [record for record in source_assertions(snapshot)["records"] + check(snapshot)["records"]
                     if record["requirement"] in stale_ids]
    records.extend(fresh_records)

    command_ids = {item["requirement"] for item in snapshot["config"].get("validation_checks", [])}
    stale_command_ids = stale_ids & command_ids
    if run_commands and stale_command_ids:
        # Filtering selects which declared requirements execute; the original snapshot and
        # its full configuration remain bound into the runner's before/after drift checks.
        records.extend(run_checks(snapshot, root, requirement_ids=stale_command_ids)["records"])
    elif not run_commands:
        requirements = {r["id"]: r for r in snapshot["config"].get("requirements", [])}
        for item in snapshot["config"].get("validation_checks", []):
            rid = item["requirement"]
            if rid not in stale_command_ids:
                continue
            records.append({"requirement": rid, "snapshot_id": snapshot["snapshot_id"],
                            "fingerprints": {n: snapshot["nodes"][n]["fingerprint"]
                                             for n in requirements[rid]["nodes"]},
                            "result": "unknown", "summary": "Declared command check was not executed; enable --run-checks with --root",
                            "checks": [{"id": item["id"], "result": "unknown", "summary": "Not executed"}],
                            "method": "explicit_command_checks"})
    grouped = {}
    for record in records:
        grouped.setdefault(record["requirement"], []).append(record)
    combined = []
    for requirement, items in grouped.items():
        if len(items) == 1:
            combined.append(items[0])
            continue
        states = {r["result"] for r in items}
        state = "fail" if "fail" in states else "unknown" if "unknown" in states else "pass"
        combined.append({"requirement": requirement, "snapshot_id": snapshot["snapshot_id"],
                         "fingerprints": items[0]["fingerprints"], "result": state,
                         "summary": "; ".join(r["summary"] for r in items),
                         "checks": [c for r in items for c in r.get("checks", [])],
                         "method": "combined_checks", "methods": [r["method"] for r in items],
                         **({"evidence_reused": True,
                            "from_snapshot_id": items[0].get("from_snapshot_id")}
                            if items and all(r.get("evidence_reused") for r in items) else {})})
    annotate(combined, snapshot)
    requirements = {req["id"]: req for req in snapshot["config"].get("requirements", [])}
    for record in combined:
        req = requirements[record["requirement"]]
        incomplete = any(snapshot["nodes"][node].get("coverage") != "declared_sources_scanned" or
                         snapshot["nodes"][node].get("problems") for node in req["nodes"])
        if incomplete and record["result"] != "fail":
            record["result"] = "unknown"
            record["summary"] += "; required source coverage is incomplete"
    # Revalidation describes the final verification decision, including fresh checks.
    for req in snapshot["config"].get("requirements", []):
        rid = req["id"]
        used = [record for record in combined if record["requirement"] == rid]
        decision_by_req[rid] = {"requirement": rid,
                                "action": "reuse" if used and all(r.get("evidence_reused") for r in used)
                                          else "run" if configured[rid]["checks"] else "not_configured",
                                "reason": "scoped evidence remains valid" if used and all(r.get("evidence_reused") for r in used)
                                          else "checks executed for current candidate" if used
                                          else "no verification checks configured",
                                "relevant_check_ids": [c["id"] for c in configured[rid]["checks"]]}
    return {"schema_version": 1, "records": combined,
            "revalidation": [decision_by_req[r["id"]] for r in snapshot["config"].get("requirements", [])]}
