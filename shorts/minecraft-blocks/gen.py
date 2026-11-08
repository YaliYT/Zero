"""Builds compositions/blocks.html: pixel blocks, white look, one segment per block.
Segment times come from assets/words.json. Re-run after changing the voice."""
import json, pathlib

ROOT = pathlib.Path(__file__).parent
words = json.loads((ROOT / "assets/words.json").read_text(encoding="utf-8"))
END = round(words[-1]["end"] + 0.6, 2)


def t(word):  # start time of the first word that starts with `word`
    return next(w["start"] for w in words if w["text"].startswith(word))


# (id, label, texture set, start)
SEG = [
    ("dirt", "אדמה", "dirt", t("אדמה") - 0.15),
    ("dia", "יהלום", "ore", t("יהלום") - 0.15),
    ("tnt", "TNT", "tnt", t("טי") - 0.15),
    ("obs", "אובסידיאן", "obs", t("אובסידיאן") - 0.15),
    ("bed", "בדרוק", "bed", t("בדרוק") - 0.15),
]
CTA = t("תכתבו") - 0.15
starts = [s[3] for s in SEG] + [CTA]
SEG = [(i, l, x, round(s, 2), round(starts[n + 1] - s, 2)) for n, (i, l, x, s) in enumerate(SEG)]
HOOK_D = round(SEG[0][3], 2)


def cube(cid, tex, size, extra=""):
    w, h = size, round(size * 1.1)
    return f'<canvas class="cube" id="{cid}" data-tex="{tex}" width="{w}" height="{h}" style="margin:{-h//2}px 0 0 {-w//2}px" {extra}></canvas>'


html, js = [], []

# Hook: five mini blocks + series pill. Visible at frame 0 (thumbnail).
html.append(f'<div id="hook" class="clip seg" data-start="0" data-duration="{HOOK_D}">')
html.append('<div class="pill" id="hook-pill" style="font-size:54px">מה הבלוק שלך אומר עליך?</div>')
for n, (_, _, tex, _, _) in enumerate(SEG):
    x, y = [(540, 560), (300, 760), (780, 760), (390, 1010), (690, 1010)][n]
    html.append(f'<div class="slot" style="left:{x}px;top:{y}px">{cube(f"hook-c{n}", tex, 170)}</div>')
    js.append(f'tl.fromTo("#hook-c{n}", {{scale:{0.6 if n else 1}, rotation:0}}, {{scale:1, duration:0.35, ease:"back.out(2.2)"}}, {0.12 * n:.2f});')
    sp = 0.12 * n + 0.36
    js.append(f'tl.to("#hook-c{n}", {{rotation:{(-1)**n * 8}, y:-20, repeat:1, yoyo:true, duration:{(HOOK_D - sp - 0.05) / 2:.2f}, ease:"power1.inOut"}}, {sp:.2f});')
html.append('</div>')

# One segment per block.
for sid, label, tex, st, d in SEG:
    html.append(f'<div id="{sid}" class="clip seg" data-start="{st}" data-duration="{d}">')
    html.append(f'<div class="pill" id="{sid}-pill">{label}</div>')
    html.append(f'<div class="slot" style="left:540px;top:680px">{cube(f"{sid}-c", tex, 380)}</div>')
    html.append('</div>')
    spin = 0 if sid == "bed" else 70  # bedrock does not move. Ever.
    js.append(f'tl.fromTo("#{sid}-pill", {{scale:0.6, opacity:0}}, {{scale:1, opacity:1, duration:0.25, ease:"back.out(3)"}}, {st});')
    js.append(f'tl.fromTo("#{sid}-c", {{scale:0, rotation:-12}}, {{scale:1, rotation:0, duration:0.4, ease:"back.out(1.8)"}}, {st});')
    if spin:
        js.append(f'tl.to("#{sid}-c", {{y:-24, duration:{(d - 0.5) / 2:.2f}, repeat:1, yoyo:true, ease:"sine.inOut"}}, {st + 0.4:.2f});')

# Diamond: sparkles.
for n, (x, y) in enumerate([(330, 480), (770, 560), (720, 900), (360, 860)]):
    html.append(f'<div class="spark clip" id="spark{n}" data-start="{SEG[1][3]}" data-duration="{SEG[1][4]}" style="left:{x}px;top:{y}px"></div>')
    js.append(f'tl.fromTo("#spark{n}", {{scale:0, rotation:0}}, {{scale:1, rotation:90, duration:0.35, ease:"power2.out", repeat:5, yoyo:true}}, {SEG[1][3] + 0.3 + n * 0.25:.2f});')

# TNT: blows up on "יבנה".
boom = t("יבנה")
js.append(f'tl.to("#tnt-c", {{scale:1.25, duration:0.12, repeat:3, yoyo:true, ease:"power1.inOut"}}, {boom - 0.5:.2f});')
js.append(f'tl.to("#tnt-c", {{scale:0, duration:0.08}}, {boom + 0.05:.2f});')
html.append(f'<div id="flash" class="clip" data-start="{boom:.2f}" data-duration="0.5"></div>')
js.append(f'tl.fromTo("#flash", {{opacity:1}}, {{opacity:0, duration:0.45, ease:"power2.out"}}, {boom:.2f});')
debris = [(-300, -260), (280, -320), (-360, 60), (340, 120), (-120, -420), (160, 300), (-220, 320), (420, -80)]
for n, (dx, dy) in enumerate(debris):
    html.append(f'<div class="bit clip" id="bit{n}" data-start="{boom:.2f}" data-duration="0.9" style="background:{["#c8302a", "#eee", "#3a3a3a", "#c8302a"][n % 4]}"></div>')
    js.append(f'tl.fromTo("#bit{n}", {{x:0, y:0, rotation:0, opacity:1}}, {{x:{dx}, y:{dy}, rotation:{(n % 3 - 1) * 200}, opacity:0, duration:0.85, ease:"power3.out"}}, {boom:.2f});')
js.append(f'tl.fromTo("#stage", {{x:0}}, {{x:18, duration:0.05, repeat:7, yoyo:true}}, {boom:.2f});')

# CTA: all five blocks in a row + subscribe pill.
cd = round(END - CTA, 2)
html.append(f'<div id="cta" class="clip seg" data-start="{CTA:.2f}" data-duration="{cd}">')
html.append('<div class="pill" id="cta-pill">איזה בלוק אתם?</div>')
for n, (_, _, tex, _, _) in enumerate(SEG):
    html.append(f'<div class="slot" style="left:{170 + n * 185}px;top:680px">{cube(f"cta-c{n}", tex, 130)}</div>')
    js.append(f'tl.fromTo("#cta-c{n}", {{y:-200, opacity:0}}, {{y:0, opacity:1, duration:0.4, ease:"bounce.out"}}, {CTA + 0.08 * n:.2f});')
html.append('<div id="sub">סאב לחלק 2</div>')
js.append(f'tl.fromTo("#sub", {{scale:0}}, {{scale:1, duration:0.35, ease:"back.out(2.5)"}}, {t("ותעשו") - 0.1:.2f});')
html.append('</div>')

out = f'''<template>
  <style>
    @font-face {{ font-family: "Heebo"; src: url("assets/fonts/Heebo.ttf"); font-weight: 100 900; }}
    #root {{ position: absolute; inset: 0; direction: rtl; font-family: "Heebo", sans-serif; background: #fff; overflow: hidden; }}
    #stage {{ position: absolute; inset: 0; }}
    .seg {{ position: absolute; inset: 0; }}
    .pill {{ position: absolute; top: 250px; left: 0; right: 0; margin: 0 auto; width: max-content;
      padding: 14px 44px; border-radius: 999px; background: #111; color: #fff; font-size: 64px; font-weight: 900; }}
    .slot {{ position: absolute; width: 0; height: 0; }}
    .cube {{ position: absolute; left: 0; top: 0; }}
    .spark {{ position: absolute; width: 60px; height: 60px; margin: -30px; background: #4fe6e0;
      clip-path: polygon(50% 0, 60% 40%, 100% 50%, 60% 60%, 50% 100%, 40% 60%, 0 50%, 40% 40%); }}
    #flash {{ position: absolute; inset: 0; background: #fff6c8; }}
    .bit {{ position: absolute; left: 510px; top: 650px; width: 60px; height: 60px; }}
    #sub {{ position: absolute; top: 1420px; left: 0; right: 0; margin: 0 auto; width: max-content; padding: 18px 54px;
      border-radius: 999px; background: #e62117; color: #fff; font-size: 72px; font-weight: 900; }}
  </style>
  <div id="root" data-composition-id="blocks" data-width="1080" data-height="1920">
    <div id="stage">
{chr(10).join(html)}
    </div>
  </div>
  <script>
    // Pixel textures, drawn once. Seeded so every render is identical.
    (function () {{
      let s = 7;
      const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
      const pick = (a) => a[Math.floor(rnd() * a.length)];
      const P = {{
        grass: ["#5fa83a", "#6dbb44", "#4f9230", "#79c64e"],
        dirt: ["#8a5a36", "#7a4e2e", "#9b6a42", "#6b4426"],
        stone: ["#8b8b8b", "#7c7c7c", "#999", "#727272"],
        dia: ["#4fe6e0", "#2bc8c2", "#a8fff9"],
        obs: ["#1a1026", "#24163a", "#140c1e", "#3b2463"],
        bed: ["#575757", "#2e2e2e", "#8a8a8a", "#1c1c1c", "#6e6e6e"],
      }};
      const T = [".###.", "..#..", "..#..", "..#..", "..#.."], N = ["#...#", "##..#", "#.#.#", "#..##", "#...#"];
      const TNT = T.map((r, i) => "." + r.slice(1, 4) + "." + N[i] + "." + r.slice(1, 4) + "..");
      function px(kind, x, y) {{
        switch (kind) {{
          case "dirt-top": return pick(P.grass);
          case "dirt-side": return y < 3 || (y === 3 && rnd() < 0.5) ? pick(P.grass) : pick(P.dirt);
          case "ore-top": case "ore-side": {{
            const blob = [[3, 3], [11, 4], [6, 10], [12, 12]].some(([a, b]) => Math.abs(x - a) + Math.abs(y - b) < 2);
            return blob ? pick(P.dia) : pick(P.stone); }}
          case "tnt-top": return (x - 7.5) ** 2 + (y - 7.5) ** 2 < 5 ? "#3a3a3a" : pick(["#c9a76a", "#b8955a"]);
          case "tnt-side":
            if (y >= 5 && y <= 10) return y >= 6 && TNT[y - 6][x] === "#" ? "#222" : "#eee";
            return x % 4 === 0 ? "#9e2420" : pick(["#c8302a", "#d43a33"]);
          case "obs-top": case "obs-side": return rnd() < 0.1 ? P.obs[3] : pick(P.obs.slice(0, 3));
          default: return pick(P.bed);
        }}
      }}
      // Isometric cube: top, left, right faces, each a 16x16 pixel grid.
      function draw(c, tex) {{
        const g = c.getContext("2d"), a = c.width / 32, b = a * 0.5, v = a * 1.2, cx = c.width / 2;
        const faces = [
          [tex + "-top", [a, b, -a, b, cx, 0], 0],
          [tex + "-side", [a, b, 0, v, 0, 16 * b], 0.18],
          [tex + "-side", [a, -b, 0, v, cx, 32 * b], 0.36],
        ];
        for (const [kind, m, shade] of faces) {{
          g.setTransform(...m);
          for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) {{ g.fillStyle = px(kind, x, y); g.fillRect(x, y, 1.04, 1.04); }}
          if (shade) {{ g.fillStyle = `rgba(0,0,0,${{shade}})`; g.fillRect(0, 0, 16, 16); }}
        }}
        g.setTransform(1, 0, 0, 1, 0, 0);
      }}
      document.querySelectorAll('[data-composition-id="blocks"] canvas.cube').forEach((c) => draw(c, c.dataset.tex));
    }})();
    const tl = gsap.timeline({{ paused: true }});
    {chr(10).join("    " + l for l in js).lstrip()}
    window.__timelines["blocks"] = tl;
  </script>
</template>
'''
(ROOT / "compositions/blocks.html").write_text(out, encoding="utf-8")
print("END", END, "segments", [(s[0], s[3], s[4]) for s in SEG], "cta", CTA)
