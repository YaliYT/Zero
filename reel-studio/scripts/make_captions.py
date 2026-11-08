#!/usr/bin/env python3
"""Turn words.json into a HyperFrames captions scene: word-by-word, RTL-aware, current word highlighted.

  make_captions.py assets/words.json [--out compositions/captions.html]
      [--width 1080 --height 1920] [--max-words 3] [--bottom 640]
      [--font "Heebo"] [--size 92] [--color "#fff"] [--accent "#ff3b30"]

Then mount it in index.html (it prints the host <div> to paste).
"""
import argparse
import html
import json
import re

SENTENCE_END = re.compile(r"[.!?…,:;]$")
HEBREW = re.compile(r"[֐-׿]")


def groups_from(words, max_words, gap):
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        pause = nxt and (nxt["start"] - w["end"]) >= gap
        if len(cur) >= max_words or SENTENCE_END.search(w["text"]) or pause or not nxt:
            groups.append(cur)
            cur = []
    return groups


def main():
    p = argparse.ArgumentParser()
    p.add_argument("words")
    p.add_argument("--out", default="compositions/captions.html")
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1920)
    p.add_argument("--max-words", type=int, default=3, help="2-3 energetic, 3-5 conversational")
    p.add_argument("--gap", type=float, default=0.15, help="pause (s) that starts a new group")
    p.add_argument("--bottom", type=int, default=640, help="px from the bottom (portrait ~600-700)")
    p.add_argument("--font", default="Heebo")
    p.add_argument("--font-file", default="assets/fonts/Heebo.ttf", help="'' if the font is bundled")
    p.add_argument("--weight", default="900")
    p.add_argument("--size", type=int, default=92)
    p.add_argument("--color", default="#ffffff")
    p.add_argument("--accent", default="#ff3b30")
    args = p.parse_args()

    with open(args.words, encoding="utf-8") as f:
        words = [w for w in json.load(f) if w["text"].strip() and w["end"] > w["start"]]
    if not words:
        raise SystemExit("no words")
    rtl = sum(bool(HEBREW.search(w["text"])) for w in words) > len(words) / 3
    groups = groups_from(words, args.max_words, args.gap)

    markup, js = [], []
    for gi, g in enumerate(groups):
        start = max(0.1, g[0]["start"] - 0.05)
        nxt = groups[gi + 1][0]["start"] - 0.02 if gi + 1 < len(groups) else g[-1]["end"] + 0.4
        end = max(g[-1]["end"] + 0.05, min(nxt, g[-1]["end"] + 0.6))
        spans = []
        for wi, w in enumerate(g):
            wid = f"cap-g{gi}-w{wi}"
            spans.append(f'<span id="{wid}" class="cap-word">{html.escape(w["text"])}</span>')
            w_end = g[wi + 1]["start"] if wi + 1 < len(g) else end
            js.append(f'tl.fromTo("#{wid}", {{color: C, scale: 1}}, {{color: A, scale: 1.12, duration: 0.08, ease: "power2.out"}}, {w["start"]:.3f});')
            js.append(f'tl.to("#{wid}", {{color: C, scale: 1, duration: 0.08}}, {max(w["start"] + 0.08, w_end - 0.04):.3f});')
        markup.append(f'    <div id="cap-g{gi}" class="cap-group">{" ".join(spans)}</div>')
        js.append(f'tl.fromTo("#cap-g{gi}", {{opacity: 0, y: 24, visibility: "visible"}}, {{opacity: 1, y: 0, duration: 0.14, ease: "back.out(2)"}}, {start:.3f});')
        js.append(f'tl.to("#cap-g{gi}", {{opacity: 0, duration: 0.1, ease: "power2.in"}}, {end - 0.1:.3f});')
        js.append(f'tl.set("#cap-g{gi}", {{opacity: 0, visibility: "hidden"}}, {end:.3f});')

    total = round(max(w["end"] for w in words) + 0.6, 2)
    font_face = (
        f"@font-face {{ font-family: '{args.font}'; src: url('{args.font_file}'); font-weight: 100 900; }}"
        if args.font_file else ""
    )
    doc = f"""<template>
  <style>
    {font_face}
    #root {{ position: absolute; inset: 0; pointer-events: none; }}
    .cap-group {{
      position: absolute; left: 0; right: 0; bottom: {args.bottom}px;
      padding: 0 {int(args.width * 0.1)}px; text-align: center; overflow: visible;
      direction: {"rtl" if rtl else "ltr"}; opacity: 0; visibility: hidden;
      font-family: '{args.font}', 'Open Sans', sans-serif; font-weight: {args.weight};
      font-size: {args.size}px; line-height: 1.1; color: {args.color};
      text-shadow: 0 6px 24px rgba(0,0,0,.65);
    }}
    .cap-word {{ display: inline-block; margin: 0 .12em; }}
  </style>
  <div id="root" data-composition-id="captions" data-width="{args.width}" data-height="{args.height}">
{chr(10).join(markup)}
  </div>
  <script>
    const C = "{args.color}", A = "{args.accent}";
    const tl = gsap.timeline({{ paused: true }});
    {(chr(10) + "    ").join(js)}
    window.__timelines["captions"] = tl;
  </script>
</template>
"""
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"{len(groups)} caption groups, {len(words)} words, {'RTL' if rtl else 'LTR'} -> {args.out}")
    print("Host for index.html (inside #root):")
    print(
        f'<div id="captions" data-composition-id="captions" data-composition-src="{args.out}" '
        f'data-start="0" data-duration="{total}" data-track-index="9" data-track-kind="captions" '
        f'data-width="{args.width}" data-height="{args.height}" style="z-index:50"></div>'
    )


if __name__ == "__main__":
    main()
