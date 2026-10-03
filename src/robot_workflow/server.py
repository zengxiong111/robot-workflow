"""Loopback-only local engineering console for Robot Workflow."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import os
import socket
from copy import deepcopy
from pathlib import Path
import json
import re
import secrets
import signal
import shutil
import subprocess
import threading
import time
from urllib.parse import urlparse

from . import engine
from .cases import _state_lock as state_lock, sync_cases, update_case
from .discovery import discover
from .report import render
from .verification import verify

MAX_BODY = 1_000_000
MAX_CLONE_SECONDS = 300
_MUTATION_LOCK = threading.Lock()


def _loopback(host):
    import ipaddress
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def _safe_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _safe_repo_path(root, rel):
    if not isinstance(rel, str) or not rel or "\\" in rel:
        raise ValueError("Repository path must be a nonempty relative path")
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts or ".git" in candidate.parts:
        raise ValueError("Repository path cannot contain traversal or .git")
    destination = (root / candidate).resolve()
    if not destination.is_relative_to(root):
        raise ValueError("Repository destination escapes root")
    # Also reject an existing symlink component even if its resolved target is inside root.
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Repository path cannot pass through a symlink")
    return destination


def _remove_import_tree(destination):
    """Remove only a newly created clone destination, never follow its symlink."""
    if destination.is_symlink():
        destination.unlink()
    elif destination.is_dir():
        shutil.rmtree(destination)


def _latest(state_dir, name):
    path = state_dir / name
    return _safe_json(path)


def _prior_verification(state_dir, config_hash):
    directory = state_dir / "verification"
    candidates = sorted(directory.glob(f"{config_hash}-*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True) if directory.is_dir() else []
    return _safe_json(candidates[0]) if candidates else _latest(state_dir, "verification.json")


def merge_discovery(existing, found):
    """Append discoveries while retaining every user-authored workflow record."""
    if not existing:
        return found
    merged = deepcopy(existing)
    repo_ids = {repo["id"] for repo in merged.get("repositories", [])}
    node_ids = {node["id"] for node in merged.get("nodes", [])}
    merged.setdefault("repositories", []).extend(
        deepcopy(repo) for repo in found.get("repositories", []) if repo["id"] not in repo_ids)
    merged.setdefault("nodes", []).extend(
        deepcopy(node) for node in found.get("nodes", []) if node["id"] not in node_ids)
    known_directions = {(edge["from"], edge["to"]) for edge in merged.get("edges", [])}
    merged.setdefault("edges", []).extend(
        deepcopy(edge) for edge in found.get("edges", [])
        if (edge["from"], edge["to"]) not in known_directions)
    merged["discovery"] = found.get("discovery", merged.get("discovery", {}))
    return merged


def _preserve_view(report, state_dir):
    previous = _latest(state_dir, "report.json")
    view = (previous or {}).get("view") or _latest(state_dir, "view.json")
    if not isinstance(view, dict):
        return report
    node_ids = {node["id"] for node in report.get("config", {}).get("nodes", [])}
    positions = view.get("positions", {})
    if isinstance(positions, dict) and not set(positions) <= node_ids:
        return report
    kept = deepcopy(view)
    if kept.get("selected") not in node_ids:
        kept.pop("selected", None)
    report["view"] = kept
    _atomic_json(Path(state_dir) / "view.json", kept)
    return report


def _clone(argv):
    """Clone with bounded runtime and terminate the owned process group on timeout."""
    process = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=(os.name == "posix"))
    try:
        code = process.wait(timeout=MAX_CLONE_SECONDS)
    except subprocess.TimeoutExpired as exc:
        _stop_clone(process)
        raise RuntimeError("Git clone exceeded the 300 second limit and was stopped") from exc
    except BaseException:
        _stop_clone(process)
        raise
    if code:
        raise RuntimeError(f"Git clone failed (exit {code}); confirm the URL and branch")


def _stop_clone(process):
    """Terminate the complete owned process group, even if its leader exits first."""
    if os.name != "posix":  # pragma: no cover - Windows
        if process.poll() is None:
            process.kill()
        process.wait()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def serve(config_path, root, state_dir, host="127.0.0.1", port=8780):
    """Serve the local console until interrupted. Paths are fixed by the caller."""
    if not _loopback(host):
        raise ValueError("The console can bind only to a loopback address")
    root, state_dir = Path(root).resolve(), Path(state_dir).resolve()
    config_path = Path(config_path).resolve()
    if not root.is_dir():
        raise ValueError("Workflow root must be an existing directory")
    if config_path.is_relative_to(root) or state_dir.is_relative_to(root):
        raise ValueError("Configuration and console state must be outside the inspected root")
    page_path = Path(__file__).with_name("console.html")
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        server_version = "RobotWorkflowConsole/1"
        sys_version = ""

        def log_message(self, fmt, *args):
            pass

        def _headers_ok(self):
            raw_host = self.headers.get("Host", "")
            host_header = raw_host[1:raw_host.find("]")] if raw_host.startswith("[") and "]" in raw_host else raw_host.rsplit(":", 1)[0] if raw_host.count(":") == 1 else raw_host
            if not _loopback(host_header):
                self._send(403, {"error": "Host must be localhost or a loopback address"})
                return False
            origin = self.headers.get("Origin")
            if origin:
                parsed = urlparse(origin)
                if parsed.scheme != "http" or not parsed.hostname or not _loopback(parsed.hostname) or parsed.netloc != self.headers.get("Host"):
                    self._send(403, {"error": "Origin must match this local console"})
                    return False
            return True

        def _send(self, status, value, content_type="application/json; charset=utf-8", extra_headers=None):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            for name, header_value in (extra_headers or {}).items():
                self.send_header(name, header_value)
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = self.headers.get("Content-Length", "")
            if not length.isdecimal() or int(length) > MAX_BODY:
                raise ValueError("Request body missing or exceeds 1 MB")
            return json.loads(self.rfile.read(int(length)).decode("utf-8"))

        def _config(self):
            if not config_path.is_file():
                raise ValueError("Workflow is not initialized. Review discovered repositories and save the configuration first.")
            return engine.validate_config(_safe_json(config_path))

        def _mutate(self, action):
            if not self._headers_ok():
                return
            if self.headers.get("X-Workflow-CSRF") != token:
                self._send(403, {"error": "Session token missing or invalid; reload the console"})
                return
            if not _MUTATION_LOCK.acquire(blocking=False):
                self._send(409, {"error": "Another console update is in progress; retry shortly"})
                return
            try:
                with state_lock(state_dir / "console-mutation.lock"):
                    action()
            except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
                self._send(400, {"error": str(exc)})
            except Exception:
                self._send(500, {"error": "Operation failed unexpectedly; inspect the input and try again"})
            finally:
                _MUTATION_LOCK.release()

        def do_GET(self):
            try:
                self._do_get()
            except (ValueError, KeyError, OSError, RuntimeError, json.JSONDecodeError) as exc:
                self._send(400, {"error": str(exc)})
            except Exception:
                self._send(500, {"error": "Could not load local workflow data; check the configured files and retry"})

        def _do_get(self):
            if not self._headers_ok(): return
            route = urlparse(self.path).path
            if route == "/":
                page = page_path.read_text(encoding="utf-8").replace("__CSRF__", token).replace("__ROOT__", html.escape(root.name))
                return self._send(200, page.encode(), "text/html; charset=utf-8", {
                    "X-Frame-Options": "DENY",
                    "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                })
            if route == "/api/state":
                config = _safe_json(config_path)
                return self._send(200, {"initialized": config is not None, "root": root.name,
                    "config": config, "snapshot": _latest(state_dir, "current.json"),
                    "report": _latest(state_dir, "report.json"),
                    "verification": _latest(state_dir, "verification.json"),
                    "cases": _latest(state_dir, "cases.json") or {"cases": []},
                    "report_url": "/report" if (state_dir / "report.html").is_file() else None})
            if route == "/api/discover":
                try:
                    found = discover(root)
                    return self._send(200, merge_discovery(_safe_json(config_path), found))
                except (ValueError, OSError, RuntimeError) as exc:
                    return self._send(400, {"error": str(exc)})
            if route == "/report":
                path = state_dir / "report.html"
                return self._send(200, path.read_bytes(), "text/html; charset=utf-8") if path.is_file() else self._send(404, {"error": "No report yet; refresh the workflow"})
            self._send(404, {"error": "Unknown endpoint"})

        def do_POST(self):
            route = urlparse(self.path).path
            def run():
                data = self._body()
                if route == "/api/config":
                    config = engine.validate_config(data.get("config"))
                    for repo in config["repositories"]:
                        _safe_repo_path(root, repo["path"])
                    _atomic_json(config_path, config)
                    config_hash = engine.digest(config)
                    baseline_path = state_dir / "baselines" / f"{config_hash}.json"
                    if not baseline_path.exists():
                        baseline = engine.snapshot(config, root, label="baseline after reviewed configuration")
                        engine.write_json(baseline_path, baseline)
                    # Retain the conventional pointer for older readers; snapshots and reports are also archived by identity.
                    engine.write_json(state_dir / "baseline.json", engine.read_json(baseline_path))
                    return self._send(200, {"saved": True, "config": config})
                if route == "/api/import":
                    data_url, branch, rel = data.get("url", ""), data.get("branch", ""), data.get("path", "")
                    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", data_url):
                        raise ValueError("Use a GitHub HTTPS repository URL")
                    if branch and (len(branch) > 200 or branch.startswith("-") or ".." in branch or any(c.isspace() for c in branch)):
                        raise ValueError("Branch name is invalid")
                    destination = _safe_repo_path(root, rel)
                    if destination.exists():
                        raise ValueError("Destination already exists")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    argv = ["git", "-c", f"core.hooksPath={os.devnull}", "clone", "--depth", "2"]
                    if branch: argv += ["--branch", branch]
                    argv += ["--", data_url, str(destination)]
                    try:
                        _clone(argv)
                        git_dir = destination / ".git"
                        if (destination.is_symlink() or not destination.resolve().is_relative_to(root) or
                                git_dir.is_symlink() or not git_dir.is_dir() or
                                not git_dir.resolve().is_relative_to(destination.resolve())):
                            raise ValueError("Imported checkout has an unsafe destination or .git path")
                    except Exception:
                        _remove_import_tree(destination)
                        raise
                    return self._send(200, {"imported": True, "path": rel})
                if route == "/api/refresh":
                    config = self._config()
                    current = engine.snapshot(config, root, label="current")
                    current_path = state_dir / "snapshots" / f"{current['snapshot_id']}.json"
                    engine.write_json(current_path, current)
                    baseline_path = state_dir / "baselines" / f"{current['config_hash']}.json"
                    baseline_reset = not baseline_path.exists()
                    if baseline_reset:
                        engine.write_json(baseline_path, current)
                    baseline = engine.read_json(baseline_path)
                    if baseline.get("config_hash") != current["config_hash"]:
                        baseline = current
                        engine.write_json(baseline_path, baseline)
                        baseline_reset = True
                    prior_evidence = _prior_verification(state_dir, current["config_hash"])
                    report = engine.compare(baseline, current, evidence=prior_evidence)
                    report = _preserve_view(report, state_dir)
                    from .report import render as render_report
                    engine.write_json(state_dir / "current.json", current)
                    case_state = sync_cases(report, state_dir / "cases.json")
                    report["case_state"] = case_state
                    engine.write_json(state_dir / "report.json", report)
                    engine.write_json(state_dir / "reports" / f"{current['config_hash']}-{current['snapshot_id']}.json", report)
                    render_report(report, state_dir / "report.html")
                    return self._send(200, {"snapshot": current, "report": report, "report_url": "/report",
                                            "baseline_reset": baseline_reset})
                if route == "/api/check":
                    config = self._config()
                    checked = engine.snapshot(config, root, label="verification candidate")
                    engine.write_json(state_dir / "snapshots" / f"{checked['snapshot_id']}.json", checked)
                    prior_evidence = None if data.get("force") else _prior_verification(state_dir, checked["config_hash"])
                    result = verify(checked, root=root, run_commands=True, evidence=prior_evidence)
                    current = engine.snapshot(config, root, label="after verification")
                    stale = current["snapshot_id"] != checked["snapshot_id"]
                    engine.write_json(state_dir / "snapshots" / f"{current['snapshot_id']}.json", current)
                    engine.write_json(state_dir / "verification.json", result)
                    engine.write_json(state_dir / "verification" / f"{checked['config_hash']}-{checked['snapshot_id']}.json", result)
                    baseline_path = state_dir / "baselines" / f"{current['config_hash']}.json"
                    if not baseline_path.exists():
                        engine.write_json(baseline_path, current)
                    report = engine.compare(engine.read_json(baseline_path), current, evidence=result)
                    report = _preserve_view(report, state_dir)
                    engine.write_json(state_dir / "current.json", current)
                    case_state = sync_cases(report, state_dir / "cases.json")
                    report["case_state"] = case_state
                    engine.write_json(state_dir / "report.json", report)
                    engine.write_json(state_dir / "reports" / f"{current['config_hash']}-{current['snapshot_id']}.json", report)
                    render(report, state_dir / "report.html")
                    return self._send(200, {"verification": result, "stale": stale,
                        "plan": ("Sources changed while checks ran. Refresh and rerun applicable checks against the new snapshot." if stale else
                                 "Review the per-requirement revalidation decisions. Refresh after source changes, then run or reuse checks as indicated."),
                        "snapshot_id": current["snapshot_id"], "snapshot": current, "report": report,
                        "report_url": "/report", "cases": _latest(state_dir, "cases.json")})
                if route == "/api/case":
                    result = update_case(state_dir / "cases.json", data.get("id"), data.get("status"),
                        data.get("actor"), data.get("note", ""), data.get("owner"))
                    report = _latest(state_dir, "report.json")
                    if report is not None:
                        report["case_state"] = result
                        engine.write_json(state_dir / "report.json", report)
                        candidate = report.get("candidate", {})
                        config_hash = engine.digest(report.get("config", {}))
                        report_path = state_dir / "reports" / f"{config_hash}-{candidate.get('id', '')}.json"
                        engine.write_json(report_path, report)
                        render(report, state_dir / "report.html")
                    return self._send(200, result)
                raise ValueError("Unknown mutation endpoint")
            self._mutate(run)

    if ":" in host:
        class IPv6Server(ThreadingHTTPServer):
            address_family = socket.AF_INET6
        httpd = IPv6Server((host, port), Handler)
    else:
        httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
