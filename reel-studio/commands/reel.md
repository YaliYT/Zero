---
description: Make a full vertical AI reel (script → voice → word-by-word captions → scenes → MP4)
argument-hint: <topic, or path to a recording/script> [--no-stops]
---

Make a reel with the `hebrew-ai-reels` skill. Follow its steps in order.

Request: $ARGUMENTS

- If the request is a path to an audio/video file, it is the voice: transcribe it instead of writing a script.
- If it is a `.txt` file, it is the script.
- Otherwise it is the topic: write the script.
- `--no-stops`: do not wait for approval between steps; still run the checks and look at the frames before delivering.
