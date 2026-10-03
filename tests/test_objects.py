import copy
import unittest

from robot_workflow.objects import engineering_objects, validate


class EngineeringObjectsTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "schema_version": 1,
            "nodes": [
                {"id": "planner", "kind": "model", "ports": [
                    {"id": "trajectory", "direction": "output", "contract": {
                        "type": "JointTrajectory", "unit": "rad", "frame": "base",
                        "joint_order": ["j1", "j2"], "rate_hz": 100}}]},
                {"id": "controller", "kind": "component", "ports": [
                    {"id": "command", "direction": "input", "contract": {
                        "type": "JointTrajectory", "unit": "rad", "frame": "base",
                        "joint_order": ["j1", "j2"], "rate_hz": 100}}]},
            ],
            "edges": [{"from": "planner", "to": "controller", "from_port": "trajectory",
                       "to_port": "command"}],
        }

    def test_schema_one_without_engineering_metadata_remains_valid(self):
        config = {"schema_version": 1, "nodes": [{"id": "legacy"}], "edges": []}
        self.assertIs(validate(config), config)
        projection = engineering_objects(config)
        self.assertEqual(projection["nodes"], [{"id": "legacy", "kind": None, "ports": []}])

    def test_matching_metadata_is_declared_only(self):
        projection = engineering_objects(self.config)
        relation, = projection["relations"]
        self.assertEqual(relation["contract_comparison"]["unit"]["status"], "match")
        self.assertEqual(relation["contract_comparison"]["joint_order"]["status"], "match")
        self.assertEqual(projection["evidence_layer"], "declared_configuration_metadata")
        self.assertIn("does not establish", projection["claim_boundary"])

    def test_unit_frame_and_joint_order_mismatches_are_visible(self):
        config = copy.deepcopy(self.config)
        consumer = config["nodes"][1]["ports"][0]["contract"]
        consumer.update(unit="deg", frame="tool", joint_order=["j2", "j1"])
        comparisons = engineering_objects(config)["relations"][0]["contract_comparison"]
        for field in ("unit", "frame", "joint_order"):
            self.assertEqual(comparisons[field]["status"], "mismatch")

    def test_missing_contract_field_is_unknown(self):
        config = copy.deepcopy(self.config)
        del config["nodes"][1]["ports"][0]["contract"]["frame"]
        comparison = engineering_objects(config)["relations"][0]["contract_comparison"]["frame"]
        self.assertEqual(comparison["status"], "unknown")
        self.assertTrue(comparison["source_declared"])
        self.assertFalse(comparison["target_declared"])

    def test_rate_must_be_finite_positive_number_not_boolean(self):
        config = copy.deepcopy(self.config)
        config["nodes"][0]["ports"][0]["contract"]["rate_hz"] = True
        # Invalid rate types are rejected rather than compared using Python equality.
        with self.assertRaises(ValueError):
            engineering_objects(config)
        config["nodes"][0]["ports"][0]["contract"]["rate_hz"] = 1
        self.assertEqual(engineering_objects(config)["relations"][0]["contract_comparison"]["rate_hz"]["status"],
                         "mismatch")

    def test_digest_comparison_uses_canonical_json_representation(self):
        config = copy.deepcopy(self.config)
        config["nodes"][0]["ports"][0]["contract"]["rate_hz"] = 1
        config["nodes"][1]["ports"][0]["contract"]["rate_hz"] = 1.0
        self.assertEqual(engineering_objects(config)["relations"][0]["contract_comparison"]["rate_hz"]["status"],
                         "mismatch")

    def test_no_conversion_is_invented(self):
        config = copy.deepcopy(self.config)
        config["nodes"][1]["ports"][0]["contract"]["unit"] = "deg"
        relation, = engineering_objects(config)["relations"]
        self.assertEqual(relation["contract_comparison"]["unit"]["status"], "mismatch")
        self.assertFalse(any(key in relation for key in ("conversion", "transform", "adapter")))

    def test_dangling_or_wrong_direction_ports_are_rejected(self):
        mutations = [
            lambda c: c["edges"][0].update(from_port="absent"),
            lambda c: c["edges"][0].update(to_port="absent"),
            lambda c: c["nodes"][0]["ports"][0].update(direction="input"),
            lambda c: c["nodes"][1]["ports"][0].update(direction="output"),
            lambda c: c["edges"][0].pop("to_port"),
        ]
        for mutate in mutations:
            config = copy.deepcopy(self.config)
            mutate(config)
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate(config)

    def test_bad_optional_metadata_is_rejected(self):
        mutations = [
            lambda c: c["nodes"][0].update(kind="robot"),
            lambda c: c["nodes"][0]["ports"][0].update(id=""),
            lambda c: c["nodes"][0]["ports"][0]["contract"].update(rate_hz=0),
            lambda c: c["nodes"][0]["ports"][0]["contract"].update(joint_order=["j", "j"]),
        ]
        for mutate in mutations:
            config = copy.deepcopy(self.config)
            mutate(config)
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate(config)


if __name__ == "__main__":
    unittest.main()
