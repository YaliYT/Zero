"""System / process / VRAM sampling helpers for the Phase-2 harness (no model access)."""
import ctypes
from ctypes import wintypes as w
import json
import subprocess
import threading
import time

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

MiB = 1024 * 1024


class MemoryStatus(ctypes.Structure):
    _fields_ = [("length", w.DWORD), ("load", w.DWORD)] + [
        (n, ctypes.c_ulonglong) for n in ("total", "available", "page_total", "page_available",
                                          "virtual_total", "virtual_available", "extended_available")]


_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
_k.GlobalMemoryStatusEx.restype = w.BOOL


def ram():
    s = MemoryStatus()
    s.length = ctypes.sizeof(s)
    if not _k.GlobalMemoryStatusEx(ctypes.byref(s)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"used_percent": round(100 * (1 - s.available / s.total), 2),
            "total_mib": round(s.total / MiB), "available_mib": round(s.available / MiB),
            "commit_used_mib": round((s.page_total - s.page_available) / MiB),
            "commit_limit_mib": round(s.page_total / MiB)}


def pagefile():
    if psutil is None:
        return {}
    p = psutil.swap_memory()
    return {"pagefile_used_mib": round(p.used / MiB), "pagefile_total_mib": round(p.total / MiB)}


def proc(pid):
    """Working set / private bytes / cumulative page faults of one process (None if unreadable)."""
    if psutil is None or not pid:
        return None
    try:
        m = psutil.Process(pid).memory_info()
        return {"ws_mib": round(m.wset / MiB, 1), "private_mib": round(getattr(m, "private", 0) / MiB, 1),
                "faults": int(m.num_page_faults)}
    except Exception:
        return None


def _smi(args, timeout=8):
    try:
        out = subprocess.run(["nvidia-smi"] + args, capture_output=True, text=True, timeout=timeout,
                             creationflags=0x08000000)
        return out.stdout.strip()
    except Exception:
        return ""


def vram():
    text = _smi(["--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"])
    try:
        used, total = (int(x) for x in text.splitlines()[0].split(","))
        return {"vram_used_mib": used, "vram_total_mib": total}
    except Exception:
        return {}


def vram_by_process():
    text = _smi(["--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"])
    return text


class Sampler:
    """Polls RAM+process memory every `interval` s and VRAM every `vram_interval` s.

    `ceiling` (percent): when RAM reaches it, `on_ceiling()` is called once (kills only owned processes).
    """

    def __init__(self, get_pid, interval=1.0, vram_interval=2.0, ceiling=88.0, on_ceiling=None, valve=None, on_valve=None, valve_cooldown=8.0):
        self.get_pid, self.interval, self.vram_interval = get_pid, interval, vram_interval
        self.ceiling, self.on_ceiling = ceiling, on_ceiling
        self.valve, self.on_valve, self.valve_cooldown = valve, on_valve, valve_cooldown
        self.valve_events, self._last_valve = [], float('-inf')
        self.samples, self.vram_samples = [], []
        self.stop_event = threading.Event()
        self.tripped = None
        self.lock = threading.Lock()
        self.threads = []

    def _ram_loop(self):
        while not self.stop_event.is_set():
            t = time.perf_counter()
            try:
                r = ram()
                p = proc(self.get_pid())
                row = {"t": t, "ram": r["used_percent"], "avail_mib": r["available_mib"],
                       "commit_mib": r["commit_used_mib"]}
                if p:
                    row.update(ws=p["ws_mib"], private=p["private_mib"], faults=p["faults"])
                with self.lock:
                    self.samples.append(row)
                if (self.valve and r["used_percent"] >= self.valve and r["used_percent"] < self.ceiling and self.on_valve
                        and t - self._last_valve >= self.valve_cooldown and self.tripped is None):
                    self._last_valve = t
                    ok = self.on_valve()
                    self.valve_events.append({"t": t, "time": time.time(), "ram": r["used_percent"], "ok": ok})
                if r["used_percent"] >= self.ceiling and self.tripped is None:
                    self.tripped = {"t": t, "ram": r["used_percent"], "time": time.time()}
                    if self.on_ceiling:
                        self.on_ceiling(self.tripped)
            except Exception as e:  # keep sampling
                with self.lock:
                    self.samples.append({"t": t, "error": str(e)})
            self.stop_event.wait(self.interval)

    def _vram_loop(self):
        while not self.stop_event.is_set():
            t = time.perf_counter()
            v = vram()
            if v:
                with self.lock:
                    self.vram_samples.append({"t": t, **v})
            self.stop_event.wait(self.vram_interval)

    def start(self):
        for target in (self._ram_loop, self._vram_loop):
            th = threading.Thread(target=target, daemon=True)
            th.start()
            self.threads.append(th)
        return self

    def stop(self):
        self.stop_event.set()
        for th in self.threads:
            th.join(5)

    def window(self, t0, t1):
        with self.lock:
            s = [x for x in self.samples if t0 <= x["t"] <= t1 and "ram" in x]
            v = [x for x in self.vram_samples if t0 - 2 <= x["t"] <= t1 + 2]
        out = {"n_ram_samples": len(s), "n_vram_samples": len(v),
               "valve_trims": sum(1 for e in self.valve_events if t0 <= e["t"] <= t1)}
        if s:
            out.update(ram_min=min(x["ram"] for x in s), ram_max=max(x["ram"] for x in s),
                       ram_mean=round(sum(x["ram"] for x in s) / len(s), 2))
            ws = [x["ws"] for x in s if "ws" in x]
            if ws:
                out.update(ws_min_mib=min(ws), ws_max_mib=max(ws))
            pr = [x["private"] for x in s if "private" in x]
            if pr:
                out.update(private_max_mib=max(pr))
        if v:
            out.update(vram_max_mib=max(x["vram_used_mib"] for x in v), vram_min_mib=min(x["vram_used_mib"] for x in v))
        return out
