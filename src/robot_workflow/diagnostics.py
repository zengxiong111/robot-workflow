"""Read-only setup diagnostics for a discovered workflow configuration."""

from pathlib import Path
import subprocess

from .engine import snapshot, validate_config


def _git(repo, *args):
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                                text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _issue(severity, node, message, action):
    return {"severity": severity, "node": node, "message": message, "action": action}


def inspect_workflow(config, root):
    """Inspect config and local repositories without changing files or contacting remotes.

    Returns a list of readable issue records with ``severity``, ``node``,
    ``message`` and ``action`` fields. Git inspection is limited to local
    status, branch and upstream metadata; no fetch, pull or push is performed.
    """
    root = Path(root).resolve()
    issues = []
    try:
        validate_config(config)
    except (KeyError, TypeError, ValueError) as exc:
        return {"issues": [_issue("error", None, f"Invalid workflow configuration: {exc}",
                                   "Correct the configuration before taking a snapshot.")]}

    try:
        current = snapshot(config, root, label="diagnostics")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        return {"issues": [_issue("error", None, f"Could not inspect workflow sources: {exc}",
                                   "Check repository paths and local file access, then rerun diagnostics.")]}

    nodes = {node["id"]: node for node in config["nodes"]}
    for node_id, result in current["nodes"].items():
        for problem in result["problems"]:
            path = problem.get("path", problem.get("glob", "artifact"))
            issues.append(_issue("error", node_id,
                                 f"Artifact {path}: {problem['reason']}",
                                 "Restore the artifact or correct its path, parser, or size limit."))
        if not nodes[node_id].get("owner") or nodes[node_id]["owner"] == "unassigned":
            issues.append(_issue("warning", node_id, "No maintainer is assigned.",
                                 "Assign a responsible owner before routing change notifications."))
        parsers = {spec["parser"] for spec in nodes[node_id].get("artifacts", [])}
        if parsers == {"markdown"}:
            issues.append(_issue("warning", node_id,
                                 "Coverage is documentation-only; functional sources were not discovered.",
                                 "Add supported implementation or interface artifacts to assess functional changes."))

    for edge in config.get("edges", []):
        if str(edge.get("basis", "")).startswith("inferred:"):
            issues.append(_issue("warning", edge["to"],
                                 f"Inferred dependency needs review: {edge['from']} → {edge['to']} ({edge.get('reason', 'no reason')}).",
                                 "Confirm the dependency and its watched/emitted facets, or remove the edge."))

    discovery = config.get("discovery", {})
    for note in discovery.get("notes", []):
        issues.append(_issue("info", None, f"Discovery note: {note}",
                             "Review the note and complete any omitted setup information."))

    for repo in config["repositories"]:
        path = (root / repo["path"]).resolve()
        node_id = next((n["id"] for n in config["nodes"] if n["repository"] == repo["id"]), None)
        top = _git(path, "rev-parse", "--show-toplevel")
        if not path.is_dir() or not top or Path(top).resolve() != path:
            continue
        branch = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
        if not branch:
            issues.append(_issue("warning", node_id, f"Repository {repo['path']} is on a detached HEAD.",
                                 "Check out the intended branch before making or publishing changes."))
        upstream = _git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        if branch and not upstream:
            issues.append(_issue("warning", node_id, f"Branch {branch} has no configured upstream.",
                                 "Set an upstream only if this branch is intended to track a remote branch."))
        if _git(path, "status", "--porcelain"):
            issues.append(_issue("warning", node_id, f"Repository {repo['path']} has local changes.",
                                 "Review and preserve local changes before updating or switching branches."))
    return {"issues": issues}
