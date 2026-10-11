"""Save completed measurements and tested installation without touching model or user state."""
import hashlib
import json
from pathlib import Path
import shutil

BASE=Path(__file__).resolve().parent
DELIVERY=BASE/'v4-delivery'
TARGET=Path('C:/Users/nagor/Downloads/Qwen-Agent-work')
OUT=TARGET/'token-speed-tests-v4-20261011'
OUT.mkdir(exist_ok=False)
installation=json.loads((DELIVERY/'installation.json').read_text(encoding='utf-8-sig'))
for name,digest in installation['files'].items():
    if hashlib.sha256((TARGET/name).read_bytes()).hexdigest()!=digest:
        raise RuntimeError('Installed hash differs: '+name)
for folder in sorted(BASE.glob('run-token500-v4-*')):
    data=json.loads((folder/'results.json').read_text(encoding='utf-8'))
    if 'aborted' not in data:
        raise RuntimeError('Cannot archive unfinished run: '+folder.name)
    shutil.copytree(folder,OUT/folder.name)
shutil.copytree(BASE/'run-entrypoint-v4',OUT/'run-entrypoint-v4')
shutil.copytree(DELIVERY/'app/verification/token500-v4-verified',OUT/'offline-tests')
tested=OUT/'tested-change'
tested.mkdir()
for name in installation['changed_files']:
    shutil.copy2(DELIVERY/'app'/name,tested/name)
sources=OUT/'benchmark-source'
sources.mkdir()
for name in ('probe.py','gpu_probe.py','prepare_v4.py','verify_launch_v4.py','build_v4_report.py',
             'save_v4_evidence.py','resume_v4.py','install-v4.ps1','v4-original-settings.json',
             'runtime-b11552-paths.json','runtime-b11552-mixed-paths.json','vulkan-download.json'):
    shutil.copy2(BASE/name,sources/name)
app_sources=sources/'experimental-app'
app_sources.mkdir()
for p in (BASE/'app').glob('*.py'):
    shutil.copy2(p,app_sources/p.name)
for name in ('qwen-agent-settings.json','qwen-cpu-runner-paths.json'):
    shutil.copy2(BASE/'app'/name,app_sources/name)
for name in ('speculative-b11552.cpp','ggml-vulkan-b11552.cpp'):
    shutil.copy2(BASE/name,sources/name)
for p in DELIVERY.glob('*.json'):
    shutil.copy2(p,OUT/p.name)
for name,source in [('Qwen-Token-Speed-Report-v4.md',DELIVERY/'Qwen-Token-Speed-Report-v4.md'),
                    ('Restore-Token-Speed-v4.ps1',BASE/'Restore-Token-Speed-v4.ps1')]:
    shutil.copy2(source,TARGET/name)
manifest={str(p.relative_to(OUT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
          for p in OUT.rglob('*') if p.is_file()}
(OUT/'evidence-sha256.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
for name,digest in manifest.items():
    if hashlib.sha256((OUT/name).read_bytes()).hexdigest()!=digest:
        raise RuntimeError('Archived hash differs: '+name)
print(json.dumps(dict(verified=True,evidence=str(OUT),files=len(manifest),report=str(TARGET/'Qwen-Token-Speed-Report-v4.md'))))
