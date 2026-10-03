"""Run explicit source assertions and bind evidence to a candidate snapshot."""

from .engine import validate_snapshot


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
                passed = left == right
                results.append({"id": assertion["id"], "result": "pass" if passed else "fail",
                                "summary": "Source assertion matches" if passed else "Source assertion mismatch"})
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                results.append({"id": assertion["id"], "result": "fail", "summary": f"Cannot evaluate assertion: {exc}"})
        records.append({
            "requirement": req["id"], "snapshot_id": snapshot["snapshot_id"],
            "fingerprints": {n: snapshot["nodes"][n]["fingerprint"] for n in req["nodes"]},
            "result": "pass" if all(r["result"] == "pass" for r in results) else "fail",
            "summary": f"{sum(r['result'] == 'pass' for r in results)}/{len(results)} source assertions passed; "
                       "this does not establish simulation or hardware behavior",
            "checks": results, "method": "deterministic_source_assertions",
        })
    return {"schema_version": 1, "records": records}


def verify(snapshot, root=None, run_commands=False):
    """Combine all declared checks; skipped command checks remain unknown."""
    from .interface_contracts import check
    from .checks import run_checks

    records = source_assertions(snapshot)["records"] + check(snapshot)["records"]
    if run_commands:
        if root is None:
            raise ValueError("--root is required with --run-checks")
        records.extend(run_checks(snapshot, root)["records"])
    else:
        requirements = {r["id"]: r for r in snapshot["config"].get("requirements", [])}
        for item in snapshot["config"].get("validation_checks", []):
            req = requirements[item["requirement"]]
            records.append({"requirement": req["id"], "snapshot_id": snapshot["snapshot_id"],
                            "fingerprints": {n: snapshot["nodes"][n]["fingerprint"] for n in req["nodes"]},
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
                         "method": "combined_checks", "methods": [r["method"] for r in items]})
    return {"schema_version": 1, "records": combined}
