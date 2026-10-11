import ctypes
import json
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qwen_cpu_runner import native_chat, ExtendedLimits

class Response:
    def __init__(self, lines):
        self.lines = lines
    def __enter__(self):
        return self.lines
    def __exit__(self, *args):
        pass

def line(delta, finish=None):
    return b'data: ' + json.dumps({'choices': [{'delta': delta, 'finish_reason': finish}]}).encode() + b'\n'

fragments = [line({'tool_calls': [{'index': 0, 'id': 'abc', 'function': {'name': 'read_file', 'arguments': '{"path":"qwen-'}}]}),
             line({'tool_calls': [{'index': 0, 'function': {'arguments': 'agent-test.txt"}'}}]}),
             line({}, 'tool_calls'), b'data: [DONE]\n']
with patch('urllib.request.urlopen', return_value=Response(fragments)):
    result = native_chat([{'role': 'user', 'content': 'Read the file'}], [], 57206)
    assert result['tool_calls'][0]['id'] == 'abc'
    assert json.loads(result['tool_calls'][0]['function']['arguments']) == {'path': 'qwen-agent-test.txt'}
with patch('urllib.request.urlopen', return_value=Response(fragments[:2])):
    try:
        native_chat([{'role': 'user', 'content': 'Read the file'}], [], 57206)
    except RuntimeError:
        pass
    else:
        raise AssertionError('Incomplete tool response must not be returned for execution')
assert ctypes.sizeof(ExtendedLimits) == 144
limited = [fragments[0], line({}, 'length'), b'data: [DONE]\n']
with patch('urllib.request.urlopen', return_value=Response(limited)):
    try:
        native_chat([{'role':'user','content':'Read the file'}], [], 57206, max_tokens=16)
    except RuntimeError as error:
        assert 'output limit' in str(error)
    else:
        raise AssertionError('A truncated tool call must not be returned for execution')
print('PASS: fragmented tool arguments; interrupted streams reject actions; Windows job layout')

