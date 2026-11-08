---
description: Install the reel toolbox - ffmpeg, Playwright + Chromium, HyperFrames, Whisper (Hebrew), and check ElevenLabs
argument-hint: "[--no-whisper]"
---

Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh" $ARGUMENTS` and show the person a short summary: what is ready (✓) and what still needs them (!).

If something failed, fix what you can (for example a missing ffmpeg via the system package manager) and run it again. Things only the person can do:
- Set `ELEVENLABS_API_KEY` (elevenlabs.io → Profile → API keys) in their shell profile or in `.claude/settings.local.json` under `env`.
- Install Node 22+ if it is older.
- Optionally run `npx hyperframes skills update` to add HyperFrames' own Claude skills.

Finish with: "Next: `/reel-voice` to clone your voice, then `/reel <topic>`".
