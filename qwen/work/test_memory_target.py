import json
from pathlib import Path
import sys
import tempfile
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qwen_memory_guard import MemoryGuard

class FakeWindows:
    session = 1
    def __init__(self):
        self.k = self
        self.used = 70
        self.trimmed = []
    def snapshot(self):
        return {'used_percent': self.used, 'available_mib': 1000, 'total_mib': 32000}
    def foreground_name(self): return 'chatgpt.exe'
    def processes(self): return [1, 2, 3, 4]
    def session_id(self, pid): return 1
    def process_info(self, pid, handle=None):
        return {'pid': pid, 'name': 'discord.exe', 'path': 'discord.exe', 'working_set_mib': 64}
    def OpenProcess(self, access, inherit, pid): return pid
    def CloseHandle(self, handle): pass
    def K32EmptyWorkingSet(self, handle):
        self.trimmed.append(handle)
        self.used -= 10
        return True

with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
    guard = MemoryGuard(directory, {'memory_target_percent': 40, 'memory_cleanup_aggressive': True,
                                   'native_runner_enabled': True, 'native_sleep_idle_seconds': 30})
    guard.api = FakeWindows()
    guard.cleanup_pending = True
    result = guard.clean_once()
    assert guard.api.trimmed == [1, 2, 3], guard.api.trimmed
    assert result['target_reached'] and result['after']['used_percent'] == 40
    assert guard.clean_once() is None
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"is_sleeping":true}'
    original = urllib.request.urlopen
    urls = []
    def fake_open(url, timeout):
        urls.append(url)
        return Response()
    urllib.request.urlopen = fake_open
    try:
        guard.observe_sleep()
        guard.observe_sleep()
    finally:
        urllib.request.urlopen = original
    assert all(url.endswith('/props') for url in urls), urls
    events = [json.loads(line) for line in (Path(directory) / 'qwen-memory-cleanup.jsonl').read_text(encoding='utf-8').splitlines()]
    assert sum(event.get('event') == 'model_idle_unloaded' for event in events) == 1
print('PASS: cleanup continues below trigger, stops at 40%, smaller background processes, non-waking sleep observation')

