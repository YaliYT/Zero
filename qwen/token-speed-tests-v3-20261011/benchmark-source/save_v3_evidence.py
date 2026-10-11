import hashlib
import json
from pathlib import Path
import shutil

BASE = Path(__file__).resolve().parent
TARGET = Path('C:/Users/nagor/Downloads/Qwen-Agent-work')
OUT = TARGET/'token-speed-tests-v3-20261011'
OUT.mkdir(exist_ok=False)
for folder in sorted(BASE.glob('run-token500-v3-*')):
    data = json.loads((folder/'results.json').read_text(encoding='utf-8'))
    if 'aborted' not in data:
        raise RuntimeError('Cannot package an unfinished benchmark: '+folder.name)
    shutil.copytree(folder,OUT/folder.name)
shutil.copytree(BASE/'run-token500-v2-physical12-draft3',OUT/'reference-v2-physical12-draft3')
sources = OUT/'benchmark-source'
sources.mkdir()
for name in ('probe.py','gpu_probe.py','build_v3_report.py','resume_v3.py','save_v3_evidence.py'):
    shutil.copy2(BASE/name,sources/name)
app_sources = sources/'app'
app_sources.mkdir()
for p in (BASE/'app').glob('*.py'):
    shutil.copy2(p,app_sources/p.name)
for name in ('qwen-agent-settings.json','qwen-cpu-runner-paths.json'):
    shutil.copy2(BASE/'app'/name,app_sources/name)
shutil.copy2(BASE/'runtime-b11552-paths.json',sources/'runtime-b11552-paths.json')
for name in ('power-followup.json','power-v3-diagnostics.json'):
    shutil.copy2(BASE/name,OUT/name)
for p in (BASE/'v3-delivery').glob('*.json'):
    shutil.copy2(p,OUT/p.name)
shutil.copy2(BASE/'v3-delivery/Qwen-Token-Speed-Report-v3.md',TARGET/'Qwen-Token-Speed-Report-v3.md')
manifest={str(p.relative_to(OUT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
          for p in OUT.rglob('*') if p.is_file()}
(OUT/'evidence-sha256.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
for name,digest in manifest.items():
    if hashlib.sha256((OUT/name).read_bytes()).hexdigest()!=digest:
        raise RuntimeError('Saved evidence hash differs: '+name)
print(json.dumps(dict(evidence=str(OUT),report=str(TARGET/'Qwen-Token-Speed-Report-v3.md'),
                      file_count=len(manifest),verified=True)))
