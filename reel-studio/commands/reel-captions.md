---
description: Add word-by-word Hebrew captions to an existing video (Whisper ivrit-ai + HyperFrames)
argument-hint: <video file> [--max-words 3]
---

Burn word-synced captions onto an existing video, in the reel's caption style.

Input: $ARGUMENTS

1. Make a project: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/new_reel.sh" <video-name>-captions` and `cd` into it. Remove the backdrop and hook hosts from `index.html`.
2. Convert the video if needed (`ff.sh mp4` for MOV, `ff.sh vertical` if it is not 9:16) into `assets/media/source.mp4`.
3. `ff.sh audio assets/media/source.mp4 assets/voice.wav`, then `transcribe.py assets/voice.wav --out assets/words.json`. Read the transcript and fix misheard words by position.
4. In `index.html` add `<video id="src" class="clip" src="assets/media/source.mp4" data-start="0" data-duration="<len>" data-track-index="0" data-has-audio="true" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover"></video>` and set the root `data-duration` to the video's length (`ffprobe`).
5. `make_captions.py assets/words.json` (+ any options given) and paste the printed host into `index.html`.
6. `npx hyperframes check --json`, fix, `npx hyperframes render -o out/captioned.mp4`, then `ff.sh frames` and look at the sheet before delivering.

Scripts are in `${CLAUDE_PLUGIN_ROOT}/scripts/`.
