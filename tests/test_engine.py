import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from robot_workflow.contracts import extract
from robot_workflow.engine import compare, snapshot, validate_config, write_json
from robot_workflow.cli import main
from robot_workflow.report import render
from robot_workflow.verification import verify


URDF = '''<robot name="r"><link name="base"/><link name="hand">
<inertial><mass value="1"/></inertial><visual><geometry><mesh filename="a.stl"/></geometry></visual>
</link><joint name="wrist" type="revolute"><parent link="base"/><child link="hand"/>
<origin xyz="0 0 1" rpy="0 0 0"/><axis xyz="0 0 1"/><limit lower="-1" upper="1" effort="2" velocity="3"/>
</joint></robot>'''


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('robot', 'policy', 'deploy'):
            (self.root / name).mkdir()
        (self.root / 'robot/model.urdf').write_text(URDF)
        (self.root / 'policy/actor.json').write_text('{"width":134,"order":["object","hand"]}')
        (self.root / 'deploy/config.json').write_text('{"clock":"ROS"}')
        self.config = {
            'schema_version': 1, 'project': 'Test robot',
            'repositories': [{'id': n, 'path': n} for n in ('robot', 'policy', 'deploy')],
            'nodes': [
                {'id': 'robot', 'label': 'Robot', 'repository': 'robot', 'artifacts': [{'glob': 'model.urdf', 'parser': 'urdf'}]},
                {'id': 'policy', 'label': 'Policy', 'repository': 'policy', 'artifacts': [{'glob': 'actor.json', 'parser': 'json'}]},
                {'id': 'deploy', 'label': 'Deploy', 'repository': 'deploy', 'artifacts': [{'glob': 'config.json', 'parser': 'json'}]},
            ],
            'edges': [
                {'from': 'robot', 'to': 'policy', 'watch': ['kinematics', 'joint_order'], 'emits': ['data'], 'reason': 'FK contract'},
                {'from': 'policy', 'to': 'deploy', 'watch': ['data'], 'emits': ['config'], 'reason': 'Policy contract'},
            ],
            'requirements': [{'id': 'width', 'title': 'Width 134', 'nodes': ['policy'], 'assertions': [
                {'id': 'width', 'source': {'node': 'policy', 'path': 'actor.json', 'pointer': '/data/width'}, 'equals': 134}]}],
        }

    def snap(self):
        return snapshot(self.config, self.root)

    def test_kinematics_propagates_transitively_with_reason(self):
        old = self.snap()
        (self.root / 'robot/model.urdf').write_text(URDF.replace('xyz="0 0 1" rpy', 'xyz="0 0 2" rpy'))
        report = compare(old, self.snap())
        self.assertEqual(report['impacts']['deploy']['status'], 'potential_impact')
        paths = report['impacts']['deploy']['paths']
        self.assertEqual(paths[0]['nodes'], ['robot', 'policy', 'deploy'])
        self.assertEqual(paths[0]['reasons'], ['FK contract', 'Policy contract'])

    def test_visual_change_does_not_invalidate_kinematics(self):
        old = self.snap()
        (self.root / 'robot/model.urdf').write_text(URDF.replace('a.stl', 'b.stl'))
        report = compare(old, self.snap())
        self.assertEqual(report['changes'][0]['facets'], ['visuals'])
        self.assertEqual(report['impacts']['policy']['status'], 'no_registered_impact')

    def test_mass_has_distinct_dynamics_facet(self):
        old = self.snap()
        (self.root / 'robot/model.urdf').write_text(URDF.replace('value="1"', 'value="2"'))
        self.assertEqual(compare(old, self.snap())['changes'][0]['facets'], ['dynamics'])

    def test_json_order_same_dimension_is_a_semantic_change(self):
        old = self.snap()
        (self.root / 'policy/actor.json').write_text('{"width":134,"order":["hand","object"]}')
        report = compare(old, self.snap())
        self.assertEqual(report['impacts']['deploy']['status'], 'potential_impact')
        self.assertEqual(report['changes'][0]['details'][0]['path'], '/data/order')

    def test_deleted_artifact_is_unknown_and_propagates(self):
        old = self.snap()
        (self.root / 'robot/model.urdf').unlink()
        report = compare(old, self.snap())
        self.assertEqual(report['impacts']['robot']['status'], 'unknown')
        self.assertEqual(report['impacts']['deploy']['status'], 'unknown')

    def test_parse_error_is_unknown(self):
        (self.root / 'robot/model.urdf').write_text('<robot>')
        self.assertTrue(self.snap()['nodes']['robot']['problems'])

    def test_python_comment_and_docstring_are_nonsemantic(self):
        a = b'"""old"""\nx=1\ndef f():\n    """a"""\n    return x\n'
        b = b'"""new"""\n# comment\nx = 1\ndef f():\n    """b"""\n    return x\n'
        self.assertEqual(extract(a, 'python'), extract(b, 'python'))
        self.assertNotEqual(extract(b.replace(b'x = 1', b'x = 2'), 'python'), extract(a, 'python'))

    def test_ros_schema_and_comment_handling(self):
        self.assertEqual(extract(b'float64[] q # hi\n', 'ros'), extract(b'float64[]   q\n', 'ros'))
        self.assertNotEqual(extract(b'float64[] q', 'ros'), extract(b'float32[] q', 'ros'))

    def test_yaml_preserves_hash_inside_quotes(self):
        self.assertNotEqual(extract(b'frame: "a#b"', 'yaml'), extract(b'frame: "a#c"', 'yaml'))

    def test_lfs_pointer_is_unknown(self):
        with self.assertRaises(ValueError):
            extract(b'version https://git-lfs.github.com/spec/v1\noid sha256:x', 'text')

    def test_path_traversal_and_bad_edges_rejected(self):
        config = copy.deepcopy(self.config)
        config['nodes'][0]['artifacts'][0]['glob'] = '../secret'
        with self.assertRaises(ValueError):
            validate_config(config)
        config = copy.deepcopy(self.config)
        config['edges'][0]['to'] = 'missing'
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_symlink_escape_not_read(self):
        outside = self.root / 'secret'
        outside.write_text('secret')
        (self.root / 'robot/model.urdf').unlink()
        (self.root / 'robot/model.urdf').symlink_to(outside)
        node = self.snap()['nodes']['robot']
        self.assertFalse(node['files'])
        self.assertIn('escapes', node['problems'][0]['reason'])

    def test_cycle_terminates_and_preserves_change_status(self):
        self.config['edges'].append({'from': 'deploy', 'to': 'robot', 'watch': ['config'], 'emits': ['kinematics'], 'reason': 'cycle'})
        old = self.snap()
        (self.root / 'robot/model.urdf').write_text(URDF.replace('upper="1"', 'upper="2"'))
        result = compare(old, self.snap())
        self.assertEqual(result['impacts']['robot']['status'], 'changed')

    def test_evidence_expires_on_candidate_change(self):
        old = self.snap()
        evidence = verify(old)
        self.assertEqual(compare(old, old, evidence)['requirements'][0]['state'], 'verified')
        (self.root / 'policy/actor.json').write_text('{"width":135}')
        new = self.snap()
        self.assertEqual(compare(old, new, evidence)['requirements'][0]['state'], 'stale')
        self.assertEqual(compare(old, new, verify(new))['requirements'][0]['state'], 'failed')

    def test_snapshot_tamper_is_rejected(self):
        old = self.snap()
        new = copy.deepcopy(old)
        new['nodes']['robot']['files']['model.urdf']['facets']['joint_order'] = []
        with self.assertRaisesRegex(ValueError, 'integrity'):
            compare(old, new)

    def test_graph_change_requires_separate_review(self):
        old = self.snap()
        self.config['edges'][0]['reason'] = 'new dependency'
        with self.assertRaisesRegex(ValueError, 'Configs differ'):
            compare(old, self.snap())

    def test_unregistered_source_change_is_not_silent(self):
        (self.root / 'robot/driver.py').write_text('x=1')
        old = self.snap()
        (self.root / 'robot/driver.py').write_text('x=2')
        report = compare(old, self.snap())
        self.assertEqual(report['unregistered_changes'][0]['path'], 'driver.py')
        self.assertEqual(report['unregistered_changes'][0]['status'], 'unknown')

    def test_git_untracked_source_addition_is_unknown(self):
        repo = self.root / 'robot'
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), 'add', 'model.urdf'], check=True)
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                        'commit', '-qm', 'baseline'], check=True)
        old = self.snap()
        (repo / 'new_driver.py').write_text('POSITION_SCALE=2')
        report = compare(old, self.snap())
        self.assertEqual(report['unregistered_changes'][0]['path'], 'new_driver.py')
        self.assertEqual(report['summary']['unregistered_changes'], 1)

    def test_readiness_is_bound_and_expires(self):
        repo = self.root / 'robot'
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), 'add', 'model.urdf'], check=True)
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                        'commit', '-qm', 'baseline'], check=True)
        initial = self.snap()
        self.config['nodes'][0]['readiness'] = {'state':'implemented', 'summary':'Source inspected',
            'reviewed_commit':initial['repositories']['robot']['commit'],
            'reviewed_fingerprint':initial['nodes']['robot']['fingerprint']}
        old = self.snap()
        self.assertEqual(compare(old, old)['readiness']['robot']['state'], 'implemented')
        (repo / 'model.urdf').write_text(URDF.replace('upper="1"', 'upper="2"'))
        self.assertEqual(compare(old, self.snap())['readiness']['robot']['state'], 'stale')

    def test_nested_checkout_does_not_inherit_parent_commit(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.assertIsNone(self.snap()['repositories']['robot']['commit'])

    def test_report_escapes_untrusted_html(self):
        old = self.snap()
        report = compare(old, old)
        report['project'] = '</script><script>alert(1)</script>'
        path = self.root / 'report.html'
        render(report, path)
        self.assertNotIn('</script><script>alert(1)', path.read_text())
        self.assertIn('\\u003c/script', path.read_text())

    def test_cli_end_to_end_and_gate(self):
        config = self.root / 'workflow.json'
        write_json(config, self.config)
        old = self.root / 'before.json'
        new = self.root / 'after.json'
        report = self.root / 'report.json'
        html = self.root / 'report.html'
        self.assertEqual(main(['snapshot', '--config', str(config), '--root', str(self.root), '--output', str(old)]), 0)
        (self.root / 'policy/actor.json').write_text('{"width":135}')
        self.assertEqual(main(['snapshot', '--config', str(config), '--root', str(self.root), '--output', str(new)]), 0)
        self.assertEqual(main(['compare', '--before', str(old), '--after', str(new), '--output', str(report), '--html', str(html), '--fail-on-impact']), 2)
        self.assertTrue(html.exists())


if __name__ == '__main__':
    unittest.main()
