import copy
import unittest
from unittest.mock import patch

from robot_workflow.interface_contracts import check, validate


class InterfaceContractTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "schema_version": 1,
            "nodes": [{"id": "producer"}, {"id": "consumer"}],
            "requirements": [{"id": "runtime", "nodes": ["producer", "consumer"]}],
            "interface_contracts": [{
                "id": "policy-input",
                "requirement": "runtime",
                "producer": {"node": "producer", "path": "schema.json", "pointer": "/data"},
                "consumer": {"node": "consumer", "path": "config.json", "pointer": "/input"},
                "fields": [
                    {"name": "units", "pointer": "/units"},
                    {"name": "frame", "pointer": "/frame"},
                ],
            }],
        }
        self.snapshot = {
            "config": self.config,
            "snapshot_id": "snapshot-1",
            "nodes": {
                "producer": {"fingerprint": "fp-p", "files": {
                    "schema.json": {"facets": {"data": {"units": "rad", "frame": "base"}}}}},
                "consumer": {"fingerprint": "fp-c", "files": {
                    "config.json": {"facets": {"input": {"units": "rad", "frame": "base"}}}}},
            },
        }

    def test_validate_accepts_explicit_selected_fields(self):
        self.assertIs(validate(self.config), self.config)

    def test_matching_selected_fields_pass(self):
        with patch("robot_workflow.engine.validate_snapshot"):
            result = check(self.snapshot)
        record, = result["records"]
        self.assertEqual(record["result"], "pass")
        self.assertEqual(record["method"], "interface_contracts")
        self.assertEqual(record["requirement"], "runtime")
        self.assertEqual(record["fingerprints"], {"producer": "fp-p", "consumer": "fp-c"})
        self.assertEqual([c["id"] for c in record["checks"]],
                         ["policy-input:units", "policy-input:frame"])
        self.assertEqual(record["checks"][0]["producer"], self.config["interface_contracts"][0]["producer"])
        self.assertEqual(record["checks"][0]["consumer"], self.config["interface_contracts"][0]["consumer"])
        self.assertEqual(record["checks"][0]["field_pointer"], "/units")
        self.assertNotIn("value", record["checks"][0])

    def test_mismatch_fails_with_field_level_detail(self):
        self.snapshot["nodes"]["consumer"]["files"]["config.json"]["facets"]["input"]["units"] = "degree"
        with patch("robot_workflow.engine.validate_snapshot"):
            record, = check(self.snapshot)["records"]
        self.assertEqual(record["result"], "fail")
        self.assertEqual(record["checks"][0], {
            "id": "policy-input:units", "result": "fail",
            "summary": "Selected interface field mismatch",
            "producer": self.config["interface_contracts"][0]["producer"],
            "consumer": self.config["interface_contracts"][0]["consumer"],
            "field_pointer": "/units"})

    def test_json_boolean_does_not_match_integer(self):
        self.snapshot["nodes"]["producer"]["files"]["schema.json"]["facets"]["data"]["units"] = True
        self.snapshot["nodes"]["consumer"]["files"]["config.json"]["facets"]["input"]["units"] = 1
        with patch("robot_workflow.engine.validate_snapshot"):
            record, = check(self.snapshot)["records"]
        self.assertEqual(record["result"], "fail")
        self.assertEqual(record["checks"][0]["result"], "fail")

    def test_mismatch_takes_precedence_over_missing_selected_field(self):
        self.snapshot["nodes"]["consumer"]["files"]["config.json"]["facets"]["input"]["units"] = "degree"
        del self.snapshot["nodes"]["consumer"]["files"]["config.json"]["facets"]["input"]["frame"]
        with patch("robot_workflow.engine.validate_snapshot"):
            record, = check(self.snapshot)["records"]
        self.assertEqual(record["result"], "fail")
        self.assertEqual([item["result"] for item in record["checks"]], ["fail", "unknown"])

    def test_missing_source_is_unknown_not_pass(self):
        del self.snapshot["nodes"]["consumer"]["files"]["config.json"]
        with patch("robot_workflow.engine.validate_snapshot"):
            record, = check(self.snapshot)["records"]
        self.assertEqual(record["result"], "unknown")
        self.assertEqual(record["checks"][0]["result"], "unknown")
        self.assertIn("Cannot evaluate interface source", record["checks"][0]["summary"])

    def test_missing_selected_field_is_unknown(self):
        del self.snapshot["nodes"]["consumer"]["files"]["config.json"]["facets"]["input"]["frame"]
        with patch("robot_workflow.engine.validate_snapshot"):
            record, = check(self.snapshot)["records"]
        self.assertEqual(record["result"], "unknown")
        self.assertEqual(record["checks"][1]["result"], "unknown")

    def test_malformed_contracts_rejected(self):
        mutations = [
            lambda c: c["interface_contracts"].append(copy.deepcopy(c["interface_contracts"][0])),
            lambda c: c["interface_contracts"][0].update(requirement="absent"),
            lambda c: c["interface_contracts"][0]["consumer"].update(node="absent"),
            lambda c: c["interface_contracts"][0]["producer"].update(path="../secret.json"),
            lambda c: c["interface_contracts"][0]["consumer"].update(pointer="/bad~2escape"),
            lambda c: c["interface_contracts"][0]["fields"][0].update(pointer="relative"),
            lambda c: c["interface_contracts"][0]["fields"].append(
                {"name": "units", "pointer": "/other"}),
            lambda c: c["requirements"][0].update(nodes=["producer"]),
        ]
        for mutate in mutations:
            config = copy.deepcopy(self.config)
            mutate(config)
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate(config)


if __name__ == "__main__":
    unittest.main()
