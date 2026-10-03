"""Run explicit source assertions and bind evidence to a candidate snapshot."""

from .engine import validate_snapshot


def pointer(value, path):
    if not path:
        return value
    if not path.startswith("/"):
        raise ValueError("JSON pointer must start with /")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def source_value(snapshot, source):
    artifact = snapshot["nodes"][source["node"]]["files"][source["path"]]
    return pointer(artifact["facets"], source.get("pointer", ""))


def verify(snapshot):
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
