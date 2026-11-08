#!/usr/bin/env python3
"""ElevenLabs helper: clone a voice, or turn a script into speech with word timings.

  clone  --name "My voice" sample1.mp3 sample2.wav ...   -> prints the new voice_id
  speak  --voice VOICE_ID --text-file script.txt --out assets/voice.mp3 [--words assets/words.json]
  voices                                                  -> lists the voices on the account

Needs ELEVENLABS_API_KEY in the environment. Uses only the standard library.
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
import uuid

API = "https://api.elevenlabs.io/v1"


def key():
    k = os.environ.get("ELEVENLABS_API_KEY")
    if not k:
        sys.exit("ELEVENLABS_API_KEY is not set. Get one at elevenlabs.io -> Profile -> API keys.")
    return k


def request(method, path, body=None, headers=None):
    h = {"xi-api-key": key(), **(headers or {})}
    req = urllib.request.Request(API + path, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"ElevenLabs {e.code}: {e.read().decode(errors='replace')[:500]}")


def clone(args):
    boundary = uuid.uuid4().hex
    parts = []

    def field(name, value):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())

    field("name", args.name)
    field("remove_background_noise", "true")
    for path in args.samples:
        mime = mimetypes.guess_type(path)[0] or "audio/mpeg"
        with open(path, "rb") as f:
            data = f.read()
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{os.path.basename(path)}"\r\n'
            f"Content-Type: {mime}\r\n\r\n".encode() + data + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    res = request("POST", "/voices/add", b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    print(res["voice_id"])


def voices(_args):
    for v in request("GET", "/voices")["voices"]:
        print(f'{v["voice_id"]}\t{v["name"]}\t{v.get("category", "")}')


def chars_to_words(alignment):
    """Group ElevenLabs character timings into words: [{id, text, start, end}]."""
    chars = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    words, cur, cur_start, cur_end = [], "", None, None
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append((cur, cur_start, cur_end))
            cur, cur_start = "", None
            continue
        if not cur:
            cur_start = s
        cur += ch
        cur_end = e
    if cur:
        words.append((cur, cur_start, cur_end))
    return [{"id": f"w{i}", "text": t, "start": round(s, 3), "end": round(e, 3)} for i, (t, s, e) in enumerate(words)]


def speak(args):
    with open(args.text_file, encoding="utf-8") as f:
        text = f.read().strip()
    body = {
        "text": text,
        "model_id": args.model,
        "voice_settings": {"stability": args.stability, "similarity_boost": 0.85, "style": 0.3, "speed": args.speed},
    }
    if args.language:
        body["language_code"] = args.language
    res = request(
        "POST",
        f"/text-to-speech/{args.voice}/with-timestamps?output_format=mp3_44100_128",
        json.dumps(body).encode(),
        {"Content-Type": "application/json"},
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(base64.b64decode(res["audio_base64"]))
    print(f"audio -> {args.out}")
    alignment = res.get("normalized_alignment") or res.get("alignment")
    if args.words and alignment:
        words = chars_to_words(alignment)
        with open(args.words, "w", encoding="utf-8") as f:
            json.dump(words, f, ensure_ascii=False, indent=1)
        print(f"{len(words)} words -> {args.words}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("clone")
    c.add_argument("--name", required=True)
    c.add_argument("samples", nargs="+")
    c.set_defaults(fn=clone)
    v = sub.add_parser("voices")
    v.set_defaults(fn=voices)
    s = sub.add_parser("speak")
    s.add_argument("--voice", default=os.environ.get("ELEVENLABS_VOICE_ID"), help="voice_id (or ELEVENLABS_VOICE_ID)")
    s.add_argument("--text-file", required=True)
    s.add_argument("--out", default="assets/voice.mp3")
    s.add_argument("--words", default="assets/words.json", help="write word timings here ('' to skip)")
    s.add_argument("--model", default="eleven_v3", help="eleven_v3 supports Hebrew")
    s.add_argument("--language", default="he")
    s.add_argument("--speed", type=float, default=1.0)
    s.add_argument("--stability", type=float, default=0.5)
    s.set_defaults(fn=speak)
    args = p.parse_args()
    if getattr(args, "cmd", None) == "speak" and not args.voice:
        sys.exit("Pass --voice or set ELEVENLABS_VOICE_ID (see: tts_elevenlabs.py voices)")
    args.fn(args)


if __name__ == "__main__":
    main()
