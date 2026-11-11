"""Kiểm tra retry bằng HTTP giả; không gọi API hay chờ thời gian thật."""
import io
import unittest
from contextlib import nullcontext
from unittest.mock import patch
from urllib.error import HTTPError

import providers


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.enter = patch('providers._wait_request_slot').start()
        self.defer = patch('providers._defer_requests').start()
        patch.dict('os.environ', {'LAB_API_MIN_INTERVAL': '5',
                                 'LAB_API_MAX_RETRIES': '3'}).start()
        self.addCleanup(patch.stopall)

    def error(self, code, retry_after=None):
        return HTTPError('https://example.test', code, 'test',
                         {'Retry-After': retry_after} if retry_after else {}, None)

    def test_429_and_503_recover_without_changing_payload(self):
        success = nullcontext(io.StringIO('{"ok":true}'))
        with patch('providers.urllib.request.urlopen', side_effect=[
                self.error(429, '20'), self.error(503), success]) as request:
            self.assertEqual(providers.post_json('https://example.test', {}, {'model': 'test'}),
                             {'ok': True})
        self.assertEqual(request.call_count, 3)
        self.assertEqual([c.args[1] for c in self.defer.call_args_list], [20, 30])
        self.assertEqual(len({id(c.args[0]) for c in request.call_args_list}), 1)

    def test_persistent_429_is_bounded_and_keeps_http_cause(self):
        with patch('providers.urllib.request.urlopen', side_effect=self.error(429)) as request:
            with self.assertRaises(RuntimeError) as caught:
                providers.post_json('https://example.test', {}, {})
        self.assertEqual(request.call_count, 4)
        self.assertEqual(caught.exception.__cause__.code, 429)

    def test_402_is_not_retried(self):
        with patch('providers.urllib.request.urlopen', side_effect=self.error(402)) as request:
            with self.assertRaises(RuntimeError):
                providers.post_json('https://example.test', {}, {})
        self.assertEqual(request.call_count, 1)
        self.defer.assert_not_called()

    def test_long_retry_after_stops_instead_of_retrying_early(self):
        with patch('providers.urllib.request.urlopen', side_effect=self.error(429, '3600')) as request:
            with self.assertRaises(RuntimeError):
                providers.post_json('https://example.test', {}, {})
        self.assertEqual(request.call_count, 1)
        self.defer.assert_not_called()


class PacingTests(unittest.TestCase):
    def test_calls_share_spacing_and_retry_cooldown(self):
        now = [100.0]
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            now[0] += seconds

        with patch.dict(providers._next_request_at, {}, clear=True), \
                patch('providers.time.monotonic', side_effect=lambda: now[0]), \
                patch('providers.time.sleep', side_effect=sleep):
            providers._wait_request_slot('same-provider', 5)
            providers._wait_request_slot('same-provider', 5)
            providers._defer_requests('same-provider', 30)
            providers._wait_request_slot('same-provider', 5)
        self.assertEqual(waits, [5, 30])
