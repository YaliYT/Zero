"""End-to-end check of the staged real agent, one owned child and hard stop conditions."""
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from gpu_probe import GPU

BASE=Path(__file__).resolve().parent
APP=BASE/'v4-delivery/app'
sys.path.insert(0,str(APP))
from qwen_memory_guard import WindowsMemory

class Power(ctypes.Structure):
    _fields_=[('ac',w.BYTE),('flags',w.BYTE),('percent',w.BYTE),('saver',w.BYTE),('life',w.DWORD),('full',w.DWORD)]

def ac():
    value=Power()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(value)):
        raise ctypes.WinError()
    return value.ac

if ac()!=1:
    raise RuntimeError('AC not online; no test model started')
root=BASE/'run-entrypoint-v4'
root.mkdir(exist_ok=False)
project=root/'project'
project.mkdir()
api=WindowsMemory()
gpu=GPU()
report=dict(preflight=api.snapshot(),samples=[],aborted=False,
            source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in APP.glob('*.py')},
            settings=json.loads((APP/'qwen-agent-settings.json').read_text(encoding='utf-8-sig')))
environment=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
task='צור קובץ hello.txt שמכיל בדיוק hello עם ירידת שורה בסוף. אמת את התוכן וענה במשפט קצר בעברית.'
began=time.perf_counter()
with (root/'console.log').open('w',encoding='utf-8') as log:
    child=subprocess.Popen([sys.executable,str(APP/'Qwen-Agent.py'),'--project',str(project),
                            '--task',task,'--report',str(root/'answer.json')],
                           stdout=log,stderr=subprocess.STDOUT,env=environment,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        while child.poll() is None:
            sample=api.snapshot()
            report['samples'].append(sample)
            reason=None
            if len(report['samples'])%10==0:
                sample['gpu']=gpu.snapshot()
                sample['ac']=ac()
                if sample['gpu']['free_mib']<64:
                    reason='GPU headroom below 64 MiB'
                if sample['ac']!=1:
                    reason='AC report changed'
            if sample['used_percent']>=88:
                reason='RAM88 safety stop'
            if time.perf_counter()-began>180:
                reason='180-second safety stop'
            if reason:
                report.update(aborted=True,abort_reason=reason)
                child.terminate()  # Its kill-on-close job releases only its own model.
                break
            time.sleep(.1)
        report['exit_code']=child.wait(timeout=25)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=25)
        gpu.close()
report['seconds_including_model_load']=time.perf_counter()-began
report['peak_ram_percent']=max(s['used_percent'] for s in report['samples'])
output=project/'hello.txt'
report['verified_bytes']=output.is_file() and output.read_bytes()==b'hello\n'
if (root/'answer.json').is_file():
    report['result']=json.loads((root/'answer.json').read_text(encoding='utf-8'))
report['verified']=report['verified_bytes'] and report['exit_code']==0 and not report['aborted']
(root/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('samples','source_sha256','settings')},ensure_ascii=False))
raise SystemExit(0 if report['verified'] else 1)
