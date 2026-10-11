"""Stage only the selected MTP confidence option; trial GPU backends stay isolated."""
import hashlib
import json
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parent
ROOT = Path('C:/Users/nagor/Downloads/Qwen-Agent-work')
DELIVERY = BASE/'v4-delivery'
APP = DELIVERY/'app'
APP.mkdir(parents=True,exist_ok=True)
manifest = json.loads((ROOT/'token-speed-tests-v2-20261011/installation.json').read_text(encoding='utf-8-sig'))
for name,expected in manifest['files'].items():
    if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:
        raise RuntimeError('Installed source changed during tests: '+name)
for p in ROOT.glob('*.py'):
    shutil.copy2(p,APP/p.name)
shutil.copytree(ROOT/'vendor',APP/'vendor',dirs_exist_ok=True)
for name in ('qwen-agent-settings.json','qwen-cpu-runner-paths.json','Run-Offline-Tests.ps1'):
    shutil.copy2(ROOT/name,APP/name)
(APP/'work').mkdir(exist_ok=True)
for p in (ROOT/'work').glob('test*.py'):
    shutil.copy2(p,APP/'work'/p.name)
runner = (APP/'qwen_cpu_runner.py').read_text(encoding='utf-8')
anchor = "        if settings.get('native_op_offload') is False:\n            args.append('--no-op-offload')\n"
if runner.count(anchor)!=1:
    raise RuntimeError('Expected runner insertion anchor differs')
runner=runner.replace(anchor,anchor+"""        if 'native_draft_probability_min' in settings:
            probability = float(settings['native_draft_probability_min'])
            if not 0 <= probability <= 1:
                raise ValueError('Invalid draft probability threshold')
            args += ['--spec-draft-p-min', str(probability)]
""")
(APP/'qwen_cpu_runner.py').write_text(runner,encoding='utf-8')
settings=json.loads((APP/'qwen-agent-settings.json').read_text(encoding='utf-8-sig'))
settings.update(draft_num_predict=4,native_draft_probability_min=0.3)
(APP/'qwen-agent-settings.json').write_text(json.dumps(settings,indent=2)+'\n',encoding='utf-8')
names=('qwen_cpu_runner.py','qwen-agent-settings.json')
before={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
after={name:hashlib.sha256((APP/name).read_bytes()).hexdigest() for name in names}
(DELIVERY/'before-sha256.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
(DELIVERY/'tested-files-sha256.json').write_text(json.dumps(after,indent=2),encoding='utf-8')
print(json.dumps(dict(staged=str(APP),files=names,settings_changes=dict(draft_num_predict=4,native_draft_probability_min=0.3))))
