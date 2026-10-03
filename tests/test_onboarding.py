import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from robot_workflow.cli import main
from robot_workflow.onboarding import latest_report


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'repos'
        self.repo = self.root / 'model'
        self.repo.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        (self.repo / 'model.json').write_text('{"joint_order": ["a"]}')
        self.state = self.base / 'state'

    def run_cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(list(args))

    def test_setup_generates_report_without_git_updates_or_source_edits(self):
        original = (self.repo / 'model.json').read_bytes()
        with patch('robot_workflow.monitor.sync_repositories', side_effect=AssertionError('Unexpected sync')):
            result = self.run_cli('setup', '--root', str(self.root), '--state-dir', str(self.state),
                                  '--owner', 'model-team', '--yes', '--no-open')
        self.assertEqual(result, 0)
        config = json.loads((self.state / 'workflow.json').read_text())
        self.assertEqual(config['nodes'][0]['owner'], 'model-team')
        self.assertTrue(latest_report(self.state).is_file())
        self.assertEqual((self.repo / 'model.json').read_bytes(), original)
        saved = (self.state / 'workflow.json').read_bytes()
        self.assertEqual(self.run_cli('setup', '--root', str(self.root), '--state-dir', str(self.state),
                                     '--owner', 'replacement', '--yes', '--no-open'), 0)
        self.assertEqual((self.state / 'workflow.json').read_bytes(), saved)

    def test_rejects_state_under_sources_before_writing(self):
        self.assertEqual(self.run_cli('setup', '--root', str(self.root), '--state-dir', str(self.root / 'state'),
                                     '--yes', '--no-open'), 1)
        self.assertFalse((self.root / 'state').exists())

    def test_interactive_owner_without_json_editing(self):
        with patch('builtins.input', side_effect=['Team workflow', 'controls']):
            self.assertEqual(self.run_cli('setup', '--root', str(self.root), '--state-dir', str(self.state), '--no-open'), 0)
        config = json.loads((self.state / 'workflow.json').read_text())
        self.assertEqual(config['project'], 'Team workflow')
        self.assertEqual(config['nodes'][0]['owner'], 'controls')

    def test_open_reports_missing_state_and_browser_fallback(self):
        self.assertEqual(self.run_cli('open', '--state-dir', str(self.state)), 1)
        self.run_cli('setup', '--root', str(self.root), '--state-dir', str(self.state), '--yes', '--no-open')
        with patch('robot_workflow.onboarding.webbrowser.open', return_value=False) as browser:
            self.assertEqual(self.run_cli('open', '--state-dir', str(self.state)), 0)
            self.assertTrue(browser.call_args.args[0].startswith('file:'))

    def test_setup_rejects_reused_state_for_another_root(self):
        self.run_cli('setup', '--root', str(self.root), '--state-dir', str(self.state), '--yes', '--no-open')
        other = self.base / 'other'
        other.mkdir()
        original = (self.state / 'workflow.json').read_bytes()
        self.assertEqual(self.run_cli('setup', '--root', str(other), '--state-dir', str(self.state), '--yes', '--no-open'), 1)
        self.assertEqual((self.state / 'workflow.json').read_bytes(), original)

    def test_setup_never_delivers_configured_webhooks(self):
        self.run_cli('setup', '--root', str(self.root), '--state-dir', str(self.state), '--yes', '--no-open')
        config_path = self.state / 'workflow.json'
        config = json.loads(config_path.read_text())
        config['notifications'] = {'webhook_env': 'TEST_WEBHOOK'}
        config_path.write_text(json.dumps(config))
        # First setup on saved configuration must not deliver even if an endpoint exists.
        (self.state / 'baseline.json').unlink()
        (self.repo / 'model.json').write_text('invalid JSON')
        with patch('robot_workflow.monitor._deliver', side_effect=AssertionError('Unexpected delivery')):
            self.assertEqual(self.run_cli('setup', '--root', str(self.root), '--state-dir', str(self.state),
                                         '--yes', '--no-open'), 2)
        queue = json.loads((self.state / 'notification-queue.json').read_text())
        self.assertTrue(queue)

    def test_confirmed_edges_keep_evidence_without_repeat_review_warning(self):
        from robot_workflow.discovery import discover
        config = discover(self.root)
        config['nodes'].append({**config['nodes'][0], 'id': 'consumer'})
        config['edges'] = [{'from': 'model', 'to': 'consumer', 'watch': ['*'], 'emits': ['*'],
                            'reason': 'References model (README.md:1)', 'basis': 'inferred: path reference'}]
        with patch('robot_workflow.onboarding.discover', return_value=config), \
             patch('builtins.input', side_effect=['Team', 'owner', 'owner', 'k']):
            self.assertEqual(self.run_cli('setup', '--root', str(self.root), '--state-dir', str(self.state), '--no-open'), 0)
        saved = json.loads((self.state / 'workflow.json').read_text())
        self.assertTrue(saved['edges'][0]['basis'].startswith('user-reviewed: accepted'))
        self.assertIn('inferred: path reference', saved['edges'][0]['basis'])
