"""Run explicitly requested external checks against an unchanged snapshot.

POSIX timeout cleanup owns the command's process group. Windows cleanup can
terminate only the main process; this runner is not a process sandbox.
"""

from copy import deepcopy
import platform
import os
import signal
import math
import subprocess
import sys
import threading
import time
from pathlib import Path

OUTPUT_LIMIT = 4000
READ_CHUNK = 8192


class _BoundedCapture:
    """Drain a pipe continuously while retaining only a bounded prefix."""

    def __init__(self, stream):
        self.stream = stream
        self.data = bytearray()
        self.total = 0
        self.thread = threading.Thread(target=self._drain, daemon=True)
        self.thread.start()

    def _drain(self):
        while True:
            chunk = self.stream.read(READ_CHUNK)
            if not chunk:
                return
            self.total += len(chunk)
            remaining = OUTPUT_LIMIT - len(self.data)
            if remaining > 0:
                self.data.extend(chunk[:remaining])

    def text(self):
        value = bytes(self.data).decode("utf-8", errors="replace")
        if self.total > len(self.data):
            value += f"\n...[truncated; {self.total - len(self.data)} bytes omitted]"
        return value

    def close_if_drained(self):
        if not self.thread.is_alive():
            self.stream.close()


def _signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False


def _group_exists(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _force_stop(process):
    """Stop and reap an owned command after interruption or an internal error."""
    if os.name == "posix":
        _signal_group(process.pid, signal.SIGKILL)
    elif process.poll() is None:
        process.kill()
    try:
        process.wait()
    except ProcessLookupError:
        pass


def validate(config):
    """Validate opt-in command checks embedded in a workflow configuration."""
    repositories = {repo["id"]: repo for repo in config.get("repositories", [])}
    requirements = {req["id"] for req in config.get("requirements", [])}
    checks = config.get("validation_checks", [])
    if not isinstance(checks, list):
        raise ValueError("validation_checks must be a list")
    ids = set()
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("Each validation check must be an object")
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id.strip() or check_id in ids:
            raise ValueError("Validation check ids must be nonempty and unique")
        ids.add(check_id)
        requirement = check.get("requirement")
        if not isinstance(requirement, str) or requirement not in requirements:
            raise ValueError(f"Unknown requirement for validation check {check_id}")
        repo_id = check.get("repository")
        if not isinstance(repo_id, str) or repo_id not in repositories:
            raise ValueError(f"Unknown repository for validation check {check_id}")
        argv = check.get("argv")
        if (not isinstance(argv, list) or not argv or
                any(not isinstance(arg, str) or not arg or "\0" in arg for arg in argv) or not argv[0].strip()):
            raise ValueError(f"Validation check {check_id} needs a nonempty argv of strings")
        timeout = check.get("timeout_seconds", 60)
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or
                not math.isfinite(timeout) or timeout <= 0 or timeout > 3600):
            raise ValueError(f"Validation check {check_id} timeout_seconds must be between 0 and 3600")
        repo_path = Path(repositories[repo_id]["path"])
        if repo_path.is_absolute() or ".." in repo_path.parts or not repo_path.parts:
            raise ValueError(f"Unsafe repository path for validation check {check_id}")
    return config


def _matches(snapshot_value, root):
    from .engine import snapshot
    current = snapshot(snapshot_value["config"], root, label="external-check")
    return current["snapshot_id"] == snapshot_value["snapshot_id"]


def run_checks(snapshot_value, root, requirement_ids=None):
    """Run configured checks, returning evidence only while source identity holds."""
    from .engine import validate_snapshot
    from .revalidation import current_runtime, command_identity
    validate_snapshot(snapshot_value)
    config = deepcopy(snapshot_value["config"])
    validate(config)
    root = Path(root).resolve()
    selected_requirements = None if requirement_ids is None else set(requirement_ids)
    checks = [item for item in config.get("validation_checks", [])
              if selected_requirements is None or item["requirement"] in selected_requirements]
    by_requirement = {}
    requirements = {req["id"]: req for req in config.get("requirements", [])}

    def record_check(spec, result, summary, **details):
        entry = {"id": spec["id"], "result": result, "summary": summary,
                 "argv": spec["argv"], "repository": spec["repository"], **details}
        by_requirement.setdefault(spec["requirement"], []).append(entry)

    if not checks:
        return {"schema_version": 1, "records": []}
    if not _matches(snapshot_value, root):
        for spec in checks:
            record_check(spec, "unknown", "Source snapshot changed before command execution",
                         reason="source_drift")
    else:
        repo_specs = {repo["id"]: repo for repo in config["repositories"]}
        for index, spec in enumerate(checks):
            req_nodes = requirements[spec["requirement"]]["nodes"]
            if any(snapshot_value["nodes"][node].get("coverage") != "declared_sources_scanned"
                   for node in req_nodes):
                record_check(spec, "unknown", "Requirement sources are not fully covered",
                             reason="source_coverage_unknown",
                             repository_commit=snapshot_value["repositories"][spec["repository"]]["commit"])
                continue
            command_inventory = snapshot_value["repositories"][spec["repository"]].get("command_inventory", {})
            if command_inventory.get("coverage") != "complete":
                record_check(spec, "unknown", "Selected repository command inventory is incomplete; command was not run",
                             reason="command_inventory_unknown",
                             inventory_problems=command_inventory.get("problems", []),
                             repository_commit=snapshot_value["repositories"][spec["repository"]]["commit"])
                continue
            repo_root = (root / repo_specs[spec["repository"]]["path"]).resolve()
            if not repo_root.is_relative_to(root) or not repo_root.is_dir():
                record_check(spec, "unknown", "Repository is unavailable or escapes workflow root",
                             reason="repository_unavailable", repository_commit=None)
                continue
            started = time.monotonic()
            try:
                process = subprocess.Popen(spec["argv"], cwd=repo_root, shell=False,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           start_new_session=(os.name == "posix"))
            except FileNotFoundError as exc:
                duration = time.monotonic() - started
                outcome, summary = "unknown", f"Executable unavailable: {exc.filename}"
                details = {"reason": "executable_missing", "duration_seconds": duration,
                           "repository_commit": snapshot_value["repositories"][spec["repository"]]["commit"],
                           "environment": {**current_runtime(), "command": command_identity(spec["argv"][0])}}
            except OSError as exc:
                duration = time.monotonic() - started
                outcome, summary = "unknown", f"Command could not be started: {exc}"
                details = {"reason": "execution_error", "duration_seconds": duration,
                           "repository_commit": snapshot_value["repositories"][spec["repository"]]["commit"],
                           "environment": {**current_runtime(), "command": command_identity(spec["argv"][0])}}
            else:
                stdout_capture = _BoundedCapture(process.stdout)
                stderr_capture = _BoundedCapture(process.stderr)
                timed_out = False
                residual_group = False
                try:
                    try:
                        exit_code = process.wait(timeout=spec.get("timeout_seconds", 60))
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        if os.name == "posix":
                            _signal_group(process.pid, signal.SIGTERM)
                            try:
                                process.wait(timeout=0.25)
                            except subprocess.TimeoutExpired:
                                pass
                            # Escalate by process group even when its leader has exited.
                            if _group_exists(process.pid):
                                _signal_group(process.pid, signal.SIGKILL)
                        elif process.poll() is None:
                            process.terminate()
                            try:
                                process.wait(timeout=0.25)
                            except subprocess.TimeoutExpired:
                                process.kill()
                        exit_code = process.wait()
                except BaseException:
                    _force_stop(process)
                    stdout_capture.thread.join(timeout=1)
                    stderr_capture.thread.join(timeout=1)
                    stdout_capture.close_if_drained()
                    stderr_capture.close_if_drained()
                    raise
                if os.name == "posix" and not timed_out and _group_exists(process.pid):
                    # A successful leader must not leave a background job behind.
                    residual_group = True
                    _signal_group(process.pid, signal.SIGTERM)
                    time.sleep(0.1)
                    if _group_exists(process.pid):
                        _signal_group(process.pid, signal.SIGKILL)
                stdout_capture.thread.join(timeout=1)
                stderr_capture.thread.join(timeout=1)
                readers_stuck = stdout_capture.thread.is_alive() or stderr_capture.thread.is_alive()
                stdout_capture.close_if_drained()
                stderr_capture.close_if_drained()
                duration = time.monotonic() - started
                if timed_out:
                    outcome, summary, reason = "unknown", "Command timed out; completion was not established", "timeout"
                elif residual_group or readers_stuck:
                    outcome, summary, reason = "unknown", "Command left background work or open output pipes", "residual_processes"
                else:
                    outcome = "pass" if exit_code == 0 else "fail"
                    summary = "Command exited successfully" if outcome == "pass" else f"Command exited with status {exit_code}"
                    reason = None
                details = {"stdout": stdout_capture.text(), "stderr": stderr_capture.text(),
                           "exit_code": exit_code, "duration_seconds": duration,
                           "repository_commit": snapshot_value["repositories"][spec["repository"]]["commit"],
                           "environment": {**current_runtime(), "command": command_identity(spec["argv"][0])}}
                if reason:
                    details["reason"] = reason
            record_check(spec, outcome, summary, **details)
            if not _matches(snapshot_value, root):
                # A command that edits sources cannot establish evidence for its starting snapshot.
                for entries in by_requirement.values():
                    for entry in entries:
                        entry["result"] = "unknown"
                        entry["summary"] = "Source snapshot changed during command execution"
                        entry["reason"] = "source_drift"
                for remaining in checks[index + 1:]:
                    record_check(remaining, "unknown", "Source snapshot changed during command execution",
                                 reason="source_drift")
                break

    records = []
    for requirement_id, results in by_requirement.items():
        req = requirements[requirement_id]
        states = {item["result"] for item in results}
        result = "fail" if "fail" in states else "unknown" if "unknown" in states else "pass"
        records.append({
            "requirement": requirement_id,
            "snapshot_id": snapshot_value["snapshot_id"],
            "fingerprints": {node: snapshot_value["nodes"][node]["fingerprint"] for node in req["nodes"]},
            "result": result,
            "summary": f"{sum(item['result'] == 'pass' for item in results)}/{len(results)} explicit command checks passed",
            "checks": results,
            "method": "explicit_command_checks",
        })
    return {"schema_version": 1, "records": records}
