"""Single owned model, short deterministic probes, hard RAM stop, durable evidence."""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
import urllib.request
import ctypes
import psutil
import importlib.util
import shutil
from ctypes import wintypes as w

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / 'app'))
from qwen_cpu_runner import NativeRunner
from qwen_memory_guard import WindowsMemory, MemoryGuard

parser = argparse.ArgumentParser()
parser.add_argument('--label', default='baseline')
parser.add_argument('--projector', choices=['on', 'off'], default='on')
parser.add_argument('--draft', type=int, default=4)
parser.add_argument('--threads', type=int, default=4)
parser.add_argument('--batch-threads', type=int, default=12)
parser.add_argument('--batch', type=int, default=512)
parser.add_argument('--reps', type=int, default=3)
parser.add_argument('--fit-off', action='store_true')
parser.add_argument('--host-buffer', action='store_true')
parser.add_argument('--no-pinned', action='store_true')
parser.add_argument('--load-mode', choices=['mmap', 'none'], default='mmap')
parser.add_argument('--background-guard', action='store_true')
parser.add_argument('--policies', action='store_true')
parser.add_argument('--tasks', action='store_true')
parser.add_argument('--trim-firefox', action='store_true')
parser.add_argument('--cache-ram', type=int)
parser.add_argument('--checkpoints', type=int)
parser.add_argument('--checkpoint-step', type=int)
parser.add_argument('--gpu', type=int, default=8)
parser.add_argument('--warm-only', action='store_true')
parser.add_argument('--cpu-logicals')
parser.add_argument('--repeat-task', action='store_true')
parser.add_argument('--no-startup-trim', action='store_true')
parser.add_argument('--hebrew-task', action='store_true')
parser.add_argument('--changed-task', action='store_true')
parser.add_argument('--passive', action='store_true')
parser.add_argument('--no-op-offload', action='store_true')
parser.add_argument('--tokens', type=int, default=16)
parser.add_argument('--scenario', choices=['files', 'code', 'hebrew'], default='files')
parser.add_argument('--mixed', action='store_true')
parser.add_argument('--no-cuda-graphs', action='store_true')
parser.add_argument('--cache-type', choices=['q4_0', 'q8_0', 'f16'], default='q4_0')
parser.add_argument('--compact-protocol', action='store_true')
parser.add_argument('--repack', action='store_true')
parser.add_argument('--runtime-paths')
parser.add_argument('--max-seconds', type=int, default=600)
parser.add_argument('--greedy-only', action='store_true')
parser.add_argument('--batch-cpu-logicals')
parser.add_argument('--stable-ac', action='store_true')
parser.add_argument('--tensor-override', action='append', default=[])
parser.add_argument('--gpu-memory-floor', type=int, default=0)
parser.add_argument('--power-scheme', choices=['27fa6203-3987-4dcc-918d-748559d549ec','6fecc5ae-f350-48a5-b669-b472cb895ccf'], default='27fa6203-3987-4dcc-918d-748559d549ec')
args = parser.parse_args()
if not 1 <= args.tokens <= 64:
    parser.error('--tokens must be 1-64')
task_prompt = ('צור קובץ hello.txt שמכיל בדיוק hello עם ירידת שורה בסוף. אמת את התוכן וענה במשפט קצר בעברית.'
               if args.hebrew_task else 'Create hello.txt containing exactly hello followed by a newline. Verify the contents. Reply in one short sentence.')
prompt_texts = {
    'files': 'Write three short tips for organizing files. No introduction.',
    'code': 'Write a Python function that removes duplicates from a list while preserving order. Return only code.',
    'hebrew': 'כתוב בעברית שלושה טיפים קצרים לסידור קבצים. בלי הקדמה.'
}
prompt_text = prompt_texts[args.scenario]
generation_prompt = '<|im_start|>user\n' + prompt_text + '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
root = BASE / ('run-' + args.label)
root.mkdir(exist_ok=False)
settings = json.loads((BASE / 'app' / 'qwen-agent-settings.json').read_text(encoding='utf-8-sig'))
settings.update(num_thread=args.threads, num_thread_batch=args.batch_threads, draft_num_predict=args.draft)
settings['num_batch'] = args.batch
settings['num_gpu'] = args.gpu
settings['native_greedy_sampling'] = args.greedy_only
settings['native_tensor_overrides'] = args.tensor_override
if args.repack:
    settings['model_repack'] = True
settings.update(native_cache_type_k=args.cache_type, native_cache_type_v=args.cache_type)
if args.no_cuda_graphs:
    settings['native_cuda_graphs'] = False
if args.no_op_offload:
    settings['native_op_offload'] = False
if args.cpu_logicals:
    settings['cpu_generation_logical'] = [int(value) for value in args.cpu_logicals.split(',')]
if args.batch_cpu_logicals:
    settings['cpu_batch_logical'] = [int(value) for value in args.batch_cpu_logicals.split(',')]
settings['model_load_mode'] = args.load_mode
settings['cuda_no_pinned'] = args.no_pinned
if args.passive:
    settings.update(native_passive_openmp=True, native_poll_level=0)
if args.cache_ram is not None:
    settings['native_cache_ram_mib'] = args.cache_ram
if args.checkpoints is not None:
    settings['native_context_checkpoints'] = args.checkpoints
if args.checkpoint_step is not None:
    settings['native_checkpoint_min_step'] = args.checkpoint_step
if args.fit_off:
    settings['native_fit_enabled'] = False
if args.projector == 'off':
    settings['native_projector_enabled'] = False
if args.host_buffer:
    settings['model_no_host'] = False
paths = json.loads((Path(args.runtime_paths) if args.runtime_paths else BASE / 'app' / 'qwen-cpu-runner-paths.json').read_text(encoding='utf-8-sig'))
(root / 'qwen-cpu-runner-paths.json').write_text(json.dumps(paths), encoding='utf-8')
if args.tasks:
    # Import the entire agent before measurement so editing a later candidate cannot mix versions.
    spec = importlib.util.spec_from_file_location('agent_benchmark', BASE / 'app' / 'Qwen-Agent.py')
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
source_files = list((BASE / 'app').glob('*.py'))
(root/'source-sha256.json').write_text(json.dumps({p.name:__import__('hashlib').sha256(p.read_bytes()).hexdigest()
                                                for p in source_files}, indent=2), encoding='utf-8')
api = WindowsMemory()
gpu_monitor = None
if args.gpu_memory_floor:
    from gpu_probe import GPU
    gpu_monitor = GPU()
class PowerStatus(ctypes.Structure):
    _fields_ = [('ac', w.BYTE), ('flags', w.BYTE), ('percent', w.BYTE), ('saver', w.BYTE),
                ('life', w.DWORD), ('full', w.DWORD)]

def power_status():
    value = PowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(value)):
        raise ctypes.WinError()
    return {'ac': value.ac, 'battery_percent': value.percent, 'battery_saver': value.saver}

if args.stable_ac:
    print('Waiting for 10 continuous seconds of AC power', flush=True)
    stable_since = None
    wait_deadline = time.monotonic() + 60
    while time.monotonic() < wait_deadline:
        if power_status()['ac'] == 1:
            stable_since = stable_since or time.monotonic()
            if time.monotonic() - stable_since >= 10:
                break
        else:
            stable_since = None
        time.sleep(.25)
    else:
        raise RuntimeError('AC did not stay connected for 10 continuous seconds; no model started')
    subprocess_power = __import__('subprocess')
    subprocess_power.run(['powercfg', '/setactive', args.power_scheme], check=True,
                         creationflags=subprocess_power.CREATE_NO_WINDOW)

runner = NativeRunner(root, settings)
guard = MemoryGuard(root, settings) if args.background_guard else None
runner.k.TerminateJobObject.restype = w.BOOL
runner.k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
report = {'settings': settings, 'rows': [], 'events': [], 'samples': [], 'label': args.label, 'ceiling': 88,
          'scenario': 'mixed' if args.mixed else args.scenario, 'token_limit': args.tokens,
          'power_at_start': power_status(), 'compact_protocol': args.compact_protocol,
          'runtime_paths': paths, 'requested_power_scheme': args.power_scheme}
output = root / 'results.json'
stop = threading.Event()
loaded = threading.Event()
abort = threading.Event()
started_at = time.monotonic()


def save():
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def monitor():
    last_trim = 0
    while not stop.wait(.1):
        try:
            snapshot = api.snapshot()
            sample = {'t': time.monotonic(), 'ram': snapshot['used_percent']}
            if runner.process:
                info = api.process_info(runner.process.pid)
                sample['process'] = info
                if len(report['samples']) % 10 == 0:
                    sample['children'] = [api.process_info(p.pid) for p in psutil.Process(runner.process.pid).children(recursive=True)]
            report['samples'].append(sample)
            if len(report['samples']) % 10 == 0:
                if gpu_monitor:
                    sample['gpu'] = gpu_monitor.snapshot()
                    if sample['gpu']['free_mib'] < args.gpu_memory_floor and runner.process:
                        abort.set()
                        report['events'].append({'abort': 'GPU memory headroom', 'gpu': sample['gpu'], 'floor_mib': args.gpu_memory_floor})
                        if runner.job:
                            runner.k.TerminateJobObject(runner.job, 89)
                        return
                sample['power'] = power_status()
                if sample['power']['ac'] != report['power_at_start']['ac'] and runner.process:
                    abort.set()
                    report['events'].append({'abort': 'AC power changed; timings are not comparable'})
                    if runner.job:
                        runner.k.TerminateJobObject(runner.job, 91)
                    return
            if time.monotonic() - started_at > args.max_seconds and runner.process:
                abort.set()
                report['events'].append({'abort': 'benchmark wall time limit', 'seconds': args.max_seconds})
                if runner.job:
                    runner.k.TerminateJobObject(runner.job, 90)
                return
            if snapshot['used_percent'] >= 88 and runner.process:
                abort.set()
                report['events'].append({'abort': snapshot, 'phase': 'ready' if loaded.is_set() else 'loading'})
                if runner.job:
                    runner.k.TerminateJobObject(runner.job, 88)
                return
            if not args.no_startup_trim and not loaded.is_set() and snapshot['used_percent'] >= 80 and runner.process and time.monotonic() - last_trim >= .75:
                handle = api.k.OpenProcess(0x1100, False, runner.process.pid)
                if handle:
                    try:
                        ok = bool(api.k.K32EmptyWorkingSet(handle))
                        report['events'].append({'startup_trim_ram': snapshot['used_percent'], 'ok': ok})
                    finally:
                        api.k.CloseHandle(handle)
                    last_trim = time.monotonic()
        except Exception as error:
            report['events'].append({'monitor_error': str(error)})
            abort.set()
            if runner.job:
                runner.k.TerminateJobObject(runner.job, 89)
            return


def request(body):
    if args.greedy_only:
        body.update(samplers=['temperature'], top_k=1, top_p=1, min_p=0)
    req = urllib.request.Request('http://127.0.0.1:57206/completion', json.dumps(body).encode(),
                                 {'Content-Type': 'application/json'})
    start = time.perf_counter()
    first, content, final = None, '', None
    with urllib.request.urlopen(req, timeout=120) as response:
        for line in response:
            if not line.startswith(b'data: '):
                continue
            chunk = json.loads(line[6:])
            if chunk.get('content'):
                first = first or time.perf_counter() - start
                content += chunk['content']
            if chunk.get('stop'):
                final = chunk
    if not final:
        raise RuntimeError('No final response')
    return {'seconds': time.perf_counter() - start, 'first_token_seconds': first,
            'content': content, 'timings': final.get('timings', {})}


worker = threading.Thread(target=monitor, daemon=True)
try:
    report['preflight'] = api.snapshot()
    print('PREFLIGHT ' + json.dumps(report['preflight']), flush=True)
    if guard:
        guard.cleanup_pending = True
        report['startup_background_cleanup'] = []
        for cleanup_index in range(5 if args.trim_firefox else 1):
            # Extra startup passes only after the user's explicit Firefox approval.
            # Existing per-process cooldown still prevents trimming one PID twice.
            guard.last_cleanup = float('-inf')
            cleanup = guard.clean_once(allow_foreground_names=('firefox.exe',) if args.trim_firefox else ())
            report['startup_background_cleanup'].append(cleanup)
            if not cleanup or not cleanup['trimmed'] or cleanup['target_reached']:
                break
        print('AFTER CLEANUP ' + json.dumps(api.snapshot()), flush=True)
    worker.start()
    if guard:
        guard.start()
    began = time.perf_counter()
    runner.start()
    loaded.set()
    report['load_seconds'] = time.perf_counter() - began
    print('LOADED ' + str(round(report['load_seconds'], 2)), flush=True)
    for index in range(args.reps):
        if abort.is_set():
            raise RuntimeError('RAM safety stop')
        scenario = ('files', 'files', 'code', 'code', 'hebrew', 'hebrew')[index % 6] if args.mixed else args.scenario
        current_prompt = '<|im_start|>user\n' + prompt_texts[scenario] + '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
        result = request({'prompt': current_prompt,
                          'n_predict': args.tokens, 'temperature': 0, 'seed': 1234, 'stream': True, 'cache_prompt': True})
        result['run'] = index
        result['scenario'] = scenario
        report['rows'].append(result)
        save()
        print('RESULT ' + json.dumps(result, ensure_ascii=False), flush=True)
    if args.policies:
        # Paired requests share one server and one prompt; include prepare time in user latency.
        for index, policy in enumerate(('warm', 'warm', 'warm') if args.warm_only else ('warm', 'baseline', 'warm', 'baseline', 'warm')):
            policy_settings = dict(settings)
            policy_settings['memory_prepare_request_enabled'] = policy == 'baseline'
            policy_guard = MemoryGuard(root, policy_settings)
            policy_guard.bind_model(runner.process.pid)
            began = time.perf_counter()
            policy_guard.prepare_turn()
            prepare_seconds = time.perf_counter() - began
            policy_guard.mark_request_active()
            try:
                result = request({'prompt': '<|im_start|>user\nWrite three short tips for organizing files. No introduction.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n',
                                  'n_predict': 16, 'temperature': 0, 'seed': 1234, 'stream': True, 'cache_prompt': True})
            finally:
                policy_guard.mark_request_finished()
                policy_guard.finish_turn()
            result.update(policy=policy, prepare_seconds=prepare_seconds,
                          user_first_token_seconds=prepare_seconds + result['first_token_seconds'],
                          user_total_seconds=prepare_seconds + result['seconds'])
            report['rows'].append(result)
            save()
            print('POLICY ' + json.dumps(result, ensure_ascii=False), flush=True)
    if args.tasks:
        report['tasks'] = []
        for policy in (('warm',) if args.warm_only else ('baseline', 'warm')):
            fixture = root / ('task-' + policy)
            project = fixture / 'project'
            agent_root = fixture / 'agent'
            project.mkdir(parents=True)
            agent_root.mkdir()
            task_settings = dict(settings)
            task_settings['agent_compact_protocol_enabled'] = args.compact_protocol
            task_settings['native_greedy_sampling'] = args.greedy_only
            (agent_root / 'qwen-agent-settings.json').write_text(json.dumps(task_settings), encoding='utf-8')
            agent.ROOT, agent.SETTINGS = agent_root, agent_root / 'qwen-agent-settings.json'
            agent.WORKSPACE = agent.CodingWorkspace(agent_root, project, mode='acceptEdits')
            policy_settings = dict(settings, memory_prepare_request_enabled=policy == 'baseline')
            agent.MEMORY_GUARD = MemoryGuard(agent_root, policy_settings)
            agent.MEMORY_GUARD.bind_model(runner.process.pid)
            began = time.perf_counter()
            result = agent.agent_turn(task_prompt, interactive=False)
            elapsed = time.perf_counter() - began
            verified = (project / 'hello.txt').is_file() and (project / 'hello.txt').read_text(encoding='utf-8') == 'hello\n'
            task = dict(policy=policy, seconds=elapsed, result=result, verified=verified)
            report['tasks'].append(task)
            save()
            print('TASK ' + json.dumps(task, ensure_ascii=False), flush=True)
            if args.repeat_task and verified:
                # This file was created by the isolated fixture above. No user file is touched.
                (project / 'hello.txt').unlink()
                agent.WORKSPACE.new_session()
                began = time.perf_counter()
                again = agent.agent_turn(task_prompt, interactive=False)
                elapsed = time.perf_counter() - began
                verified_again = (project / 'hello.txt').is_file() and (project / 'hello.txt').read_text(encoding='utf-8') == 'hello\n'
                task_again = dict(policy=policy, repeat=True, seconds=elapsed, result=again, verified=verified_again)
                report['tasks'].append(task_again)
                save()
                print('TASK REPEAT ' + json.dumps(task_again, ensure_ascii=False), flush=True)
            if args.changed_task and verified:
                began = time.perf_counter()
                changed = agent.agent_turn('קרא עכשיו שוב את hello.txt בעזרת read_file וציין את התוכן. ענה בקצרה בעברית.', interactive=False)
                elapsed = time.perf_counter() - began
                read_ok = any(t['name'] == 'read_file' and t['result'].get('ok') and t['result'].get('content') == 'hello' for t in changed['tools'])
                changed_task = dict(policy=policy, changed_prompt=True, seconds=elapsed, result=changed, verified=read_ok)
                report['tasks'].append(changed_task)
                save()
                print('TASK CHANGED ' + json.dumps(changed_task, ensure_ascii=False), flush=True)
except Exception as error:
    report['error'] = repr(error)
    print('ERROR ' + repr(error), flush=True)
finally:
    stop.set()
    worker.join(timeout=3)
    runner.close()
    if guard:
        guard.close()
    if gpu_monitor:
        gpu_monitor.close()
    if args.stable_ac and args.power_scheme != '27fa6203-3987-4dcc-918d-748559d549ec' and power_status()['ac'] == 1:
        subprocess_power.run(['powercfg', '/setactive', '27fa6203-3987-4dcc-918d-748559d549ec'], check=True,
                             creationflags=subprocess_power.CREATE_NO_WINDOW)
    report['peak_ram_percent'] = max((s['ram'] for s in report['samples']), default=0)
    report['aborted'] = abort.is_set()
    save()
