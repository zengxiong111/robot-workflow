import subprocess
import tempfile
import unittest
from pathlib import Path

from robot_workflow.discovery import discover
from robot_workflow.engine import compare, snapshot, validate_config


def git_repo(path):
    path.mkdir(parents=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_discovers_real_checkouts_and_declared_dependency(self):
        robot = self.root / "robot"
        policy = self.root / "policy"
        git_repo(robot)
        git_repo(policy)
        (robot / "model.urdf").write_text('<robot name="r"><link name="base"/></robot>')
        (robot / "package.xml").write_text('<package><name>robot_model</name><version>1</version><description>x</description><maintainer email="x">x</maintainer><license>MIT</license></package>')
        (policy / "pyproject.toml").write_text('[project]\nname="policy"\ndependencies=["robot_model>=1"]\n')
        (policy / "src.py").write_text("def policy(): return 1\n")
        config = discover(self.root, project="Demo")
        validate_config(config)
        self.assertEqual(config["project"], "Demo")
        self.assertEqual({r["path"] for r in config["repositories"]}, {"robot", "policy"})
        self.assertEqual(len(config["nodes"]), 2)
        edge, = config["edges"]
        self.assertEqual((edge["from"], edge["to"]), ("robot", "policy"))
        self.assertIn("pyproject.toml:3", edge["reason"])
        self.assertEqual(edge["basis"], "inferred: python dependency declaration")
        self.assertEqual(config["nodes"][0]["owner"], "unassigned")
        before = snapshot(config, self.root)
        (robot / "model.urdf").write_text('<robot name="r"><link name="base"/><link name="arm"/><joint name="j" type="revolute"><parent link="base"/><child link="arm"/><axis xyz="0 0 1"/></joint></robot>')
        report = compare(before, snapshot(config, self.root))
        self.assertEqual(report["impacts"]["policy"]["status"], "potential_impact")
        self.assertEqual(report["impacts"]["policy"]["paths"][0]["nodes"], ["robot", "policy"])

    def test_only_explicit_repository_reference_creates_edge(self):
        a, b = self.root / "a", self.root / "b"
        git_repo(a); git_repo(b)
        (a / "module.py").write_text("# see ../b/model.urdf\n")
        (a / "x.json").write_text('{"same": true}')
        (b / "x.json").write_text('{"same": true}')
        config = discover(self.root)
        self.assertEqual(len(config["edges"]), 1)
        self.assertEqual(config["edges"][0]["basis"], "inferred: explicit local repository path reference")

    def test_bare_repository_word_does_not_create_reference_edge(self):
        a, b = self.root / "a", self.root / "b"
        git_repo(a); git_repo(b)
        (a / "code.py").write_text("repository = 'b'\n# b is just a project word\n")
        (a / "config.json").write_text('{"x": 1}')
        (b / "config.json").write_text('{"x": 1}')
        self.assertEqual(discover(self.root)["edges"], [])

    def test_multiline_toml_dependencies_are_resolved(self):
        provider, consumer = self.root / "provider", self.root / "consumer"
        git_repo(provider); git_repo(consumer)
        (provider / "pyproject.toml").write_text('[project]\nname="robot-lib"\n')
        (consumer / "pyproject.toml").write_text('[project]\nname="consumer"\ndependencies = [\n  "other-lib>=1",\n  "robot-lib>=2",\n]\n')
        config = discover(self.root)
        edge, = config["edges"]
        self.assertEqual((edge["from"], edge["to"]), ("provider", "consumer"))
        self.assertIn("pyproject.toml:5", edge["reason"])

    def test_github_reference_requires_exact_remote_identity(self):
        consumer, expected, same_name = (self.root / name for name in ("consumer", "expected", "same-name"))
        for repo in (consumer, expected, same_name):
            git_repo(repo)
        for repo, remote in ((expected, "https://github.com/acme/robot-lib.git"),
                             (same_name, "https://github.com/other/robot-lib.git")):
            subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", remote], check=True)
        (consumer / "source.py").write_text("# docs: https://github.com/stranger/robot-lib\n")
        (consumer / "config.json").write_text('{"x": 1}')
        (expected / "config.json").write_text('{"x": 1}')
        (same_name / "config.json").write_text('{"x": 1}')
        self.assertEqual(discover(self.root)["edges"], [])
        (consumer / "source.py").write_text("# docs: https://github.com/acme/robot-lib\n")
        edge, = discover(self.root)["edges"]
        self.assertEqual((edge["from"], edge["to"]), ("expected", "consumer"))
        self.assertEqual(edge["basis"], "inferred: exact GitHub remote identity reference")

    def test_setup_py_literal_dependencies_are_parsed_without_execution(self):
        provider, consumer = self.root / "provider", self.root / "consumer"
        git_repo(provider); git_repo(consumer)
        (provider / "pyproject.toml").write_text('[project]\nname="robot-lib"\n')
        (consumer / "setup.py").write_text("from setuptools import setup\nsetup(install_requires=['robot-lib>=1'])\n")
        edge, = discover(self.root)["edges"]
        self.assertEqual((edge["from"], edge["to"]), ("provider", "consumer"))
        self.assertIn("setup.py:2", edge["reason"])

    def test_empty_checkout_scan_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "No Git checkouts"):
            discover(self.root)

    def test_ignores_non_git_and_symlinked_checkout(self):
        plain = self.root / "plain"
        plain.mkdir()
        outside = Path(self.temp.name).parent / (Path(self.temp.name).name + "-outside")
        git_repo(outside)
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        (self.root / "linked").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "No Git checkouts"):
            discover(self.root)

    def test_skips_readme_noise_and_reports_oversized_files(self):
        repo = self.root / "repo"
        git_repo(repo)
        (repo / "README.md").write_text("large documentation noise")
        (repo / "model.urdf").write_text('<robot name="r"><link name="base"/></robot>')
        (repo / "large.py").write_bytes(b"#" + b" " * 1_000_001)
        config = discover(self.root)
        globs = {a["glob"] for a in config["nodes"][0]["artifacts"]}
        self.assertIn("model.urdf", globs)
        self.assertNotIn("README.md", globs)
        self.assertTrue(any("large.py" in note for note in config["discovery"]["notes"]))


if __name__ == "__main__":
    unittest.main()
