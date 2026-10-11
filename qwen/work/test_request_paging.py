import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from qwen_memory_guard import MemoryGuard

class Windows:
    session = 1
    def __init__(self):
        self.k = self
        self.used = 76
        self.calls = []
        self.ws = 14000
        self.path = str(Path(os.environ['LOCALAPPDATA'])/'Programs/Ollama/lib/ollama/llama-server.exe')
    def snapshot(self):
        return dict(used_percent=self.used, available_mib=32000*(1-self.used/100), total_mib=32000,
                    pagefile_used_mib=2048, pagefile_total_mib=16384)
    def session_id(self, pid): return 1
    def process_info(self, pid, handle=None):
        return dict(pid=pid, name='llama-server.exe', path=self.path, working_set_mib=self.ws)
    def OpenProcess(self, access, inherit, pid): return pid
    def CloseHandle(self, handle): pass
    def K32EmptyWorkingSet(self, handle):
        self.calls.append(handle)
        self.ws, self.used = 1, 36
        return True

with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
    guard = MemoryGuard(directory, dict(memory_prepare_request_enabled=True, memory_idle_trim_enabled=True,
                                        memory_cleanup_active=True, memory_active_threshold_percent=80,
                                        memory_target_percent=40))
    guard.api = Windows()
    guard.stop_event.set()  # Do not wait in the fake test.
    idle = [True]
    guard.model_is_idle = lambda info: idle[0]
    guard.prepare_turn()
    assert guard.api.calls == [], 'unowned model excluded'
    guard.finish_turn()
    guard.bind_model(7)
    idle[0] = False
    guard.prepare_turn()
    assert guard.api.calls == [], 'busy server excluded'
    guard.finish_turn()
    idle[0] = True
    guard.prepare_turn()
    assert guard.api.calls == [7], 'prepare must work below the 80 percent pressure threshold'
    assert guard.turn_active
    guard.mark_request_active()
    guard.api.used, guard.api.ws = 82, 14000
    assert guard.clean_active_model() is None, 'avoid a second immediate trim during inference'
    guard.mark_request_finished()
    guard.last_request_finished -= 60
    assert guard.clean_owned_idle_model() is None, 'do not trim between tool calls of one turn'
    guard.finish_turn()
    assert guard.clean_owned_idle_model() is None, 'idle grace starts at end of entire turn'
    guard.last_request_finished -= 60
    assert guard.clean_owned_idle_model()['ok']
    assert guard.api.calls == [7, 7]
    assert guard.clean_owned_idle_model() is None, 'one trim per idle episode'
    guard.prepare_turn()
    assert guard.api.calls == [7, 7], 'already paged tiny working set needs no repeated trim'
    guard.finish_turn()
    assert '2.00/16.00 GB' in guard.memory_text(guard.api.snapshot())

    spec = importlib.util.spec_from_file_location('test_agent', root/'Qwen-Agent.py')
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    class TurnGuard:
        def __init__(self): self.starts = self.ends = 0
        def prepare_turn(self): self.starts += 1
        def finish_turn(self): self.ends += 1
    turn_guard = TurnGuard()
    agent.MEMORY_GUARD = turn_guard
    messages = iter([dict(content='', tool_calls=[dict(function=dict(name='read_file', arguments=dict(path='q')))]),
                     dict(content='391')])
    agent.chat_request = lambda messages_arg: next(messages)
    agent.execute_tool = lambda *args: dict(ok=True, content='391')
    assert agent.agent_turn('test', interactive=False)['answer'] == '391'
    assert (turn_guard.starts, turn_guard.ends) == (1, 1), 'tool loop uses a single prepare and finish'
    def fail(*args): raise RuntimeError('intentional failure')
    agent.chat_request = fail
    try: agent.agent_turn('test', interactive=False)
    except RuntimeError: pass
    assert (turn_guard.starts, turn_guard.ends) == (2, 2), 'finish must run on failure'
print('PASS: owned idle paging once per user turn; tool-loop protection; idle grace; paging telemetry; failure cleanup')

