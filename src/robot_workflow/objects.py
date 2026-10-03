"""Declared engineering objects and typed workflow-port projections.

These records describe configuration claims. A matching contract is only
metadata agreement; it is not runtime, simulation, or hardware evidence.
"""

import math

from .contracts import digest

KINDS = {"component", "model", "dataset", "calibration", "test", "requirement", "artifact"}
CONTRACT_FIELDS = ("type", "unit", "frame", "joint_order", "rate_hz")


def _nonempty_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")


def validate(config):
    """Validate optional node kinds, ports, and edge port bindings."""
    nodes = config.get("nodes", [])
    if not isinstance(nodes, list):
        raise ValueError("nodes must be a list")
    port_maps = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue  # Core config validation reports malformed nodes.
        kind = node.get("kind")
        if kind is not None and (not isinstance(kind, str) or kind not in KINDS):
            raise ValueError(f"Unknown engineering object kind on {node.get('id', '<node>')}")
        ports = node.get("ports", [])
        if not isinstance(ports, list):
            raise ValueError(f"{node.get('id', '<node>')}.ports must be a list")
        by_id = {}
        for port in ports:
            if not isinstance(port, dict):
                raise ValueError("Each port must be an object")
            identifier = port.get("id")
            _nonempty_string(identifier, "Port id")
            if identifier in by_id:
                raise ValueError(f"Duplicate port id on {node.get('id', '<node>')}: {identifier}")
            direction = port.get("direction")
            if not isinstance(direction, str) or direction not in {"input", "output"}:
                raise ValueError(f"Port {identifier} direction must be input or output")
            if "label" in port:
                _nonempty_string(port["label"], f"Port {identifier} label")
            contract = port.get("contract", {})
            if not isinstance(contract, dict):
                raise ValueError(f"Port {identifier} contract must be an object")
            unknown = set(contract) - set(CONTRACT_FIELDS)
            if unknown:
                raise ValueError(f"Port {identifier} has unsupported contract fields: {', '.join(sorted(unknown))}")
            for field in ("type", "unit", "frame"):
                if field in contract:
                    _nonempty_string(contract[field], f"Port {identifier} contract.{field}")
            if "joint_order" in contract:
                order = contract["joint_order"]
                if (not isinstance(order, list) or not order or
                        any(not isinstance(item, str) or not item for item in order) or
                        len(order) != len(set(order))):
                    raise ValueError(f"Port {identifier} contract.joint_order must be a nonempty list of unique strings")
            if "rate_hz" in contract:
                rate = contract["rate_hz"]
                if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate <= 0:
                    raise ValueError(f"Port {identifier} contract.rate_hz must be finite and positive")
            by_id[identifier] = port
        port_maps[node.get("id")] = by_id

    node_ids = set(port_maps)
    for edge in config.get("edges", []):
        if not isinstance(edge, dict):
            continue
        has_from, has_to = "from_port" in edge, "to_port" in edge
        if has_from != has_to:
            raise ValueError("Edge must declare both from_port and to_port")
        if not has_from:
            continue
        source, target = edge.get("from"), edge.get("to")
        if source not in node_ids or target not in node_ids:
            continue  # Core config validation reports unknown node references.
        from_port, to_port = edge["from_port"], edge["to_port"]
        if not isinstance(from_port, str) or not isinstance(to_port, str):
            raise ValueError("Edge from_port and to_port must be strings")
        if from_port not in port_maps[source]:
            raise ValueError(f"Unknown from_port {from_port} on {source}")
        if to_port not in port_maps[target]:
            raise ValueError(f"Unknown to_port {to_port} on {target}")
        if port_maps[source][from_port]["direction"] != "output":
            raise ValueError(f"Edge from_port {from_port} on {source} must be output")
        if port_maps[target][to_port]["direction"] != "input":
            raise ValueError(f"Edge to_port {to_port} on {target} must be input")
    return config


def _contract_comparison(source, target):
    left, right = source.get("contract", {}), target.get("contract", {})
    fields = {}
    for field in CONTRACT_FIELDS:
        in_left, in_right = field in left, field in right
        if not in_left or not in_right:
            state = "unknown"
        else:
            state = "match" if digest(left[field]) == digest(right[field]) else "mismatch"
        entry = {"status": state, "source_declared": in_left, "target_declared": in_right}
        if in_left:
            entry["source_digest"] = digest(left[field])
        if in_right:
            entry["target_digest"] = digest(right[field])
        fields[field] = entry
    return fields


def engineering_objects(config):
    """Project declared object kinds, ports, and edge contract comparisons.

    Contract comparisons use canonical digests (so JSON ``true`` and ``1``
    differ). Missing declarations are ``unknown`` and no conversion is inferred.
    """
    validate(config)
    node_index = {node["id"]: node for node in config.get("nodes", [])}
    objects = [{"id": node["id"], "kind": node.get("kind"),
                "ports": node.get("ports", [])} for node in config.get("nodes", [])]
    relations = []
    for edge in config.get("edges", []):
        relation = {"source": edge["from"], "target": edge["to"]}
        if "from_port" in edge:
            relation.update(from_port=edge["from_port"], to_port=edge["to_port"],
                            contract_comparison=_contract_comparison(
                                next(p for p in node_index[edge["from"]].get("ports", []) if p["id"] == edge["from_port"]),
                                next(p for p in node_index[edge["to"]].get("ports", []) if p["id"] == edge["to_port"])))
        relations.append(relation)
    return {"nodes": objects, "relations": relations,
            "evidence_layer": "declared_configuration_metadata",
            "claim_boundary": "Contract agreement does not establish runtime, simulation, or hardware behavior."}
