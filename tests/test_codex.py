import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from screening.narrative import default_provider


SCHEMA = {'type': 'object', 'properties': {'answer': {'type': 'string'}},
          'required': ['answer'], 'additionalProperties': False}


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('screening.codex'), 'Codex app-server adapter is missing')
        self.codex = importlib.import_module('screening.codex')
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        executable = Path(self.folder.name) / 'codex'
        shutil.copyfile(Path(__file__).parent / 'fixtures/codex_app_server.py', executable)
        executable.chmod(0o755)
        env = patch.dict(os.environ, {'CODEX_BIN': str(executable), 'PROPERTY_TEST_CODEX_MODE': ''})
        env.start()
        self.addCleanup(env.stop)

    def test_old_provider_settings_cannot_switch_away_from_codex(self):
        for provider in ('anthropic', 'openai', 'gemini'):
            with self.subTest(provider=provider), patch.dict(os.environ, {
                    'AI_PROVIDER': provider, 'ANTHROPIC_API_KEY': 'legacy',
                    'OPENAI_API_KEY': 'legacy', 'GEMINI_API_KEY': 'legacy'}, clear=True):
                self.assertEqual(default_provider(), 'codex')

    def test_completed_turn_uses_final_message_and_isolated_runtime(self):
        result = self.codex.run('Return the answer.', {}, SCHEMA)
        self.assertEqual(result['output'], {'answer': 'ok'})
        self.assertEqual(result['model'], 'test-model')

    def test_model_entry_uses_subscription_adapter_without_a_key(self):
        from screening.narrative import call_model, choose_model
        result = call_model('codex', choose_model('codex'), 'Return the answer.', {}, SCHEMA)
        self.assertEqual(result, {'answer': 'ok'})

    def test_api_key_auth_cannot_silently_bill_api(self):
        with patch.dict(os.environ, {'PROPERTY_TEST_CODEX_MODE': 'api_key'}):
            with self.assertRaisesRegex(ValueError, 'ChatGPT'):
                self.codex.run('Return the answer.', {}, SCHEMA)

    def test_failed_turn_rejects_even_a_valid_final_message(self):
        with patch.dict(os.environ, {'PROPERTY_TEST_CODEX_MODE': 'failed'}):
            with self.assertRaisesRegex(ValueError, 'Usage limit'):
                self.codex.run('Return the answer.', {}, SCHEMA)

    def test_timeout_stops_process_without_waiting_for_provider(self):
        started = time.monotonic()
        with patch.dict(os.environ, {'PROPERTY_TEST_CODEX_MODE': 'timeout'}):
            with self.assertRaises(TimeoutError):
                self.codex.run('Return the answer.', {}, SCHEMA, timeout=0.3)
        self.assertLess(time.monotonic() - started, 3)

    def test_exited_server_fails_promptly(self):
        with patch.dict(os.environ, {'PROPERTY_TEST_CODEX_MODE': 'eof'}):
            with self.assertRaisesRegex(ValueError, 'closed|exited'):
                self.codex.run('Return the answer.', {}, SCHEMA, timeout=3)

    def test_research_retains_actual_firecrawl_results(self):
        with patch.dict(os.environ, {'PROPERTY_TEST_CODEX_MODE': 'research'}):
            result = self.codex.run('Research.', {}, SCHEMA, research=True)
        self.assertEqual(result['tool_calls'][0]['arguments']['url'], 'https://agent.example/house')
        payload = json.loads(result['tool_calls'][0]['result']['content'][0]['text'])
        self.assertIn('£1,400', payload['markdown'])


class CodexOnlyAppTests(unittest.TestCase):
    def test_config_advertises_only_codex_and_propertydata(self):
        from app import create_app
        with tempfile.TemporaryDirectory() as folder:
            config = create_app(folder).test_client().get('/api/config').get_json()
        self.assertEqual(config['default_provider'], 'codex')
        self.assertEqual(set(config['providers']), {'codex', 'propertydata'})

    def test_removed_providers_cannot_start_generation_or_edits(self):
        from app import create_app
        from screening.schema import validate_submission
        from test_intake import brief
        with tempfile.TemporaryDirectory() as folder, patch('threading.Thread.start') as start:
            app = create_app(folder); client = app.test_client()
            headers = {'X-Local-Token': app.csrf_token}
            for provider in ('anthropic', 'openai', 'gemini'):
                for endpoint in ('analyse', 'pipeline', 'revise'):
                    record = app.store.create(validate_submission(brief()), 'demo')
                    with self.subTest(provider=provider, endpoint=endpoint):
                        response = client.post('/api/records/' + record['id'] + '/' + endpoint,
                            json={'revision': record['revision'], 'provider': provider, 'instruction': 'Change the title'},
                            headers=headers)
                        self.assertEqual(response.status_code, 400)
                        self.assertEqual(app.store.load(record['id']), record)
            start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
