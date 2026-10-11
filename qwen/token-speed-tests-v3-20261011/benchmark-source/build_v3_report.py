import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / 'v3-delivery'
OUT.mkdir(exist_ok=True)
reference = json.loads((BASE / 'run-token500-v2-physical12-draft3' / 'results.json').read_text(encoding='utf-8'))
ref_rows = reference['rows']
ref_ms = sum(r['timings']['predicted_ms'] for r in ref_rows)
summaries = []
for folder in sorted(BASE.glob('run-token500-v3-*')):
    p = folder / 'results.json'
    if not p.exists():
        continue
    data = json.loads(p.read_text(encoding='utf-8'))
    if 'aborted' not in data:
        continue  # A still-running benchmark is not a completed result.
    rows = data['rows']
    complete = len(rows) == 6 and not data.get('aborted') and not data.get('error')
    gpu_free = [s['gpu']['free_mib'] for s in data.get('samples', []) if 'gpu' in s]
    milliseconds = sum(r['timings']['predicted_ms'] for r in rows)
    summaries.append(dict(
        name=folder.name, complete=complete, rows=len(rows),
        generation_seconds=milliseconds / 1000,
        same_outputs_as_reference=complete and [r['content'] for r in rows] == [r['content'] for r in ref_rows],
        speed_change_vs_prior_reference_percent=(ref_ms / milliseconds - 1) * 100 if complete else None,
        load_seconds=data.get('load_seconds'), peak_ram_percent=data.get('peak_ram_percent'),
        min_gpu_free_mib=min(gpu_free) if gpu_free else None,
        first_token_seconds=[r['first_token_seconds'] for r in rows],
        token_rates=[r['timings']['predicted_per_second'] for r in rows],
        stop_events=[e for e in data.get('events', []) if 'abort' in e],
        error=data.get('error'), settings=data['settings'],
        raw_sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
control = next((r for r in summaries if r['name'] == 'run-token500-v3-installed-control' and r['complete']), None)
summary = dict(reference='run-token500-v2-physical12-draft3',
               reference_generation_seconds=ref_ms / 1000, runs=summaries,
               current_control_generation_seconds=control['generation_seconds'] if control else None,
               target_speed_increase_percent=500, target_achieved=False)
(OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
lines = [
    '# Qwen — סבב בדיקות נוסף, 11.10.2026', '',
    'המודל נשמר: Qwen3.8 27.32B Q4_K_M, אותו GGUF, Context 2048. יעד תוספת 500% (פי 6) טרם הושג. השיפור שהותקן בסבב v2 היה 35.03% במדגם המקביל שלו; בדיקות הסבב הנוכחי אינן תחליף למדידת בסיס חדשה.', '',
    'כל ניסוי הפעיל עותק מודל יחיד. עצירה ב־88% RAM, שינוי בדיווח AC או תקרת זמן; בניסויים המסומנים במידע GPU נוספה עצירה לפי זיכרון GPU פנוי. ניקוי Firefox בתחילת הבדיקה אושר על ידי המשתמש. פלטים הם יצירה אמיתית, 6 בקשות של 32 טוקנים: קבצים, קוד ועברית, כל אחד פעמיים. המגבלה חותכת תשובות ארוכות ולכן זו בדיקת קצב, לא איכות תשובה מלאה.', '',
    '| ניסוי | בקשות שהושלמו | זמן יצירה, שניות | שיא RAM | הסתיים ללא עצירה | פלטים זהים לבסיס v2 |',
    '|---|---:|---:|---:|---|---|']
for r in summaries:
    lines.append(f"| {r['name'].removeprefix('run-token500-v3-')} | {r['rows']} | {r['generation_seconds']:.2f} | {r['peak_ram_percent']:.2f}% | {'כן' if r['complete'] else 'לא'} | {'כן' if r['same_outputs_as_reference'] else ('לא' if r['complete'] else 'לא נבדק במלואו')} |")
lines += ['', f"זמן היצירה של פרופיל v2 להשוואה: {ref_ms/1000:.2f} שניות. זו מדידה מסבב קודם, במחשב פעיל; הבדלים קטנים אינם מוכיחים יתרון ללא חזרה מקבילה. אין להסיק ממדגם שנקטע מהירות לכל שש הבקשות.", '',
          '## מדידת בקרה באותו סבב', '']
if control:
    lines += [f"הפרופיל המותקן הושלם גם בסוף הסבב: {control['generation_seconds']:.2f} שניות יצירה, עם כל ששת הפלטים זהים למדידת v2. מדידה זו אינה זוג חדש של בסיס ישן/חדש לצורך עדכון נתון השיפור של 35.03%.", '',
              'טוקנים לשנייה, לפי סדר קבצים/קבצים/קוד/קוד/עברית/עברית: '+', '.join(f'{x:.2f}' for x in control['token_rates'])+'.', '',
              'טוקן ראשון בשניות באותו סדר: '+', '.join(f'{x:.2f}' for x in control['first_token_seconds'])+'.', '',
              f"מדידות הטוקן הראשון הן אחרי טעינת המודל. טעינת מדידת הבקרה לקחה {control['load_seconds']:.2f} שניות נוספות. הבקשה השנייה בכל זוג משתמשת גם במטמון הקלט; אין להציג אותה כבקשה חדשה אחרי הפעלה קרה.", '',
              'לוג הטעינה אישר 9/66 שכבות שהועברו ל־GPU, כולל output: משקלים של 13,126.95 MiB ב־CPU ושל 2,894.51 MiB ב־GPU, מעבר למטמונים ולזיכרון החישוב. לכן רוב המשקלים עדיין מעובדים דרך CPU/RAM. השיא שנמדד אינו מעיד שכל המודל רץ ב־GPU.', '',
              'הניסויים אינם אקראיים או סימולטניים. על סמך מדגם זה לא נמצא יתרון גדול ועקבי שמצדיק החלפת הפרופיל המותקן. מבחני הסבב הם מבחני טוקנים; מבחן יצירת קובץ אמיתי ובדיקות הרגרסיה מתועדים בסבב v2.', '']
else:
    lines += ['מדידת הבקרה לא הושלמה; אין להסיק ממנה מהירות מלאה.', '']
lines += ['## עצירות', '']
for r in summaries:
    if not r['complete']:
        lines.append(f"- {r['name']}: {json.dumps(r['stop_events'], ensure_ascii=False)}; error={r['error']}")
lines += ['', '## חשמל ומקורות', '',
    'המשתמש דיווח על מטען מקורי בחיבור העגול ועל סמל טעינה רציף. Windows תיעד מעברים בדיווח AC, ולעיתים גם מעבר בין Performance ל־Silent. בקרי הסוללה/AC מציגים Status OK ו־ConfigManagerErrorCode 0, ולא זוהו שגיאות ACPI/WHEA בבדיקה המצומצמת. זה אינו מוכיח תקינות חומרה ואינו מוכיח ניתוק פיזי של המטען. BIOS שנקרא: FX507ZC4.312. לא הוחלפו דרייברים, לא עודכן BIOS ולא בוצע איפוס EC.', '',
    '[הנחיות llama.cpp לבדיקת GPU ומספר Threads](https://github.com/ggml-org/llama.cpp/blob/master/docs/development/token_generation_performance_tips.md).', '',
    '[ASUS: אבחון בעיות סוללה וטעינה](https://www.asus.com/support/faq/1012793/). אבחון MyASUS הוא צעד אפשרי לבירור דיווח החשמל; אין כאן אבחנה של תקלה במטען.', '',
    '[Microsoft: משמעות ACLineStatus](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-system_power_status).', '',
    '[NVIDIA: קריאת זיכרון NVML](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html). used ב־NVML v1 כולל זיכרון reserved; תנאי העצירה משתמש ב־free, שהושווה גם ל־nvidia-smi.', '',
    'קוד הניסויים, hashes, לוגים, דגימות RAM/חשמל ופלטים נמצאים בתיקיית token-speed-tests-v3-20261011. שינוי מיקום output.weight נבדק בקוד ניסוי מבודד. אף פרופיל ניסוי מסבב זה לא הותקן אוטומטית.']
(OUT / 'Qwen-Token-Speed-Report-v3.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps([{k:v for k,v in r.items() if k in ('name','complete','rows','generation_seconds','peak_ram_percent','same_outputs_as_reference','stop_events')} for r in summaries], ensure_ascii=False, indent=2))
