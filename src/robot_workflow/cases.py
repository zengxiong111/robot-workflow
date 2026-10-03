"""Local, human-owned dispositions for candidate impact reports."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

try:  # Unix
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None
try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - exercised on Unix
    msvcrt = None


SCHEMA_VERSION = 1
IMPACT_STATUSES = {"changed", "potential_impact", "unknown"}
CASE_STATUSES = {"open", "claimed", "resolved", "dismissed"}
CLOSED_STATUSES = {"resolved", "dismissed"}


@contextmanager
def _state_lock(path):
    """Take a non-blocking cross-process lock; concurrent writers fail clearly."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        try:
            if fcntl is not None:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise RuntimeError("Case state is being updated by another process") from exc
                try:
                    yield
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows
                stream.seek(0)
                if stream.read(1) == b"":
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise RuntimeError("Case state is being updated by another process") from exc
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                raise RuntimeError("No supported file locking mechanism on this platform")
        except OSError as exc:
            raise RuntimeError(f"Unable to lock case state: {exc}") from exc


def _read_state(path):
    path = Path(path)
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "cases": []}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema_version") != SCHEMA_VERSION or not isinstance(state.get("cases"), list):
        raise ValueError("Unsupported or invalid case state schema")
    return state


def _write_state(path, state):
    """Atomically replace state using a temporary file beside state_path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _case_id(snapshot_id, node_id):
    identity = f"{snapshot_id}\0{node_id}".encode("utf-8")
    return hashlib.sha256(identity).hexdigest()[:24]


def sync_cases(report, state_path):
    """Create/update cases for actionable report impacts and return full state.

    Existing human ownership, status and notes survive every report resync.
    """
    if not isinstance(report, dict) or not isinstance(report.get("impacts"), dict):
        raise ValueError("report must contain an impacts mapping")
    candidate = report.get("candidate") or {}
    snapshot_id = candidate.get("id")
    if not snapshot_id:
        raise ValueError("report candidate must include snapshot id")
    configured_nodes = {node["id"]: node for node in report.get("config", {}).get("nodes", [])}
    path = Path(state_path)
    with _state_lock(path.with_name(path.name + ".lock")):
        state = _read_state(path)
        indexed = {item["id"]: item for item in state["cases"]}
        for node_id, impact in sorted(report["impacts"].items()):
            if impact.get("status") not in IMPACT_STATUSES:
                continue
            case_id = _case_id(snapshot_id, node_id)
            previous = indexed.get(case_id)
            node = configured_nodes.get(node_id, {})
            record = {
                "id": case_id,
                "candidate_snapshot_id": snapshot_id,
                "node": node_id,
                "impact_status": impact["status"],
                "owner": (previous.get("owner") if previous is not None else node.get("owner")),
                "status": previous.get("status", "open") if previous else "open",
                "notes": previous.get("notes", []) if previous else [],
                "history": previous.get("history", []) if previous else [],
                "paths": impact.get("paths", []),
                "checks": impact.get("checks", node.get("checks", [])),
            }
            indexed[case_id] = record
        state["cases"] = sorted(indexed.values(), key=lambda item: (item["candidate_snapshot_id"], item["node"]))
        _write_state(path, state)
        return state


def update_case(state_path, case_id, status, actor, note="", owner=None):
    """Record a human disposition; resolved means disposition, not certification."""
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("actor is required")
    if not isinstance(note, str):
        raise ValueError("note must be a string")
    if owner is not None and (not isinstance(owner, str) or not owner.strip()):
        raise ValueError("owner must be a nonempty string when supplied")
    if status not in CASE_STATUSES:
        raise ValueError(f"status must be one of {sorted(CASE_STATUSES)}")
    if status in CLOSED_STATUSES and (not isinstance(note, str) or not note.strip()):
        raise ValueError("resolving or dismissing a case requires a nonempty note")
    path = Path(state_path)
    with _state_lock(path.with_name(path.name + ".lock")):
        state = _read_state(path)
        case = next((item for item in state["cases"] if item.get("id") == case_id), None)
        if case is None:
            raise KeyError(f"Case not found: {case_id}")
        current = case.get("status", "open")
        if current in CLOSED_STATUSES and status != "open":
            raise ValueError("closed cases must be reopened as open before another transition")
        old_owner = case.get("owner")
        new_owner = owner.strip() if owner is not None else old_owner
        if status == "claimed" and owner is None:
            new_owner = actor.strip()
        case["owner"] = new_owner
        case["status"] = status
        case.setdefault("notes", [])
        if note.strip():
            case["notes"].append({"actor": actor.strip(), "text": note.strip()})
        if current != status or old_owner != new_owner:
            case.setdefault("history", []).append({
                "actor": actor.strip(),
                "from_status": current,
                "to_status": status,
                "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "note": note.strip(),
                **({"from_owner": old_owner} if old_owner != new_owner else {}),
                **({"to_owner": new_owner} if old_owner != new_owner else {}),
            })
        case["updated_by"] = actor.strip()
        _write_state(path, state)
        return state
