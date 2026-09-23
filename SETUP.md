# Setup

`README.md` is **generated**. Do not edit it by hand — edit `config.json` and re-run the
generator, or your change is gone the next time the Action runs.

```
config.json            everything you are meant to change
scripts/generate.py    draws every panel, writes README.md
assets/*.svg           generated artwork (committed, so GitHub can serve it)
data/snapshot.json     last successful data pull, used as an offline fallback
.github/workflows/     daily refresh
```

## Run it locally

Python 3.9+ and no dependencies at all.

```bash
python scripts/generate.py
```

Add `--offline` to redraw from `data/snapshot.json` without touching the network — handy
while you are tweaking colours or copy.

To look at the result before pushing, serve the repository root and open `preview.html`:

```bash
python -m http.server 8777
```

<http://127.0.0.1:8777/preview.html> lays the panels out at GitHub's content width and
loads each one as an `<img>` — the same way GitHub does — so the animations run exactly as
they will on the profile. Opening an `assets/*.svg` file directly works too.

## What each panel is

| File | Panel | Live data |
|---|---|---|
| `assets/hero.svg` | Logotype, role readout, rotary encoder, drawing title block | no |
| `assets/stack.svg` | Signal-bus schematic of the stack | no |
| `assets/module-NN.svg` | One project per rack blade | language, last push, stars |
| `assets/signal.svg` | Contribution oscilloscope + language mix | yes |
| `assets/link-*.svg` | Bracket buttons | no |

## Editing `config.json`

- **`wordmark`** — drawn stroke by stroke from the `GLYPHS` table in `generate.py`.
  `A E F H I K L M N T V W X Y Z` and space are mapped. Any other character makes the
  whole logotype fall back to outlined text, which still animates but loses the plotter
  look. To add a letter, give it an advance width and one path per pen stroke on the
  90-unit cap height used by the rest (`y=20` top, `y=110` baseline).
- **`roles`** — up to three; they cross-fade on a 3s beat.
- **`titleblock`** — four `[label, value]` pairs. A cell labelled `STATUS` gets the
  blinking green LED.
- **`stack`** — four named groups. Two are drawn above the bus, two below, and rows wrap
  automatically, so you can add entries without touching the layout.
- **`modules`** — the rack blades. `repo` must match the repository name exactly so the
  generator can attach its language, star count and last push date. `accent` is one of
  `cyan`, `amber`, `violet`, `lime`, `rose`. Add `"url"` to point a blade somewhere other
  than the repository.
- **`links`** — the button row.

Colours live in the `C` dictionary at the top of `generate.py`. Everything is derived from
it, so changing `cyan` re-themes the whole profile.

## The daily Action

`.github/workflows/refresh.yml` runs `generate.py`, and commits only when a file actually
changed. It needs no secret: the contribution calendar is scraped from the public
`github.com/users/<name>/contributions` endpoint, and `GITHUB_TOKEN` is passed purely to
raise the REST rate limit. If the fetch ever fails the generator falls back to
`data/snapshot.json` instead of failing the run.

## Cache busting

GitHub proxies README images through Camo and caches them hard. Every `<img src>` carries
`?v=<hash of the file>`, which `generate.py` recomputes on each run, so a changed panel
always gets a fresh URL. This is also why `assets/` is committed rather than ignored.

## Known limits

- Everything is one wide image per panel, so on a narrow phone the text scales down with
  it. The layouts are built at 1000px with generous type for that reason.
- `prefers-color-scheme` is deliberately not used: GitHub's theme and the browser's theme
  can disagree. Each panel carries its own dark surface so it looks intentional on both.
