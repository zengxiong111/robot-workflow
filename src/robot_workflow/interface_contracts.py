"""Compare explicitly selected values across producer and consumer sources.

This module checks declared source interfaces only. It assigns no robotics
meaning to field names such as ``units`` or ``frame``.
"""

from pathlib import PurePosixPath

from .contracts import digest

def _valid_pointer(value):
    if not isinstance(value, str):
        return False
    if value == "":
        return True
    if not value.startswith("/"):
        return False
    # RFC 6901 permits only ~0 and ~1 escapes.
    return all("~" not in token.replace("~0", "").replace("~1", "")
               for token in value[1:].split("/"))


def _validate_source(source, label):
    if not isinstance(source, dict):
        raise ValueError(f"{label} must be an object")
    if not isinstance(source.get("node"), str) or not source["node"]:
        raise ValueError(f"{label}.node must be a nonempty string")
    path = source.get("path")
    if not isinstance(path, str) or not path or "\\" in path:
        raise ValueError(f"{label}.path must be a nonempty relative POSIX path")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or "." in parsed.parts:
        raise ValueError(f"{label}.path must stay inside its source repository")
    if not _valid_pointer(source.get("pointer", "")):
        raise ValueError(f"{label}.pointer is not a valid JSON pointer")


def validate(config):
    """Validate ``config.interface_contracts`` and return the config."""
    contracts = config.get("interface_contracts", [])
    if not isinstance(contracts, list):
        raise ValueError("interface_contracts must be a list")
    requirements = {r["id"]: set(r["nodes"]) for r in config.get("requirements", [])}
    nodes = {n["id"] for n in config.get("nodes", [])}
    ids = set()
    for item in contracts:
        if not isinstance(item, dict):
            raise ValueError("Each interface contract must be an object")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("Interface contract id must be a nonempty string")
        if identifier in ids:
            raise ValueError(f"Duplicate interface contract id: {identifier}")
        ids.add(identifier)
        requirement = item.get("requirement")
        if requirement not in requirements:
            raise ValueError(f"Interface contract {identifier} references an unknown requirement")
        _validate_source(item.get("producer"), f"{identifier}.producer")
        _validate_source(item.get("consumer"), f"{identifier}.consumer")
        for label, endpoint in (("producer", item["producer"]), ("consumer", item["consumer"])):
            if endpoint["node"] not in nodes:
                raise ValueError(f"{identifier}.{label} references an unknown node")
            if endpoint["node"] not in requirements[requirement]:
                raise ValueError(f"{identifier}.{label} node is outside requirement {requirement}")
        fields = item.get("fields", [])
        if not isinstance(fields, list):
            raise ValueError(f"{identifier}.fields must be a list")
        field_names = set()
        for field in fields:
            if not isinstance(field, dict):
                raise ValueError(f"{identifier} field must be an object")
            name, pointer = field.get("name"), field.get("pointer")
            if not isinstance(name, str) or not name:
                raise ValueError(f"{identifier} field name must be a nonempty string")
            if name in field_names:
                raise ValueError(f"{identifier} has duplicate field name: {name}")
            field_names.add(name)
            if not _valid_pointer(pointer):
                raise ValueError(f"{identifier}.{name} pointer is not a valid JSON pointer")
    return config


def _field_value(value, pointer):
    # source_value owns JSON-pointer traversal semantics; applying it to a
    # minimal synthetic artifact keeps one traversal implementation.
    from .verification import pointer as resolve_pointer
    return resolve_pointer(value, pointer)


def check(snapshot):
    """Return snapshot-bound evidence records for declared interface contracts."""
    from .engine import validate_snapshot
    from .verification import source_value

    validate_snapshot(snapshot)
    config = snapshot["config"]
    validate(config)
    grouped = {}
    for contract in config.get("interface_contracts", []):
        grouped.setdefault(contract["requirement"], []).append(contract)

    records = []
    for requirement, contracts in grouped.items():
        req = next(r for r in config["requirements"] if r["id"] == requirement)
        checks = []
        for contract in contracts:
            try:
                producer = source_value(snapshot, contract["producer"])
                consumer = source_value(snapshot, contract["consumer"])
                fields = contract.get("fields", [])
                comparisons = fields or [{"name": "value", "pointer": ""}]
                for field in comparisons:
                    name = field["name"]
                    source_context = {"producer": contract["producer"],
                                      "consumer": contract["consumer"],
                                      "field_pointer": field["pointer"]}
                    try:
                        left = _field_value(producer, field["pointer"])
                        right = _field_value(consumer, field["pointer"])
                    except (KeyError, IndexError, TypeError, ValueError) as exc:
                        checks.append({"id": f"{contract['id']}:{name}", "result": "unknown",
                                       "summary": f"Cannot read selected field: {exc}", **source_context})
                        continue
                    passed = digest(left) == digest(right)
                    checks.append({"id": f"{contract['id']}:{name}",
                                   "result": "pass" if passed else "fail",
                                   "summary": "Selected interface field matches" if passed else
                                   "Selected interface field mismatch", **source_context})
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                checks.append({"id": contract["id"], "result": "unknown",
                               "summary": f"Cannot evaluate interface source: {exc}"})
        results = [item["result"] for item in checks]
        result = "fail" if "fail" in results else "unknown" if "unknown" in results else "pass"
        fingerprints = {node: snapshot["nodes"][node]["fingerprint"] for node in req["nodes"]}
        records.append({
            "requirement": requirement,
            "snapshot_id": snapshot["snapshot_id"],
            "fingerprints": fingerprints,
            "result": result,
            "summary": f"{results.count('pass')}/{len(results)} declared interface checks passed; "
                       "this does not establish simulation or hardware behavior",
            "checks": checks,
            "method": "interface_contracts",
        })
    return {"schema_version": 1, "records": records}
