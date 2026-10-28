import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch,MagicMock
from screening.providers import request_json
from screening.usage import price,tracked_worker


class UsageTests(unittest.TestCase):
    def test_counts_reported_usage_and_time_without_saving_prompts_or_keys(self):
        response={'id':'message-test','model':'claude-sonnet-5-5','usage':{
            'input_tokens':3000000,'output_tokens':100000,
            'server_tool_use':{'web_search_requests':130,'web_fetch_requests':122}}}
        stream=MagicMock();stream.__enter__.return_value.read.return_value=json.dumps(response).encode()
        with tempfile.TemporaryDirectory() as folder,patch('urllib.request.urlopen',return_value=stream):
            worker=tracked_worker(folder,'test-record',3,'pipeline',lambda:request_json(
                'https://api.anthropic.com/v1/messages',headers={'x-api-key':'SECRET'},
                body={'model':'claude-sonnet-5-5','messages':[{'content':'PRIVATE PROMPT'}]}))
            worker()
            files=list(Path(folder).glob('.usage/test-record/*.json'));self.assertEqual(len(files),1)
            raw=files[0].read_text();r=json.loads(raw)
            self.assertEqual(r['known_cost_usd'],8.3)
            self.assertTrue(r['cost_complete']);self.assertEqual(r['status'],'finished')
            self.assertGreaterEqual(r['elapsed_seconds'],0)
            self.assertIn('finished_at',r)
            self.assertNotIn('SECRET',raw);self.assertNotIn('PRIVATE PROMPT',raw)

    def test_cache_rates_and_unknown_models(self):
        u={'input_tokens':1000,'output_tokens':200,'cache_creation_input_tokens':150,
           'cache_creation':{'ephemeral_5m_input_tokens':100,'ephemeral_1h_input_tokens':50},
           'cache_read_input_tokens':500,'server_tool_use':{'web_search_requests':3}}
        self.assertAlmostEqual(price('claude-sonnet-5-5',u)['total_usd'],.0345)
        self.assertIsNone(price('claude-sonnet-5-6',u))

    def test_failed_calls_are_not_falsely_reported_as_zero_cost(self):
        with tempfile.TemporaryDirectory() as folder,patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('url',400,'bad',{},None)):
            def work():
                with self.assertRaises(ValueError):request_json('https://api.anthropic.com/v1/messages',body={'model':'claude-sonnet-5-5'})
            tracked_worker(folder,'test-record',1,'pipeline',work)()
            r=json.loads(next(Path(folder).glob('.usage/test-record/*.json')).read_text())
            self.assertFalse(r['cost_complete']);self.assertEqual(r['calls'][0]['error'],'HTTP 400')


if __name__=='__main__':unittest.main()
