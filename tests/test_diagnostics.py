import subprocess
import tempfile
import unittest
from pathlib import Path

from robot_workflow.diagnostics import inspect_workflow
from robot_workflow.discovery import discover


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                         text=True, check=True).stdout.strip()


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def repo(self, name):
        path = self.root / name
        path.mkdir()
        git(path, "init", "-q")
        git(path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "--allow-empty", "-m", "initial")
        return path

    def test_reports_setup_problems_without_mutation(self):
        provider = self.repo("provider")
        consumer = self.repo("consumer")
        (provider / "README.md").write_text("# Provider\n")
        (provider / "pyproject.toml").write_text('[project]\nname="provider"\n')
        (consumer / "pyproject.toml").write_text(
            '[project]\nname="consumer"\ndependencies=["provider"]\n')
        docs = self.repo("docs")
        (docs / "README.md").write_text("# Documentation only\n")
        config = discover(self.root)
        # Make one declared artifact missing so snapshot diagnostics can surface it.
        next(n for n in config["nodes"] if n["id"] == "consumer")["artifacts"] = [
            {"glob": "missing.json", "parser": "json"}]
        before_status = {p.name: git(p, "status", "--porcelain") for p in (provider, consumer, docs)}
        issues = inspect_workflow(config, self.root)["issues"]
        messages = [i["message"] for i in issues]
        self.assertTrue(any("No matching source files" in m for m in messages))
        self.assertTrue(any("No maintainer" in m for m in messages))
        self.assertTrue(any("Inferred dependency needs review" in m for m in messages))
        self.assertTrue(any("documentation-only" in m for m in messages))
        self.assertTrue(any("no configured upstream" in m for m in messages))
        self.assertTrue(any("Discovery note" in m for m in messages))
        self.assertTrue(all(set(i) == {"severity", "node", "message", "action"} for i in issues))
        self.assertEqual(before_status, {p.name: git(p, "status", "--porcelain") for p in (provider, consumer, docs)})

    def test_invalid_config_returns_readable_error(self):
        issues = inspect_workflow({"schema_version": 8}, self.root)["issues"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "error")
        self.assertIsNone(issues[0]["node"])
        self.assertTrue(issues[0]["action"])


if __name__ == "__main__":
    unittest.main()
