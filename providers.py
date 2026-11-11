"""Bốn provider cùng một interface. Không chứa agent loop."""
import json
import os
import math
import sys
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import urllib.error
import urllib.request

CONFIG = {
    'openai': ('OPENAI_API_KEY', 'https://api.openai.com/v1/chat/completions'),
    'gemini': ('GEMINI_API_KEY', 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'),
    'openrouter': ('OPENROUTER_API_KEY', 'https://openrouter.ai/api/v1/chat/completions'),
    'anthropic': ('ANTHROPIC_API_KEY', 'https://api.anthropic.com/v1/messages'),
}

_request_lock = threading.Lock()
_next_request_at = {}


def _wait_request_slot(url, interval):
    # Chung cho agent và judge, kể cả khi eval dùng nhiều workers.
    with _request_lock:
        remaining = _next_request_at.get(url, 0) - time.monotonic()
        while remaining > 0:
            time.sleep(min(remaining, 60))
            remaining = _next_request_at.get(url, 0) - time.monotonic()
        _next_request_at[url] = time.monotonic() + interval


def _defer_requests(url, delay):
    with _request_lock:
        _next_request_at[url] = max(_next_request_at.get(url, 0),
                                    time.monotonic() + delay)


def _retry_delay(headers, fallback):
    value = headers.get('Retry-After') if headers else None
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return fallback
    return max(fallback, seconds) if math.isfinite(seconds) else fallback


def post_json(url, headers, payload):
    interval = float(os.getenv('LAB_API_MIN_INTERVAL', '5'))
    retries = int(os.getenv('LAB_API_MAX_RETRIES', '3'))
    if not math.isfinite(interval) or not 0 <= interval <= 60 or not 0 <= retries <= 5:
        raise ValueError('LAB_API_MIN_INTERVAL phải từ 0–60; LAB_API_MAX_RETRIES từ 0–5.')
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', **headers})
    for attempt in range(retries + 1):
        _wait_request_slot(url, interval)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # Không in response body, headers, request hoặc API key.
            delay = _retry_delay(exc.headers, min(15 * 2 ** attempt, 60))
            can_retry = exc.code in (429, 500, 502, 503, 504) and attempt < retries
            if can_retry and delay <= 60:
                _defer_requests(url, delay)
                print(f'HTTP {exc.code}: chờ {delay:.0f}s, thử lại '
                      f'{attempt + 1}/{retries}.', file=sys.stderr, flush=True)
                exc.close()
                continue
            exc.close()
            raise RuntimeError(f'Provider trả HTTP {exc.code}; đã dừng sau '
                               f'{attempt + 1} lần gọi. Kiểm tra quota/credit hoặc thử sau.') from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f'Không kết nối được provider: {exc.reason}') from exc


class Provider:
    """complete(messages, schemas) -> {message, calls, finish, usage}.

    messages: system/user/assistant/tool theo format Chat Completions. message trả về
    cần được append nguyên vẹn; tool result có role, tool_call_id, content (JSON string).
    """
    def __init__(self, name, model):
        if name not in CONFIG:
            raise ValueError(f'Provider không hợp lệ: {name}')
        if not model:
            raise ValueError('Cần đặt MODEL là model có hỗ trợ tool calling.')
        self.name, self.model = name, model
        key_name, self.url = CONFIG[name]
        self.key = os.getenv(key_name)
        if not self.key:
            raise ValueError(f'Thiếu {key_name}; xem README.md.')

    def complete(self, messages, schemas):
        if self.name == 'anthropic':
            return self._anthropic(messages, schemas)
        payload = {'model': self.model, 'messages': messages}
        if schemas:
            payload['tools'] = schemas
        data = post_json(self.url, {'Authorization': f'Bearer {self.key}'}, payload)
        choice = data['choices'][0]
        message = choice['message']
        calls = [{'id': c['id'], 'name': c['function']['name'], 'arguments': c['function']['arguments']} for c in message.get('tool_calls', [])]
        return {'message': message, 'calls': calls, 'finish': choice.get('finish_reason'), 'usage': data.get('usage', {})}

    def _anthropic(self, messages, schemas):
        system = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
        native = []
        for m in messages:
            if m['role'] == 'system':
                continue
            if m['role'] == 'assistant':
                blocks = []
                if m.get('content'):
                    blocks.append({'type': 'text', 'text': m['content']})
                for call in m.get('tool_calls', []):
                    blocks.append({'type': 'tool_use', 'id': call['id'], 'name': call['function']['name'], 'input': json.loads(call['function']['arguments'])})
                native.append({'role': 'assistant', 'content': blocks})
            elif m['role'] == 'tool':
                block = {'type': 'tool_result', 'tool_use_id': m['tool_call_id'], 'content': m['content']}
                if native and native[-1]['role'] == 'user' and isinstance(native[-1]['content'], list):
                    native[-1]['content'].append(block)
                else:
                    native.append({'role': 'user', 'content': [block]})
            else:
                native.append({'role': 'user', 'content': m['content']})
        tools = [{'name': x['function']['name'], 'description': x['function']['description'], 'input_schema': x['function']['parameters']} for x in schemas]
        payload = {'model': self.model, 'max_tokens': 1024, 'system': system, 'messages': native}
        if tools:
            payload['tools'] = tools
        data = post_json(self.url, {'x-api-key': self.key, 'anthropic-version': '2023-06-01'}, payload)
        blocks = data['content']
        calls = [{'id': b['id'], 'name': b['name'], 'arguments': json.dumps(b['input'], ensure_ascii=False)} for b in blocks if b['type'] == 'tool_use']
        text = '\n'.join(b['text'] for b in blocks if b['type'] == 'text')
        message = {'role': 'assistant', 'content': text or None}
        if calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': c['arguments']}} for c in calls]
        reason = {'end_turn': 'stop', 'tool_use': 'tool_calls', 'max_tokens': 'length'}.get(data.get('stop_reason'), data.get('stop_reason'))
        return {'message': message, 'calls': calls, 'finish': reason, 'usage': data.get('usage', {})}
