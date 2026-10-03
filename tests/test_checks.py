import copy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from robot_workflow.checks import run_checks, validate
from robot_workflow.engine import snapshot


class ExternalCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "repo").mkdir()
        (self.root / "repo" / "source.json").write_text('{"value": 1}')
        self.config = {
            "schema_version": 1,
            "repositories": [{"id": "repo", "path": "repo"}],
            "nodes": [{"id": "node", "label": "Node", "repository": "repo",
                       "artifacts": [{"glob": "source.json", "parser": "json"}]}],
            "requirements": [{"id": "req", "title": "Requirement", "nodes": ["node"]}],
            "validation_checks": [],
        }

    def add_check(self, argv, **values):
        self.config["validation_checks"] = [{"id": "cmd", "requirement": "req",
                                                "repository": "repo", "argv": argv, **values}]

    def run_one(self):
        candidate = snapshot(self.config, self.root)
        return run_checks(candidate, self.root)["records"][0]

    def python(self, code):
        return [sys.executable, "-c", code]

    def test_pass_and_fail_exit_codes(self):
        self.add_check(self.python("print('ok')"))
        result = self.run_one()
        self.assertEqual(result["result"], "pass")
        self.assertEqual(result["checks"][0]["stdout"], "ok\n")
        self.add_check(self.python("raise SystemExit(3)"))
        self.assertEqual(self.run_one()["result"], "fail")

    def test_timeout_and_missing_executable_are_unknown(self):
        self.add_check(self.python("import time; time.sleep(2)"), timeout_seconds=0.05)
        timed_out = self.run_one()["checks"][0]
        self.assertEqual(timed_out["result"], "unknown")
        self.assertEqual(timed_out["reason"], "timeout")
        self.add_check(["robot-workflow-no-such-executable-9d8f"])
        missing = self.run_one()["checks"][0]
        self.assertEqual(missing["result"], "unknown")
        self.assertEqual(missing["reason"], "executable_missing")

    def test_large_output_is_drained_but_only_bounded_prefix_is_retained(self):
        self.add_check(self.python("import sys; sys.stdout.write('x' * 1000000)"))
        check = self.run_one()["checks"][0]
        self.assertEqual(check["result"], "pass")
        self.assertLessEqual(len(check["stdout"].split("\n...[truncated", 1)[0]), 4000)
        self.assertIn("bytes omitted", check["stdout"])

    @unittest.skipUnless(os.name == "posix", "process-group cleanup is POSIX-specific")
    def test_timeout_kills_descendant_that_ignores_sigterm(self):
        pidfile = self.root / "child.pid"
        child = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
        parent = ("import subprocess,sys; child=subprocess.Popen([sys.executable, '-c', " + repr(child) + "]); "
                  "open(" + repr(str(pidfile)) + ", 'w').write(str(child.pid)); child.wait()")
        self.add_check(self.python(parent), timeout_seconds=0.5)
        check = self.run_one()["checks"][0]
        self.assertEqual(check["result"], "unknown")
        self.assertEqual(check["reason"], "timeout")
        self.assertTrue(pidfile.exists())
        child_pid = int(pidfile.read_text())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            stat = Path(f"/proc/{child_pid}/stat")
            if stat.exists() and stat.read_text().split()[2] == "Z":
                break
            time.sleep(0.02)
        else:
            self.fail("timed-out descendant remained alive")

    @unittest.skipUnless(os.name == "posix", "process-group cleanup is POSIX-specific")
    def test_keyboard_interrupt_kills_and_reaps_owned_command(self):
        pidfile = self.root / "interrupt.pid"
        code = f"import os,time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); time.sleep(30)"
        argv = self.python(code)
        self.add_check(argv, timeout_seconds=10)
        original_wait = __import__("subprocess").Popen.wait
        injected = False

        def interrupt_command_once(process, timeout=None):
            nonlocal injected
            if process.args == argv and not injected:
                deadline = time.monotonic() + 2
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(pidfile.exists(), "command did not start before interruption")
                injected = True
                raise KeyboardInterrupt
            return original_wait(process, timeout=timeout)

        candidate = snapshot(self.config, self.root)
        with patch("subprocess.Popen.wait", new=interrupt_command_once):
            with self.assertRaises(KeyboardInterrupt):
                run_checks(candidate, self.root)
        child_pid = int(pidfile.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    def test_snapshot_drift_before_execution_prevents_command(self):
        marker = self.root / "ran"
        self.add_check(self.python(f"from pathlib import Path; Path({str(marker)!r}).touch()"))
        candidate = snapshot(self.config, self.root)
        (self.root / "repo" / "source.json").write_text('{"value": 2}')
        record = run_checks(candidate, self.root)["records"][0]
        self.assertEqual(record["checks"][0]["result"], "unknown")
        self.assertEqual(record["checks"][0]["reason"], "source_drift")
        self.assertFalse(marker.exists())

    def test_command_that_mutates_source_cannot_pass(self):
        source = self.root / "repo" / "source.json"
        self.add_check(self.python(f"from pathlib import Path; Path({str(source)!r}).write_text('{{\\\"value\\\": 2}}')"))
        record = self.run_one()
        self.assertEqual(record["result"], "unknown")
        self.assertEqual(record["checks"][0]["reason"], "source_drift")

    def test_validation_rejects_bad_requirement_argv_and_timeout(self):
        for mutation in (
            {"requirement": "missing"},
            {"argv": []},
            {"argv": ["ok", 3]},
            {"timeout_seconds": 0},
        ):
            self.add_check(self.python("pass"))
            self.config["validation_checks"][0].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate(copy.deepcopy(self.config))


if __name__ == "__main__":
    unittest.main()
