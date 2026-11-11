"""Tests offline cho retry tool, context và pagination; không dùng API key."""
import json
import unittest
from unittest.mock import patch

from agent import run_agent
from bonus.tools import BonusTools
from bonus.test_agent import ScriptedProvider, call, final


class RuntimeGuardsTests(unittest.TestCase):
    def test_persistent_rate_limit_stops_after_three_executions(self):
        tools = BonusTools(scenario='rate_limit_always')
        provider = ScriptedProvider([
            call(str(i), 'get_vercel_status', {}) for i in range(4)
        ] + [final('Chưa thể xác minh Vercel vì API giới hạn yêu cầu.')])
        result = run_agent('Kiểm tra Vercel', provider, tools, max_steps=6)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(tools.calls[('get_vercel_status', 'vercel')], 3)
        rejected = [e for e in result['trace'] if e['event'] == 'tool_rejected']
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]['result']['error'], 'RETRY_BUDGET_EXHAUSTED')
        third = json.loads(provider.histories[3][-1]['content'])
        self.assertFalse(third['retriable'])

    def test_long_retry_after_is_not_ignored(self):
        tools = BonusTools()
        limited = {'ok': False, 'error': 'RATE_LIMITED', 'retry_after': '3600',
                   'http_status': 429, 'retriable': True}
        provider = ScriptedProvider([call('a', 'get_vercel_status', {}),
                                     call('b', 'get_vercel_status', {}), final('Thiếu dữ liệu.')])
        with patch.object(tools, 'execute', return_value=limited) as execute, \
                patch('agent.time.sleep') as sleep:
            result = run_agent('Kiểm tra', provider, tools)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(execute.call_count, 1)
        sleep.assert_not_called()

    def test_context_omits_labelled_noise_but_trace_preserves_it(self):
        tools = BonusTools(scenario='noisy')
        provider = ScriptedProvider([call('a', 'get_vercel_status', {}), final()])
        result = run_agent('Kiểm tra Vercel', provider, tools)
        observation = json.loads(provider.histories[1][-1]['content'])
        self.assertNotIn('distractors', observation)
        self.assertEqual(observation['omitted_distractors'], 160)
        self.assertIn('incidents', observation)
        self.assertEqual(len(result['trace'][1]['result']['distractors']), 160)

    def test_pagination_cursor_and_updates_return_to_model(self):
        tools = BonusTools()
        args = {'provider': 'vercel', 'incident_id': 'sps6n39gm4sg', 'offset': 0, 'limit': 3}
        first = tools.execute('get_incident_details', args)
        self.assertIsNotNone(first['next_offset'])
        second_args = {**args, 'offset': first['next_offset']}
        provider = ScriptedProvider([call('a', 'get_incident_details', args),
                                     call('b', 'get_incident_details', second_args),
                                     final('Theo snapshot: ' + first['url'])])
        result = run_agent('Đọc timeline', provider, tools)
        self.assertEqual(result['status'], 'completed')
        page1 = json.loads(provider.histories[1][-1]['content'])
        page2 = json.loads(provider.histories[2][-1]['content'])
        self.assertEqual(page1['next_offset'], page2['offset'])
        self.assertTrue(any('GitHub' in u['body'] for u in page2['updates']))
        self.assertEqual(provider.histories[2][-1]['tool_call_id'], 'b')

    def test_each_incident_provider_needs_a_source(self):
        tools = BonusTools()
        npm = {'provider': 'npm', 'incident_id': 'cc0t2r4403sy'}
        vercel = {'provider': 'vercel', 'incident_id': 'w661l7k3kf4p'}
        url1 = tools.execute('get_incident_details', npm)['url']
        url2 = tools.execute('get_incident_details', vercel)['url']
        provider = ScriptedProvider([call('a', 'get_incident_details', npm),
                                     call('b', 'get_incident_details', vercel),
                                     final(url1), final(url1 + ' ' + url2)])
        result = run_agent('Đối chiếu', provider, tools)
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(any(e['event'] == 'validation_missing_source' for e in result['trace']))
        self.assertIn(url2, result['answer'])
