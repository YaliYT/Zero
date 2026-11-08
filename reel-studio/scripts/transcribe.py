#!/usr/bin/env python3
"""Word-level transcription tuned for Hebrew (ivrit-ai Whisper), for captions synced word by word.

  transcribe.py recording.wav [--out assets/words.json] [--language he] [--model ...]

Writes [{id, text, start, end}] — the shape HyperFrames captions use.
Drops words Whisper invents over trailing silence.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HEBREW_MODEL = "ivrit-ai/whisper-large-v3-turbo-ct2"


def trailing_silence_start(path):
    """Where the final silence begins (seconds), or None."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path, "-af", "silencedetect=noise=-35dB:d=0.6", "-f", "null", "-"],
            capture_output=True, text=True, check=False,
        ).stderr
        dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
        total = int(dur[1]) * 3600 + int(dur[2]) * 60 + float(dur[3]) if dur else None
        starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
        ends = re.findall(r"silence_end: ([\d.]+)", out)
        if starts and total and len(ends) < len(starts):  # last silence runs to the end
            return starts[-1]
    except FileNotFoundError:
        pass
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio")
    p.add_argument("--out", default="assets/words.json")
    p.add_argument("--language", default="he")
    p.add_argument("--model", default=None, help=f"default: {HEBREW_MODEL} for Hebrew, large-v3-turbo otherwise")
    p.add_argument("--device", default="auto")
    args = p.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper is missing: run /reel-setup (pip install faster-whisper)")

    model_name = args.model or (HEBREW_MODEL if args.language == "he" else "large-v3-turbo")
    compute = "int8" if args.device in ("auto", "cpu") else "float16"
    print(f"model: {model_name}", file=sys.stderr)
    model = WhisperModel(model_name, device=args.device, compute_type=compute)
    segments, _ = model.transcribe(
        args.audio, language=args.language, word_timestamps=True, vad_filter=True, beam_size=5
    )

    cut = trailing_silence_start(args.audio)
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if not text or (cut is not None and w.start >= cut):
                continue
            words.append({"id": f"w{len(words)}", "text": text, "start": round(w.start, 3), "end": round(w.end, 3)})

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False, indent=1)
    print(" ".join(w["text"] for w in words))
    print(f"\n{len(words)} words -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
