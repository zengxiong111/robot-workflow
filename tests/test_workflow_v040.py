import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from robot_workflow.cli import main
from robot_workflow.engine import compare, snapshot, write_json
from robot_workflow.verification import pointer, verify


class IntegratedChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('producer', 'consumer'):
            (self.root / name).mkdir()
            (self.root / name / 'schema.json').write_text('{"frame":"base","units":"rad"}')
        self.config = {
            'schema_version': 1, 'repositories': [{'id': n, 'path': n} for n in ('producer', 'consumer')],
            'nodes': [{'id': n, 'repository': n, 'label': n, 'artifacts': [{'glob': 'schema.json', 'parser': 'json'}]}
                      for n in ('producer', 'consumer')],
            'edges': [], 'requirements': [{'id': 'interface', 'title': 'Interface checks', 'nodes': ['producer', 'consumer']}],
            'interface_contracts': [{'id': 'frame', 'requirement': 'interface',
                                    'producer': {'node': 'producer', 'path': 'schema.json', 'pointer': '/data/frame'},
                                    'consumer': {'node': 'consumer', 'path': 'schema.json', 'pointer': '/data/frame'}}],
            'validation_checks': [{'id': 'smoke', 'requirement': 'interface', 'repository': 'consumer',
                                   'argv': [sys.executable, '-B', '-c', 'print("ok")']}],
        }

    def run_cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(list(args))

    def test_pointer_rejects_negative_and_noncanonical_array_indexes(self):
        for value in ('/-1', '/01', '/+1', '/١'):
            with self.assertRaises(ValueError):
                pointer([10, 20], value)
        self.assertEqual(pointer([10, 20], '/1'), 20)
        self.assertEqual(pointer({'01': 20}, '/01'), 20)

    def test_skipped_command_does_not_certify_passing_interface(self):
        value = snapshot(self.config, self.root)
        evidence = verify(value)
        self.assertEqual(evidence['records'][0]['result'], 'unknown')
        report = compare(value, value, evidence)
        self.assertEqual(report['requirements'][0]['state'], 'unknown')
        self.assertEqual(len(report['requirements'][0]['verification']['checks']), 2)

    def test_all_checks_required_for_pass_and_mismatch_retained(self):
        value = snapshot(self.config, self.root)
        self.assertEqual(verify(value, self.root, True)['records'][0]['result'], 'pass')
        (self.root / 'consumer/schema.json').write_text('{"frame":"camera","units":"rad"}')
        value = snapshot(self.config, self.root)
        record = verify(value, self.root, True)['records'][0]
        self.assertEqual(record['result'], 'fail')
        self.assertEqual([c['result'] for c in record['checks']], ['fail', 'pass'])

    def test_cli_requires_explicit_execution_and_cases_embed(self):
        value = snapshot(self.config, self.root)
        snap_path, evidence_path = self.root / 'snapshot.json', self.root / 'evidence.json'
        write_json(snap_path, value)
        # State/output live outside scanned repository subdirectories.
        self.assertEqual(self.run_cli('verify', '--snapshot', str(snap_path), '--output', str(evidence_path)), 2)
        self.assertEqual(self.run_cli('verify', '--snapshot', str(snap_path), '--output', str(evidence_path),
                                      '--run-checks'), 1)
        self.assertEqual(self.run_cli('verify', '--snapshot', str(snap_path), '--output', str(evidence_path),
                                      '--run-checks', '--root', str(self.root)), 0)
        (self.root / 'consumer/schema.json').write_text('{"frame":"camera","units":"rad"}')
        report = compare(value, snapshot(self.config, self.root))
        report_path, state, html = self.root / 'report.json', self.root / 'cases.json', self.root / 'report.html'
        write_json(report_path, report)
        self.assertEqual(self.run_cli('cases', 'sync', '--input', str(report_path), '--state', str(state)), 0)
        case_id = json.loads(state.read_text())['cases'][0]['id']
        self.assertEqual(self.run_cli('cases', 'update', '--state', str(state), '--id', case_id,
                                      '--status', 'claimed', '--actor', 'tester'), 0)
        self.assertEqual(self.run_cli('report', '--input', str(report_path), '--cases', str(state),
                                      '--output', str(html)), 0)
        self.assertIn('"status": "claimed"', html.read_text())


if __name__ == '__main__':
    unittest.main()
