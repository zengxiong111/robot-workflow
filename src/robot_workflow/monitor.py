"""Repository synchronization and durable, owner-routed workflow monitoring."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .engine import compare, snapshot, validate_config, write_json
from .report import render
from .verification import verify

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt


def _git(path, *args, check=False):
    result = subprocess.run(["git", "-c", f"core.hooksPath={os.devnull}", "-C", str(path), *args], capture_output=True,
                           text=True, timeout=60)
    if check and result.returncode:
        raise RuntimeError(f"{args[0]} failed (exit {result.returncode})")
    return result


def _resolve(root, repo):
    base = Path(root).resolve()
    path = (base / repo["path"]).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Repository {repo['id']} escapes root")
    return path


def sync_repositories(config, root):
    """Fetch and fast-forward eligible existing checkouts; never stash or reset."""
    validate_config(config)
    results = []
    for repo in config.get("repositories", []):
        path, old, new, remote_commit, status, error = _resolve(root, repo), None, None, None, "skipped", None
        try:
            if not path.is_dir() or _git(path, "rev-parse", "--show-toplevel").returncode:
                raise RuntimeError("repository checkout is unavailable")
            top = Path(_git(path, "rev-parse", "--show-toplevel", check=True).stdout.strip()).resolve()
            if top != path:
                raise RuntimeError("path is not the checkout root")
            old = _git(path, "rev-parse", "HEAD", check=True).stdout.strip()
            branch = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
            if branch.returncode:
                status = "detached"
            elif _git(path, "status", "--porcelain", "--untracked-files=all", check=True).stdout:
                status = "dirty"
            else:
                upstream = _git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
                if upstream.returncode:
                    declared = repo.get("ref")
                    if not declared:
                        status = "no_upstream"
                        raise _SkipSync()
                    remote = _git(path, "config", "--get", f"branch.{branch.stdout.strip()}.remote")
                    if remote.returncode:
                        status = "no_upstream"
                        raise _SkipSync()
                    remote_name = remote.stdout.strip()
                    fetch_args = ["fetch", remote_name, declared]
                    target_ref = "FETCH_HEAD"
                else:
                    target_ref = upstream.stdout.strip()
                    remote_name = target_ref.split("/", 1)[0]
                    fetch_args = ["fetch", remote_name]
                fetch = _git(path, *fetch_args)
                if fetch.returncode:
                    raise RuntimeError(f"fetch failed (exit {fetch.returncode})")
                target = _git(path, "rev-parse", target_ref)
                if target.returncode:
                    raise RuntimeError(f"rev-parse fetched ref failed (exit {target.returncode})")
                remote_commit = target.stdout.strip()
                ancestry = _git(path, "merge-base", "--is-ancestor", old, remote_commit)
                if ancestry.returncode:
                    status = "diverged"
                elif old == remote_commit:
                    status = "current"
                else:
                    merged = _git(path, "-c", "core.hooksPath=/dev/null", "merge", "--ff-only", "--no-edit", remote_commit)
                    if merged.returncode:
                        raise RuntimeError(f"merge --ff-only failed (exit {merged.returncode})")
                    status = "updated"
        except _SkipSync:
            pass
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
            status = "error"
            error = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__
        if path.is_dir():
            head = _git(path, "rev-parse", "HEAD")
            if head.returncode == 0:
                new = head.stdout.strip()
        results.append({"repository": repo["id"], "path": repo["path"], "old": old,
                        "remote_commit": remote_commit,
                        "new": new, "status": status, "error": error})
    return results


class _SkipSync(Exception):
    pass


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _owners(config, impacted):
    owner_map = {n["id"]: n.get("owner") or "unassigned" for n in config.get("nodes", [])}
    return sorted({owner_map.get(node, "unassigned") for node, info in impacted.items()
                   if info.get("status") not in {"no_registered_impact", "unchanged"}} or {"unassigned"})


def _event(report, sync, config):
    impacts = report.get("impacts", {})
    failed = [s for s in sync if s["status"] == "error"]
    owners = _owners(config, impacts)
    payload = {"source_commits": {k: v.get("commit") for k, v in report.get("candidate", {}).get("repositories", {}).items()},
               "baseline": report.get("baseline", {}).get("id"), "candidate": report.get("candidate", {}).get("id"),
               "impacts": impacts, "owners": owners, "sync_errors": failed,
               "sync_warnings": report.get("sync_warnings", []),
               "summary": report.get("summary", {})}
    event_id = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"event_id": event_id, "created_at": datetime.now(timezone.utc).isoformat(),
            "title": f"{report.get('project', 'Robot Workflow')}: workflow update", **payload}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _deliver(event, notifications):
    targets = {}
    general_env = notifications.get("webhook_env")
    if general_env:
        targets.setdefault(general_env, set())
    recipients = notifications.get("recipients", {})
    for owner in event["owners"]:
        names = recipients.get(owner, [])
        if isinstance(names, str):
            names = [names]
        for name in names:
            targets.setdefault(name, set()).add(owner)
    if not targets:
        return {"done": {}, "local_only": True, "errors": {}}
    opener = build_opener(_NoRedirect)
    done = dict(event.get("delivery", {}).get("done", {}))
    errors = {}
    delivered_url_hashes = {key.rsplit(":", 1)[1] for key in done if ":" in key}
    grouped = {}
    for env_name, owners in targets.items():
        url = os.environ.get(env_name)
        if not url:
            errors[f"{env_name}:MissingEndpoint"] = "MissingEndpoint"
            continue
        if env_name == general_env:
            owners.update(event.get("owners", []))
        endpoint_hash = hashlib.sha256(url.encode()).hexdigest()
        grouped.setdefault(endpoint_hash, {"url": url, "names": [], "owners": set()})
        grouped[endpoint_hash]["names"].append(env_name)
        grouped[endpoint_hash]["owners"].update(owners)
    for endpoint_hash, group in grouped.items():
        names, owners, url = group["names"], group["owners"], group["url"]
        target_keys = [f"{name}:{endpoint_hash}" for name in names]
        target_key = target_keys[0]
        if endpoint_hash in delivered_url_hashes or target_key in done:
            for key in target_keys:
                done[key] = sorted(set(done.get(key, [])) | owners)
            continue
        body = {k: v for k, v in event.items() if k != "delivery"}
        body["owners"] = sorted(owners)
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        try:
            request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            with opener.open(request, timeout=8) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"HTTP {response.status}")
            for key in target_keys:
                done[key] = sorted(owners)
            delivered_url_hashes.add(endpoint_hash)
        except (OSError, URLError, HTTPError, RuntimeError, ValueError) as exc:
            errors[target_key] = type(exc).__name__
    available = [name for name in targets if os.environ.get(name)]
    return {"done": done, "local_only": not targets, "errors": errors,
            "missing_endpoints": [name for name in targets if not os.environ.get(name)]}


@contextmanager
def _state_lock(path):
    with Path(path).open("a+b") as stream:
        if fcntl is not None:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        else:
            stream.seek(0)
            if stream.read(1) == b"":
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def watch_once(config, root, state_dir, update=True, notify=True):
    """Run one snapshot cycle. State and reports must live outside the source root."""
    validate_config(config)
    root, state = Path(root).resolve(), Path(state_dir).resolve()
    for repo in config.get("repositories", []):
        repo_path = _resolve(root, repo)
        if state == repo_path or state.is_relative_to(repo_path):
            raise ValueError("state_dir must not be inside a registered repository")
    if state == root or state.is_relative_to(root):
        raise ValueError("state_dir must be outside the repository root")
    state.mkdir(parents=True, exist_ok=True)
    lock_path = state / ".watch.lock"
    with _state_lock(lock_path):
        identity_path = state / "root-identity.json"
        identity = {"root": str(root)}
        if identity_path.exists():
            saved_identity = json.loads(identity_path.read_text(encoding="utf-8"))
            if saved_identity != identity:
                raise ValueError("state_dir is already bound to a different repository root")
        else:
            _atomic_json(identity_path, identity)
        return _watch_once_locked(config, root, state, update, notify)


def _watch_once_locked(config, root, state, update, notify):
    observed = snapshot(config, root, "pre-sync")
    baseline_path = state / "baseline.json"
    first = not baseline_path.exists()
    if first:
        write_json(baseline_path, observed)
        before = observed
    else:
        before = json.loads(baseline_path.read_text(encoding="utf-8"))
        if before.get("config_hash") != observed.get("config_hash"):
            raise ValueError("Configuration changed since baseline; review config changes before syncing repositories")
    sync = sync_repositories(config, root) if update else []
    current = snapshot(config, root, "watch")
    report = compare(before, current, verify(current))
    stale_statuses = {s["repository"]: s["status"] for s in sync
                      if s["status"] not in {"updated", "current"}}
    if stale_statuses:
        node_by_id = {n["id"]: n for n in config.get("nodes", [])}
        unknown_nodes = {node_id for node_id, node in node_by_id.items()
                         if node["repository"] in stale_statuses}
        outgoing = {}
        for edge in config.get("edges", []):
            outgoing.setdefault(edge["from"], []).append(edge["to"])
        pending_nodes = list(unknown_nodes)
        while pending_nodes:
            for downstream in outgoing.get(pending_nodes.pop(), []):
                if downstream not in unknown_nodes:
                    unknown_nodes.add(downstream)
                    pending_nodes.append(downstream)
        for node_id in unknown_nodes:
            report["impacts"][node_id]["status"] = "unknown"
        for requirement in report["requirements"]:
            if set(requirement.get("nodes", [])) & unknown_nodes:
                requirement["state"] = "unknown"
                requirement["reason"] = "Remote source freshness cannot be confirmed because repository synchronization did not complete"
        report["summary"]["unknown"] = sum(info["status"] == "unknown" for info in report["impacts"].values())
    report["sync"] = sync
    report["sync_warnings"] = [{"repository": s["repository"], "status": s["status"], "error": s["error"]}
                                for s in sync if s["status"] not in {"updated", "current"}]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report["sync"] = sync
    report_path, html_path = state / f"report-{stamp}.json", state / f"report-{stamp}.html"
    from .cases import sync_cases
    report["case_state"] = sync_cases(report, state / "cases.json")
    write_json(report_path, report)
    render(report, html_path)
    event = _event(report, sync, config)
    meaningful = bool(report["summary"]["semantic_changes"] or report["summary"]["unknown"]
                      or report["summary"]["unregistered_changes"] or report["sync_warnings"])
    events_path, queue_path = state / "events.jsonl", state / "notification-queue.json"
    seen = set()
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(line)["event_id"])
            except (ValueError, KeyError):
                continue
    queued = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else []
    emitted = []
    if meaningful and event["event_id"] not in seen:
        event["report"] = str(report_path)
        with events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        queued.append({"event": event, "attempts": 0, "delivery": {"done": {}}})
        emitted.append(event["event_id"])
    pending = []
    if notify:
        for item in queued:
            delivery = {"delivery": item.get("delivery", {})}
            result = _deliver({**item["event"], **delivery}, config.get("notifications", {}))
            item["delivery"] = {"done": result["done"]}
            if result["errors"]:
                item["attempts"] += 1
                item["last_error"] = result["errors"]
                pending.append(item)
    else:
        pending = queued
    _atomic_json(queue_path, pending)
    # Record post-sync source state only after the report and its events are durable.
    write_json(baseline_path, current)
    return {"baseline": first, "snapshot_id": current["snapshot_id"], "sync": sync,
            "report": str(report_path), "html": str(html_path), "events": emitted,
            "pending_notifications": len(pending)}


def watch(config, root, state_dir, interval=30, once=False, no_update=False):
    """Watch continuously, printing concise cycle status; Ctrl-C exits cleanly."""
    if not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval <= 0 or not float(interval) < float("inf"):
        raise ValueError("interval must be a positive finite number")
    while True:
        result = watch_once(config, root, state_dir, update=not no_update)
        print(json.dumps({k: result.get(k) for k in ("baseline", "snapshot_id", "sync", "events", "pending_notifications")},
                         ensure_ascii=False), flush=True)
        if once:
            return result
        time.sleep(interval)
