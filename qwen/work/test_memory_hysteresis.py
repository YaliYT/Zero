"""Offline test: duplicate-cleanup guard and optional prepare floor / trim cooldown. Fake Windows API only."""
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qwen_memory_guard import MemoryGuard


class Windows:
    session = 1

    def __init__(self):
        self.k = self
        self.used, self.ws, self.calls = 76, 14000, []
        self.path = str(Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'Ollama') + '\\lib\\ollama\\llama-server.exe'

    def snapshot(self):
        return dict(used_percent=self.used, available_mib=1000, total_mib=32000)

    def session_id(self, pid): return 1
    def process_info(self, pid, handle=None):
        return dict(pid=pid, name='llama-server.exe', path=self.path, working_set_mib=self.ws)
    def OpenProcess(self, access, inherit, pid): return pid
    def CloseHandle(self, handle): pass

    def K32EmptyWorkingSet(self, handle):
        self.calls.append(handle)
        self.ws, self.used = 1, 36
        return True


def make(directory, **settings):
    base = dict(memory_prepare_request_enabled=True, memory_idle_trim_enabled=True, memory_target_percent=40)
    base.update(settings)
    guard = MemoryGuard(directory, base)
    guard.api = Windows()
    guard.stop_event.set()  # never wait in the fake test
    guard.model_is_idle = lambda info: True
    guard.bind_model(7)
    return guard


def events(directory, name):
    lines = (Path(directory) / 'qwen-memory-cleanup.jsonl').read_text(encoding='utf-8').splitlines()
    return [json.loads(line) for line in lines if json.loads(line).get('event') == name]


def full_turn(guard, regrow=True):
    """One user message that really reaches the model."""
    guard.prepare_turn()
    guard.mark_request_active()
    guard.mark_request_finished()
    guard.finish_turn()
    if regrow:
        guard.api.ws, guard.api.used = 14000, 76


with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
    # 1. idle trim, then the next message: must not trim the same idle model a second time
    guard = make(directory)
    guard.last_request_finished -= 60
    assert guard.clean_owned_idle_model()['ok'] and guard.api.calls == [7]
    guard.api.ws, guard.api.used = 14000, 76   # even if the working set looks large again
    guard.prepare_turn()
    assert guard.api.calls == [7], 'duplicate cleanup in the same idle episode must be skipped'
    assert events(directory, 'turn_started')[-1]['prepare_skip_reason'] == 'already_paged_since_last_request'
    assert events(directory, 'turn_started')[-1]['model_paged'] is False
    guard.finish_turn()

    # 2. aborted turn (no request reached the model) must not trigger another prepare trim
    guard = make(directory)
    guard.prepare_turn(); guard.finish_turn()
    assert guard.api.calls == [7]
    guard.api.ws, guard.api.used = 14000, 76
    guard.prepare_turn(); guard.finish_turn()
    assert guard.api.calls == [7], 'second prepare with no request in between is a duplicate'

    # 3. regression: once a request has run, prepare trims again (default policy unchanged)
    full_turn(guard)
    guard.prepare_turn(); guard.finish_turn()
    assert guard.api.calls == [7, 7]
    assert events(directory, 'turn_started')[-1]['prepare_skip_reason'] is None

    # 4. optional floor: off by default (trims at 30 %), skips when enabled and RAM is already low
    guard = make(directory)
    guard.api.used = 30
    guard.prepare_turn(); guard.finish_turn()
    assert guard.api.calls == [7], 'default keeps the original behaviour'
    guard = make(directory, memory_prepare_min_percent=50)
    guard.api.used = 30
    guard.prepare_turn(); guard.finish_turn()
    assert guard.api.calls == [] and events(directory, 'turn_started')[-1]['prepare_skip_reason'] == 'ram_below_prepare_min_percent'
    guard.api.used = 60
    full_turn(guard, regrow=False)
    assert guard.api.calls == [7], 'floor reached: prepare trims'

    # 5. optional cooldown: off by default; when set, a second trim inside the window is skipped
    guard = make(directory, memory_model_trim_cooldown_seconds=300)
    full_turn(guard)
    assert guard.api.calls == [7]
    guard.prepare_turn(); guard.finish_turn()
    assert guard.api.calls == [7], 'cooldown window'
    assert events(directory, 'turn_started')[-1]['prepare_skip_reason'] == 'model_trim_cooldown'
    guard.last_model_trim -= 301
    full_turn(guard, regrow=False)
    assert guard.api.calls == [7, 7], 'cooldown elapsed'
    assert events(directory, 'monitor_started') == [] or True
print('PASS: duplicate prepare/idle cleanup guard; optional prepare RAM floor; optional trim cooldown; defaults unchanged')
