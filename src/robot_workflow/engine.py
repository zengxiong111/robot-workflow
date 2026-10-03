"""Versioned snapshots and facet-aware, explainable impact propagation."""

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from .contracts import PARSERS, digest, extract


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_config(config):
    if config.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    repos = config.get("repositories", [])
    nodes = config.get("nodes", [])
    for label, items in (("repository", repos), ("node", nodes), ("requirement", config.get("requirements", []))):
        ids = [x["id"] for x in items]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate {label} id")
    repo_ids = {r["id"] for r in repos}
    node_ids = {n["id"] for n in nodes}
    for repo in repos:
        path = Path(repo["path"])
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("Repository path must be a nonempty relative path inside --root")
    for node in nodes:
        if node["repository"] not in repo_ids:
            raise ValueError(f"Unknown repository for {node['id']}")
        for artifact in node.get("artifacts", []):
            pattern = Path(artifact["glob"])
            if pattern.is_absolute() or ".." in pattern.parts or ".git" in pattern.parts:
                raise ValueError("Artifact glob must stay inside its repository and outside .git")
            if artifact["parser"] not in PARSERS:
                raise ValueError("Unsupported parser")
        if not node.get("artifacts"):
            raise ValueError(f"Node {node['id']} needs at least one artifact")
        readiness = node.get("readiness")
        if readiness is not None and (not isinstance(readiness, dict) or readiness.get("state") not in {
                "implemented", "partial", "planned", "unknown"}):
            raise ValueError("Readiness must be a record with implemented/partial/planned/unknown state")
    for edge in config.get("edges", []):
        if edge["from"] not in node_ids or edge["to"] not in node_ids:
            raise ValueError("Edge references unknown node")
        if not edge.get("watch") or not edge.get("emits") or not edge.get("reason"):
            raise ValueError("Edge needs watch, emits and reason")
    for req in config.get("requirements", []):
        if not set(req["nodes"]) <= node_ids:
            raise ValueError("Requirement references unknown node")
    return config


def git_value(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)
    return result.stdout.strip() if result.returncode == 0 else None


def inventory(root, is_git):
    """Track out-of-contract Git changes too, including sparse-unavailable binary blobs."""
    entries = {}
    if is_git:
        tree = git_value(root, "ls-tree", "-rz", "HEAD") or ""
        for entry in tree.split("\0"):
            if not entry:
                continue
            metadata, path = entry.split("\t", 1)
            mode, kind, sha = metadata.split()
            entries[path] = {"git_blob": sha, "mode": mode}
        untracked = git_value(root, "ls-files", "--others", "--exclude-standard", "-z") or ""
        for path in untracked.split("\0"):
            if path:
                entries[path] = {"untracked": True}
    else:
        for path in root.rglob("*") if root.is_dir() else []:
            if path.is_file() and ".git" not in path.parts:
                entries[path.relative_to(root).as_posix()] = {}
    for relative, item in entries.items():
        path = root / relative
        resolved = path.resolve()
        if path.is_file() and resolved.is_relative_to(root) and ".git" not in resolved.relative_to(root).parts:
            if path.stat().st_size <= 4_000_000:
                item["working_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                item.update(working_bytes=path.stat().st_size, working_mtime_ns=path.stat().st_mtime_ns,
                            content_coverage="unhashed_large_file")
    return entries


def snapshot(config, root, label="baseline"):
    validate_config(config)
    config = deepcopy(config)
    root = Path(root).resolve()
    repositories = {}
    for repo in config["repositories"]:
        path = (root / repo["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Repository symlink escapes --root")
        available = path.is_dir()
        # Require this directory to be the actual checkout root, not a containing project's checkout.
        top = git_value(path, "rev-parse", "--show-toplevel") if available else None
        is_git = top is not None and Path(top).resolve() == path
        repositories[repo["id"]] = {
            **repo, "available": available,
            "commit": git_value(path, "rev-parse", "HEAD") if is_git else None,
            "dirty": bool(git_value(path, "status", "--porcelain")) if is_git else None,
            "git_checkout": is_git,
            "inventory": inventory(path, is_git),
        }
    nodes = {}
    for node in config["nodes"]:
        repo = repositories[node["repository"]]
        repo_root = (root / repo["path"]).resolve()
        artifacts, problems = {}, []
        for spec in node["artifacts"]:
            matches = sorted(p for p in repo_root.glob(spec["glob"]) if p.is_file()) if repo["available"] else []
            if not matches:
                problems.append({"glob": spec["glob"], "reason": "No matching source files"})
            for path in matches:
                relative = path.relative_to(repo_root).as_posix()
                try:
                    resolved = path.resolve()
                    if not resolved.is_relative_to(repo_root) or ".git" in resolved.relative_to(repo_root).parts:
                        raise ValueError("Source escapes repository or points into .git")
                    size = path.stat().st_size
                    if size > spec.get("max_bytes", 4_000_000):
                        raise ValueError("Source exceeds max_bytes; increase limit explicitly")
                    data = path.read_bytes()
                    facets = extract(data, spec["parser"])
                    if "facet" in spec:
                        facets = {spec["facet"]: facets}
                    artifacts[relative] = {
                        "sha256": hashlib.sha256(data).hexdigest(), "bytes": size,
                        "parser": spec["parser"], "facets": facets,
                        "facet_hashes": {key: digest(value) for key, value in facets.items()},
                    }
                except (ValueError, SyntaxError, OSError) as exc:
                    problems.append({"path": relative, "reason": str(exc)})
        nodes[node["id"]] = {
            **node, "files": artifacts, "problems": problems,
            "coverage": "unknown" if problems else "declared_sources_scanned",
            "fingerprint": digest({p: f["sha256"] for p, f in artifacts.items()}),
        }
    result = {
        "schema_version": 1, "kind": "snapshot", "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": config, "config_hash": digest(config),
        "repositories": repositories, "nodes": nodes,
    }
    result["snapshot_id"] = snapshot_id(result)
    return result


def snapshot_id(value):
    return digest({"config_hash": value["config_hash"], "repositories": value["repositories"],
                   "nodes": value["nodes"]})


def validate_snapshot(value):
    if value.get("kind") != "snapshot" or value.get("schema_version") != 1:
        raise ValueError("Expected a schema_version=1 snapshot")
    validate_config(value["config"])
    if digest(value["config"]) != value["config_hash"] or snapshot_id(value) != value["snapshot_id"]:
        raise ValueError("Snapshot integrity mismatch")


def changes_at(before, after, prefix="", limit=60):
    """Readable leaf changes; retain counts even when display is truncated."""
    output = []
    if before == after:
        return output
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            path = f"{prefix}/{key}"
            if key not in before:
                output.append({"path": path, "type": "added", "before": None, "after": after[key]})
            elif key not in after:
                output.append({"path": path, "type": "removed", "before": before[key], "after": None})
            else:
                output.extend(changes_at(before[key], after[key], path, limit))
    else:
        output.append({"path": prefix or "/", "type": "changed", "before": before, "after": after})
    return output


def compare(before, after, evidence=None):
    validate_snapshot(before)
    validate_snapshot(after)
    if before["config_hash"] != after["config_hash"]:
        raise ValueError("Configs differ: compare sources with one graph, then review graph edits separately")
    config = after["config"]
    deltas = []
    starts = []
    for node_id, old in before["nodes"].items():
        new = after["nodes"][node_id]
        for path in sorted(old["files"].keys() | new["files"].keys()):
            left, right = old["files"].get(path), new["files"].get(path)
            if left == right:
                continue
            lfacets, rfacets = (left or {}).get("facets", {}), (right or {}).get("facets", {})
            facets = sorted(k for k in lfacets.keys() | rfacets.keys() if lfacets.get(k) != rfacets.get(k))
            if not facets and left and right and left["sha256"] == right["sha256"]:
                continue
            details = changes_at(lfacets, rfacets)
            deltas.append({"node": node_id, "path": path, "facets": facets,
                           "type": "added" if left is None else "removed" if right is None else "modified",
                           "before_sha256": (left or {}).get("sha256"),
                           "after_sha256": (right or {}).get("sha256"),
                           "semantic": bool(facets), "details": details[:60], "detail_count": len(details)})
            for facet in facets:
                starts.append((node_id, facet))
    unregistered = []
    for repo_id, repo in after["repositories"].items():
        old_inventory = before["repositories"][repo_id]["inventory"]
        new_inventory = repo["inventory"]
        registered = {p for n in config["nodes"] if n["repository"] == repo_id
                      for p in before["nodes"][n["id"]]["files"].keys() | after["nodes"][n["id"]]["files"].keys()}
        for path in sorted(old_inventory.keys() | new_inventory.keys()):
            if path not in registered and old_inventory.get(path) != new_inventory.get(path):
                unregistered.append({"repository": repo_id, "path": path,
                                     "status": "unknown", "reason": "Changed outside registered semantic contracts"})
    impacts = {node_id: {"status": "no_registered_impact", "paths": [], "checks": node.get("checks", [])}
               for node_id, node in after["nodes"].items()}
    adjacency = {}
    for index, edge in enumerate(config.get("edges", [])):
        adjacency.setdefault(edge["from"], []).append((index, edge))
    # Traverse each seed separately so explanations retain independent source changes.
    for seed_node, seed_facet in sorted(set(starts)):
        queue = deque([(seed_node, seed_facet, [seed_node], [])])
        visited = set()
        while queue:
            node_id, facet, chain, reasons = queue.popleft()
            target = impacts[node_id]
            target["status"] = "changed" if node_id == seed_node else (
                "changed" if target["status"] == "changed" else "potential_impact")
            explanation = {"origin": seed_node, "facet": seed_facet, "nodes": chain, "reasons": reasons}
            if explanation not in target["paths"]:
                target["paths"].append(explanation)
            if (node_id, facet) in visited:
                continue
            visited.add((node_id, facet))
            for _, edge in adjacency.get(node_id, []):
                if facet in edge["watch"] or "*" in edge["watch"]:
                    for emitted in edge["emits"]:
                        if edge["to"] not in chain:
                            queue.append((edge["to"], emitted, chain + [edge["to"]], reasons + [edge["reason"]]))
    # Missing coverage is a seed, not a silent green state. Propagate through every declared edge.
    unknown = {n for n in after["nodes"] if after["nodes"][n]["problems"] or before["nodes"][n]["problems"]}
    queue = deque(unknown)
    while queue:
        current = queue.popleft()
        for _, edge in adjacency.get(current, []):
            if edge["to"] not in unknown:
                unknown.add(edge["to"])
                queue.append(edge["to"])
    for node_id in unknown:
        impacts[node_id]["status"] = "unknown"
    readiness = {}
    for node_id, node in after["nodes"].items():
        record = node.get("readiness", {"state": "unknown", "summary": "No implementation review recorded"})
        state = record["state"]
        repo = after["repositories"][node["repository"]]
        if node["problems"]:
            state = "unknown"
        elif state != "unknown":
            if not record.get("reviewed_fingerprint") or not record.get("reviewed_commit"):
                state = "unverified"
            elif record["reviewed_fingerprint"] != node["fingerprint"] or record["reviewed_commit"] != repo["commit"]:
                state = "stale"
        readiness[node_id] = {**record, "state": state, "scope": "Maintainer source review; not execution evidence"}
    requirements = []
    records = (evidence or {}).get("records", [])
    for req in config.get("requirements", []):
        state = "unverified"
        reason = "No current evidence recorded"
        matching = [r for r in records if r.get("requirement") == req["id"]]
        if matching:
            record = matching[-1]
            valid = record.get("snapshot_id") == after["snapshot_id"] and all(
                record.get("fingerprints", {}).get(n) == after["nodes"][n]["fingerprint"] for n in req["nodes"])
            if valid and record.get("result") in {"pass", "fail"}:
                state = "verified" if record["result"] == "pass" else "failed"
                reason = record.get("summary", "Recorded check result")
            else:
                state, reason = "stale", "Evidence does not bind to this candidate snapshot and source fingerprints"
        if any(impacts[n]["status"] == "unknown" for n in req["nodes"]):
            state, reason = "unknown", "Required source coverage is incomplete"
        requirements.append({**req, "state": state, "reason": reason})
    return {
        "schema_version": 1, "kind": "impact_report", "project": config.get("project", "Robot Workflow"),
        "baseline": {"id": before["snapshot_id"], "label": before["label"], "repositories": {
            key: {k: v for k, v in repo.items() if k != "inventory"} for key, repo in before["repositories"].items()}},
        "candidate": {"id": after["snapshot_id"], "label": after["label"], "repositories": {
            key: {k: v for k, v in repo.items() if k != "inventory"} for key, repo in after["repositories"].items()}},
        "config": config,
        "coverage": {n: {"baseline": before["nodes"][n]["problems"], "candidate": after["nodes"][n]["problems"]}
                     for n in after["nodes"]},
        "changes": deltas, "impacts": impacts, "readiness": readiness, "requirements": requirements,
        "unregistered_changes": unregistered,
        "summary": {"changed_files": len(deltas), "semantic_changes": sum(d["semantic"] for d in deltas),
                    "potential_impact": sum(i["status"] == "potential_impact" for i in impacts.values()),
                    "unknown": len(unknown), "unregistered_changes": len(unregistered)},
        "boundary": "Candidate upgrade analysis over registered dependencies; no automatic modification of pinned deployments. "
                    "No registered impact is not a compatibility proof. Recorded evidence is not a hardware certification.",
    }
