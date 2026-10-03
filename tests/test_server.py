import http.client
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from robot_workflow import server
from robot_workflow.engine import write_json


class CapturingHTTPServer(server.ThreadingHTTPServer):
    def __init__(self, address, handler):
        super().__init__(address, handler)
        self.daemon_threads = True


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "sources"
        (self.root / "repo").mkdir(parents=True)
        (self.root / "repo" / "spec.txt").write_text("initial\n")
        self.state = self.base / "private-state"
        self.config_path = self.base / "workflow.json"
        self.httpd = None
        self.thread = None
        def capture(address, handler):
            self.httpd = CapturingHTTPServer(address, handler)
            return self.httpd

        self.patch_server = patch.object(server, "ThreadingHTTPServer", side_effect=capture)
        self.patch_server.start()
        self.addCleanup(self.patch_server.stop)
        self.thread = threading.Thread(target=server.serve,
            args=(self.config_path, self.root, self.state, "127.0.0.1", 0), daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.httpd is not None and self.httpd.server_address[1]:
                break
            threading.Event().wait(.01)
        self.port = self.httpd.server_address[1]
        self.token = None

    def tearDown(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.thread:
            self.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        data = json.dumps(body) if body is not None else None
        h = {"Host": f"127.0.0.1:{self.port}"}
        if data is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn.request(method, path, data, h)
        response = conn.getresponse()
        payload = response.read()
        content_type = response.getheader("Content-Type", "")
        conn.close()
        if "json" in content_type:
            payload = json.loads(payload)
        return response.status, payload

    def csrf(self):
        _, page = self.request("GET", "/")
        import re
        return re.search(r"const csrf='([^']+)'", page.decode()).group(1)

    def post(self, path, body):
        return self.request("POST", path, body, {"X-Workflow-CSRF": self.csrf()})

    def config(self):
        return {"schema_version": 1, "project": "console-test",
            "repositories": [{"id": "repo", "path": "repo"}],
            "nodes": [{"id": "repo", "label": "Repo", "repository": "repo",
                        "owner": "alice", "artifacts": [{"glob": "spec.txt", "parser": "text"}]}],
            "edges": [], "requirements": []}

    def test_loopback_and_host_origin_protection(self):
        self.assertEqual(server._loopback("127.0.0.1"), True)
        self.assertEqual(server._loopback("::1"), True)
        self.assertEqual(server._loopback("0.0.0.0"), False)
        status, _ = self.request("POST", "/api/config", {"config": self.config()},
                                 {"Host": "attacker.example", "X-Workflow-CSRF": "x"})
        self.assertEqual(status, 403)
        status, _ = self.request("GET", "/api/state", headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_rediscovery_merge_preserves_authored_nodes_repositories_and_edges(self):
        old = {"schema_version": 1, "project": "hand-authored", "repositories": [
            {"id": "repo", "path": "repo", "url": "https://example.invalid/manual"}],
            "nodes": [
                {"id": "repo", "repository": "repo", "label": "Curated", "owner": "alice",
                 "kind": "hand", "ports": [{"name": "command"}], "artifacts": [{"glob": "custom.yaml", "parser": "yaml"}]},
                {"id": "manual-node", "repository": "repo", "label": "Second view", "owner": "bob",
                 "artifacts": [{"glob": "other.py", "parser": "python"}]},
            ], "edges": [{"from": "manual-node", "to": "repo", "reason": "reviewed", "watch": ["x"], "emits": ["y"]}],
            "requirements": [{"id": "req", "nodes": ["repo"]}],
            "interface_contracts": [{"id": "port"}], "validation_checks": [{"id": "check"}],
        }
        found = {"schema_version": 1, "project": "scan", "repositories": [
            {"id": "repo", "path": "repo"}, {"id": "new", "path": "new"}],
            "nodes": [
                {"id": "repo", "repository": "repo", "label": "Auto", "owner": "unassigned",
                 "artifacts": [{"glob": "readme.md", "parser": "text"}]},
                {"id": "new", "repository": "new", "label": "New", "owner": "unassigned",
                 "artifacts": [{"glob": "main.py", "parser": "python"}]},
            ], "edges": [{"from": "repo", "to": "new", "reason": "inferred", "watch": ["*"], "emits": ["*"]}],
            "discovery": {"method": "fresh scan"}}
        merged = server.merge_discovery(old, found)
        self.assertEqual(merged["project"], "hand-authored")
        self.assertEqual(merged["repositories"][0]["url"], old["repositories"][0]["url"])
        self.assertEqual(merged["nodes"][0], old["nodes"][0])
        self.assertEqual({node["id"] for node in merged["nodes"]}, {"repo", "manual-node", "new"})
        self.assertEqual(merged["edges"][0], old["edges"][0])
        self.assertEqual(len(merged["edges"]), 2)
        self.assertEqual(merged["requirements"], old["requirements"])
        self.assertEqual(merged["interface_contracts"], old["interface_contracts"])
        self.assertEqual(merged["validation_checks"], old["validation_checks"])

    def test_saved_report_view_survives_refresh_when_its_nodes_remain(self):
        state = self.base / "layout-state"
        state.mkdir()
        write_json(state / "report.json", {"view": {"title_zh": "十仓库布局",
            "positions": {"repo": [24, 40]}, "lanes": [{"label": "部署", "y": 0, "height": 200}]}})
        report = {"config": {"nodes": [{"id": "repo"}]}}
        self.assertEqual(server._preserve_view(report, state)["view"]["title_zh"], "十仓库布局")
        report_without_repo = {"config": {"nodes": [{"id": "another"}]}}
        self.assertNotIn("view", server._preserve_view(report_without_repo, state))

    @unittest.skipUnless(os.name == "posix", "process group test requires POSIX")
    def test_clone_cleanup_kills_ignoring_child_after_leader_exits(self):
        pid_file = self.base / "child.pid"
        script = ("import os,signal,sys,time; p=os.fork(); "
                  "(signal.signal(signal.SIGTERM,signal.SIG_IGN),open(sys.argv[1],'w').write(str(os.getpid())),time.sleep(30)) if p==0 "
                  "else time.sleep(30)")
        process = server.subprocess.Popen([sys.executable, "-c", script, str(pid_file)],
            stdout=server.subprocess.DEVNULL, stderr=server.subprocess.DEVNULL, start_new_session=True)
        for _ in range(100):
            if pid_file.exists(): break
            time.sleep(.01)
        self.assertTrue(pid_file.exists())
        child_pid = int(pid_file.read_text())
        server._stop_clone(process)
        child_status = "R"
        for _ in range(100):
            try:
                child_status = Path(f"/proc/{child_pid}/stat").read_text().split()[2]
            except FileNotFoundError:
                child_status = None
            if child_status in (None, "Z"):
                break
            time.sleep(.01)
        self.assertIn(child_status, (None, "Z"))

    def test_mutation_requires_session_csrf_and_validated_config(self):
        status, _ = self.request("POST", "/api/config", {"config": self.config()})
        self.assertEqual(status, 403)
        bad = self.config()
        bad["repositories"][0]["path"] = "../outside"
        status, result = self.post("/api/config", {"config": bad})
        self.assertEqual(status, 400)
        self.assertIn("relative", result["error"])
        self.assertFalse(self.config_path.exists())
        status, result = self.post("/api/config", {"config": self.config()})
        self.assertEqual(status, 200)
        self.assertTrue(result["saved"])
        self.assertEqual(json.loads(self.config_path.read_text())["nodes"][0]["owner"], "alice")

    def test_case_update_requires_actor_and_records_disposition(self):
        case = {"schema_version": 1, "cases": [{"id": "case-1", "status": "open", "owner": "alice"}]}
        write_json(self.state / "cases.json", case)
        config = self.config()
        write_json(self.state / "report.json", {"config": config,
            "candidate": {"id": "candidate-a"}, "case_state": case})
        status, result = self.post("/api/case", {"id": "case-1", "status": "claimed", "actor": "", "note": ""})
        self.assertEqual(status, 400)
        status, result = self.post("/api/case", {"id": "case-1", "status": "claimed", "actor": "bob", "note": "Taking this"})
        self.assertEqual(status, 200)
        self.assertEqual(result["cases"][0]["owner"], "bob")
        status, result = self.post("/api/case", {"id": "case-1", "status": "resolved", "actor": "bob", "note": "Reviewed"})
        self.assertEqual(status, 200)
        self.assertEqual(result["cases"][0]["status"], "resolved")
        self.assertEqual(json.loads((self.state / "report.json").read_text())["case_state"], result)
        self.assertTrue((self.state / "report.html").is_file())

    def test_refresh_builds_report_and_commands_run_only_on_explicit_check(self):
        self.assertEqual(self.post("/api/config", {"config": self.config()})[0], 200)
        with patch.object(server, "verify", wraps=server.verify) as verifier:
            status, result = self.post("/api/refresh", {})
            self.assertEqual(status, 200)
            self.assertTrue((self.state / "report.html").is_file())
            self.assertEqual(verifier.call_count, 0)
            status, _ = self.post("/api/check", {})
            self.assertEqual(status, 200)
            verifier.assert_called_once_with(unittest.mock.ANY, root=self.root, run_commands=True, evidence=None)
            self.assertTrue((self.state / "reports" / f"{result['snapshot']['config_hash']}-{result['snapshot']['snapshot_id']}.json").is_file())

    def test_configuration_change_creates_new_scoped_baseline_and_keeps_old(self):
        original = self.config()
        self.assertEqual(self.post("/api/config", {"config": original})[0], 200)
        self.assertEqual(self.post("/api/refresh", {})[0], 200)
        changed = self.config()
        changed["nodes"][0]["owner"] = "bob"
        self.assertEqual(self.post("/api/config", {"config": changed})[0], 200)
        baselines = list((self.state / "baselines").glob("*.json"))
        self.assertEqual(len(baselines), 2)
        status, result = self.post("/api/refresh", {})
        self.assertEqual(status, 200)
        self.assertFalse(result["baseline_reset"])
        self.assertEqual(result["report"]["baseline"]["id"], result["report"]["candidate"]["id"])
        self.assertEqual(len(list((self.state / "snapshots").glob("*.json"))), 2)

    def test_check_captures_fresh_sources_before_reusing_or_running_evidence(self):
        config = self.config()
        config["requirements"] = [{"id": "req", "nodes": ["repo"]}]
        config["validation_checks"] = [{"id": "check", "requirement": "req", "repository": "repo",
                                        "argv": ["true"], "timeout_seconds": 1}]
        self.assertEqual(self.post("/api/config", {"config": config})[0], 200)
        self.assertEqual(self.post("/api/refresh", {})[0], 200)
        contents = "changed after last refresh\n"
        (self.root / "repo" / "spec.txt").write_text(contents)
        expected_hash = hashlib.sha256(contents.encode()).hexdigest()
        def checking(*args, **kwargs):
            (self.root / "repo" / "spec.txt").write_text("changed during check\n")
            return {"schema_version": 1, "records": [], "revalidation": []}
        with patch.object(server, "verify", side_effect=checking) as verifier:
            status, result = self.post("/api/check", {})
        self.assertEqual(status, 200)
        candidate = verifier.call_args.args[0]
        self.assertEqual(candidate["nodes"]["repo"]["files"]["spec.txt"]["sha256"], expected_hash)
        self.assertNotEqual(result["snapshot"]["snapshot_id"], candidate["snapshot_id"])
        self.assertEqual(result["snapshot"]["nodes"]["repo"]["files"]["spec.txt"]["sha256"],
                         hashlib.sha256(b"changed during check\n").hexdigest())
        self.assertTrue(result["stale"])
        self.assertTrue((self.state / "report.html").is_file())
        self.assertTrue((self.state / "cases.json").is_file())

    def test_import_requires_github_https_and_refuses_existing_destination(self):
        status, result = self.post("/api/import", {"url": "file:///tmp/repo", "path": "new-repo"})
        self.assertEqual(status, 400)
        (self.root / "existing").mkdir()
        with patch.object(server.subprocess, "run") as run:
            status, result = self.post("/api/import", {"url": "https://github.com/org/repo.git", "path": "existing"})
            self.assertEqual(status, 400)
            run.assert_not_called()

    def test_import_clones_only_after_explicit_request_and_returns_relative_path(self):
        def clone(argv, **kwargs):
            destination = Path(argv[-1])
            destination.mkdir(parents=True)
            (destination / ".git").mkdir()
            process = unittest.mock.Mock()
            process.wait.return_value = 0
            return process
        with patch.object(server.subprocess, "Popen", side_effect=clone) as run:
            status, result = self.post("/api/import", {"url": "https://github.com/org/repo.git",
                                                        "branch": "main", "path": "new-repo"})
        self.assertEqual(status, 200)
        self.assertEqual(result, {"imported": True, "path": "new-repo"})
        self.assertTrue(run.call_args.kwargs["start_new_session"])
        self.assertTrue((self.root / "new-repo" / ".git").is_dir())

    @unittest.skipUnless(os.name == "posix", "symlink safety test requires POSIX")
    def test_import_rejects_git_symlink_without_touching_external_target(self):
        external = self.base / "external-git-data"
        external.mkdir()
        marker = external / "keep.txt"
        marker.write_text("preserve")
        def clone(argv, **kwargs):
            destination = Path(argv[-1])
            destination.mkdir(parents=True)
            (destination / ".git").symlink_to(external, target_is_directory=True)
            process = unittest.mock.Mock()
            process.wait.return_value = 0
            return process
        with patch.object(server.subprocess, "Popen", side_effect=clone):
            status, result = self.post("/api/import", {"url": "https://github.com/org/repo.git", "path": "unsafe"})
        self.assertEqual(status, 400)
        self.assertFalse((self.root / "unsafe").exists())
        self.assertEqual(marker.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
