import sys
import os
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qwen_memory_guard import BACKGROUND_APPS, foreground_family, MemoryGuard

assert not BACKGROUND_APPS.intersection({"llama-server.exe", "ollama.exe", "python.exe", "chatgpt.exe", "codex.exe", "msmpeng.exe", "explorer.exe"})
assert "steamwebhelper.exe" in foreground_family("steam.exe")
assert "whatsapp.root.exe" in foreground_family("whatsapp.exe")

class FakeWindows:
    session = 1
    k = None
    def __init__(self):
        self.k = self
        self.trimmed = []
        self.foreground = "firefox.exe"
    def snapshot(self):
        return {"used_percent": 85, "available_mib": 4500, "total_mib": 32000}
    def foreground_name(self):
        return self.foreground
    def processes(self):
        return [1, 2, 3, 4]
    def session_id(self, pid):
        return 2 if pid == 4 else 1
    def process_info(self, pid, handle=None):
        name = {1: "llama-server.exe", 2: "firefox.exe", 3: "discord.exe", 4: "discord.exe"}[pid]
        return {"pid": pid, "name": name, "path": name, "working_set_mib": 1500}
    def OpenProcess(self, access, inherit, pid):
        return pid
    def CloseHandle(self, handle):
        pass
    def K32EmptyWorkingSet(self, handle):
        self.trimmed.append(handle)
        return True

root = Path(__file__).resolve().parent
guard = MemoryGuard(root, {})
guard.api = FakeWindows()
guard.clean_once()
assert guard.api.trimmed == [3], guard.api.trimmed
guard.clean_once()
assert guard.api.trimmed == [3], "global cooldown failed"
guard.last_cleanup = float("-inf")
guard.clean_once()
assert guard.api.trimmed == [3], "per-process cooldown failed"
guard.last_cleanup = float("-inf")
guard.api.foreground = None
assert guard.clean_once() is None, "unknown foreground must skip cleanup"
restored = MemoryGuard(root, {})
restored._restore_cooldowns()
restored.api = FakeWindows()
assert restored.clean_once() is None, "restart cooldown failed"
print("PASS: model/system/foreground/session exclusions; global and per-process cooldowns")

model_guard = MemoryGuard(root, {"memory_cleanup_llama": True})
model_guard.api = FakeWindows()
original_info = model_guard.api.process_info
def model_info(pid, handle=None):
    item = original_info(pid, handle)
    if pid == 1:
        item['path'] = str(Path(os.environ['LOCALAPPDATA']) / 'Programs/Ollama/lib/ollama/llama-server.exe')
        item['working_set_mib'] = 17000
    return item
model_guard.api.process_info = model_info
busy = True
def model_idle(info):
    if busy:
        model_guard.model_idle_since.pop(info['pid'], None)
        return False
    model_guard.model_idle_since.setdefault(info['pid'], time.monotonic())
    return True
model_guard.model_is_idle = model_idle
assert model_guard.clean_models(force=True) is None
assert not model_guard.api.trimmed, 'must never trim a busy model'
busy = False
assert model_guard.clean_models() is None, 'idle grace period failed'
model_guard.model_idle_since[1] = time.monotonic() - 50
assert model_guard.clean_models() is not None
assert model_guard.api.trimmed == [1], 'must trim only Ollama llama-server'
assert model_guard.clean_models(force=True) is None, 'model cooldown failed'
model_guard.mark_request_active()
assert not model_guard.model_idle_since
assert model_guard.clean_models(force=True) is None
model_guard.mark_request_finished()
assert not model_guard.request_active.is_set()
print('PASS: llama idle grace, busy exclusion, cooldown and request activity reset')

