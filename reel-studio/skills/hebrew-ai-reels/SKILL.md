---
name: hebrew-ai-reels
description: Make a complete vertical AI video (Instagram Reel / TikTok / Shorts) from a topic, a script or a voice recording, end to end, inside Claude Code - script, voice (ElevenLabs cloned voice or the person's recording), word-by-word Hebrew captions (Whisper ivrit-ai), titles, transitions and motion graphics in HyperFrames, review with Playwright/Chrome, and finishing with ffmpeg. Use whenever the person asks for a reel, short, TikTok, a "video with AI", captions synced to speech, a voiceover in their cloned voice, or to turn a recording/audiobook chapter into a video. Hebrew-first, works in any language.
---

# Hebrew AI Reels

The pipeline from the reel this plugin is based on: **Claude Code runs every tool, the person only gives the idea and notes.**

| Tool | Job in the pipeline |
| --- | --- |
| Claude Code | writes the script, the scenes, runs everything |
| ElevenLabs | the person's cloned voice reads the script (`scripts/tts_elevenlabs.py`) |
| Whisper (`ivrit-ai/whisper-large-v3-turbo-ct2`) | transcribes a recording word by word, tuned for Hebrew (`scripts/transcribe.py`) |
| HyperFrames | HTML → MP4: scenes, titles, transitions, captions (`npx hyperframes`) |
| Playwright / Chrome | opens the composition and steps through frames for review (`hyperframes check/snapshot` drive Chrome) |
| ffmpeg | cuts, joins, mixes, compresses, MOV → MP4 (`scripts/ff.sh`) |
| prompt-motion.com | style references: the person picks an animation there and pastes its prompt; adapt it into a scene |

`${CLAUDE_PLUGIN_ROOT}` is this plugin's folder; scripts live in `${CLAUDE_PLUGIN_ROOT}/scripts/`.

## 0. Tools ready?

If `npx hyperframes --version`, `ffmpeg -version` or `python3 -c "import faster_whisper"` fails, run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh` (or tell the person to run `/reel-setup`). ElevenLabs needs `ELEVENLABS_API_KEY`; without it, offer the person's own recording instead.

## 1. The script

- Ask only what is missing: topic, length (default 45–60 s), language (default Hebrew), voice source (cloned voice / their recording / an audio file they already have, e.g. an audiobook chapter `chapter_01.wav`).
- Write it for the ear: short sentences, ~2.3 Hebrew words per second, a hook in the first sentence (a number, a result, a question), one idea per beat, a call to action at the end (e.g. "תגיבו X ואשלח לכם בפרטי").
- Save `script.txt`. Show it and wait for approval unless the person said to run without stops.

## 2. Project

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/new_reel.sh <name>      # 1080x1920, dark/red look, Heebo font, local GSAP
cd <name>
```

## 3. Voice + word timings

**Cloned voice (ElevenLabs):**
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/tts_elevenlabs.py speak --text-file script.txt --out assets/voice.mp3 --words assets/words.json
```
Uses `ELEVENLABS_VOICE_ID` (or `--voice`). The `/with-timestamps` endpoint returns exact word timings, so no transcription is needed. `--speed 0.9` if the person says it is too fast ("פי 1.2 מהיר מדי").

**The person's recording (or any audio/video):**
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/ff.sh audio recording.mov assets/voice.wav   # any format -> 16 kHz WAV
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/transcribe.py assets/voice.wav --out assets/words.json
```
Read the printed transcript against the script and fix misheard words in `words.json` by position (keep the timings). Long recordings: cut first with `ff.sh cut`.

The video's length = last word end + ~0.6 s. Set the root `data-duration`, the backdrop's and the `<audio id="voice">` (uncomment it in `index.html`) to that.

## 4. Captions - every word on time

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/make_captions.py assets/words.json --max-words 3
```
It writes `compositions/captions.html` (RTL auto-detected, current word in the accent colour) and prints the host `<div>`: paste it in `index.html` in place of the captions comment. Options: `--max-words` 2–3 energetic / 3–5 calm, `--bottom` px from the bottom, `--size`, `--accent`.

## 5. Scenes - titles, transitions, motion

Plan one scene per beat of the script (a beat every 2–4 s; shots of 1–2 s for a reel). For each, copy `compositions/hook.html` to `compositions/<beat>.html`, rename every id (`hook-` → `<beat>-`, `data-composition-id`, `window.__timelines[...]`) and add a host in `index.html` with matching `id` / `data-composition-id` and its `data-start`/`data-duration` taken from the words it covers.

The look from the reel (see `references/style.md`): near-black ground with a red glow, white heavy Hebrew type, one red accent word per line, pill labels, big numbers that count up, app-icon "toolbox" grids, terminal windows typing commands, phone mockups, waveforms. Animate with GSAP `fromTo` only; punchy eases (`back.out`, `power4.out`), 0.15–0.35 s entrances.

- A style from **prompt-motion.com**: when the person pastes a prompt from there, rebuild that animation as a HyperFrames scene in this look.
- HyperFrames has ready-made blocks: `npx hyperframes catalog --json` (transitions, caption styles, titles). Install one with `npx hyperframes add <name>` before hand-writing it.
- Their own media (screen recordings, photos, logo): put it in `assets/media/` and use `<video muted class="clip">` / `<img>`. Convert MOV first: `ff.sh mp4 in.mov`.
- Music: an `<audio id="music" class="clip" data-volume="0.15">`, or mix at the end with `ff.sh mix`.
- If HyperFrames' own skills are installed (`/hyperframes`), follow its contract; key rules are in `references/style.md`.

## 6. Review (Playwright / Chrome)

```bash
npx hyperframes check --json          # contract, layout, contrast, first frame
npx hyperframes snapshot --at 0.5,3,8  # stills you then look at
```
Fix every error. Look at the stills yourself: text inside 168–1330 px from the top, nothing under the right-hand rail, frame 0 already shows the hook (it is the thumbnail). Offer the live preview: `npx hyperframes preview`.

## 7. Render + finish

```bash
npx hyperframes render -o out/reel.mp4
bash ${CLAUDE_PLUGIN_ROOT}/scripts/ff.sh compress out/reel.mp4 out/reel_ig.mp4   # upload-ready
bash ${CLAUDE_PLUGIN_ROOT}/scripts/ff.sh frames out/reel_ig.mp4 out/review 2      # contact sheet to check
```
Look at the contact sheet before saying it is done. Report the file path, length, and one line on what to tweak next.

## Notes from the person = edits

Treat feedback like "פי 1.2 מהיר מדי", "עוד כותרת פה", "הצבע של המילה" as precise edits: change only that, re-check, re-render. Keep `script.txt`, `words.json` and the scenes in sync.

## Gotchas

- GSAP is loaded from `assets/vendor/gsap.min.js`; never switch back to a CDN (renders break offline).
- Hebrew text needs a Hebrew font: Heebo is in `assets/fonts/` (OFL). Another font = `@font-face` to a file in `assets/fonts/`.
- Mixed Hebrew/English lines: put English inside `<span dir="ltr">` if punctuation lands on the wrong side.
- First Whisper run downloads ~1.6 GB; on a laptop without GPU, a 1-minute clip takes ~1–2 minutes.
- Never `play()`/`seek` media or use `Date.now()` / `Math.random()` in scenes: rendering seeks frame by frame.
