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
windows are drawn on a transparent canvas, so both need a look.

## The panels

Three macOS terminal windows, one image each.

| File | Window | Live data |
|---|---|---|
| `assets/hero.svg` | `whoami` — logotype, tagline, `about.txt` | no |
| `assets/stack.svg` | `cat stack.txt` | no |
| `assets/activity.svg` | contribution chart + language mix | yes |
| `assets/link-*.svg` | the button row | no |

## Two rules the drawing code follows

**Everything sits on a character grid.** Text is never flowed; each run is placed at a
column, `cx(col)`, at 0.6em per character — the widest advance among the fonts in the
stack. A reader whose monospace font is narrower gets slightly looser columns, never a
collision, so the panels hold their shape on any machine.

**Animation may only add, never hide.** A README image can be painted with its SMIL
timeline still at `t=0`: offscreen, throttled, scaled, captured as a still, or under
reduced motion. Anything whose first keyframe is invisible renders as an empty panel in
exactly the situations you cannot reproduce. So there are no reveal fades, no typing
wipes and no draw-on strokes — every glyph is in its final place at `t=0`, and the only
moving parts (the cursor blink, the logotype's colour drift, the peak ripple) are
correct frozen at their first frame.

## Editing `config.json`

- **`wordmark`** — drawn stroke by stroke from the `GLYPHS` table in `generate.py`.
  `A E F H I K L M N T V W X Y Z` and space are mapped; any other character falls back
  to outlined text. To add a letter, give it an advance width and one path per pen
  stroke on the same 90-unit cap height (`y=20` top, `y=110` baseline).
- **`shell_user`** — the name in each window's title bar and prompt.
- **`about`** — `[label, value]` pairs. A row labelled `status` gets the green dot.
- **`stack`** — group name to list. Groups are coloured in order: blue, mauve, peach,
  teal. Keep a row under about 75 characters and it will not run past the window.
- **`links`** — the buttons. `accent` is one of `blue`, `mauve`, `peach`, `teal`,
  `green`, `yellow`.

Colours live in the `C` dictionary at the top of `generate.py` — Catppuccin Mocha, with
the real macOS window-button colours for the three dots. Change `blue` and the whole
profile re-themes.

## The daily Action

`.github/workflows/refresh.yml` runs the generator and commits only when a file actually
changed. It needs no secret: the contribution calendar comes from the public
`github.com/users/<name>/contributions` endpoint, and `GITHUB_TOKEN` is passed only to
raise the REST rate limit. If any repository's language data cannot be read the run
raises rather than publishing a partial mix, and falls back to `data/snapshot.json`.

Because each panel prints its own sync time, expect one commit a day. Move the `cron` to
weekly if that is too noisy.

## Cache busting

GitHub proxies README images through Camo and caches them hard, so every `<img src>`
carries `?v=<hash of the file>`, recomputed on each run. That is also why `assets/` is
committed rather than ignored.
