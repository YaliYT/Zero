"""Phase 2 step 1: observation without inference. Read-only: no model requests, no process changes."""
import ctypes, json, os, subprocess, sys, time, urllib.request, socket
from ctypes import wintypes as w
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
import sysmon, psutil

class PS(ctypes.Structure):
    _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("pct", ctypes.c_ubyte), ("saver", ctypes.c_ubyte),
                ("life", w.DWORD), ("full", w.DWORD)]
ps = PS(); ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(ps))

def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15, creationflags=0x08000000).stdout.strip()
    except Exception as e:
        return "ERR " + str(e)

obs = {"captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "inference_performed": False}
obs["ram"] = sysmon.ram()
obs["pagefile"] = sysmon.pagefile()
vm = psutil.virtual_memory()
obs["psutil_virtual_memory"] = {"percent": vm.percent, "available_mib": round(vm.available / sysmon.MiB), "used_mib": round(vm.used / sysmon.MiB)}
procs = []
for p in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
    n = (p.info["name"] or "").lower()
    cl = " ".join(p.info["cmdline"] or [])
    if n in ("ollama.exe", "ollama app.exe", "llama-server.exe") or ("qwen-agent" in cl.lower() and n.startswith("python")) or "qwen_" in cl.lower():
        info = sysmon.proc(p.info["pid"]) or {}
        procs.append({"pid": p.info["pid"], "name": p.info["name"], "exe": p.info["exe"], "cmdline": cl[:400], **info})
obs["relevant_processes"] = procs
obs["llama_server_running"] = any(x["name"].lower() == "llama-server.exe" for x in procs)
top = sorted(((sysmon.proc(p.pid) or {}, p.info["name"], p.pid) for p in psutil.process_iter(["name"])), key=lambda x: -x[0].get("ws_mib", 0))[:12]
obs["top_working_sets"] = [{"name": n, "pid": pid, "ws_mib": i.get("ws_mib"), "private_mib": i.get("private_mib")} for i, n, pid in top]
with socket.socket() as s:
    s.settimeout(1)
    obs["port_57206_listening"] = s.connect_ex(("127.0.0.1", 57206)) == 0
    s2 = socket.socket(); s2.settimeout(1); obs["port_11434_listening"] = s2.connect_ex(("127.0.0.1", 11434)) == 0; s2.close()
try:
    with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=3) as r:   # read-only: lists loaded models
        obs["ollama_api_ps"] = json.load(r)
except Exception as e:
    obs["ollama_api_ps"] = "ERR " + str(e)
obs["vram"] = sysmon.vram()
obs["nvidia_smi_compute_apps"] = sysmon.vram_by_process()
obs["nvidia_smi_gpu"] = run(["nvidia-smi", "--query-gpu=name,driver_version,temperature.gpu,power.draw,clocks.sm,utilization.gpu", "--format=csv,noheader"])
obs["power_scheme"] = run(["powercfg", "/getactivescheme"])
obs["ac_line_status"] = {0: "battery", 1: "AC (plugged in)", 255: "unknown"}.get(ps.ac, ps.ac)
obs["battery_percent"] = ps.pct
obs["battery_saver"] = bool(ps.saver)
obs["cpu_percent_1s"] = psutil.cpu_percent(interval=1)
out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("observation.json")
out.write_text(json.dumps(obs, indent=2), encoding="utf-8")
print(json.dumps({k: obs[k] for k in ("ram", "pagefile", "llama_server_running", "port_57206_listening", "ollama_api_ps", "vram", "power_scheme", "ac_line_status", "relevant_processes")}, indent=1))
