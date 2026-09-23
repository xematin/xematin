#!/usr/bin/env python3
"""
Draw the profile as a set of macOS terminal windows, from config.json + live data.

Everything sits on a real character grid -- every glyph is placed at a column, the
way a terminal lays out text -- so the panels stay aligned whatever monospace font
the reader happens to have.

Stdlib only, so the GitHub Action needs no install step, and every endpoint it
reads is public, so it needs no token either.

    python scripts/generate.py            # fetch live data and render
    python scripts/generate.py --offline  # render from data/snapshot.json
"""

import collections
import datetime
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
DATA = os.path.join(ROOT, "data")
UA = "xematin-profile-generator"

# ------------------------------------------------------------------- palette
# Catppuccin Mocha, chosen for contrast at small sizes, with the real macOS
# window-button colours so the chrome reads as itself.

C = {
    "win":    "#1e1e2e",
    "bar":    "#181825",
    "edge":   "#313244",
    "track":  "#2a2b3c",
    "text":   "#cdd6f4",
    "sub":    "#a6adc8",
    "dim":    "#6c7086",
    "green":  "#a6e3a1",
    "blue":   "#89b4fa",
    "mauve":  "#cba6f7",
    "peach":  "#fab387",
    "teal":   "#94e2d5",
    "yellow": "#f9e2af",
    "red":    "#f38ba8",
    "close":  "#ff5f57",
    "min":    "#febc2e",
    "zoom":   "#28c840",
}
ACCENTS = {k: C[k] for k in ("blue", "mauve", "peach", "teal", "green", "yellow")}
LANG_COLORS = [C["blue"], C["peach"], C["mauve"], C["teal"], C["yellow"], C["dim"]]

MONO = ("ui-monospace,'SF Mono',SFMono-Regular,Menlo,Monaco,'Cascadia Mono',"
        "'Segoe UI Mono','Roboto Mono','DejaVu Sans Mono',monospace")

# ------------------------------------------------------------------- metrics
# 0.6em is the widest advance among the monospace fonts in the stack above, so
# laying out at 0.6 guarantees no column ever collides on a narrower font.

W = 880                 # panel width; the README scales it up, so text reads larger
PADX = 12               # room for the window shadow
WINX = PADX
WINW = W - PADX * 2
WINY = 10
BAR = 38                # title bar height
FS = 14                 # body text size
CH = FS * 0.6           # character advance
LINE = 28               # line height
COL0 = PADX + 26        # column 0
COLS = int((WINW - 52) / CH)


def cx(col):
    return COL0 + col * CH


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def txt(x, y, s, size=FS, fill=None, anchor="start", opacity=None, weight=None):
    a = [f'x="{x:.1f}"', f'y="{y:.1f}"', f'font-size="{size}"',
         f'fill="{fill or C["text"]}"']
    if anchor != "start":
        a.append(f'text-anchor="{anchor}"')
    if opacity is not None:
        a.append(f'opacity="{opacity}"')
    if weight:
        a.append(f'font-weight="{weight}"')
    return f'<text {" ".join(a)}>{esc(s)}</text>'


# Motion rule: animation may only ADD, never hide.
#
# A README image can be painted with its SMIL timeline still sitting at t=0 --
# offscreen, throttled, scaled, captured as a still, or under reduced motion.
# Anything whose first keyframe is "invisible" therefore renders as an empty
# panel in exactly the cases nobody can debug. So no reveal fades, no typing
# wipes, no draw-on strokes: every glyph is in its final place at t=0, and the
# only moving parts (the cursor blink, the logotype's colour drift, the peak
# ripple) look correct frozen at their first frame.


# ---------------------------------------------------------------- data layer

def fetch(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": UA})
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def fetch_json(url):
    return json.loads(fetch(url))


def contributions(user):
    """Scrape the public contribution calendar -- no authentication needed."""
    html = fetch(f"https://github.com/users/{user}/contributions", "text/html")
    tips = {}
    for m in re.finditer(
            r'for="(contribution-day-component-\d+-\d+)"[^>]*>\s*(No|[\d,]+)\s+contribution',
            html):
        tips[m.group(1)] = 0 if m.group(2) == "No" else int(m.group(2).replace(",", ""))
    cells = re.findall(
        r'data-date="(\d{4}-\d{2}-\d{2})"\s+id="(contribution-day-component-\d+-\d+)"',
        html)
    days = sorted((d, tips.get(i, 0)) for d, i in cells)
    if not days:
        raise RuntimeError("contribution calendar returned no cells")
    return days


def weekly(days):
    buckets = collections.OrderedDict()
    for d, n in days:
        dt = datetime.date.fromisoformat(d)
        key = dt - datetime.timedelta(days=(dt.weekday() + 1) % 7)   # weeks start Sunday
        buckets[key] = buckets.get(key, 0) + n
    return list(buckets.items())


def collect(user):
    prof = fetch_json(f"https://api.github.com/users/{user}")
    repos = fetch_json(f"https://api.github.com/users/{user}/repos?per_page=100&sort=pushed")
    langs = collections.Counter()
    missed = []
    for r in repos:
        if r["fork"]:
            continue
        try:
            for k, v in fetch_json(r["languages_url"]).items():
                langs[k] += v
        except urllib.error.URLError as exc:
            missed.append(f'{r["name"]} ({exc})')
    if missed:
        # One skipped repository silently shifts every percentage, so refuse the
        # partial answer and let main() fall back to the last good snapshot.
        raise RuntimeError("language data incomplete: " + ", ".join(missed))
    wk = weekly(contributions(user))
    return {
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%MZ"),
        "user": user,
        "since": prof["created_at"][:4],
        "repos_total": prof["public_repos"],
        "repos_own": sum(1 for r in repos if not r["fork"]),
        "weeks": [[str(k), v] for k, v in wk],
        "languages": langs.most_common(12),
    }


# ------------------------------------------------------------------ wordmark
# Stroke glyphs on a 90-unit cap height (y 20..110), straight segments only, so
# the draw-on reads like a plotter and no font has to be available.

GLYPHS = {
    "M": (60, ["M0,110 L0,20 L30,72 L60,20 L60,110"]),
    "A": (60, ["M0,110 L30,20 L60,110", "M12.7,72 L47.3,72"]),
    "T": (60, ["M0,20 L60,20", "M30,20 L30,110"]),
    "I": (30, ["M0,20 L30,20", "M15,20 L15,110", "M0,110 L30,110"]),
    "N": (60, ["M0,110 L0,20 L60,110 L60,20"]),
    "E": (54, ["M54,20 L0,20 L0,110 L54,110", "M0,65 L40,65"]),
    "F": (52, ["M52,20 L0,20 L0,110", "M0,65 L38,65"]),
    "H": (60, ["M0,20 L0,110", "M60,20 L60,110", "M0,65 L60,65"]),
    "K": (58, ["M0,20 L0,110", "M58,20 L2,68", "M20,55 L58,110"]),
    "L": (52, ["M0,20 L0,110 L52,110"]),
    "V": (60, ["M0,20 L30,110 L60,20"]),
    "W": (84, ["M0,20 L21,110 L42,46 L63,110 L84,20"]),
    "X": (58, ["M0,20 L58,110", "M58,20 L0,110"]),
    "Y": (58, ["M0,20 L29,66 L58,20", "M29,66 L29,110"]),
    "Z": (56, ["M0,20 L56,20 L0,110 L56,110"]),
    " ": (26, []),
}
GAP = 22


def wordmark(text, x, top, height, uid):
    """Plotter-drawn logotype; falls back to outlined text for unmapped glyphs."""
    text = text.upper()
    s = height / 90.0
    if any(ch not in GLYPHS for ch in text):
        return (f'<text x="{x}" y="{top + height}" font-size="{height}" fill="none" '
                f'stroke="{C["text"]}" stroke-width="2">{esc(text)}</text>')
    strokes, cur = [], 0.0
    for ch in text:
        adv, paths = GLYPHS[ch]
        for p in paths:
            strokes.append((cur, p))
        cur += adv + GAP
    body = "".join(f'<path transform="translate({off:.1f},0)" d="{p}"/>'
                   for off, p in strokes)
    # userSpaceOnUse, because a purely horizontal or vertical stroke has a
    # zero-area bounding box and an objectBoundingBox gradient would drop it --
    # which is what silently ate the T and the I of MATIN.
    w = cur - GAP
    grad = (f'<defs><linearGradient id="wm{uid}" gradientUnits="userSpaceOnUse" '
            f'x1="0" y1="0" x2="{w:.0f}" y2="0">'
            f'<stop offset="0" stop-color="{C["text"]}"/>'
            f'<stop offset="1" stop-color="{C["blue"]}"/>'
            f'<animate attributeName="x2" values="{w:.0f};{w * 2.6:.0f};{w:.0f}" '
            f'dur="11s" repeatCount="indefinite" calcMode="spline" keyTimes="0;0.5;1" '
            f'keySplines="0.4 0 0.6 1;0.4 0 0.6 1"/></linearGradient></defs>')
    return (f'{grad}<g transform="translate({x:.1f},{top - 20 * s:.1f}) scale({s:.4f})" '
            f'fill="none" stroke="url(#wm{uid})" stroke-width="7" '
            f'stroke-linecap="square" stroke-linejoin="miter">{body}</g>')


# ------------------------------------------------------------ window builder

class Term:
    """A macOS terminal window laid out on a character grid."""

    def __init__(self, uid, title):
        self.uid, self.title = uid, title
        self.o = []
        self.y = WINY + BAR + 40          # first baseline

    # -- layout ------------------------------------------------------------
    def blank(self, k=1.0):
        self.y += LINE * k

    def gap(self, px):
        self.y += px

    # -- content -----------------------------------------------------------
    def _prompt(self, y):
        return (f'<path d="M{cx(0):.1f},{y - 9.5:.1f} l5.6,4.8 l-5.6,4.8" fill="none" '
                f'stroke="{C["green"]}" stroke-width="1.9" stroke-linecap="round" '
                f'stroke-linejoin="round"/>' + txt(cx(2), y, "~", fill=C["blue"]))

    def cmd(self, text):
        self.o.append(self._prompt(self.y) + txt(cx(4), self.y, text))
        self.y += LINE

    def row(self, cells):
        """One output line: a list of (column, text, colour, size)."""
        self.o.append("".join(txt(cx(col), self.y, s, size=size, fill=fill)
                              for col, s, fill, size in cells))
        self.y += LINE

    def raw(self, markup, advance=0.0):
        self.o.append(markup)
        self.y += advance

    def cursor(self):
        y = self.y
        self.o.append(
            self._prompt(y)
            + f'<rect x="{cx(4):.1f}" y="{y - FS + 1:.1f}" width="{CH:.1f}" '
              f'height="{FS + 3}" rx="1" fill="{C["text"]}">'
              f'<animate attributeName="opacity" values="1;1;0;0" '
              f'keyTimes="0;.5;.5001;1" dur="1.1s" repeatCount="indefinite"/></rect>')
        self.y += LINE

    # -- output ------------------------------------------------------------
    def render(self, bottom=30):
        h = self.y - LINE + bottom - WINY
        svg_h = int(WINY + h + 26)
        r = 11
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {svg_h}" '
               f'width="{W}" height="{svg_h}" role="img" font-family="{MONO}" '
               f'text-rendering="geometricPrecision">',
               "<defs>",
               f'<linearGradient id="ar{self.uid}" x1="0" y1="0" x2="0" y2="1">'
               f'<stop offset="0" stop-color="{C["blue"]}" stop-opacity=".30"/>'
               f'<stop offset="1" stop-color="{C["blue"]}" stop-opacity="0"/>'
               f'</linearGradient>',
               f'<filter id="sh{self.uid}" x="-12%" y="-12%" width="124%" height="130%">'
               f'<feDropShadow dx="0" dy="7" stdDeviation="9" flood-color="#000" '
               f'flood-opacity=".34"/></filter>',
               "</defs>",
               f'<rect x="{WINX}" y="{WINY}" width="{WINW}" height="{h:.0f}" rx="{r}" '
               f'fill="{C["win"]}" filter="url(#sh{self.uid})"/>',
               f'<path d="M{WINX},{WINY + r} a{r},{r} 0 0 1 {r},-{r} h{WINW - 2 * r} '
               f'a{r},{r} 0 0 1 {r},{r} v{BAR - r} h-{WINW} z" fill="{C["bar"]}"/>',
               f'<line x1="{WINX}" y1="{WINY + BAR}" x2="{WINX + WINW}" '
               f'y2="{WINY + BAR}" stroke="{C["edge"]}" stroke-width="1"/>']
        for i, key in enumerate(("close", "min", "zoom")):
            out.append(f'<circle cx="{WINX + 22 + i * 20}" cy="{WINY + BAR / 2:.0f}" '
                       f'r="6.5" fill="{C[key]}"/>')
        out.append(txt(W / 2, WINY + BAR / 2 + 4, self.title, size=11.5,
                       fill=C["dim"], anchor="middle"))
        out.extend(self.o)
        out.append(f'<rect x="{WINX}.5" y="{WINY}.5" width="{WINW - 1}" '
                   f'height="{h - 1:.0f}" rx="{r}" fill="none" stroke="{C["edge"]}" '
                   f'stroke-width="1"/>')
        out.append("</svg>")
        return "\n".join(out)


# -------------------------------------------------------------------- panels

def hero(cfg, d):
    t = Term("a", f'{cfg["shell_user"]} — ~ — zsh')
    t.cmd("whoami")
    t.blank(0.45)
    t.raw(wordmark(cfg["wordmark"], cx(3), t.y, 58, "a"), 58 + 26)
    t.row([(3, cfg["tagline"], C["sub"], 13)])
    t.blank(0.75)
    t.cmd("cat about.txt")
    t.blank(0.45)
    for k, v in cfg["about"][:5]:
        if k == "status":
            t.raw(txt(cx(3), t.y, k, fill=C["dim"])
                  + f'<circle cx="{cx(13.5):.1f}" cy="{t.y - 4.5:.1f}" r="4" '
                    f'fill="{C["green"]}"/>'
                  + txt(cx(16), t.y, v), LINE)
        else:
            t.row([(3, k, C["dim"], FS), (13, v, C["text"], FS)])
    t.blank(0.6)
    t.cursor()
    return t.render()


def stack_panel(cfg, d):
    t = Term("b", f'{cfg["shell_user"]} — ~/stack — zsh')
    t.cmd("cat stack.txt")
    t.blank(0.5)
    accents = [C["blue"], C["mauve"], C["peach"], C["teal"], C["green"]]
    for i, (group, items) in enumerate(cfg["stack"].items()):
        cells = [(3, group, accents[i % len(accents)], FS)]
        col = 15
        for j, item in enumerate(items):
            if j:
                cells.append((col - 2, "·", C["dim"], FS))
            cells.append((col, item, C["text"], FS))
            col += len(item) + 3
        t.row(cells)
        t.blank(0.28)
    t.blank(0.4)
    t.cursor()
    return t.render()


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def activity(cfg, d):
    t = Term("c", f'{cfg["shell_user"]} — ~/activity — zsh')
    weeks = [(datetime.date.fromisoformat(k), v) for k, v in d["weeks"]]
    vals = [v for _, v in weeks]
    vmax = max(vals) or 1
    peak_i = vals.index(vmax)

    t.cmd("activity --window 12m")
    t.blank(0.45)

    x0, x1 = cx(3), WINX + WINW - 26
    top, base = t.y, t.y + 108
    px = [x0 + (x1 - x0) * i / max(1, len(vals) - 1) for i in range(len(vals))]
    py = [base - (v / vmax) * (base - top) for v in vals]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(px, py))
    line = " ".join(("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}"
                    for i, (x, y) in enumerate(zip(px, py)))
    t.raw(f'<line x1="{x0:.1f}" y1="{base}" x2="{x1:.1f}" y2="{base}" '
          f'stroke="{C["edge"]}" stroke-width="1"/>'
          f'<polygon points="{px[0]:.1f},{base} {pts} {px[-1]:.1f},{base}" '
          f'fill="url(#arc)"/>'
          f'<path d="{line}" fill="none" stroke="{C["blue"]}" stroke-width="1.7" '
          f'stroke-linejoin="round"/>'
          f'<circle cx="{px[peak_i]:.1f}" cy="{py[peak_i]:.1f}" r="3.4" fill="none" '
          f'stroke="{C["peach"]}" stroke-width="1.3" opacity=".4">'
          f'<animate attributeName="r" values="3.4;12" dur="2.8s" '
          f'repeatCount="indefinite"/>'
          f'<animate attributeName="opacity" values=".4;0" dur="2.8s" '
          f'repeatCount="indefinite"/></circle>'
          f'<circle cx="{px[peak_i]:.1f}" cy="{py[peak_i]:.1f}" r="3.4" '
          f'fill="{C["win"]}" stroke="{C["peach"]}" stroke-width="1.8"/>'
          + txt(x1, top + 4, f"peak {vmax}/week", size=11.5, fill=C["dim"],
                anchor="end"))
    t.gap(108 + 22)

    seen, ml = None, []
    for i, (dt, _) in enumerate(weeks):
        if dt.month != seen and (not ml or px[i] - ml[-1][0] > 24):
            seen = dt.month
            ml.append((px[i], MONTHS[dt.month - 1]))
        seen = dt.month
    t.raw("".join(txt(x, t.y, m, size=11, fill=C["dim"]) for x, m in ml))
    t.blank(1.1)

    t.cmd("languages --by bytes")
    t.blank(0.55)
    total = sum(v for _, v in d["languages"]) or 1
    rows = [(k, v * 100.0 / total) for k, v in d["languages"][:6]]
    cells, bar_cols = 22, 22
    y0 = t.y
    for i, (name, pct) in enumerate(rows):
        col = 3 if i % 2 == 0 else 49
        y = y0 + (i // 2) * (LINE + 4)
        colr = LANG_COLORS[i % len(LANG_COLORS)]
        lit = max(1, round(pct / 100.0 * cells))
        seg = "".join(
            f'<rect x="{cx(col + 12) + j * CH:.1f}" y="{y - 10:.1f}" '
            f'width="{CH - 1.8:.1f}" height="10" rx="1.5" '
            f'fill="{colr if j < lit else C["track"]}"/>' for j in range(cells))
        t.raw(txt(cx(col), y, name.lower(), size=13, fill=C["sub"]) + seg
              + txt(cx(col + 12 + bar_cols + 1.5), y, f"{pct:.1f}%", size=12.5,
                    fill=C["dim"]))
    t.y = y0 + ((len(rows) + 1) // 2) * (LINE + 4)
    t.blank(0.45)
    t.cursor()
    return t.render()


def button(i, link):
    lab = link["label"]
    accent = ACCENTS.get(link.get("accent", "blue"), C["blue"])
    fs, ch = 12.5, 7.5
    w, h = int(38 + len(lab) * ch + 18), 36
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}" role="img" font-family="{MONO}">'
            f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="8" '
            f'fill="{C["win"]}" stroke="{C["edge"]}" stroke-width="1"/>'
            f'<circle cx="19" cy="{h / 2:.0f}" r="4" fill="{accent}"/>'
            + txt(32, h / 2 + 4.4, lab, size=fs, fill=C["text"]) + "</svg>")


# --------------------------------------------------------------- readme out

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def ver(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:8]


def write_readme(cfg, d, links):
    u = cfg["user"]

    def src(name):
        return f"assets/{name}?v={ver(os.path.join(ASSETS, name))}"

    who = cfg["tagline"].replace("  ·  ", ", ").lower()
    row = "&nbsp;&nbsp;".join(
        f'<a href="{esc(l["url"])}"><img src="{src(fn)}" height="36" '
        f'alt="{esc(l["label"])}"></a>' for fn, l in links)
    L = ["<!-- Generated by scripts/generate.py from config.json. "
         "Edit config.json, not this file. -->", "",
         '<div align="center">', "",
         f'<img src="{src("hero.svg")}" width="100%" '
         f'alt="{esc(cfg["shell_user"])} — {esc(who)}">', "", row, "", "</div>", "",
         f'<img src="{src("stack.svg")}" width="100%" '
         f'alt="Stack — {esc(", ".join(cfg["stack"]))}">', "",
         f'<img src="{src("activity.svg")}" width="100%" '
         f'alt="Contribution activity over {len(d["weeks"])} weeks, '
         f'and language mix across {d["repos_own"]} source repositories">', "",
         '<div align="center"><sub>',
         f'Self-hosted SVG, redrawn daily by '
         f'<a href="https://github.com/{u}/{u}/actions">GitHub Actions</a> · '
         f'last sync {d["generated"]}', "</sub></div>", ""]
    with open(os.path.join(ROOT, "README.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))


def main():
    cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    os.makedirs(ASSETS, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)
    snap = os.path.join(DATA, "snapshot.json")

    if "--offline" in sys.argv:
        d = json.load(open(snap, encoding="utf-8"))
        print("using cached snapshot")
    else:
        try:
            d = collect(cfg["user"])
            with open(snap, "w", encoding="utf-8", newline="\n") as f:
                json.dump(d, f, indent=1)
        except Exception as exc:                  # noqa: BLE001 - never fail the Action
            print(f"live fetch failed ({exc}); falling back to cache", file=sys.stderr)
            d = json.load(open(snap, encoding="utf-8"))

    def put(name, body):
        with open(os.path.join(ASSETS, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(body + "\n")
        print(f"  {name:<16} {len(body) // 1024 or 1} KB")

    put("hero.svg", hero(cfg, d))
    put("stack.svg", stack_panel(cfg, d))
    put("activity.svg", activity(cfg, d))
    links = []
    for i, link in enumerate(cfg["links"]):
        fn = f"link-{slug(link['label'])}.svg"
        put(fn, button(i, link))
        links.append((fn, link))

    write_readme(cfg, d, links)
    print(f"README.md written · {len(d['weeks'])} weeks · "
          f"{len(d['languages'])} languages · {COLS} columns · sync {d['generated']}")


if __name__ == "__main__":
    main()
