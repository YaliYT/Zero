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
        self.used = 92
        self.calls = []
        self.name = 'llama-server.exe'
        self.path = str(Path(os.environ['LOCALAPPDATA'])/'Programs/Ollama/lib/ollama/llama-server.exe')
    def snapshot(self): return {'used_percent':self.used,'available_mib':2000,'total_mib':32000}
    def session_id(self,pid): return 1
    def process_info(self,pid,handle=None): return {'pid':pid,'name':self.name,'path':self.path,'working_set_mib':14000}
    def OpenProcess(self,access,inherit,pid): return pid
    def CloseHandle(self,handle): pass
    def K32EmptyWorkingSet(self,handle): self.calls.append(handle); return True

with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
    guard = MemoryGuard(directory, {'memory_cleanup_active':True,'memory_active_threshold_percent':90})
    guard.api = Windows()
    guard.mark_request_active()
    assert guard.clean_active_model() is None, 'unowned server must be excluded'
    guard.bind_model(7)
    guard.api.name = 'chatgpt.exe'
    assert guard.clean_active_model() is None, 'other apps must be excluded'
    guard.api.name = 'llama-server.exe'
    guard.api.used = 89
    assert guard.clean_active_model() is None, 'avoid unnecessary active paging'
    guard.api.used = 92
    assert guard.clean_active_model()['ok']
    assert guard.api.calls == [7]
    assert guard.clean_active_model() is None, 'active cooldown must apply'
    guard.mark_request_finished()
    guard.last_active_cleanup = float('-inf')
    assert guard.clean_active_model() is None, 'idle path is managed separately'
print('PASS: owned process only, RAM pressure threshold, cleanup while request active, bounded frequency')

