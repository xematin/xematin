# Setup

`README.md` is **generated**. Edit `config.json` and re-run the generator — a change
made by hand in the README is gone the next time the Action runs.

```
config.json            everything you are meant to change
scripts/generate.py    draws the panels, writes README.md
assets/*.svg           generated artwork, committed so GitHub can serve it
data/snapshot.json     last good data pull, used as an offline fallback
preview.html           local preview on both GitHub backgrounds
.github/workflows/     daily refresh
```

## Run it

Python 3.9+, no dependencies.

```bash
python scripts/generate.py
```

`--offline` redraws from `data/snapshot.json` without touching the network, which is
what you want while tweaking colours or copy.

To see the result before pushing, serve the repository root:

```bash
python -m http.server 8777
```

…then open <http://127.0.0.1:8777/preview.html>. It loads each panel as an `<img>`, the
way GitHub does, and shows them on both the light and the dark GitHub background — the
panels are rounded on a transparent canvas, so both are worth a look.

## The panels

Three engineering-drawing plates, each inside a macOS window frame.

| File | Panel | Live data |
|---|---|---|
| `assets/hero.svg` | Logotype, role readout, rotary encoder, drawing title block | no |
| `assets/stack.svg` | Signal-bus schematic of the stack | no |
| `assets/signal.svg` | Contribution scope + language mix | yes |
| `assets/link-*.svg` | The button row | no |

## The one rule the drawing code follows

**Animation may only add, never hide.** A README image can be painted with its SMIL
timeline still at `t=0`: offscreen, throttled, scaled, captured as a still, or under
reduced motion. Anything whose first keyframe is invisible renders as an empty panel in
exactly the situations you cannot reproduce — which is how an early draft of this
profile shipped a blank contribution chart. So there are no reveal fades and no draw-on
strokes. Every mark is in its final place at `t=0`, and the moving parts — the encoder,
the bus flow, the status LED, the peak ripple, the logotype's colour drift — all read
correctly frozen at their first frame. The role line cycles, and its *first* entry is
the resting frame, so a frozen panel still shows a role.

## Editing `config.json`

- **`wordmark`** — drawn stroke by stroke from the `GLYPHS` table in `generate.py`.
  `A E F H I K L M N T V W X Y Z` and space are mapped; any other character falls back
  to outlined text. To add a letter, give it an advance width and one path per pen
  stroke on the same 90-unit cap height (`y=20` top, `y=110` baseline). Its gradient is
  `userSpaceOnUse` on purpose: a purely horizontal or vertical stroke has a zero-area
  bounding box, and an `objectBoundingBox` gradient drops it — which is what silently
  ate the T and the I.
- **`shell_user`** — the name in each window's title bar.
- **`roles`** — up to three; they cross-fade on a 3s beat.
- **`titleblock`** — four `[label, value]` pairs. A cell labelled `STATUS` gets the
  blinking green LED.
- **`stack`** — four named groups. Two are drawn above the bus and two below, and chips
  wrap automatically, so entries can be added without touching the layout.
- **`links`** — the buttons. `accent` is one of `cyan`, `amber`, `violet`, `green`,
  `rose`.

Colours live in the `C` dictionary at the top of `generate.py`, with the real macOS
button colours for the three lights. Change `cyan` and the whole profile re-themes.

## The daily Action

`.github/workflows/refresh.yml` runs the generator and commits only when a file actually
changed. It needs no secret: the contribution calendar comes from the public
`github.com/users/<name>/contributions` endpoint, and `GITHUB_TOKEN` is passed only to
raise the REST rate limit. If any repository's language data cannot be read the run
raises rather than publishing a partial mix, and falls back to `data/snapshot.json`.

Because the activity panel prints its own sync time, expect one commit a day. Move the
`cron` to weekly if that is too noisy.

## Cache busting

GitHub proxies README images through Camo and caches them hard, so every `<img src>`
carries `?v=<hash of the file>`, recomputed on each run. That is also why `assets/` is
committed rather than ignored.
