---
description: Clone your voice in ElevenLabs from recordings, so reels are read in your voice
argument-hint: <recording files...> [--name "My voice"]
---

Clone the person's voice with ElevenLabs.

Files / options: $ARGUMENTS

1. Check `ELEVENLABS_API_KEY` is set; if not, explain how to get it and stop.
2. If no files were given, ask for 1–3 clean recordings (1–3 minutes total, no music, one speaker). Video files are fine: extract audio first with `bash "${CLAUDE_PLUGIN_ROOT}/scripts/ff.sh" audio <file> <file>.wav`.
3. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tts_elevenlabs.py" clone --name "<name>" <files...>`; it prints the new `voice_id`.
4. Test it: write one Hebrew sentence to a temp `test.txt` and run `tts_elevenlabs.py speak --voice <id> --text-file test.txt --out voice_test.mp3 --words ''`. Tell the person where the file is so they can listen.
5. Tell them to save `ELEVENLABS_VOICE_ID=<id>` (shell profile or `.claude/settings.local.json` → `env`). Do not write secrets into tracked files.

Note: Instant Voice Cloning needs a paid ElevenLabs plan (Starter or above).
