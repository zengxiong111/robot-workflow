"""End-to-end checks for the local workspace and scoped verification CLI."""

import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from robot_workflow.cli import main
from robot_workflow.engine import read_json, snapshot, write_json
from robot_workflow.report import render


class Workflow050Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'sources'
        (self.root / 'producer').mkdir(parents=True)
        (self.root / 'consumer').mkdir()
        (self.root / 'producer/value.json').write_text('{"unit":"rad"}')
        (self.root / 'consumer/value.json').write_text('{"unit":"rad"}')
        self.marker = self.base / 'executions.txt'
        self.config = {
            'schema_version': 1,
            'repositories': [{'id': name, 'path': name} for name in ('producer', 'consumer')],
            'nodes': [{'id': name, 'repository': name, 'kind': 'component',
                       'ports': [{'id': 'value', 'direction': direction, 'contract': {'unit': 'rad'}}],
                       'artifacts': [{'glob': 'value.json', 'parser': 'json'}]}
                      for name, direction in [('producer', 'output'), ('consumer', 'input')]],
            'edges': [{'from': 'producer', 'to': 'consumer', 'from_port': 'value', 'to_port': 'value',
                       'watch': ['data'], 'emits': ['data'], 'reason': 'Shared declared unit'}],
            'requirements': [{'id': 'unit', 'title': 'Units agree', 'nodes': ['producer', 'consumer']}],
            'interface_contracts': [{'id': 'units', 'requirement': 'unit',
                'producer': {'node': 'producer', 'path': 'value.json', 'pointer': '/data/unit'},
                'consumer': {'node': 'consumer', 'path': 'value.json', 'pointer': '/data/unit'}}],
            'validation_checks': [{'id': 'smoke', 'requirement': 'unit', 'repository': 'consumer',
                'argv': [sys.executable, '-B', '-c',
                         f"from pathlib import Path; p=Path({str(self.marker)!r}); p.write_text((p.read_text() if p.exists() else '')+'run\\n')"]}],
        }

    def test_cli_reuses_mixed_checks_and_force_execution_is_explicit(self):
        path, old, new = (self.base / name for name in ('snapshot.json', 'old.json', 'new.json'))
        write_json(path, snapshot(self.config, self.root))
        args = ['verify', '--snapshot', str(path), '--root', str(self.root), '--run-checks']
        self.assertEqual(main(args + ['--output', str(old)]), 0)
        self.assertEqual(self.marker.read_text(), 'run\n')
        self.assertEqual(main(args + ['--output', str(new), '--evidence', str(old)]), 0)
        self.assertEqual(self.marker.read_text(), 'run\n')
        record, = read_json(new)['records']
        self.assertTrue(record['evidence_reused'])
        self.assertEqual(main(args + ['--output', str(new)]), 0)
        self.assertEqual(self.marker.read_text(), 'run\nrun\n')

    def test_serve_cli_passes_fixed_paths_and_loopback_defaults(self):
        state = self.base / 'state'
        with patch('robot_workflow.server.serve') as serve:
            self.assertEqual(main(['serve', '--root', str(self.root), '--state-dir', str(state)]), 0)
            serve.assert_called_once_with(str(state / 'workflow.json'), str(self.root), str(state),
                                          host='127.0.0.1', port=8780)

    def test_report_contains_interfaces_and_revalidation_without_script_escape(self):
        from robot_workflow.engine import compare
        from robot_workflow.verification import verify
        value = snapshot(self.config, self.root)
        report = compare(value, value, verify(value))
        report['project'] = '</script><script>alert(1)</script>'
        output = self.base / 'report.html'
        render(report, output)
        page = output.read_text()
        self.assertIn('data-tab="ports"', page)
        self.assertIn('data-tab="revalidation"', page)
        self.assertNotIn(report['project'], page)
        payload = re.search(r'<script[^>]*id="report-data"[^>]*>(.*?)</script>', page, re.S).group(1)
        decoded = json.loads(payload)
        self.assertEqual(decoded['engineering_objects']['relations'][0]['from_port'], 'value')
        self.assertEqual(decoded['revalidation'][0]['action'], 'run')
