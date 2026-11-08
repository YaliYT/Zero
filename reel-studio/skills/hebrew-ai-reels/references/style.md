# The Reel Studio look

Taken from the reference reel (a 2-minute Hebrew explainer made 100% with AI in Claude Code).

## Palette
- Ground `#070505` → `#1a0606` vertical gradient, a soft red radial glow behind the middle.
- Ink `#ffffff`; accent `#ff3b30` (one or two words per line, labels, pills, waveforms).
- Thin vertical red light streaks drifting down; tiny white specks (dust) are optional.

## Type
- Heebo 800–900 for Hebrew; tight line height (1.05–1.1).
- Captions at the bottom of the safe band, 2–3 words, the spoken word turns red.
- Big numbers (`100%`, `30:00`, `1,000,000,000`): 200–280 px, white with a red outer glow; count them up with a GSAP tween on an object and write the value into the text on update (deterministic: it is driven by the timeline).

## Recurring components
| Component | Build |
| --- | --- |
| Pill label | rounded 999px, red fill or red 2px border, 36–44 px bold text ("הספר הקולי שלי", "MOV → MP4") |
| Toolbox grid ("ארגז הכלים") | dark rounded card, 4+3 app tiles with icon + name; tick badges pop in one by one as each tool is "installed" |
| Terminal window | `#121212` card, three dots, `claude — ~/videos` title, monospace lines typed char by char (`Bash(pip install imageio-ffmpeg)` then a green `✓ ffmpeg ready`) |
| Browser window | address bar `file:///videos/index.html`, a frame counter `frame 1,936 / 3,672` ticking, a filmstrip under it |
| Phone mockups | three tilted phones (center one larger) showing finished reels |
| Waveform | 40–60 rounded bars, heights from a seeded sequence, a red playhead line sweeping across |
| Stamp | red bordered box rotated -6°, scale-punch in ("הכל הותקן לבד") |
| Cut-out portrait | person PNG with a white sticker outline, above a waveform while they speak |

## Motion
- Entrances 0.15–0.35 s: `back.out(2)` for pills/stamps, `power4.out` for big type, small blur-to-sharp on numbers.
- A slow push-in (scale 1 → 1.06) on whatever holds the frame.
- Scene changes on sentence boundaries; whip/slide transitions 0.25 s; never a fade to black mid-video.
- A new visual beat every 2–4 s.

## HyperFrames rules that bite
- Every timed element: `class="clip"` + `data-start` + `data-duration`; scene root id = host id = timeline key.
- Use `fromTo` inside scenes; no `Date.now()`, unseeded random, timers, or `repeat: -1`.
- Do not tween `display`/`visibility` on a `.clip` - animate a child.
- Asset paths are relative: `assets/...`.
