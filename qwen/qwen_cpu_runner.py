"""Owned llama-server process with separate generation and prompt CPU pools."""
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
from qwen_terminal import DisplayStream


class BasicLimits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong), ('flags', w.DWORD),
                ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t), ('active', w.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', BasicLimits), ('io', ctypes.c_ulonglong * 6),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]


class NativeRunner:
    def __init__(self, root, settings):
        self.root = Path(root)
        self.settings = settings
        self.port = int(settings.get('native_runner_port', 57206))
        self.process = None
        self.log = None
        self.job = None
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateJobObjectW': (w.HANDLE, [ctypes.c_void_p, w.LPCWSTR]),
            'SetInformationJobObject': (w.BOOL, [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]),
            'AssignProcessToJobObject': (w.BOOL, [w.HANDLE, w.HANDLE]),
            'CloseHandle': (w.BOOL, [w.HANDLE]),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.k, name)
            function.restype, function.argtypes = result, arguments

    def start(self):
        config = json.loads((self.root / 'qwen-cpu-runner-paths.json').read_text(encoding='utf-8-sig'))
        for name in ('executable', 'model', 'cuda_library') + (('projector',) if self.settings.get('native_projector_enabled', True) else ()):
            if not Path(config[name]).is_file():
                raise FileNotFoundError(config[name])
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(('127.0.0.1', self.port)) == 0:
                raise RuntimeError('A Qwen runner is already using this port. Use the existing agent window.')
        # Reuse the working CUDA DLL environment before unloading Ollama's copy of these weights.
        environment = os.environ.copy()
        try:
            import psutil
            for process in psutil.process_iter(['name', 'exe']):
                if process.info['name'] == 'llama-server.exe' and process.info['exe'] == config['executable']:
                    environment = process.environ()
                    break
        except (ImportError, OSError):
            pass
        libraries = [str(Path(config['executable']).parent), str(Path(config['cuda_library']).parent)]
        libraries += config.get('runtime_library_dirs', [])
        environment['PATH'] = os.pathsep.join(libraries + [environment.get('PATH', '')])
        environment['GGML_BACKEND_PATH'] = config['cuda_library']
        if self.settings.get('cuda_no_pinned', False):
            environment['GGML_CUDA_NO_PINNED'] = '1'
        if self.settings.get('native_cuda_graphs') is False:
            environment['GGML_CUDA_DISABLE_GRAPHS'] = '1'
        else:
            environment.pop('GGML_CUDA_DISABLE_GRAPHS', None)
        if self.settings.get('native_passive_openmp', False):
            environment['OMP_WAIT_POLICY'] = 'PASSIVE'
            environment['KMP_BLOCKTIME'] = '0'
        body = {'model': 'qwen3.8:latest', 'keep_alive': 0}
        request = urllib.request.Request('http://127.0.0.1:11434/api/generate', json.dumps(body).encode(),
                                         {'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            json.load(response)
        settings = self.settings
        load_mode = settings.get('model_load_mode', 'none')
        if load_mode not in ('none', 'mmap'):
            raise ValueError('model_load_mode must be none or mmap')
        generation = settings['cpu_generation_logical']
        batch = settings['cpu_batch_logical']
        if not generation or not batch or any(type(cpu) is not int or not 0 <= cpu < 64 for cpu in generation + batch):
            raise ValueError('Invalid tested CPU affinity settings')
        args = [config['executable'], '--model', config['model'], '--port', str(self.port), '--host', '127.0.0.1',
                '--no-webui', '--offline', '-c', str(settings['num_ctx']), '-np', '1', '--log-verbosity', '4',
                '--no-log-prefix', '--no-log-timestamps', '--jinja',
                '--spec-type', 'draft-mtp', '--spec-draft-n-max', str(settings['draft_num_predict']),
                '--spec-draft-backend-sampling', '--load-mode', load_mode,
                '--cache-type-k', settings.get('native_cache_type_k', 'q4_0'),
                '--cache-type-v', settings.get('native_cache_type_v', 'q4_0'),
                '--flash-attn', 'on', '-b', str(settings['num_batch']), '-ub', str(settings['num_batch']),
                '-ngl', str(settings['num_gpu']), '-t', str(settings['num_thread']), '-tb', str(settings['num_thread_batch']),
                '--cpu-mask', format(sum(1 << cpu for cpu in generation), 'x'), '--cpu-strict', '1',
                '--cpu-mask-batch', format(sum(1 << cpu for cpu in batch), 'x'), '--cpu-strict-batch', '1',
                '--context-shift', '--keep', '4']
        if settings.get('model_no_host', False):
            args.append('--no-host')
        if settings.get('model_repack') is False:
            args.append('--no-repack')
        if settings.get('native_fit_enabled') is False:
            args += ['--fit', 'off']
        if settings.get('native_op_offload') is False:
            args.append('--no-op-offload')
        if 'native_draft_probability_min' in settings:
            probability = float(settings['native_draft_probability_min'])
            if not 0 <= probability <= 1:
                raise ValueError('Invalid draft probability threshold')
            args += ['--spec-draft-p-min', str(probability)]
        if 'native_cache_ram_mib' in settings:
            args += ['--cache-ram', str(int(settings['native_cache_ram_mib']))]
        if 'native_context_checkpoints' in settings:
            args += ['--ctx-checkpoints', str(int(settings['native_context_checkpoints']))]
        if 'native_checkpoint_min_step' in settings:
            args += ['--checkpoint-min-step', str(int(settings['native_checkpoint_min_step']))]
        if 'native_poll_level' in settings:
            level = str(int(settings['native_poll_level']))
            args += ['--poll', level, '--poll-batch', level, '--spec-draft-poll', level, '--spec-draft-poll-batch', level]
        if settings.get('native_projector_enabled') is False:
            args.append('--no-mmproj')
        else:
            args += ['--mmproj', config['projector'], '--no-mmproj-offload']
        if int(settings.get('draft_num_predict', 4)) == 0:
            args[args.index('--spec-type') + 1] = 'none'
        sleep_seconds = int(settings.get('native_sleep_idle_seconds', -1))
        if sleep_seconds >= 15:
            args += ['--sleep-idle-seconds', str(sleep_seconds)]
        self.job = self.k.CreateJobObjectW(None, None)
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE: closing the console also releases model memory.
        if not self.job or not self.k.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.log = (self.root / 'qwen-cpu-runner.log').open('w', encoding='utf-8')
        self.process = subprocess.Popen(args, env=environment, cwd=str(Path(config['executable']).parent),
                                        stdout=self.log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        if not self.k.AssignProcessToJobObject(self.job, w.HANDLE(int(self.process._handle))):
            raise ctypes.WinError(ctypes.get_last_error())
        (self.root / 'qwen-cpu-runner-status.json').write_text(json.dumps({'pid': self.process.pid, 'args': args}, indent=2), encoding='utf-8')
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('Qwen runner failed; see qwen-cpu-runner.log')
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/health', timeout=2) as response:
                    if json.load(response).get('status') == 'ok':
                        return
            except Exception:
                time.sleep(1)
        raise TimeoutError('Qwen runner loading timed out')

    def close(self):
        if self.job:
            self.k.CloseHandle(self.job)
            self.job = None
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=20)
        if self.log:
            self.log.close()


def convert_messages(messages):
    converted, identifiers = [], {}
    for message in messages:
        item = {'role': message['role'], 'content': message['content']}
        if message.get('tool_calls'):
            item['tool_calls'] = []
            for index, call in enumerate(message['tool_calls']):
                identifier = call.get('id') or f'call_{len(converted)}_{index}'
                name = call['function']['name']
                arguments = call['function'].get('arguments', {})
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                item['tool_calls'].append({'id': identifier, 'type': 'function', 'function': {'name': name, 'arguments': arguments}})
                identifiers.setdefault(name, []).append(identifier)
        if item['role'] == 'tool':
            item['tool_call_id'] = identifiers[message['tool_name']].pop(0)
        converted.append(item)
    return converted


def native_chat(messages, tools, port, max_tokens=512, tool_choice=None, greedy_only=False):
    converted = convert_messages(messages)
    body = {'messages': converted, 'tools': tools, 'stream': True, 'max_tokens': max_tokens,
            'temperature': 0, 'seed': 1234, 'chat_template_kwargs': {'enable_thinking': False}}
    if greedy_only:
        body.update(samplers=['temperature'], top_k=1, top_p=1, min_p=0)
    if tool_choice is not None:
        body['tool_choice'] = tool_choice
    request = urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions', json.dumps(body).encode(),
                                     {'Content-Type': 'application/json'})
    content, calls, done, finished, truncated = [], {}, False, False, False
    with DisplayStream() as display, urllib.request.urlopen(request, timeout=300) as response:
        for line in response:
            if not line.startswith(b'data: '):
                continue
            data = line[6:].strip()
            if data == b'[DONE]':
                done = True
                break
            chunk = json.loads(data)
            if chunk.get('error'):
                raise RuntimeError(str(chunk['error']))
            for choice in chunk.get('choices', []):
                delta = choice.get('delta', {})
                if delta.get('content'):
                    content.append(delta['content'])
                    display.feed(delta['content'])
                for fragment in delta.get('tool_calls', []):
                    call = calls.setdefault(fragment['index'], {'id': '', 'type': 'function',
                                           'function': {'name': '', 'arguments': ''}})
                    if fragment.get('id'):
                        call['id'] = fragment['id']
                    function = fragment.get('function', {})
                    call['function']['name'] += function.get('name') or ''
                    call['function']['arguments'] += function.get('arguments') or ''
                finished = finished or choice.get('finish_reason') is not None
                truncated = truncated or choice.get('finish_reason') == 'length'
    if not done or not finished:
        raise RuntimeError('Qwen disconnected before completing its response')
    if calls and truncated:
        raise RuntimeError('Qwen reached the output limit before completing its tool call; no tool was executed.')
    result = {'role': 'assistant', 'content': ''.join(content)}
    if calls:
        result['tool_calls'] = [calls[index] for index in sorted(calls)]
    return result
