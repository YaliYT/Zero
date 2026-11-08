# Reel Studio: סרטוני AI עם Claude Code

פלאגין ל-Claude Code שבונה סרטון אנכי שלם (Reels / TikTok / Shorts) מרעיון אחד.
אתם נותנים נושא או הקלטה, ו-Claude עושה את השאר: כותב תסריט, מקריא אותו בקול המשובט שלכם, מוסיף כתוביות שבהן כל מילה מופיעה בדיוק כשהיא נאמרת, ומוסיף כותרות, מעברים, אנימציות ורינדור ל-MP4.

## ארגז הכלים

| כלי | מה הוא עושה |
| --- | --- |
| **Claude Code** | מנהל את הכול, כותב תסריט וסצנות ומריץ את הכלים |
| **ElevenLabs** | מקריא את התסריט בקול המשובט שלכם |
| **Whisper** (`ivrit-ai/whisper-large-v3-turbo`) | מתמלל הקלטות מילה-מילה, מותאם במיוחד לעברית |
| **HyperFrames** | ממיר HTML לווידאו: סצנות, כותרות, מעברים וכתוביות |
| **Playwright / Chromium** | פותח את הסרטון בדפדפן ובודק אותו פריים-פריים |
| **ffmpeg** | חותך, מחבר, מכווץ וממיר (MOV → MP4) |
| **prompt-motion.com** | מקור לסגנונות אנימציה: מעתיקים פרומפט ו-Claude בונה ממנו סצנה |

## התקנה

ב-Claude Code:

```
/plugin marketplace add YaliYT/Zero
/plugin install reel-studio@zero
```

ואז:

```
/reel-setup
```

הפקודה מתקינה לבד את ffmpeg, Playwright + Chromium, HyperFrames ו-Whisper, ובודקת את ElevenLabs.

דרישות: Node.js 22 ומעלה, Python 3.9 ומעלה. ל-ElevenLabs צריך מפתח API (`ELEVENLABS_API_KEY`) ומנוי בתשלום כדי לשבט קול.

## שימוש

| פקודה | מה היא עושה |
| --- | --- |
| `/reel-setup` | מתקינה את כל הכלים |
| `/reel-voice sample1.mp3 sample2.mp3` | משבטת את הקול שלכם ב-ElevenLabs |
| `/reel הסיפור מאחורי OpenAI` | בונה סרטון שלם מנושא |
| `/reel chapter_01.wav` | בונה סרטון מהקלטה קיימת (גם פרק מספר קולי) |
| `/reel script.txt --no-stops` | בונה מתסריט מוכן בלי לעצור לאישורים |
| `/reel-captions my_video.mov` | מוסיפה כתוביות מילה-מילה לסרטון קיים |
| `/reel-finish compress out/reel.mp4` | מכווצת, ממירה, מחברת או מוסיפה מוזיקה |

אפשר גם פשוט לכתוב "תעשה לי ריל על..." והסקיל `hebrew-ai-reels` ייכנס לפעולה לבד.

הערות כותבים בשפה רגילה, למשל "פי 1.2 מהיר מדי" או "תוסיף כותרת בשנייה 5", ו-Claude מתקן ומרנדר מחדש.

## איך זה עובד

1. **תסריט**: משפטים קצרים, הוק בשנייה הראשונה וקריאה לפעולה בסוף.
2. **קול**: ElevenLabs מחזיר את האודיו יחד עם תזמון של כל מילה. אם יש לכם הקלטה, Whisper בעברית מתמלל אותה.
3. **כתוביות**: `make_captions.py` מחלק את הטקסט ל-2–3 מילים בכל פעם, מימין לשמאל, והמילה שנאמרת באותו רגע נצבעת באדום.
4. **סצנות**: כל קטע בתסריט הוא קובץ HTML עם אנימציות GSAP, בסגנון של כהה, זוהר אדום וכתב לבן כבד.
5. **בדיקה**: `hyperframes check` ו-`snapshot` מצלמים פריימים בדפדפן, ו-Claude מסתכל עליהם לפני המסירה.
6. **רינדור**: HyperFrames מוציא MP4, ו-ffmpeg מכווץ אותו להעלאה.

## קבצים

```
reel-studio/
├── commands/            פקודות /reel, /reel-setup, /reel-voice, /reel-captions, /reel-finish
├── skills/hebrew-ai-reels/   ההוראות המלאות ל-Claude + מדריך סגנון
├── scripts/
│   ├── setup.sh         התקנת הכלים
│   ├── new_reel.sh      פרויקט חדש מהתבנית
│   ├── tts_elevenlabs.py  שיבוט קול והקראה עם תזמון מילים
│   ├── transcribe.py    Whisper עברית → words.json
│   ├── make_captions.py words.json → סצנת כתוביות
│   └── ff.sh            ארגז כלים של ffmpeg
└── templates/reel/      תבנית 1080x1920 (פונט Heebo, רישיון OFL)
```
