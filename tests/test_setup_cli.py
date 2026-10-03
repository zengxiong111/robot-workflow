"""CLI onboarding behavior using disposable local repositories."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from robot_workflow.cli import main


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'repos'
        self.repo = self.root / 'model'
        self.repo.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        (self.repo / 'model.json').write_text('{"joint_order":["j1"]}')
        self.config = self.base / 'workflow.json'

    def run_cli(self, args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(args)

    def test_init_discovers_and_routes_without_overwriting_configuration(self):
        args = ['init', '--root', str(self.root), '--output', str(self.config),
                '--owner', 'controls', '--route', 'controls=CONTROLS_WEBHOOK_URL']
        self.assertEqual(self.run_cli(args), 0)
        config = json.loads(self.config.read_text())
        self.assertEqual(config['nodes'][0]['owner'], 'controls')
        self.assertEqual(config['notifications']['recipients'], {'controls': 'CONTROLS_WEBHOOK_URL'})
        original = self.config.read_bytes()
        self.assertEqual(self.run_cli(args), 1)
        self.assertEqual(self.config.read_bytes(), original)

    def test_init_rejects_output_inside_inspected_checkout(self):
        self.assertEqual(self.run_cli(['init', '--root', str(self.root),
                                      '--output', str(self.repo / 'workflow.json')]), 1)
        self.assertFalse((self.repo / 'workflow.json').exists())

    def test_start_once_creates_configuration_and_baseline(self):
        state = self.base / 'state'
        self.assertEqual(self.run_cli(['start', '--root', str(self.root), '--state-dir', str(state),
                                      '--once', '--no-update']), 0)
        self.assertTrue((state / 'workflow.json').is_file())
        self.assertTrue((state / 'baseline.json').is_file())

    def test_sync_operational_failure_returns_nonzero(self):
        self.run_cli(['init', '--root', str(self.root), '--output', str(self.config)])
        with patch('robot_workflow.monitor.sync_repositories', return_value=[{'status':'error'}]):
            self.assertEqual(self.run_cli(['sync', '--root', str(self.root),
                                          '--config', str(self.config)]), 1)

    def test_start_rejects_state_inside_root_before_writing_configuration(self):
        state = self.root / 'monitor'
        self.assertEqual(self.run_cli(['start', '--root', str(self.root),
                                      '--state-dir', str(state), '--once', '--no-update']), 1)
        self.assertFalse(state.exists())
