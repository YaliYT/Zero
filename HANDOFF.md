# Reel Studio: המשך עבודה (שורטים של מיינקראפט)

> להמשך במכונה אחרת: לפתוח Claude Code, להדביק את הקובץ הזה בהודעה הראשונה ולכתוב "תמשיך מכאן".

## מה המטרה
פלאגין Reel Studio ל-Claude Code שמייצר סרטוני AI אנכיים. הוא מבוסס על הריל של bennyfarber:
https://www.instagram.com/reel/De4cLc0NSUk/

הכלים: ElevenLabs לקול, Whisper של ivrit-ai לתמלול, HyperFrames להמרת HTML לווידאו, Playwright לבדיקה ו-ffmpeg לעיבוד.

**המטרה עכשיו:** שורטים של מיינקראפט בסגנון הערוץ "שוטיסט":
https://www.youtube.com/@%D7%A9%D7%95%D7%98%D7%99%D7%A1%D7%98/shorts

## הסגנון של הערוץ (נבדק)
- **אורך:** 20–35 שניות.
- **מראה:** רקע לבן, דמות או בלוק במרכז, כתב עברי שחור ועבה מתחת.
- **טון:** קריינות עם עקיצה. בסוף: "תכתבו בתגובות".
- **הסדרות החזקות שלו:**
  - "משפטי מיינקראפט שהם קשים": עד 134K צפיות.
  - "מה הסקין שלך אומר עליך": עד 50K צפיות.
  - חידות "רק 1% יצליחו": עד 61K צפיות.

## הקוד
- **Repo:** ‏`YaliYT/Zero`, ענף `claude/claude-code-mod-video-0jc84j`.
- **הפלאגין:** בתיקייה `reel-studio/`. ה-marketplace נקרא "zero".
- **השורט הראשון:** בתיקייה `shorts/minecraft-blocks/`. כולל `script.txt`, `gen.py`, `index.html`, `compositions/`, `assets/voice.mp3`, `assets/words.json` ו-`out/minecraft-blocks-short.mp4`.

## שורט 1: "מה הבלוק האהוב עליך במיינקראפט אומר עליך?" (מוכן)
- **פלט:** ‏36.5 שניות, 1080x1920, H.264 ו-AAC.
- **קול:** George של ElevenLabs (`JBFqnCBsd6RMkjVDRZzb`), כי עדיין אין קול משובט.
- **בלוקים:** אדמה, יהלום, TNT, אובסידיאן, בדרוק, ובסוף מסך CTA: "סאב לחלק 2".
- **איך הסצנות נבנות:** `gen.py` בונה את `compositions/blocks.html` מתוך `words.json`.
  - כל בלוק הוא קובייה איזומטרית דו-ממדית שמצוירת ב-canvas מטקסטורות פיקסלים מקוריות.
  - הצבעים מוגרלים עם seed קבוע, כך שכל רינדור יוצא זהה. אין שימוש בטקסטורות של Mojang.
  - TNT מתפוצץ על המילה "יבנה", ובדרוק לא זז בכלל.
- **כתוביות:** נוצרות עם `make_captions.py`, עם הפרמטרים `--max-words 3 --bottom 560 --size 100 --color "#111111" --accent "#2e9e2e"`. אחרי זה מוחקים את ה-text-shadow.
- **לקח מהגרסה הראשונה:** קוביות CSS תלת-ממדיות יצאו שבורות ברינדור, ולכן עברנו לציור איזומטרי ב-canvas.

## הפקודות של התהליך (מתוך תיקיית הפרויקט)
```bash
P=<plugin>/scripts   # ~/.claude/plugins/cache/zero/reel-studio/1.0.0/scripts
python $P/tts_elevenlabs.py speak --voice JBFqnCBsd6RMkjVDRZzb --text-file script.txt --out assets/voice.mp3 --words assets/words.json
python gen.py
python $P/make_captions.py assets/words.json --max-words 3 --bottom 560 --size 100 --color "#111111" --accent "#2e9e2e" --font-file ""
npx hyperframes check --json
npx hyperframes snapshot --at 0,5,11,17,29,34.8
npx hyperframes render -o out/reel.mp4
bash $P/ff.sh compress out/reel.mp4 out/<name>.mp4
```
אחרי שינוי באורך הקריינות צריך לעדכן את `data-duration` ב-`index.html`. הערך הנכון הוא ה-END ש-`gen.py` מדפיס.

## התקנה במכונה החדשה
```
/plugin marketplace add YaliYT/Zero#claude/claude-code-mod-video-0jc84j
/plugin install reel-studio@zero
/reel-setup
git clone -b claude/claude-code-mod-video-0jc84j https://github.com/YaliYT/Zero.git
```
- **דרישות:** Node 22 ומעלה, Python 3.9 ומעלה, ffmpeg.
- **מפתח ElevenLabs:** צריך להגדיר מחדש `ELEVENLABS_API_KEY` במכונה החדשה. המפתח לא נמצא ב-repo.
  - ב-Windows: `setx ELEVENLABS_API_KEY "..."`.
  - ב-Mac או Linux: להוסיף `export` לקובץ shell rc.

## השלבים הבאים
1. לקבל הערות על שורט 1 ולתקן.
2. חלק 2 עם בלוקים אחרים, למשל חול, קרח, ספוג, קקטוס ומגמה.
3. שורטים מהסדרות האחרות: משפטי מיינקראפט וחידות 1%.
4. שיבוט הקול של המשתמש עם `/reel-voice`, ואז קריינות מחדש.
