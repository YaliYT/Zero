"""Summarize measured runs; never substitute cache hits or shorter answers for token speed."""
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE/'v4-delivery'
raw = {}
runs = []
for folder in sorted(BASE.glob('run-token500-v4-*')):
    path = folder/'results.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    if 'aborted' not in data:
        raise RuntimeError('Unfinished run: '+folder.name)
    name = folder.name.removeprefix('run-token500-v4-')
    raw[name] = data
    rows = data['rows']
    free = [s['gpu']['free_mib'] for s in data.get('samples',[]) if 'gpu' in s]
    runs.append(dict(name=name, complete=len(rows)==6 and not data['aborted'] and not data.get('error'),
                     rows=len(rows), generation_seconds=sum(r['timings']['predicted_ms'] for r in rows)/1000,
                     load_seconds=data.get('load_seconds'), peak_ram_percent=data.get('peak_ram_percent'),
                     min_gpu_free_mib=min(free) if free else None,
                     token_rates=[r['timings']['predicted_per_second'] for r in rows],
                     first_token_seconds=[r['first_token_seconds'] for r in rows],
                     proposed_tokens=sum(r['timings'].get('draft_n',0) for r in rows),
                     accepted_draft_tokens=sum(r['timings'].get('draft_n_accepted',0) for r in rows),
                     settings=data['settings'], raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
reference=[r['content'] for r in raw['original-control']['rows']]
for run in runs:
    run['same_outputs_as_original']=run['complete'] and [r['content'] for r in raw[run['name']]['rows']]==reference
by_name={r['name']:r for r in runs}
selected=by_name['candidate-repeat']
for name in ('original-control','installed-control','confidence4','candidate-repeat'):
    if not by_name[name]['same_outputs_as_original']:
        raise RuntimeError('Selected comparison did not complete with identical outputs: '+name)
original=by_name['original-control']
installed=by_name['installed-control']
selected['speed_increase_vs_original_percent']=(original['generation_seconds']/selected['generation_seconds']-1)*100
selected['speed_increase_vs_installed_percent']=(installed['generation_seconds']/selected['generation_seconds']-1)*100
offline=json.loads((OUT/'app/verification/token500-v4-verified/offline-tests.json').read_text(encoding='utf-8-sig'))
entry=json.loads((BASE/'run-entrypoint-v4/results.json').read_text(encoding='utf-8'))
if not offline['all_passed'] or not entry['verified']:
    raise RuntimeError('Candidate verification failed')
summary=dict(target_speed_increase_percent=500,target_achieved=False,selected=selected,
             original_control=original,installed_control=installed,runs=runs,
             offline_tests=offline,real_entrypoint={k:v for k,v in entry.items() if k not in ('samples','settings')})
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# Qwen — שיפור MTP ובדיקות GPU, 11.10.2026','',
       f"יעד תוספת 500% (פי 6) לא הושג. במדידה חדשה עם אותו מודל ואותם ששת הפלטים: {original['generation_seconds']:.2f} → {selected['generation_seconds']:.2f} שניות יצירה, שיפור קצב של {selected['speed_increase_vs_original_percent']:.2f}% מול הפרופיל המקורי. מול הפרופיל שכבר הותקן: {installed['generation_seconds']:.2f} → {selected['generation_seconds']:.2f}, שיפור נוסף של {selected['speed_increase_vs_installed_percent']:.2f}%. אין לחבר אחוזים מסבבים שונים.", '',
       'Qwen3.8 27.32B Q4_K_M, אותו GGUF בגודל 16,810,714,464 בתים, Context 2048. i5-12500H, ‏32GB DDR4 3200, ‏RTX 3050 Laptop ‏4GiB וכרטיס Intel Iris Xe מובנה. המודל וההקשר נשמרו.', '',
       '## השינוי שנבחר','',
       'טיוטת MTP עד 4 טוקנים, עם --spec-draft-p-min 0.3: הטיוטה נפסקת כאשר הביטחון נמוך במקום להמשיך לייצר טוקנים שהמודל הראשי צפוי לדחות. קוד השרת מאמת את הטיוטה. הפרופיל המקורי הציע 243 טוקנים וקיבל 121; הפרופיל המותקן הציע 189 וקיבל 121; המועמד הציע 179 וקיבל 123. מספר טוקני התשובה זהה: 192 בכל הרצה.', '',
       'שני ניסויים של הפרופיל הנבחר ארכו 47.91 ו־47.86 שניות יצירה. רק qwen_cpu_runner.py והגדרות האגנט משתנים. זמן הריצה b11552, הכלים, הרשאותיהם, הזיכרונות ומשקלי המודל נשמרים. אפשר לשחזר את שני הקבצים עם Restore-Token-Speed-v4.ps1 אחרי סגירת האגנט.', '',
       '## מדידות','',
       '| ניסוי | בקשות | זמן יצירה, שניות | שיא RAM | פלטים זהים למקור |',
       '|---|---:|---:|---:|---|']
for r in runs:
    lines.append(f"| {r['name']} | {r['rows']} | {r['generation_seconds']:.2f} | {r['peak_ram_percent']:.2f}% | {'כן' if r['same_outputs_as_original'] else 'לא'} |")
lines += ['', '| בקשה | מקור: טוקנים/שנייה | מותקן קודם | פרופיל נבחר | מקור: טוקן ראשון | נבחר: טוקן ראשון |',
          '|---|---:|---:|---:|---:|---:|']
for i,r in enumerate(raw['candidate-repeat']['rows']):
    lines.append(f"| {i+1}: {r['scenario']} | {original['token_rates'][i]:.2f} | {installed['token_rates'][i]:.2f} | {selected['token_rates'][i]:.2f} | {original['first_token_seconds'][i]:.2f} שנ׳ | {selected['first_token_seconds'][i]:.2f} שנ׳ |")
lines += ['', f"טעינת המודל במדידת הפרופיל הנבחר: {selected['load_seconds']:.2f} שניות נוספות. זמן טוקן ראשון בטבלה מתחיל אחרי טעינת המודל. הבקשה השנייה בכל זוג משתמשת במטמון הקלט. שש תשובות של 32 טוקנים הן בדיקת קצב; תשובות ארוכות נחתכות ולכן אין זו הערכת איכות מלאה.", '',
          'אלה הרצות עוקבות במחשב פעיל, ללא אקראיות או רווח סמך. RAM רקע ירד מכ־40% לכ־32% במהלך הסבב בלי סגירת יישומים על ידינו. שתי הבקרות והחזרה הנבחרת בוצעו אחרי הירידה, בתנאי רקע דומים. אין להסיק השוואה מדויקת בין ההרצות המוקדמות למאוחרות.', '',
          '## תוצאות החלופות','',
          'זמן ריצה Vulkan רשמי מאותה גרסה נבדק בבידוד. פיצול כל 66 השכבות בין Intel Iris Xe ל־NVIDIA השאיר כ־682 MiB משקלים ב־CPU, כ־12,926 MiB ב־Intel וכ־2,413 MiB ב־NVIDIA, אך לא נתן האצה כוללת עקבית לעומת CUDA חלקי. הטיוטה נשארה ב־CUDA. בניסוי mixed-draft8 גם פלט העברית השתנה ולכן הוא לא נבחר.', '',
          'ngram-cache לא הציע אפילו טוקן אחד במדגם לפי לוג השרת; אין לייחס לו האצה. MTP ארוך 8 עם סף 0.6 לא הוביל לתוצאה הכוללת הטובה ביותר. בפרופיל הנבחר רוב המשקלים עדיין ב־CPU: ‏13,126.95 MiB מול 2,894.51 MiB ב־GPU. ניקוי RAM או העברת נתונים לדיסק אינם תחליף לרוחב פס של RAM/VRAM ואינם מוכיחים יצירה מהירה יותר.', '',
          '## אימות','',
          f"13/13 בדיקות רגרסיה עברו. נקודת ההפעלה האמיתית יצרה hello.txt עם בדיוק b'hello\\n', אימתה את הכתיבה והחזירה תשובה בעברית; {entry['seconds_including_model_load']:.2f} שניות כולל טעינת מודל. זו בדיקת תפקוד ללא זוג בסיס חדש למשימה המלאה; אין להציג אותה כאחוז האצה של משימות שלמות.", '',
          'כל ניסוי הפעיל מודל אחד, עם עצירה ב־88% RAM, פחות מ־64 MiB זיכרון NVIDIA פנוי, שינוי בדיווח החשמל או תקרת 180 שניות. לא נדרשה עצירה בסבב v4. החשמל היה יציב לפי Windows בבדיקות הסבב הזה; מצב Performance הופעל רק על AC. לא שונו BIOS, דרייברים או שירותי ASUS.', '',
          '## מקורות רשמיים','',
          '- [llama.cpp b11552](https://github.com/ggml-org/llama.cpp/releases/tag/b11552)',
          '- [מימוש MTP וסף הביטחון בגרסה שנבדקה](https://github.com/ggml-org/llama.cpp/blob/b11552/common/speculative.cpp)',
          '- [הגדרות ספקולציה ומכשירי GPU](https://github.com/ggml-org/llama.cpp/blob/b11552/common/arg.cpp)',
          '- [מימוש Vulkan בגרסה שנבדקה](https://github.com/ggml-org/llama.cpp/blob/b11552/ggml/src/ggml-vulkan/ggml-vulkan.cpp)', '',
          'קוד ניסוי מבודד, מדידות גולמיות, לוגים, דגימות זיכרון/חשמל, SHA256, בדיקות ואימות התקנה נמצאים ב־token-speed-tests-v4-20261011. הקוד המורחב לבדיקת Vulkan ו־ngram אינו מותקן באגנט. יעד פי 6 נשאר לא מושג; אין כאן הבטחה ששינוי תוכנה נוסף ישיג אותו במחשב הזה.']
(OUT/'Qwen-Token-Speed-Report-v4.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in selected.items() if k in ('generation_seconds','speed_increase_vs_original_percent','speed_increase_vs_installed_percent')},indent=2))
