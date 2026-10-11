"""Bounded sampling A/B on the user's existing idle native server; never kills it."""
import json
from pathlib import Path
import socket
import threading
import time
import urllib.request
import sys

base = Path(__file__).resolve().parent
sys.path.insert(0, str(base / 'app'))
from qwen_memory_guard import WindowsMemory
api = WindowsMemory()
url = 'http://127.0.0.1:57206'
out = base / 'run-live-token-sampling'
out.mkdir(exist_ok=False)
report = {'preflight': api.snapshot(), 'rows': [], 'samples': [], 'error': None}
stop = threading.Event()
active = None

def json_get(path):
    with urllib.request.urlopen(url + path, timeout=3) as response:
        return json.load(response)

def monitor():
    while not stop.wait(.1):
        sample = api.snapshot()
        report['samples'].append(sample)
        if sample['used_percent'] >= 88:
            report['error'] = 'RAM ceiling 88%: cancel benchmark response only'
            stop.set()
            if active is not None:
                try:
                    active.fp.raw._sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
            return

prompt = '<|im_start|>user\nWrite three short tips for organizing files. No introduction.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
worker = threading.Thread(target=monitor, daemon=True)
worker.start()
try:
    for index, enabled in enumerate((False, False, True, True, False, True)):
        slots = json_get('/slots')
        if any(slot['is_processing'] for slot in slots):
            raise RuntimeError('Server is busy; no benchmark queued')
        if stop.is_set():
            raise RuntimeError(report['error'])
        body = {'prompt': prompt, 'n_predict': 16, 'temperature': 0, 'seed': 1234,
                'stream': True, 'cache_prompt': True, 'backend_sampling': enabled}
        request = urllib.request.Request(url + '/completion', json.dumps(body).encode(), {'Content-Type': 'application/json'})
        started = time.perf_counter()
        row = {'index': index, 'backend_sampling': enabled, 'content': '', 'first_token_seconds': None}
        with urllib.request.urlopen(request, timeout=35) as response:
            active = response
            for line in response:
                if not line.startswith(b'data: '):
                    continue
                chunk = json.loads(line[6:])
                if chunk.get('content'):
                    if row['first_token_seconds'] is None:
                        row['first_token_seconds'] = time.perf_counter() - started
                    row['content'] += chunk['content']
                if chunk.get('stop'):
                    row['timings'] = chunk['timings']
                    row['generation_settings'] = chunk.get('generation_settings')
            active = None
        row['seconds'] = time.perf_counter() - started
        if 'timings' not in row:
            raise RuntimeError('Missing final timings')
        report['rows'].append(row)
        print(json.dumps(row), flush=True)
        (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
except Exception as error:
    report['error'] = str(error)
    print('ERROR ' + str(error), flush=True)
finally:
    stop.set()
    worker.join(timeout=2)
    report['peak_ram_percent'] = max((s['used_percent'] for s in report['samples']), default=report['preflight']['used_percent'])
    (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
