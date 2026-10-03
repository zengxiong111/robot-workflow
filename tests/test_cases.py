import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime

from robot_workflow.cases import sync_cases, update_case


def report(snapshot_id="candidate-a", status="potential_impact", owner="runtime-team"):
    return {
        "candidate": {"id": snapshot_id},
        "config": {"nodes": [{"id": "deploy", "owner": owner, "checks": ["smoke"]}]},
        "impacts": {"deploy": {
            "status": status,
            "paths": [{"nodes": ["robot", "deploy"], "reasons": ["interface"]}],
            "checks": ["deploy-test"],
        }},
    }


class CaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state_path = Path(self.temp.name) / "cases.json"

    def test_sync_is_idempotent_and_preserves_case_identity(self):
        first = sync_cases(report(), self.state_path)
        second = sync_cases(report(), self.state_path)
        self.assertEqual(first, second)
        self.assertEqual(len(second["cases"]), 1)
        self.assertEqual(second["cases"][0]["owner"], "runtime-team")
        self.assertEqual(second["cases"][0]["paths"][0]["nodes"], ["robot", "deploy"])
        self.assertEqual(json.loads(self.state_path.read_text())["schema_version"], 1)

    def test_distinct_candidate_snapshots_get_distinct_cases(self):
        a = sync_cases(report("a"), self.state_path)["cases"][0]
        all_cases = sync_cases(report("b"), self.state_path)["cases"]
        self.assertNotEqual(a["id"], all_cases[1]["id"])
        self.assertEqual({c["candidate_snapshot_id"] for c in all_cases}, {"a", "b"})

    def test_resync_preserves_human_owner_status_and_notes(self):
        initial = sync_cases(report(), self.state_path)["cases"][0]
        claimed = update_case(self.state_path, initial["id"], "claimed", "alice")["cases"][0]
        update_case(self.state_path, initial["id"], "open", "alice", note="Needs another review")
        refreshed = sync_cases(report(owner="new-default"), self.state_path)["cases"][0]
        self.assertEqual(refreshed["owner"], "alice")
        self.assertEqual(refreshed["status"], "open")
        self.assertEqual(refreshed["notes"][0]["text"], "Needs another review")
        self.assertEqual(len(refreshed["history"]), 2)
        self.assertEqual(claimed["owner"], "alice")

    def test_claim_assigns_actor_or_explicit_owner(self):
        case = sync_cases(report(), self.state_path)["cases"][0]
        own = update_case(self.state_path, case["id"], "claimed", "alice")["cases"][0]
        self.assertEqual(own["owner"], "alice")
        update_case(self.state_path, case["id"], "open", "alice")
        assigned = update_case(self.state_path, case["id"], "claimed", "alice", owner="bob")["cases"][0]
        self.assertEqual(assigned["owner"], "bob")

    def test_reclaim_reassigns_to_actor_and_audits_each_transition(self):
        case = sync_cases(report(), self.state_path)["cases"][0]
        update_case(self.state_path, case["id"], "claimed", "alice")
        reclaimed = update_case(self.state_path, case["id"], "claimed", "bob")["cases"][0]
        self.assertEqual(reclaimed["owner"], "bob")
        history = reclaimed["history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["from_status"], "open")
        self.assertEqual(history[0]["to_status"], "claimed")
        self.assertEqual(history[0]["from_owner"], "runtime-team")
        self.assertEqual(history[0]["to_owner"], "alice")
        self.assertEqual(history[1]["actor"], "bob")
        self.assertEqual(history[1]["from_owner"], "alice")
        self.assertEqual(history[1]["to_owner"], "bob")
        self.assertEqual(history[1]["note"], "")
        self.assertTrue(history[1]["at"].endswith("Z"))
        datetime.fromisoformat(history[1]["at"].replace("Z", "+00:00"))

    def test_invalid_status_actor_and_empty_disposition_note_rejected(self):
        case = sync_cases(report(), self.state_path)["cases"][0]
        for args in [("invalid", "alice", ""), ("claimed", "", ""),
                     ("resolved", "alice", " "), ("dismissed", "alice", "")]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                update_case(self.state_path, case["id"], args[0], args[1], note=args[2])

    def test_note_and_supplied_owner_must_be_valid_strings(self):
        case = sync_cases(report(), self.state_path)["cases"][0]
        with self.assertRaises(ValueError):
            update_case(self.state_path, case["id"], "open", "alice", note=None)
        for invalid_owner in ("", "  ", 5):
            with self.subTest(owner=invalid_owner), self.assertRaises(ValueError):
                update_case(self.state_path, case["id"], "claimed", "alice", owner=invalid_owner)

    def test_missing_case_rejected(self):
        with self.assertRaises(KeyError):
            update_case(self.state_path, "missing", "open", "alice")

    def test_closed_case_requires_explicit_reopen(self):
        case = sync_cases(report(), self.state_path)["cases"][0]
        closed = update_case(self.state_path, case["id"], "resolved", "alice", "Reviewed deployment path")
        self.assertEqual(closed["cases"][0]["status"], "resolved")
        with self.assertRaises(ValueError):
            update_case(self.state_path, case["id"], "dismissed", "bob", "Changed disposition")
        reopened = update_case(self.state_path, case["id"], "open", "alice")
        self.assertEqual(reopened["cases"][0]["status"], "open")
        self.assertEqual(len(reopened["cases"][0]["notes"]), 1)

    def test_resolution_is_recorded_as_human_disposition(self):
        case = sync_cases(report(), self.state_path)["cases"][0]
        result = update_case(self.state_path, case["id"], "resolved", "alice", "Reviewed manually")["cases"][0]
        self.assertEqual(result["status"], "resolved")
        self.assertNotIn("verified", result)
        self.assertNotIn("certified", result)


if __name__ == "__main__":
    unittest.main()
