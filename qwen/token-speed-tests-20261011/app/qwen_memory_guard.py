"""Bounded RAM cleanup for background apps and this agent's owned Qwen process."""
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import urllib.request
from qwen_terminal import terminal_print as print

try:
    import psutil
except ImportError:
    psutil = None

MiB = 1024 * 1024
BACKGROUND_APPS = frozenset({
    "firefox.exe", "chrome.exe", "msedge.exe", "discord.exe",
    "steamwebhelper.exe", "epicgameslauncher.exe", "epicwebhelper.exe",
    "whatsapp.root.exe", "whatsapp.exe", "spotify.exe",
})
APP_FAMILIES = (
    frozenset({"steam.exe", "steamwebhelper.exe"}),
    frozenset({"epicgameslauncher.exe", "epicwebhelper.exe"}),
    frozenset({"whatsapp.exe", "whatsapp.root.exe"}),
)


def foreground_family(name):
    return next((group for group in APP_FAMILIES if name in group), frozenset({name}))


class MemoryStatus(ctypes.Structure):
    _fields_ = [("length", w.DWORD), ("load", w.DWORD)] + [
        (name, ctypes.c_ulonglong) for name in (
            "total", "available", "page_total", "page_available", "virtual_total",
            "virtual_available", "extended_available")]


class ProcessMemory(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("faults", w.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            "peak_ws", "ws", "peak_pool_paged", "pool_paged", "peak_pool_nonpaged",
            "pool_nonpaged", "page_usage", "peak_page_usage", "private_usage")]


class WindowsMemory:
    def __init__(self):
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        signatures = {
            "OpenProcess": (w.HANDLE, [w.DWORD, w.BOOL, w.DWORD]),
            "CloseHandle": (w.BOOL, [w.HANDLE]),
            "GlobalMemoryStatusEx": (w.BOOL, [ctypes.POINTER(MemoryStatus)]),
            "K32EnumProcesses": (w.BOOL, [ctypes.POINTER(w.DWORD), w.DWORD, ctypes.POINTER(w.DWORD)]),
            "QueryFullProcessImageNameW": (w.BOOL, [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]),
            "K32GetProcessMemoryInfo": (w.BOOL, [w.HANDLE, ctypes.POINTER(ProcessMemory), w.DWORD]),
            "K32EmptyWorkingSet": (w.BOOL, [w.HANDLE]),
            "ProcessIdToSessionId": (w.BOOL, [w.DWORD, ctypes.POINTER(w.DWORD)]),
            "CreateMutexW": (w.HANDLE, [ctypes.c_void_p, w.BOOL, w.LPCWSTR]),
        }
        for name, (result, args) in signatures.items():
            function = getattr(self.k, name)
            function.restype, function.argtypes = result, args
        self.u.GetForegroundWindow.restype = w.HWND
        self.u.GetForegroundWindow.argtypes = []
        self.u.GetWindowThreadProcessId.restype = w.DWORD
        self.u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        self.session = self.session_id(os.getpid())

    def snapshot(self):
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not self.k.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        result = {"used_percent": round(100 * (1 - status.available / status.total), 2),
                "available_mib": round(status.available / MiB, 2),
                "total_mib": round(status.total / MiB, 2)}
        if psutil is not None:
            try:
                paging = psutil.swap_memory()
                result.update(pagefile_used_mib=round(paging.used / MiB, 2),
                              pagefile_total_mib=round(paging.total / MiB, 2))
            except (OSError, RuntimeError):
                pass
        return result

    def session_id(self, pid):
        value = w.DWORD()
        return value.value if self.k.ProcessIdToSessionId(pid, ctypes.byref(value)) else None

    def process_info(self, pid, handle=None):
        owned = handle is None
        handle = handle or self.k.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            path, length = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
            memory = ProcessMemory()
            memory.cb = ctypes.sizeof(memory)
            if not self.k.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)):
                return None
            if not self.k.K32GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                return None
            return {"pid": pid, "name": Path(path.value).name.lower(), "path": path.value,
                    "working_set_mib": round(memory.ws / MiB, 2)}
        finally:
            if owned:
                self.k.CloseHandle(handle)

    def foreground_name(self):
        pid = w.DWORD()
        self.u.GetWindowThreadProcessId(self.u.GetForegroundWindow(), ctypes.byref(pid))
        # Unknown foreground: skip this pass rather than trim the app being used.
        info = self.process_info(pid.value)
        return info["name"] if info else None

    def processes(self):
        ids, size = (w.DWORD * 16384)(), w.DWORD()
        if not self.k.K32EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return ids[:size.value // ctypes.sizeof(w.DWORD)]


class MemoryGuard:
    def __init__(self, root, settings):
        self.root = Path(root)
        self.enabled = bool(settings.get("memory_cleanup_enabled", True))
        self.threshold = max(70, min(95, int(settings.get("memory_threshold_percent", 80))))
        self.target = max(20, min(self.threshold - 2, int(settings.get("memory_target_percent", self.threshold - 2))))
        self.aggressive = bool(settings.get("memory_cleanup_aggressive", False))
        self.cleanup_pending = False
        self.sleep_port = int(settings.get("native_runner_port", 57206)) if settings.get("native_runner_enabled") and int(settings.get("native_sleep_idle_seconds", -1)) >= 15 else None
        self.sleeping = False
        self.loaded_snapshot = None
        self.active_cleanup = bool(settings.get("memory_cleanup_active", False))
        self.active_threshold = max(80, min(97, int(settings.get("memory_active_threshold_percent", 90))))
        self.active_interval = max(60, int(settings.get("memory_active_interval_seconds", 120)))
        self.owned_model_pid = None
        self.last_active_cleanup = float("-inf")
        self.idle_trim_enabled = bool(settings.get("memory_idle_trim_enabled", False))
        self.idle_trim_seconds = max(15, int(settings.get("memory_idle_trim_seconds", 30)))
        self.last_request_finished = time.monotonic()
        self.idle_paged = False
        # Phase-1 scaffolding. Both knobs default to 0 = off, i.e. unchanged behaviour.
        self.prepare_min_percent = max(0, min(95, int(settings.get("memory_prepare_min_percent", 0))))
        self.model_trim_cooldown = max(0, int(settings.get("memory_model_trim_cooldown_seconds", 0)))
        self.last_model_trim = float("-inf")
        self.skip_reason = None
        self.prepare_request_enabled = bool(settings.get("memory_prepare_request_enabled", False))
        self.disk_backing = "mapped_model_and_windows_pagefile" if settings.get("model_load_mode", "mmap") == "mmap" else "windows_pagefile"
        self.turn_active = False
        self.clean_llama = bool(settings.get("memory_cleanup_llama", False))
        self.llama_idle_seconds = max(15, int(settings.get("memory_llama_idle_seconds", 45)))
        self.stop_event = threading.Event()
        self.thread = None
        self.mutex = None
        self.last_cleanup = float("-inf")
        self.process_cooldowns = {}
        self.model_idle_since = {}
        self.model_ports = {}
        self.request_active = threading.Event()
        self.request_lock = threading.RLock()
        self.last_result = None
        self.api = WindowsMemory()

    def start(self):
        if not self.enabled:
            return self
        ctypes.set_last_error(0)
        self.mutex = self.api.k.CreateMutexW(None, False, "Local\\QwenAgentMemoryGuard")
        error = ctypes.get_last_error()
        if not self.mutex:
            raise ctypes.WinError(error)
        if error == 183:  # Another agent window already owns the monitor.
            self.api.k.CloseHandle(self.mutex)
            self.mutex = None
            return self
        self._restore_cooldowns()
        self.last_request_finished = time.monotonic()
        self.record({"time": time.time(), "event": "monitor_started", "pid": os.getpid(),
                     "threshold_percent": self.threshold, "poll_seconds": 5,
                     "target_percent": self.target, "aggressive": self.aggressive,
                     "active_cleanup": self.active_cleanup, "active_threshold_percent": self.active_threshold,
                     "idle_trim_enabled": self.idle_trim_enabled, "idle_trim_seconds": self.idle_trim_seconds,
                     "prepare_request_enabled": self.prepare_request_enabled,
                     "pass_cooldown_seconds": 120, "process_cooldown_seconds": 600,
                     "llama_cleanup": self.clean_llama, "llama_idle_seconds": self.llama_idle_seconds,
                     "prepare_min_percent": self.prepare_min_percent,
                     "model_trim_cooldown_seconds": self.model_trim_cooldown})
        self.thread = threading.Thread(target=self._monitor, name="Qwen-MemoryGuard", daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)
        if self.mutex:
            self.record({"time": time.time(), "event": "monitor_stopped", "pid": os.getpid()})
            self.api.k.CloseHandle(self.mutex)
            self.mutex = None

    def _restore_cooldowns(self):
        log = self.root / "qwen-memory-cleanup.jsonl"
        if not log.exists():
            return
        wall, mono = time.time(), time.monotonic()
        try:
            with log.open("rb") as handle:
                handle.seek(max(0, log.stat().st_size - 65536))
                lines = handle.read().decode("utf-8", errors="replace").splitlines()
            for line in lines:
                try:
                    result = json.loads(line)
                    age = max(0, wall - float(result["time"]))
                    if "before" not in result or age >= 600:
                        continue
                    if result.get("event") != "llama_cleanup":
                        self.last_cleanup = max(self.last_cleanup, mono - age)
                    for item in result["trimmed"]:
                        self.process_cooldowns[(item["pid"], item["name"])] = mono - age
                except (ValueError, KeyError, TypeError):
                    continue
        except OSError:
            pass

    def _monitor(self):
        while not self.stop_event.is_set():
            try:
                self.clean_active_model()
                self.observe_sleep()
                self.clean_owned_idle_model()
                load = self.api.snapshot()["used_percent"]
                if load >= self.threshold:
                    self.cleanup_pending = True
                if load <= self.target:
                    self.cleanup_pending = False
                if self.cleanup_pending:
                    # /slots wakes a sleeping native model. Let its built-in idle unload manage it.
                    if self.clean_llama and not self.sleep_port and not self.idle_trim_enabled:
                        self.clean_models()
                    self.clean_once()
            except Exception as error:
                self.record({"time": time.time(), "error": str(error)})
            self.stop_event.wait(5)

    def bind_model(self, pid):
        # Only the NativeRunner owned by this agent can be trimmed while processing.
        self.owned_model_pid = int(pid)

    def clean_owned_idle_model(self, force=False):
        with self.request_lock:
            if not self.enabled or not self.owned_model_pid or self.sleeping or self.request_active.is_set():
                return None
            if not force and (not self.idle_trim_enabled or self.idle_paged or self.turn_active):
                return None
            if force and self.idle_paged:
                # Duplicate-cleanup guard: the model was already trimmed (idle or earlier prepare) and no
                # request has run since, so a second EmptyWorkingSet would only cost the settle wait.
                self.skip_reason = "already_paged_since_last_request"
                return None
            if not force and time.monotonic() - self.last_request_finished < self.idle_trim_seconds:
                return None
            before = self.api.snapshot()
            if not force and before["used_percent"] <= self.target:
                return None
            if self.model_trim_cooldown and time.monotonic() - self.last_model_trim < self.model_trim_cooldown:
                self.skip_reason = "model_trim_cooldown"
                return None
            if force and self.prepare_min_percent and before["used_percent"] < self.prepare_min_percent:
                self.skip_reason = "ram_below_prepare_min_percent"
                return None
            pid = self.owned_model_pid
            if self.api.session_id(pid) != self.api.session:
                return None
            info = self.api.process_info(pid)
            ollama_root = str(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Ollama").lower() + "\\"
            if not info or info["name"] != "llama-server.exe" or not info["path"].lower().startswith(ollama_root) or info["working_set_mib"] < 512:
                return None
            # Check once per idle episode, not every poll: /slots resets the native sleep timer.
            if not self.model_is_idle(info):
                return None
            handle = self.api.k.OpenProcess(0x1100, False, pid)
            if not handle:
                return None
            try:
                current = self.api.process_info(pid, handle)
                if not current or current["path"] != info["path"] or not self.model_is_idle(info):
                    return None
                ok = bool(self.api.k.K32EmptyWorkingSet(handle))
                self.idle_paged = ok
                if ok:
                    self.last_active_cleanup = time.monotonic()
                    self.last_model_trim = time.monotonic()
            finally:
                self.api.k.CloseHandle(handle)
            self.stop_event.wait(2)
            after = self.api.snapshot()
            result = {"time": time.time(), "event": "request_model_paged" if force else "idle_model_paged", "pid": pid, "ok": ok,
                      "before": before, "after": after, "target_percent": self.target,
                      "target_reached": after["used_percent"] <= self.target, "model_retained": True}
            self.record(result)
            if ok:
                label = "ניקוי לפני הודעה" if force else "ניקוי בהמתנה"
                print(f"\n[{label}] RAM: {before['used_percent']}% -> {after['used_percent']}%. המודל נשאר טעון.", flush=True)
            return result

    @staticmethod
    def memory_text(snapshot):
        text = f"RAM: {snapshot['used_percent']}%"
        if "pagefile_used_mib" in snapshot:
            text += f" | זיכרון וירטואלי בדיסק, כל המחשב: {snapshot['pagefile_used_mib']/1024:.2f}/{snapshot['pagefile_total_mib']/1024:.2f} GB"
        return text

    def prepare_turn(self):
        # Run once per user message, never between its tool calls.
        with self.request_lock:
            if not self.enabled:
                return
            try:
                self.skip_reason = None
                result = self.clean_owned_idle_model(force=True) if self.prepare_request_enabled else None
                snapshot = self.api.snapshot()
                self.record({"time": time.time(), "event": "turn_started", "snapshot": snapshot,
                             "model_paged": bool(result and result["ok"]), "prepare_skip_reason": self.skip_reason,
                             "disk_backing": self.disk_backing})
                print(f"[זיכרון בתחילת הודעה] {self.memory_text(snapshot)}", flush=True)
            except Exception as error:
                self.record({"time": time.time(), "event": "turn_memory_error", "error": str(error)})
            finally:
                self.turn_active = True

    def finish_turn(self):
        with self.request_lock:
            self.turn_active = False
            self.last_request_finished = time.monotonic()
            if not self.enabled:
                return
            try:
                snapshot = self.api.snapshot()
                self.record({"time": time.time(), "event": "turn_finished", "snapshot": snapshot})
                print(f"\n[זיכרון בסיום הודעה] {self.memory_text(snapshot)}", flush=True)
            except Exception as error:
                self.record({"time": time.time(), "event": "turn_memory_error", "error": str(error)})

    def clean_active_model(self):
        with self.request_lock:
            if not self.active_cleanup or not self.owned_model_pid or not self.request_active.is_set():
                return None
            now = time.monotonic()
            before = self.api.snapshot()
            if before["used_percent"] < self.active_threshold or now - self.last_active_cleanup < self.active_interval:
                return None
            pid = self.owned_model_pid
            if self.api.session_id(pid) != self.api.session:
                return None
            info = self.api.process_info(pid)
            ollama_root = str(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Ollama").lower() + "\\"
            if not info or info["name"] != "llama-server.exe" or not info["path"].lower().startswith(ollama_root) or info["working_set_mib"] < 2048:
                return None
            handle = self.api.k.OpenProcess(0x1100, False, pid)
            if not handle:
                return None
            try:
                current = self.api.process_info(pid, handle)
                if not current or current["path"] != info["path"]:
                    return None
                ok = bool(self.api.k.K32EmptyWorkingSet(handle))
                self.last_active_cleanup = now
                immediate = self.api.process_info(pid, handle)
            finally:
                self.api.k.CloseHandle(handle)
            # Keep inference running; Windows chooses which cached or disk-backed pages to reuse.
            self.stop_event.wait(1)
            after = self.api.snapshot()
            result = {"time": time.time(), "event": "active_model_cleanup", "pid": pid, "ok": ok,
                      "threshold_percent": self.active_threshold, "before": before, "after": after,
                      "working_set_before_mib": current["working_set_mib"],
                      "working_set_immediate_mib": immediate["working_set_mib"] if immediate else None,
                      "available_change_mib": round(after["available_mib"] - before["available_mib"], 2)}
            self.record(result)
            if ok:
                print(f"\n[ניקוי בזמן תשובה] RAM: {before['used_percent']}% -> {after['used_percent']}%. המודל ממשיך לעבוד.", flush=True)
            return result

    def observe_sleep(self):
        if not self.sleep_port:
            return
        with urllib.request.urlopen(f"http://127.0.0.1:{self.sleep_port}/props", timeout=2) as response:
            props = json.load(response)
        sleeping = props.get("is_sleeping")
        if type(sleeping) is not bool:
            return
        snapshot = self.api.snapshot()
        if not sleeping:
            self.loaded_snapshot = snapshot
        if sleeping and not self.sleeping:
            result = {"time": time.time(), "event": "model_idle_unloaded", "before": self.loaded_snapshot,
                      "after": snapshot, "target_percent": self.target,
                      "target_reached": snapshot["used_percent"] <= self.target}
            self.record(result)
            print(f"\n[ניקוי זיכרון] המודל נפרק בזמן המתנה. RAM: {snapshot['used_percent']}%; יעד: {self.target}%. ההודעה הבאה תטען אותו מחדש.", flush=True)
        self.sleeping = sleeping

    def record(self, result):
        self.last_result = result
        with (self.root / "qwen-memory-cleanup.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")

    def model_is_idle(self, info):
        pid = info["pid"]
        if pid not in self.model_ports:
            try:
                try:
                    import psutil
                    command = " ".join(psutil.Process(pid).cmdline())
                except ImportError:
                    command = subprocess.check_output(
                        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                         f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
                        encoding="utf-8", errors="replace", timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                port = re.search(r"--port\s+(\d+)", command)
                if not port:
                    return False
                self.model_ports[pid] = int(port.group(1))
            except Exception:
                return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.model_ports[pid]}/slots", timeout=2) as response:
                slots = json.load(response)
            # Unknown state is never considered idle.
            idle = isinstance(slots, list) and bool(slots) and all(
                isinstance(slot, dict) and slot.get("is_processing") is False for slot in slots)
        except Exception:
            self.model_ports.pop(pid, None)
            idle = False
        if idle:
            self.model_idle_since.setdefault(pid, time.monotonic())
        else:
            self.model_idle_since.pop(pid, None)
        return idle

    def clean_models(self, force=False):
        with self.request_lock:
            return self._clean_models(force)

    def _clean_models(self, force=False):
        if not self.clean_llama or self.request_active.is_set():
            return None
        now = time.monotonic()
        before = self.api.snapshot()
        if not force and before["used_percent"] < self.threshold:
            return None
        ollama_root = str(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Ollama").lower() + "\\"
        trimmed = []
        for pid in self.api.processes():
            if self.stop_event.is_set() or self.api.session_id(pid) != self.api.session:
                continue
            info = self.api.process_info(pid)
            if not info or info["name"] != "llama-server.exe" or not info["path"].lower().startswith(ollama_root):
                continue
            if not self.model_is_idle(info):
                continue
            if not force and now - self.model_idle_since[pid] < self.llama_idle_seconds:
                continue
            if now - self.process_cooldowns.get((pid, info["name"]), float("-inf")) < 600:
                continue
            if info["working_set_mib"] < 512:
                continue
            handle = self.api.k.OpenProcess(0x1100, False, pid)
            if not handle:
                continue
            try:
                current = self.api.process_info(pid, handle)
                if not current or current["path"] != info["path"] or not self.model_is_idle(info):
                    continue
                if not self.api.k.K32EmptyWorkingSet(handle):
                    self.record({"time": time.time(), "event": "llama_cleanup_failed", "pid": pid,
                                 "winerror": ctypes.get_last_error()})
                    continue
                after = self.api.process_info(pid, handle)
                trimmed.append({"pid": pid, "name": info["name"], "before_mib": current["working_set_mib"],
                                "after_mib": after["working_set_mib"] if after else None})
                self.process_cooldowns[(pid, info["name"])] = now
            finally:
                self.api.k.CloseHandle(handle)
        if not trimmed:
            return None
        self.stop_event.wait(2)
        after = self.api.snapshot()
        result = {"time": time.time(), "event": "llama_cleanup", "threshold_percent": self.threshold,
                  "before": before, "after": after,
                  "available_change_mib": round(after["available_mib"] - before["available_mib"], 2),
                  "trimmed": trimmed}
        self.record(result)
        return result

    def mark_request_active(self):
        # Reset the idle grace period before our own request is sent to Ollama.
        with self.request_lock:
            self.request_active.set()
            self.idle_paged = False
            self.model_idle_since.clear()

    def mark_request_finished(self):
        with self.request_lock:
            self.model_idle_since.clear()
            self.request_active.clear()
            self.last_request_finished = time.monotonic()

    def clean_once(self, allow_foreground_names=()):
        now = time.monotonic()
        before = self.api.snapshot()
        if (before["used_percent"] < self.threshold and not self.cleanup_pending) or before["used_percent"] <= self.target or now - self.last_cleanup < 120:
            return None
        foreground = self.api.foreground_name()
        if not foreground:
            return None
        self.last_cleanup = now
        candidates = []
        for pid in self.api.processes():
            if self.stop_event.is_set():
                break
            if self.api.session_id(pid) != self.api.session:
                continue
            info = self.api.process_info(pid)
            if info and info["name"] in BACKGROUND_APPS and (info["name"] not in foreground_family(foreground) or info["name"] in allow_foreground_names):
                key = (pid, info["name"])
                if info["working_set_mib"] >= (32 if self.aggressive else 128) and now - self.process_cooldowns.get(key, float("-inf")) >= 600:
                    candidates.append(info)
        candidates.sort(key=lambda item: item["working_set_mib"], reverse=True)
        trimmed = []
        for info in candidates[:32 if self.aggressive else 8]:
            if self.stop_event.is_set() or self.api.snapshot()["used_percent"] <= self.target:
                break
            # Recheck foreground just before each trim, including all helpers with the same exe name.
            current_foreground = self.api.foreground_name()
            if not current_foreground:
                break
            if info["name"] in foreground_family(current_foreground) and info["name"] not in allow_foreground_names:
                continue
            handle = self.api.k.OpenProcess(0x1100, False, info["pid"])
            if not handle:
                continue
            try:
                current = self.api.process_info(info["pid"], handle)
                if not current or current["path"] != info["path"]:
                    continue
                if self.api.k.K32EmptyWorkingSet(handle):
                    after = self.api.process_info(info["pid"], handle)
                    trimmed.append({"pid": info["pid"], "name": info["name"],
                                    "before_mib": current["working_set_mib"],
                                    "after_mib": after["working_set_mib"] if after else None})
                    self.process_cooldowns[(info["pid"], info["name"])] = now
            finally:
                self.api.k.CloseHandle(handle)
        self.stop_event.wait(1)
        after = self.api.snapshot()
        result = {"time": time.time(), "threshold_percent": self.threshold, "foreground_excluded": foreground,
                  "target_percent": self.target, "target_reached": after["used_percent"] <= self.target,
                  "before": before, "after": after,
                  "available_change_mib": round(after["available_mib"] - before["available_mib"], 2),
                  "trimmed": trimmed}
        self.record(result)
        return result
