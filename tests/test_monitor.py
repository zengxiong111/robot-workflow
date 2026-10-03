import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import unittest

from robot_workflow.monitor import sync_repositories, watch_once


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "root"
        self.state = self.base / "state"
        self.root.mkdir()
        self.bare = self.base / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.bare)], check=True, capture_output=True)
        git(self.bare, "symbolic-ref", "HEAD", "refs/heads/main")
        seed = self.base / "seed"
        subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
        git(seed, "config", "user.name", "Test")
        git(seed, "config", "user.email", "test@example.invalid")
        (seed / "model.json").write_text('{"width": 1}\n')
        git(seed, "add", "model.json")
        git(seed, "commit", "-m", "initial")
        git(seed, "remote", "add", "origin", str(self.bare))
        git(seed, "push", "-u", "origin", "main")
        self.repo = self.root / "robot"
        subprocess.run(["git", "clone", "-q", str(self.bare), str(self.repo)], check=True,
                       capture_output=True)
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.invalid")
        self.config = {
            "schema_version": 1,
            "repositories": [{"id": "robot", "path": "robot"}],
            "nodes": [{"id": "robot", "label": "Robot", "repository": "robot",
                       "owner": "controls", "artifacts": [{"glob": "model.json", "parser": "json"}]}],
            "edges": [], "requirements": [{"id": "width", "title": "Width is one", "nodes": ["robot"],
                                            "assertions": [{"id": "width", "source": {
                                                "node": "robot", "path": "model.json", "pointer": "/data/width"},
                                                "equals": 1}]}],
        }

    def commit_remote(self, content):
        seed = self.base / "seed"
        (seed / "model.json").write_text(content + "\n")
        git(seed, "add", "model.json")
        git(seed, "commit", "-m", "remote update")
        git(seed, "push", "origin", "main")

    def test_clean_checkout_fast_forwards_from_local_bare_remote(self):
        old = git(self.repo, "rev-parse", "HEAD")
        self.commit_remote('{"width": 2}')
        result = sync_repositories(self.config, self.root)[0]
        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["old"], old)
        self.assertEqual(result["new"], git(self.repo, "rev-parse", "HEAD"))
        self.assertNotEqual(result["new"], old)

    def test_dirty_checkout_is_not_modified(self):
        (self.repo / "model.json").write_text('{"width": 9}\n')
        before = (self.repo / "model.json").read_text()
        result = sync_repositories(self.config, self.root)[0]
        self.assertEqual(result["status"], "dirty")
        self.assertEqual((self.repo / "model.json").read_text(), before)

    def test_diverged_checkout_is_not_reset_or_merged(self):
        (self.repo / "local.txt").write_text("local\n")
        git(self.repo, "add", "local.txt")
        git(self.repo, "commit", "-m", "local commit")
        local_head = git(self.repo, "rev-parse", "HEAD")
        self.commit_remote('{"width": 2}')
        result = sync_repositories(self.config, self.root)[0]
        self.assertEqual(result["status"], "diverged")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), local_head)
        self.assertEqual(result["new"], local_head)
        self.assertNotEqual(result["remote_commit"], local_head)
        self.assertTrue((self.repo / "local.txt").exists())

    def test_update_before_first_watch_baseline_is_reported(self):
        self.commit_remote('{"width": 2}')
        first = watch_once(self.config, self.root, self.state, update=True, notify=False)
        self.assertTrue(first["baseline"])
        self.assertEqual(first["sync"][0]["status"], "updated")
        event_lines = (self.state / "events.jsonl").read_text().splitlines()
        self.assertEqual(len(event_lines), 1)
        report = json.loads(Path(first["report"]).read_text())
        self.assertEqual(report["summary"]["semantic_changes"], 1)

    def test_sync_failure_makes_passing_source_requirement_unknown(self):
        watch_once(self.config, self.root, self.state, update=False)
        git(self.repo, "remote", "set-url", "origin", "http://127.0.0.1:1/private-token.git")
        result = watch_once(self.config, self.root, self.state, update=True, notify=False)
        report = json.loads(Path(result["report"]).read_text())
        self.assertEqual(report["sync"][0]["status"], "error")
        self.assertEqual(report["requirements"][0]["state"], "unknown")
        self.assertIn("Remote source freshness cannot be confirmed", report["requirements"][0]["reason"])
        self.assertEqual(report["impacts"]["robot"]["status"], "unknown")
        self.assertTrue(Path(result["html"]).is_file())
        self.assertNotIn("private-token", "".join(path.read_text(errors="ignore") for path in self.state.iterdir() if path.is_file()))

    def test_sync_unknown_summary_keeps_unrelated_source_coverage_unknown(self):
        from unittest.mock import patch
        other = self.root / "other"
        other.mkdir()
        (other / "broken.json").write_text("{invalid json\n")
        self.config["repositories"].append({"id": "other", "path": "other"})
        self.config["nodes"].append({"id": "other", "label": "Other", "repository": "other",
                                     "owner": "perception", "artifacts": [{"glob": "broken.json", "parser": "json"}]})
        watch_once(self.config, self.root, self.state, update=False)
        sync = [
            {"repository": "robot", "path": "robot", "old": "a", "new": "a", "remote_commit": None,
             "status": "error", "error": "fetch failed (exit 128)"},
            {"repository": "other", "path": "other", "old": None, "new": None, "remote_commit": None,
             "status": "current", "error": None},
        ]
        with patch("robot_workflow.monitor.sync_repositories", return_value=sync):
            result = watch_once(self.config, self.root, self.state, update=True, notify=False)
        report = json.loads(Path(result["report"]).read_text())
        self.assertEqual(report["impacts"]["robot"]["status"], "unknown")
        self.assertEqual(report["impacts"]["other"]["status"], "unknown")
        self.assertEqual(report["summary"]["unknown"], 2)

    def test_config_change_is_rejected_before_repository_sync(self):
        from unittest.mock import patch
        watch_once(self.config, self.root, self.state, update=False)
        self.config["project"] = "Renamed project"
        with patch("robot_workflow.monitor.sync_repositories") as sync:
            with self.assertRaisesRegex(ValueError, "Configuration changed"):
                watch_once(self.config, self.root, self.state, update=True)
            sync.assert_not_called()

    def test_first_watch_sets_baseline_without_notification_then_reports_change(self):
        self.config["notifications"] = {"webhook_env": "ROBOT_WORKFLOW_TEST_WEBHOOK"}
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner):
                calls.append(json.loads(inner.rfile.read(int(inner.headers["Content-Length"]))))
                inner.send_response(200)
                inner.end_headers()

            def log_message(inner, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        key = "ROBOT_WORKFLOW_TEST_WEBHOOK"
        old = os.environ.get(key)
        os.environ[key] = f"http://127.0.0.1:{server.server_port}/notify"
        self.addCleanup(lambda: os.environ.pop(key, None) if old is None else os.environ.__setitem__(key, old))

        initial = watch_once(self.config, self.root, self.state, update=False)
        self.assertTrue(initial["baseline"])
        self.assertEqual(calls, [])
        (self.repo / "model.json").write_text('{"width": 2}\n')
        changed = watch_once(self.config, self.root, self.state, update=False)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["owners"], ["controls"])
        self.assertEqual(changed["pending_notifications"], 0)
        repeated = watch_once(self.config, self.root, self.state, update=False)
        self.assertEqual(repeated["events"], [])
        self.assertEqual(len(calls), 1)
        self.assertTrue(Path(changed["html"]).is_file())

    def test_nonsemantic_formatting_change_does_not_notify(self):
        self.config["notifications"] = {"webhook_env": "ROBOT_WORKFLOW_TEST_WEBHOOK"}
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner):
                calls.append(inner.rfile.read(int(inner.headers["Content-Length"])))
                inner.send_response(200)
                inner.end_headers()

            def log_message(inner, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        name = "ROBOT_WORKFLOW_TEST_WEBHOOK"
        previous = os.environ.get(name)
        os.environ[name] = f"http://127.0.0.1:{server.server_port}/hook"
        self.addCleanup(lambda: os.environ.pop(name, None) if previous is None else os.environ.__setitem__(name, previous))
        watch_once(self.config, self.root, self.state, update=False)
        (self.repo / "model.json").write_text('{ "width" : 1 }\n')
        result = watch_once(self.config, self.root, self.state, update=False)
        report = json.loads(Path(result["report"]).read_text())
        self.assertEqual(report["summary"]["semantic_changes"], 0)
        self.assertEqual(calls, [])
        self.assertEqual(result["events"], [])

    def test_failed_notification_remains_queued_and_retries(self):
        self.config["notifications"] = {"webhook_env": "ROBOT_WORKFLOW_TEST_WEBHOOK"}
        key = "ROBOT_WORKFLOW_TEST_WEBHOOK"
        old = os.environ.get(key)
        os.environ[key] = "http://127.0.0.1:1/unreachable"
        self.addCleanup(lambda: os.environ.pop(key, None) if old is None else os.environ.__setitem__(key, old))
        watch_once(self.config, self.root, self.state, update=False)
        (self.repo / "model.json").write_text('{"width": 3}\n')
        first = watch_once(self.config, self.root, self.state, update=False)
        queue = json.loads((self.state / "notification-queue.json").read_text())
        self.assertEqual(first["pending_notifications"], 1)
        self.assertEqual(queue[0]["attempts"], 1)
        # A new endpoint succeeds; retrying the queue must not create a duplicate event.
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner):
                calls.append(json.loads(inner.rfile.read(int(inner.headers["Content-Length"]))))
                inner.send_response(200)
                inner.end_headers()

            def log_message(inner, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[key] = f"http://127.0.0.1:{server.server_port}/notify"
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        second = watch_once(self.config, self.root, self.state, update=False)
        self.assertEqual(second["events"], [])
        self.assertEqual(second["pending_notifications"], 0)
        self.assertEqual(len(calls), 1)

    def test_configured_but_missing_endpoint_waits_then_delivers(self):
        name = "ROBOT_WORKFLOW_LATE_WEBHOOK"
        previous = os.environ.pop(name, None)
        self.addCleanup(lambda: os.environ.pop(name, None) if previous is None else os.environ.__setitem__(name, previous))
        self.config["notifications"] = {"webhook_env": name}
        watch_once(self.config, self.root, self.state, update=False)
        (self.repo / "model.json").write_text('{"width": 5}\n')
        first = watch_once(self.config, self.root, self.state, update=False)
        self.assertEqual(first["pending_notifications"], 1)
        queue = json.loads((self.state / "notification-queue.json").read_text())
        self.assertEqual(queue[0]["last_error"], {f"{name}:MissingEndpoint": "MissingEndpoint"})
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner):
                calls.append(json.loads(inner.rfile.read(int(inner.headers["Content-Length"]))))
                inner.send_response(200)
                inner.end_headers()

            def log_message(inner, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        os.environ[name] = f"http://127.0.0.1:{server.server_port}/hook"
        second = watch_once(self.config, self.root, self.state, update=False)
        self.assertEqual(second["events"], [])
        self.assertEqual(second["pending_notifications"], 0)
        self.assertEqual(len(calls), 1)

    def test_state_dir_inside_registered_repo_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "registered repository"):
            watch_once(self.config, self.root, self.repo / "state", update=False)

    def test_state_dir_is_bound_to_repository_root(self):
        watch_once(self.config, self.root, self.state, update=False)
        other_root = self.base / "other-root"
        (other_root / "robot").mkdir(parents=True)
        (other_root / "robot/model.json").write_text('{"width": 1}\n')
        with self.assertRaisesRegex(ValueError, "different repository root"):
            watch_once(self.config, other_root, self.state, update=False)

    def test_watch_rejects_nonpositive_or_nonfinite_interval(self):
        from robot_workflow.monitor import watch
        for interval in (0, -1, float("inf"), float("nan")):
            with self.subTest(interval=interval), self.assertRaisesRegex(ValueError, "positive finite"):
                watch(self.config, self.root, self.state, interval=interval, once=True)

    def test_retry_does_not_repeat_successful_owner_endpoint(self):
        counts = {"ok": 0, "retry": 0}

        def handler_for(name):
            class Handler(BaseHTTPRequestHandler):
                def do_POST(inner):
                    inner.rfile.read(int(inner.headers["Content-Length"]))
                    counts[name] += 1
                    inner.send_response(503 if name == "retry" and counts[name] == 1 else 200)
                    inner.end_headers()

                def log_message(inner, *args):
                    pass
            return Handler

        servers = []
        for name in counts:
            server = HTTPServer(("127.0.0.1", 0), handler_for(name))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        names = ["ROBOT_WORKFLOW_OK", "ROBOT_WORKFLOW_RETRY"]
        old_values = {name: os.environ.get(name) for name in names}
        for name, server in zip(names, servers):
            os.environ[name] = f"http://127.0.0.1:{server.server_port}/hook"
        self.addCleanup(lambda: [os.environ.pop(name, None) if old_values[name] is None
                                 else os.environ.__setitem__(name, old_values[name]) for name in names])
        self.config["notifications"] = {"webhook_env": names[0], "recipients": {"controls": names[1]}}
        watch_once(self.config, self.root, self.state, update=False)
        (self.repo / "model.json").write_text('{"width": 4}\n')
        watch_once(self.config, self.root, self.state, update=False)
        self.assertEqual(counts, {"ok": 1, "retry": 1})
        watch_once(self.config, self.root, self.state, update=False)
        self.assertEqual(counts, {"ok": 1, "retry": 2})


if __name__ == "__main__":
    unittest.main()
