"""Resume the existing installation once, and verify only the newly owned process."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import psutil

ROOT = Path('C:/Users/nagor/Downloads/Qwen-Agent-work')
BASE = Path(__file__).resolve().parent
expected = json.loads((ROOT / 'token-speed-tests-v2-20261011/installation.json').read_text(encoding='utf-8-sig'))['files']
actual = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in expected}
if actual != expected:
    raise RuntimeError('Installed files differ from the verified v2 installation; not launching silently')
agent_path = str(ROOT/'Qwen-Agent.py').lower()
for process in psutil.process_iter(['name', 'cmdline']):
    if 'python' in (process.info['name'] or '').lower() and any(str(x).lower() == agent_path for x in process.info['cmdline'] or []):
        raise RuntimeError('An installed user agent is already running; do not launch another copy')
with __import__('socket').socket() as port:
    port.settimeout(1)
    if port.connect_ex(('127.0.0.1',57206)) == 0:
        raise RuntimeError('A model is still occupying the agent port; do not launch another copy')
ps_script = ROOT/'Qwen-Agent.ps1'
launch = subprocess.run(['powershell.exe','-NoProfile','-Command',
    f"Start-Process -FilePath 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe' -ArgumentList '-NoExit -NoProfile -ExecutionPolicy Bypass -File \"{ps_script}\" -Continue' -PassThru | Select-Object -ExpandProperty Id"],
    check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
shell_pid = int(launch.stdout.strip())
parent = psutil.Process(shell_pid)
peak = 0
report = dict(time=datetime.datetime.now().astimezone().isoformat(), shell_pid=shell_pid,
              all_installed_hashes_match=True, verified_hashes=actual)
try:
    for _ in range(900):
        usage = psutil.virtual_memory().percent
        peak = max(peak, usage)
        if usage >= 88:
            for child in parent.children(recursive=True):
                if 'python' in child.name().lower() and any(str(x).lower() == agent_path for x in child.cmdline()):
                    child.terminate()  # Its kill-on-close job releases only its owned model.
            raise RuntimeError('Owned agent stopped at RAM88 during restart')
        try:
            with urllib.request.urlopen('http://127.0.0.1:57206/health', timeout=1) as response:
                health = json.load(response)
            if health.get('status') == 'ok':
                with urllib.request.urlopen('http://127.0.0.1:57206/slots', timeout=2) as response:
                    slots = json.load(response)
                children = parent.children(recursive=True)
                agent_pids = [p.pid for p in children if any(str(x).lower() == agent_path for x in p.cmdline())]
                runner = json.loads((ROOT/'qwen-cpu-runner-status.json').read_text(encoding='utf-8-sig'))
                if not agent_pids or not any(p.pid == runner['pid'] for p in children):
                    raise RuntimeError('Health belongs to an unexpected process')
                report.update(health=health, slots=slots, agent_pids=agent_pids, runner=runner,
                              ram_used_percent=usage, peak_startup_ram_percent=peak, verified=True)
                break
        except (OSError, ValueError):
            pass
        time.sleep(.1)
    else:
        raise TimeoutError('Restart did not become healthy within 90 seconds')
except Exception as error:
    report.update(verified=False, error=repr(error), peak_startup_ram_percent=peak)
    raise
finally:
    (BASE/'v3-delivery/resumed-agent-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('verified_hashes','runner','slots')},ensure_ascii=False))
