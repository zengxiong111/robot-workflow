import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import sys

from robot_workflow.engine import compare, snapshot
from robot_workflow.verification import verify


class RevalidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ("policy", "ui"):
            (self.root / name).mkdir()
        (self.root / "policy/input.json").write_text('{"width": 1, "other": 7}')
        (self.root / "ui/theme.json").write_text('{"color": "blue"}')
        self.config = {
            "schema_version": 1,
            "repositories": [{"id": "policy", "path": "policy"}, {"id": "ui", "path": "ui"}],
            "nodes": [
                {"id": "policy", "repository": "policy", "artifacts": [{"glob": "input.json", "parser": "json"}]},
                {"id": "ui", "repository": "ui", "artifacts": [{"glob": "theme.json", "parser": "json"}]},
            ],
            "edges": [],
            "requirements": [{"id": "width", "nodes": ["policy"], "assertions": [{
                "id": "width-is-one", "source": {"node": "policy", "path": "input.json", "pointer": "/data/width"}, "equals": 1,
            }]}],
        }

    def snap(self, config=None):
        return snapshot(config or self.config, self.root)

    def test_unrelated_repository_change_reuses_source_evidence(self):
        before = self.snap()
        evidence = verify(before)
        (self.root / "ui/theme.json").write_text('{"color": "green"}')
        after = self.snap()
        report = compare(before, after, evidence)
        self.assertEqual(report["requirements"][0]["state"], "verified")
        self.assertTrue(report["requirements"][0]["verification"]["evidence_reused"])
        self.assertEqual(report["requirements"][0]["revalidation"]["action"], "reuse")

    def test_unrelated_pointer_change_reuses_but_assertion_pointer_change_stales(self):
        before = self.snap()
        evidence = verify(before)
        (self.root / "policy/input.json").write_text('{"width": 1, "other": 8}')
        report = compare(before, self.snap(), evidence)
        self.assertEqual(report["requirements"][0]["state"], "verified")
        self.config["requirements"][0]["assertions"][0]["source"]["pointer"] = "/data/other"
        report = compare(before, self.snap(), evidence)
        self.assertEqual(report["requirements"][0]["state"], "stale")

    def test_assertion_definition_and_selected_source_change_invalidate(self):
        before = self.snap()
        evidence = verify(before)
        self.config["requirements"][0]["assertions"][0]["equals"] = 2
        report = compare(before, self.snap(), evidence)
        self.assertEqual(report["requirements"][0]["state"], "stale")
        self.config["requirements"][0]["assertions"][0]["equals"] = 1
        (self.root / "policy/input.json").write_text('{"width": 2, "other": 7}')
        report = compare(before, self.snap(), evidence)
        self.assertEqual(report["requirements"][0]["state"], "stale")

    def test_ui_metadata_change_does_not_invalidate_requirement_check(self):
        before = self.snap()
        evidence = verify(before)
        changed = copy.deepcopy(self.config)
        changed["nodes"][1]["label"] = "New UI label"
        report = compare(before, self.snap(changed), evidence)
        self.assertEqual(report["requirements"][0]["state"], "verified")

    def test_unrelated_artifact_registration_does_not_change_source_check_scope(self):
        before = self.snap()
        evidence = verify(before)
        (self.root / "policy/unused.json").write_text('{"unused": true}')
        changed = copy.deepcopy(self.config)
        changed["nodes"][0]["artifacts"].append({"glob": "unused.json", "parser": "json"})
        current = verify(self.snap(changed), evidence=evidence)
        self.assertTrue(current["records"][0]["evidence_reused"])
        changed["nodes"][0]["artifacts"][0]["parser"] = "text"
        stale = verify(self.snap(changed), evidence=evidence)
        self.assertFalse(stale["records"][0].get("evidence_reused", False))

    def test_unmatched_unrelated_glob_blocks_reuse_and_command_execution(self):
        self.config["validation_checks"] = [{"id": "smoke", "requirement": "width", "repository": "policy",
                                              "argv": [sys.executable, "-c", "raise SystemExit(0)"]}]
        before = self.snap()
        evidence = verify(before, root=self.root, run_commands=True)
        changed = copy.deepcopy(self.config)
        changed["nodes"][0]["artifacts"].append({"glob": "missing/*.json", "parser": "json"})
        candidate = self.snap(changed)
        with patch("robot_workflow.checks._matches", return_value=True), \
                patch("robot_workflow.checks.subprocess.Popen", side_effect=AssertionError("must not execute")) as process:
            result = verify(candidate, root=self.root, run_commands=True, evidence=evidence)
        process.assert_not_called()
        self.assertEqual(result["records"][0]["result"], "unknown")
        self.assertFalse(result["records"][0].get("evidence_reused", False))

    def test_missing_tracked_command_input_is_unknown_without_execution(self):
        self.config["validation_checks"] = [{"id": "smoke", "requirement": "width", "repository": "policy",
                                              "argv": [sys.executable, "-c", "raise SystemExit(0)"]}]
        repo = self.root / "policy"
        missing = repo / "large-input.bin"
        missing.write_bytes(b"fixture")
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "add", "input.json", "large-input.bin"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                        "commit", "-m", "baseline"], check=True, capture_output=True)
        missing.unlink()
        candidate = self.snap()
        self.assertEqual(candidate["nodes"]["policy"]["coverage"], "declared_sources_scanned")
        self.assertEqual(candidate["repositories"]["policy"]["command_inventory"]["coverage"], "unknown")
        with patch("robot_workflow.checks._matches", return_value=True), \
                patch("robot_workflow.checks.subprocess.Popen", side_effect=AssertionError("must not execute")) as process:
            evidence = verify(candidate, root=self.root, run_commands=True)
        process.assert_not_called()
        self.assertEqual(evidence["records"][0]["result"], "unknown")
        report = compare(candidate, candidate, evidence)
        self.assertEqual(report["requirements"][0]["state"], "unknown")
        self.assertIn("command_inventory_incomplete", report["requirements"][0]["reason"])

    def test_compare_without_evidence_plans_run_for_configured_checks(self):
        value = self.snap()
        report = compare(value, value)
        self.assertEqual(report["requirements"][0]["revalidation"]["action"], "run")
        no_checks = copy.deepcopy(self.config)
        no_checks["requirements"][0].pop("assertions")
        unconfigured = self.snap(no_checks)
        report = compare(unconfigured, unconfigured)
        self.assertEqual(report["requirements"][0]["revalidation"]["action"], "not_configured")

    def test_boolean_does_not_equal_number_and_missing_source_is_unknown(self):
        # Recompute integrity through a fresh valid snapshot.
        altered = copy.deepcopy(self.config)
        altered["requirements"][0]["assertions"][0]["equals"] = True
        self.assertEqual(verify(self.snap(altered))["records"][0]["result"], "fail")
        altered["requirements"][0]["assertions"][0]["source"]["path"] = "missing.json"
        self.assertEqual(verify(self.snap(altered))["records"][0]["result"], "unknown")

    def test_command_evidence_invalidates_on_any_selected_repo_drift(self):
        self.config["validation_checks"] = [{"id": "smoke", "requirement": "width", "repository": "policy",
                                              "argv": ["python", "-c", "pass"]}]
        before = self.snap()
        evidence = verify(before, root=self.root, run_commands=True)
        (self.root / "policy/extra.txt").write_text("changed")
        report = compare(before, self.snap(), evidence)
        self.assertEqual(report["requirements"][0]["state"], "stale")

    def test_legacy_evidence_stays_exact_snapshot_bound(self):
        before = self.snap()
        evidence = verify(before)
        for record in evidence["records"]:
            record.pop("evidence_scope", None)
        (self.root / "ui/theme.json").write_text('{"color": "green"}')
        report = compare(before, self.snap(), evidence)
        self.assertEqual(report["requirements"][0]["state"], "stale")

    def _add_command_and_interface(self, argv=None):
        self.config["requirements"][0]["nodes"] = ["policy"]
        self.config["interface_contracts"] = [{
            "id": "policy-self-interface", "requirement": "width",
            "producer": {"node": "policy", "path": "input.json", "pointer": "/data"},
            "consumer": {"node": "policy", "path": "input.json", "pointer": "/data"},
            "fields": [{"name": "width", "pointer": "/width"}],
        }]
        self.config["validation_checks"] = [{"id": "smoke", "requirement": "width", "repository": "policy",
                                              "argv": argv or [sys.executable, "-c", "pass"]}]

    def test_mixed_interface_and_command_reuses_complete_passing_record(self):
        from robot_workflow import checks
        self._add_command_and_interface()
        before = self.snap()
        evidence = verify(before, root=self.root, run_commands=True)
        self.assertEqual(evidence["records"][0]["result"], "pass")
        with patch.object(checks, "run_checks", side_effect=AssertionError("should reuse")):
            reused = verify(self.snap(), root=self.root, run_commands=True, evidence=evidence)
        self.assertEqual(reused["records"][0]["result"], "pass")
        self.assertTrue(reused["records"][0]["evidence_reused"])
        self.assertEqual(reused["revalidation"][0]["action"], "reuse")

    def test_command_definition_change_reruns_and_old_failure_is_not_retained(self):
        from robot_workflow import checks
        self._add_command_and_interface([sys.executable, "-c", "raise SystemExit(2)"])
        before = self.snap()
        failed = verify(before, root=self.root, run_commands=True)
        self.assertEqual(failed["records"][0]["result"], "fail")
        self.config["validation_checks"][0]["argv"] = [sys.executable, "-c", "pass"]
        with patch("robot_workflow.checks.run_checks", wraps=checks.run_checks) as run:
            corrected = verify(self.snap(), root=self.root, run_commands=True, evidence=failed)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(corrected["records"][0]["result"], "pass")
        self.assertFalse(corrected["records"][0].get("evidence_reused", False))

    def test_adding_a_check_kind_invalidates_aggregate_coverage(self):
        before = self.snap()
        evidence = verify(before)
        self._add_command_and_interface()
        with patch("robot_workflow.checks.run_checks") as run:
            candidate = verify(self.snap(), root=self.root, run_commands=True, evidence=evidence)
        run.assert_called_once()
        self.assertFalse(candidate["records"][0].get("evidence_reused", False))

    def test_command_reuse_survives_an_unrelated_repository_change(self):
        self._add_command_and_interface()
        before = self.snap()
        evidence = verify(before, root=self.root, run_commands=True)
        (self.root / "ui/theme.json").write_text('{"color": "red"}')
        with patch("robot_workflow.checks.run_checks", side_effect=AssertionError("should reuse")):
            report = verify(self.snap(), root=self.root, run_commands=True, evidence=evidence)
        self.assertTrue(report["records"][0]["evidence_reused"])

    def test_only_stale_requirement_command_runs_and_other_record_is_reused(self):
        policy_counter = self.root / "policy-runs.txt"
        ui_counter = self.root / "ui-runs.txt"
        self.config["requirements"].append({"id": "theme", "nodes": ["ui"]})
        self.config["validation_checks"] = [
            {"id": "policy-smoke", "requirement": "width", "repository": "policy",
             "argv": [sys.executable, "-c", f"from pathlib import Path; p=Path({str(policy_counter)!r}); p.write_text((p.read_text() if p.exists() else '')+'run\\n')"]},
            {"id": "ui-smoke", "requirement": "theme", "repository": "ui",
             "argv": [sys.executable, "-c", f"from pathlib import Path; p=Path({str(ui_counter)!r}); p.write_text((p.read_text() if p.exists() else '')+'run\\n')"]},
        ]
        before = self.snap()
        evidence = verify(before, root=self.root, run_commands=True)
        (self.root / "policy/extra.txt").write_text("changed command input")
        updated = verify(self.snap(), root=self.root, run_commands=True, evidence=evidence)
        self.assertEqual(policy_counter.read_text(), "run\nrun\n")
        self.assertEqual(ui_counter.read_text(), "run\n")
        records = {record["requirement"]: record for record in updated["records"]}
        self.assertFalse(records["width"].get("evidence_reused", False))
        self.assertTrue(records["theme"]["evidence_reused"])
        self.assertEqual({record["requirement"] for record in updated["records"]}, {"width", "theme"})

    def test_ignored_selected_repository_file_is_in_command_inventory(self):
        self._add_command_and_interface()
        repo = self.root / "policy"
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        (repo / ".gitignore").write_text("ignored.bin\n")
        (repo / "tracked.bin").write_bytes(b"tracked")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore", "input.json", "tracked.bin"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                        "commit", "-m", "baseline"], check=True, capture_output=True)
        (repo / "ignored.bin").write_bytes(b"first")
        (repo / "untracked.bin").write_bytes(b"untracked")
        for relative in ("tracked.bin", "untracked.bin", "ignored.bin"):
            before = self.snap()
            evidence = verify(before, root=self.root, run_commands=True)
            (repo / relative).write_bytes(b"changed")
            with patch("robot_workflow.checks.run_checks") as run:
                candidate = verify(self.snap(), root=self.root, run_commands=True, evidence=evidence)
            run.assert_called_once()
            self.assertFalse(candidate["records"][0].get("evidence_reused", False))
            (repo / relative).write_bytes(b"tracked" if relative == "tracked.bin" else
                                          b"untracked" if relative == "untracked.bin" else b"first")

    def test_runtime_change_and_legacy_fingerprint_mismatch_invalidate(self):
        self._add_command_and_interface()
        before = self.snap()
        evidence = verify(before, root=self.root, run_commands=True)
        with patch("robot_workflow.revalidation.current_runtime", return_value={"python": "different"}):
            with patch("robot_workflow.checks.run_checks") as run:
                verify(self.snap(), root=self.root, run_commands=True, evidence=evidence)
            run.assert_called_once()
        source_only = verify(self.snap())
        for record in source_only["records"]:
            record.pop("evidence_scope", None)
            record["fingerprints"]["policy"] = "tampered"
        report = compare(before, self.snap(), source_only)
        self.assertEqual(report["requirements"][0]["state"], "stale")

    def test_compare_rejects_removing_a_graph_edge(self):
        configured = copy.deepcopy(self.config)
        configured["edges"] = [{"from": "policy", "to": "ui", "watch": ["data"],
                                "emits": ["data"], "reason": "policy flow"}]
        before = self.snap(configured)
        configured["edges"] = []
        with self.assertRaisesRegex(ValueError, "graph changes"):
            compare(before, self.snap(configured))


if __name__ == "__main__":
    unittest.main()
