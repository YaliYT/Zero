---
description: ffmpeg finishing - convert MOV→MP4, join clips, add music, compress for Instagram/TikTok
argument-hint: <what to do, e.g. "compress out/reel.mp4" or "join a.mp4 b.mp4 + music.mp3">
---

Do the requested finishing work with `bash "${CLAUDE_PLUGIN_ROOT}/scripts/ff.sh"`:

$ARGUMENTS

Commands: `mp4` (any → H.264/AAC, MOV → MP4), `compress`, `concat`, `cut`, `audio`, `mix` (voice + music at -18 dB), `vertical` (to 1080x1920), `frames` (contact sheet). Run `ff.sh` with no arguments for usage.

After writing the output, check it with `ffprobe` (codec, 1080x1920, duration, has audio) and report the path and size.
