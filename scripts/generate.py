#!/usr/bin/env python3
"""
Render every SVG panel of the profile README from config.json + live GitHub data.

Stdlib only -- no pip install, so the GitHub Action stays fast and dependency free.
Everything it reads is public, so no token is required. If GITHUB_TOKEN is present
it is used purely to raise the REST rate limit.

    python scripts/generate.py            # fetch live data and render
    python scripts/generate.py --offline  # render from cache (data/snapshot.json)
"""

import collections
import datetime
import hashlib
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
DATA = os.path.join(ROOT, "data")
UA = "xematin-profile-generator"

# ---------------------------------------------------------------- design tokens

C = {
    "bg":     "#05080a",
    "panel":  "#090e13",
    "chip":   "#0a1219",
    "grid":   "#0d1720",
    "grid2":  "#142430",
    "rule":   "#1d3240",
    "ink":    "#e2eff7",
    "dim":    "#6b879a",
    "dim2":   "#9db6c6",
    "muted":  "#3e5666",
    "ghost":  "#2a4352",
    "cyan":   "#22e3ff",
    "cyand":  "#0e7f94",
    "amber":  "#ffb454",
    "violet": "#a78bfa",
    "lime":   "#8bff6e",
    "rose":   "#ff6b8a",
}
MONO = "ui-monospace,'SF Mono',SFMono-Regular,Menlo,Consolas,'DejaVu Sans Mono',monospace"
ACCENTS = {"cyan": C["cyan"], "amber": C["amber"], "violet": C["violet"],
           "lime": C["lime"], "rose": C["rose"]}
LANG_COLORS = [C["cyan"], C["amber"], C["violet"], C["lime"], C["rose"], C["cyand"]]


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def tw(text, size, ratio=0.615):
    """Approximate rendered width of monospace text."""
    return len(str(text)) * size * ratio


def txt(x, y, s, size=11, fill=None, anchor="start", ls=0, weight=None, opacity=None,
        family=MONO, extra=""):
    a = [f'x="{x:.1f}"', f'y="{y:.1f}"', f'font-family="{family}"',
         f'font-size="{size}"', f'fill="{fill or C["ink"]}"']
    if anchor != "start":
        a.append(f'text-anchor="{anchor}"')
    if ls:
        a.append(f'letter-spacing="{ls}"')
    if weight:
        a.append(f'font-weight="{weight}"')
    if opacity is not None:
        a.append(f'opacity="{opacity}"')
    if extra:
        a.append(extra)
    return f'<text {" ".join(a)}>{esc(s)}</text>'


def label(x, y, s, fill=None, size=7.5, ls=2.4):
    return txt(x, y, s, size=size, fill=fill or C["muted"], ls=ls)


def delayed(attr, hidden, shown, delay, dur, splines="0.3 0 0.2 1"):
    """Play an element in without ever making its resting state the hidden one.

    The element keeps `shown` as its base attribute value, so a renderer that skips
    SMIL -- reduced motion, a still thumbnail, an image that never scrolls into view
    -- shows the finished panel instead of a blank one. The delay lives in keyTimes
    rather than in `begin`, so nothing flashes before the animation starts.
    """
    total = delay + dur
    return (f'<animate attributeName="{attr}" values="{hidden};{hidden};{shown}" '
            f'keyTimes="0;{delay / total:.4f};1" dur="{total:.2f}s" fill="freeze" '
            f'calcMode="spline" keySplines="0 0 1 1;{splines}"/>')


# ------------------------------------------------------------------- data layer

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
        key = dt - datetime.timedelta(days=(dt.weekday() + 1) % 7)   # week starts Sunday
        buckets[key] = buckets.get(key, 0) + n
    return list(buckets.items())


def collect(user):
    prof = fetch_json(f"https://api.github.com/users/{user}")
    repos = fetch_json(f"https://api.github.com/users/{user}/repos?per_page=100&sort=pushed")
    langs = collections.Counter()
    for r in repos:
        if r["fork"]:
            continue
        try:
            for k, v in fetch_json(r["languages_url"]).items():
                langs[k] += v
        except urllib.error.URLError:
            pass
    days = contributions(user)
    wk = weekly(days)
    return {
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%MZ"),
        "user": user,
        "since": prof["created_at"][:4],
        "repos_total": prof["public_repos"],
        "repos_own": sum(1 for r in repos if not r["fork"]),
        "days": days,
        "weeks": [[str(k), v] for k, v in wk],
        "languages": langs.most_common(12),
        "repo_meta": {r["name"]: {"lang": r["language"], "pushed": r["pushed_at"][:10],
                                  "stars": r["stargazers_count"],
                                  "home": r.get("homepage") or ""}
                      for r in repos},
    }


# ------------------------------------------------------------- shared chrome

def shell(w, h, uid, grid=True, vignette=True, inset=12):
    """Opening tag + defs + blueprint background shared by every panel."""
    d = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" ' f'viewBox="0 0 {w} {h}" width="{w}" '
         f'height="{h}" role="img" font-family="{MONO}">', "<defs>",
         f'<pattern id="gm{uid}" width="10" height="10" patternUnits="userSpaceOnUse">'
         f'<path d="M10 0V10M0 10H10" stroke="{C["grid"]}" stroke-width=".5" fill="none"/></pattern>',
         f'<pattern id="gM{uid}" width="50" height="50" patternUnits="userSpaceOnUse">'
         f'<path d="M50 0V50M0 50H50" stroke="{C["grid2"]}" stroke-width=".7" fill="none"/></pattern>',
         f'<radialGradient id="vg{uid}" cx="42%" cy="38%" r="80%">'
         f'<stop offset=".42" stop-color="#000" stop-opacity="0"/>'
         f'<stop offset="1" stop-color="#000" stop-opacity=".6"/></radialGradient>',
         f'<linearGradient id="sc{uid}" x1="0" y1="0" x2="0" y2="1">'
         f'<stop offset="0" stop-color="{C["cyan"]}" stop-opacity="0"/>'
         f'<stop offset=".5" stop-color="{C["cyan"]}" stop-opacity=".055"/>'
         f'<stop offset="1" stop-color="{C["cyan"]}" stop-opacity="0"/></linearGradient>',
         f'<filter id="gl{uid}" x="-60%" y="-60%" width="220%" height="220%">'
         f'<feGaussianBlur stdDeviation="3.4"/></filter>',
         f'<filter id="gs{uid}" x="-160%" y="-160%" width="420%" height="420%">'
         f'<feGaussianBlur stdDeviation="2"/></filter>', "</defs>",
         f'<rect width="{w}" height="{h}" fill="{C["bg"]}"/>']
    if grid:
        d.append(f'<rect width="{w}" height="{h}" fill="url(#gm{uid})"/>'
                 f'<rect width="{w}" height="{h}" fill="url(#gM{uid})"/>')
    if vignette:
        d.append(f'<rect width="{w}" height="{h}" fill="url(#vg{uid})"/>')
    if inset:
        i, iw, ih = inset, w - inset * 2, h - inset * 2
        d.append(f'<rect x="{i}.5" y="{i}.5" width="{iw - 1}" height="{ih - 1}" fill="none" '
                 f'stroke="{C["rule"]}" stroke-width="1"/>')
        L = 15
        for cx, cy, sx, sy in ((i, i, 1, 1), (w - i, i, -1, 1),
                               (i, h - i, 1, -1), (w - i, h - i, -1, -1)):
            d.append(f'<path d="M{cx},{cy + sy * L}V{cy}H{cx + sx * L}" fill="none" '
                     f'stroke="{C["cyand"]}" stroke-width="1.6"/>')
    return "\n".join(d)


def scanline(w, h, uid, inset=12, dur="9s"):
    band = 36
    return (f'<rect x="{inset}" y="{inset}" width="{w - inset * 2}" height="{band}" '
            f'fill="url(#sc{uid})"><animate attributeName="y" '
            f'values="{inset};{h - inset - band};{inset}" dur="{dur}" '
            f'repeatCount="indefinite"/></rect>')


def header_bar(w, y, left, right):
    return (f'<rect x="30" y="{y - 7}" width="5" height="5" fill="{C["cyan"]}"/>'
            + label(43, y, left, fill=C["dim"], size=8.5, ls=3)
            + txt(w - 30, y, right, size=8, fill=C["muted"], anchor="end", ls=1.8))


# -------------------------------------------------------------------- wordmark
# Stroke glyphs on a 90-unit cap height (y 20..110), straight segments only, so
# the draw-on animation reads like a pen plotter and no font has to be loaded.

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


def wordmark(text, x, y, target_w, uid):
    """Plotter-drawn logotype. Falls back to stroked text for unmapped glyphs."""
    text = text.upper()
    if any(ch not in GLYPHS for ch in text):
        return (f'<text x="{x}" y="{y + 84}" font-family="{MONO}" font-size="76" '
                f'letter-spacing="6" fill="none" stroke="{C["ink"]}" stroke-width="2.4">'
                f'{esc(text)}</text>', tw(text, 76) + len(text) * 6)
    strokes, cur = [], 0.0
    for ch in text:
        adv, paths = GLYPHS[ch]
        for p in paths:
            strokes.append((cur, p))
        cur += adv + GAP
    native = cur - GAP
    s = min(0.95, target_w / native)
    body = []
    for i, (off, p) in enumerate(strokes):
        body.append(
            f'<path transform="translate({off:.1f},0)" d="{p}" pathLength="100" '
            f'stroke-dasharray="100" stroke-dashoffset="0">'
            + delayed("stroke-dashoffset", 100, 0, 0.10 + i * 0.085, 1.15,
                      "0.16 1 0.3 1") + '</path>')
    inner = "".join(body)
    common = 'fill="none" stroke-linecap="square" stroke-linejoin="miter" stroke-width="7"'
    g = (f'<g transform="translate({x},{y}) scale({s:.4f})">'
         f'<g {common} stroke="{C["cyan"]}" filter="url(#gl{uid})" opacity=".34">{inner}'
         f'<animate attributeName="opacity" values=".20;.55;.20" dur="4.6s" '
         f'repeatCount="indefinite"/></g>'
         f'<g {common} stroke="{C["ink"]}">{inner}</g></g>')
    return g, native * s


# ------------------------------------------------------------------------ hero

def hero(cfg, d):
    w, h, uid = 1000, 300, "h"
    o = [shell(w, h, uid)]
    mark, mark_w = wordmark(cfg["wordmark"], 56, 30, 308, uid)
    o.append(mark)
    right = 56 + mark_w

    # underline with a solid cap, drawn once the logotype has landed
    o.append(f'<rect x="56" y="139" width="6" height="6" fill="{C["cyan"]}"/>')
    o.append(f'<line x1="62" y1="142" x2="{right:.0f}" y2="142" stroke="{C["cyand"]}" '
             f'stroke-width="1.4" stroke-dasharray="{right - 62:.0f}" '
             f'stroke-dashoffset="0">'
             + delayed("stroke-dashoffset", f"{right - 62:.0f}", 0, 0.95, 0.8)
             + '</line>')

    # cycling role readout with a blinking caret
    roles = cfg["roles"][:3]
    cyc = len(roles) * 3.0
    for i, r in enumerate(roles):
        rw = tw(r, 11.5) + len(r) * 3.4          # caret rides the end of this role
        caret = (f'<rect x="{56 + rw + 4:.0f}" y="159" width="7" height="11" '
                 f'fill="{C["cyan"]}"><animate attributeName="opacity" values="1;1;0;0" '
                 f'keyTimes="0;.49;.5;1" dur="1.05s" repeatCount="indefinite"/></rect>')
        o.append(f'<g opacity="{1 if i == 0 else 0}">'
                 f'<animate attributeName="opacity" values="0;1;1;0;0" '
                 f'keyTimes="0;0.05;0.30;0.35;1" dur="{cyc}s" begin="{i * 3.0}s" '
                 f'repeatCount="indefinite"/>'
                 + txt(56, 168, r, size=11.5, fill=C["dim2"], ls=3.4) + caret + "</g>")

    # drafting callouts pointing back at the logotype
    for cy, ly, text in ((82, 60, cfg["callout_a"]), (104, 128, cfg["callout_b"])):
        o.append('<g opacity="1">' + delayed("opacity", 0, 1, 1.35, 0.7)
                 + f'<path d="M{right + 8:.0f},{cy} L{right + 62:.0f},{ly} H{right + 120:.0f}" '
                 f'fill="none" stroke="{C["rule"]}" stroke-width="1"/>'
                 f'<circle cx="{right + 8:.0f}" cy="{cy}" r="2.3" fill="{C["cyan"]}"/>'
                 + label(right + 128, ly + 3.4, text, fill=C["dim"], size=8.5, ls=2.2)
                 + "</g>")

    # measuring tape with a travelling index
    tx0, tx1, ty = 56, 724, 192
    o.append(f'<line x1="{tx0}" y1="{ty}" x2="{tx1}" y2="{ty}" stroke="{C["ghost"]}" '
             f'stroke-width="1"/>')
    ticks = []
    for i in range((tx1 - tx0) // 8 + 1):
        x = tx0 + i * 8
        ln = 8 if i % 5 == 0 else 4
        col = C["dim"] if i % 5 == 0 else C["ghost"]
        ticks.append(f'<line x1="{x}" y1="{ty}" x2="{x}" y2="{ty - ln}" stroke="{col}" '
                     f'stroke-width="1"/>')
    o.append(f'<g shape-rendering="crispEdges">{"".join(ticks)}</g>')
    o.append(f'<g><animateTransform attributeName="transform" type="translate" '
             f'values="0 0;{tx1 - tx0 - 8} 0;0 0" dur="11s" calcMode="spline" '
             f'keyTimes="0;0.5;1" keySplines="0.4 0 0.6 1;0.4 0 0.6 1" '
             f'repeatCount="indefinite"/>'
             f'<line x1="{tx0}" y1="{ty - 13}" x2="{tx0}" y2="{ty + 5}" stroke="{C["cyan"]}" '
             f'stroke-width="1.4"/>'
             f'<path d="M{tx0 - 4},{ty - 13} H{tx0 + 4} L{tx0},{ty - 7} Z" '
             f'fill="{C["cyan"]}"/></g>')

    # rotary encoder instrument
    ecx, ecy = 838, 112

    def ring(r, sw, col, op=1.0):
        return (f'<circle cx="{ecx}" cy="{ecy}" r="{r}" fill="none" stroke="{col}" '
                f'stroke-width="{sw}" opacity="{op}"/>')

    o.append(ring(84, 1, C["rule"]) + ring(46, 1, C["rule"], .8) + ring(15, 1, C["cyand"]))
    outer = []
    for i in range(72):
        a = math.radians(i * 5)
        ln = 9 if i % 6 == 0 else 5
        col = C["cyand"] if i % 6 == 0 else C["grid2"]
        outer.append(
            f'<line x1="{ecx + 76 * math.sin(a):.1f}" y1="{ecy - 76 * math.cos(a):.1f}" '
            f'x2="{ecx + (76 - ln) * math.sin(a):.1f}" y2="{ecy - (76 - ln) * math.cos(a):.1f}" '
            f'stroke="{col}" stroke-width="1"/>')
    o.append(f'<g>{"".join(outer)}</g>')
    for r0, r1, count, dur, rev, col in ((56, 70, 24, "34s", False, C["cyand"]),
                                         (24, 40, 14, "21s", True, C["rule"])):
        seg, step = [], 360.0 / count
        for i in range(count):
            a0, a1 = math.radians(i * step), math.radians(i * step + step * 0.46)
            seg.append(f'<path d="M{ecx + r0 * math.sin(a0):.1f},{ecy - r0 * math.cos(a0):.1f} '
                       f'L{ecx + r1 * math.sin(a0):.1f},{ecy - r1 * math.cos(a0):.1f} '
                       f'L{ecx + r1 * math.sin(a1):.1f},{ecy - r1 * math.cos(a1):.1f} '
                       f'L{ecx + r0 * math.sin(a1):.1f},{ecy - r0 * math.cos(a1):.1f} Z" '
                       f'fill="{col}" opacity=".5"/>')
        a, b = (360, 0) if rev else (0, 360)
        o.append(f'<g>{"".join(seg)}<animateTransform attributeName="transform" type="rotate" '
                 f'from="{a} {ecx} {ecy}" to="{b} {ecx} {ecy}" dur="{dur}" '
                 f'repeatCount="indefinite"/></g>')
    swx = ecx + 74 * math.sin(math.radians(52))
    swy = ecy - 74 * math.cos(math.radians(52))
    o.append(f'<g><path d="M{ecx},{ecy} L{ecx},{ecy - 74} A74,74 0 0,1 {swx:.1f},{swy:.1f} Z" '
             f'fill="{C["cyan"]}" opacity=".07"/>'
             f'<line x1="{ecx}" y1="{ecy}" x2="{ecx}" y2="{ecy - 78}" stroke="{C["cyan"]}" '
             f'stroke-width="1.2" opacity=".5"/>'
             f'<animateTransform attributeName="transform" type="rotate" '
             f'from="0 {ecx} {ecy}" to="360 {ecx} {ecy}" dur="6.5s" '
             f'repeatCount="indefinite"/></g>')
    o.append(f'<circle cx="{ecx}" cy="{ecy}" r="5" fill="{C["cyan"]}" filter="url(#gs{uid})"/>'
             f'<circle cx="{ecx}" cy="{ecy}" r="3" fill="{C["ink"]}"/>'
             f'<path d="M{ecx - 5},{ecy - 90} H{ecx + 5} L{ecx},{ecy - 82} Z" '
             f'fill="{C["cyand"]}"/>')

    # drawing title block
    o.append(f'<rect x="12" y="211" width="108" height="3" fill="{C["cyan"]}"/>')
    o.append(f'<line x1="12" y1="214" x2="988" y2="214" stroke="{C["rule"]}" stroke-width="1"/>')
    edges = [12, 256, 500, 744, 988]
    for i, (lab, val) in enumerate(cfg["titleblock"][:4]):
        cx = edges[i] + 22
        if i:
            o.append(f'<line x1="{edges[i]}" y1="214" x2="{edges[i]}" y2="288" '
                     f'stroke="{C["rule"]}" stroke-width="1"/>')
        o.append(label(cx, 241, lab))
        if lab.upper() == "STATUS":
            o.append(f'<circle cx="{cx + 4}" cy="261" r="3.4" fill="{C["lime"]}" '
                     f'filter="url(#gs{uid})">'
                     f'<animate attributeName="opacity" values="1;.25;1" dur="2.4s" '
                     f'repeatCount="indefinite"/></circle>')
            o.append(txt(cx + 16, 265, val, size=12, fill=C["ink"], ls=1.2))
        else:
            o.append(txt(cx, 265, val, size=12, fill=C["ink"], ls=1.2))

    o.append(scanline(w, h, uid, dur="11s"))
    o.append("</svg>")
    return "\n".join(o)


# ----------------------------------------------------------------------- stack

def chip(x, y, text, accent, delay):
    cw = 13 + tw(text, 10.5) + len(text) * 0.8 + 14
    return ('<g opacity="1">' + delayed("opacity", 0, 1, delay, 0.5)
            + f'<rect x="{x:.1f}" y="{y}" width="{cw:.1f}" height="26" rx="3" '
            f'fill="{C["chip"]}" stroke="{C["rule"]}" stroke-width="1"/>'
            f'<rect x="{x:.1f}" y="{y}" width="2.5" height="26" rx="1.2" fill="{accent}"/>'
            + txt(x + 13, y + 17.5, text, size=10.5, fill=C["ink"], ls=0.8) + "</g>"), cw


def flow_row(x0, y, gx, gw, items, accent, t0):
    """Lay chips out left to right, wrapping inside gw. Returns (markup, rows)."""
    out, cx, cy, rows = [], gx, y, 1
    for i, it in enumerate(items):
        m, cw = chip(cx, cy, it, accent, t0 + i * 0.07)
        if cx > gx and cx + cw > gx + gw:
            cy += 35
            rows += 1
            cx = gx
            m, cw = chip(cx, cy, it, accent, t0 + i * 0.07)
        out.append(m)
        cx += cw + 8
    return "".join(out), rows


def stack(cfg, d):
    w, uid = 1000, "s"
    groups = list(cfg["stack"].items())
    accents = [C["cyan"], C["amber"], C["violet"], C["lime"]]
    gw, cols = 465, [30, 505]

    def group_block(gx, gy, name, items, accent, t0):
        m = [f'<rect x="{gx}" y="{gy - 7}" width="5" height="5" fill="{accent}"/>',
             label(gx + 12, gy, name, fill=C["dim"], size=8.5, ls=2.8)]
        lw = tw(name, 8.5) + len(name) * 2.8 + 26
        m.append(f'<line x1="{gx + lw:.0f}" y1="{gy - 3.5}" x2="{gx + gw}" y2="{gy - 3.5}" '
                 f'stroke="{C["grid2"]}" stroke-width="1"/>')
        body, rows = flow_row(gx, gy + 16, gx, gw, items, accent, t0)
        m.append(body)
        return "".join(m), rows

    top = []
    top_rows = 1
    for i in range(min(2, len(groups))):
        name, items = groups[i]
        mk, rows = group_block(cols[i], 54, name, items, accents[i], 0.25 + i * 0.3)
        top.append(mk)
        top_rows = max(top_rows, rows)

    bus_y = 54 + 16 + top_rows * 35 + 12
    bot_label_y = bus_y + 28
    bot, bot_rows = [], 1
    for i in range(2, min(4, len(groups))):
        name, items = groups[i]
        mk, rows = group_block(cols[i - 2], bot_label_y, name, items, accents[i], 0.5 + (i - 2) * 0.3)
        bot.append(mk)
        bot_rows = max(bot_rows, rows)

    h = bot_label_y + 16 + bot_rows * 35 + 22
    o = [shell(w, h, uid)]
    o.append(header_bar(w, 30, "SYSTEM SCHEMATIC", f'SHEET 02 · REV {d["generated"][:10]}'))
    o.extend(top)

    # signal bus with flowing current and stubs into each group
    o.append(f'<line x1="30" y1="{bus_y}" x2="970" y2="{bus_y}" stroke="{C["rule"]}" '
             f'stroke-width="2"/>')
    o.append(f'<line x1="30" y1="{bus_y}" x2="970" y2="{bus_y}" stroke="{C["cyan"]}" '
             f'stroke-width="1.4" stroke-dasharray="16 12" opacity=".45">'
             f'<animate attributeName="stroke-dashoffset" from="56" to="0" dur="1.9s" '
             f'repeatCount="indefinite"/></line>')
    for cx in (262, 738):
        o.append(f'<line x1="{cx}" y1="{bus_y - 16}" x2="{cx}" y2="{bus_y + 16}" '
                 f'stroke="{C["rule"]}" stroke-width="1"/>'
                 f'<rect x="{cx - 3}" y="{bus_y - 3}" width="6" height="6" fill="{C["cyand"]}"/>')
    for i, bg in enumerate((0, 1.6, 3.2)):
        o.append(f'<circle cx="30" cy="{bus_y}" r="2.6" fill="{C["cyan"]}" '
                 f'filter="url(#gs{uid})">'
                 f'<animate attributeName="cx" from="30" to="970" dur="4.8s" '
                 f'begin="{bg}s" repeatCount="indefinite"/>'
                 f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.06;.94;1" '
                 f'dur="4.8s" begin="{bg}s" repeatCount="indefinite"/></circle>')
    o.extend(bot)
    o.append(scanline(w, h, uid, dur="13s"))
    o.append("</svg>")
    return "\n".join(o)


# ---------------------------------------------------------------------- signal

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def signal(cfg, d):
    w, h, uid = 1000, 348, "g"
    weeks = [(datetime.date.fromisoformat(k), v) for k, v in d["weeks"]]
    vals = [v for _, v in weeks]
    vmax = max(vals) or 1
    active = sum(1 for v in vals if v > 0)
    peak_i = vals.index(vmax)

    sx0, sx1, sy0, sy1 = 30, 648, 50, 250
    base, top = sy1 - 16, sy0 + 26
    span = sx1 - sx0 - 24
    px = [sx0 + 12 + (span * i / max(1, len(vals) - 1)) for i in range(len(vals))]
    py = [base - (v / vmax) * (base - top) for v in vals]

    o = [shell(w, h, uid)]
    o.append(header_bar(w, 30, "ACTIVITY SIGNAL",
                        f'SYNC {d["generated"]} · {len(vals)} SAMPLES'))
    o.append(f'<defs><linearGradient id="ar{uid}" x1="0" y1="0" x2="0" y2="1">'
             f'<stop offset="0" stop-color="{C["cyan"]}" stop-opacity=".26"/>'
             f'<stop offset="1" stop-color="{C["cyan"]}" stop-opacity="0"/>'
             f'</linearGradient></defs>')

    # scope well + graticule
    o.append(f'<rect x="{sx0}" y="{sy0}" width="{sx1 - sx0}" height="{sy1 - sy0}" '
             f'fill="#070c11" stroke="{C["rule"]}" stroke-width="1"/>')
    grat = []
    for i in range(1, 10):
        x = sx0 + (sx1 - sx0) * i / 10
        grat.append(f'<line x1="{x:.1f}" y1="{sy0}" x2="{x:.1f}" y2="{sy1}" '
                    f'stroke="{C["grid"]}" stroke-width="1" stroke-dasharray="1 4"/>')
    for i in range(1, 6):
        y = sy0 + (sy1 - sy0) * i / 6
        grat.append(f'<line x1="{sx0}" y1="{y:.1f}" x2="{sx1}" y2="{y:.1f}" '
                    f'stroke="{C["grid"]}" stroke-width="1" stroke-dasharray="1 4"/>')
    o.append("".join(grat))
    o.append(f'<line x1="{sx0}" y1="{base}" x2="{sx1}" y2="{base}" stroke="{C["grid2"]}" '
             f'stroke-width="1"/>')

    # impulse stems, so sparse weeks still read as a deliberate signal
    stems = [f'<line x1="{px[i]:.1f}" y1="{base}" x2="{px[i]:.1f}" y2="{py[i]:.1f}" '
             f'stroke="{C["cyand"]}" stroke-width="1" opacity=".5"/>'
             for i, v in enumerate(vals) if v > 0]
    o.append(f'<g opacity="1">{"".join(stems)}'
             + delayed("opacity", 0, 1, 1.1, 0.9) + '</g>')

    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(px, py))
    o.append(f'<polygon points="{px[0]:.1f},{base} {pts} {px[-1]:.1f},{base}" '
             f'fill="url(#ar{uid})" opacity="1">'
             + delayed("opacity", 0, 1, 1.4, 1.0) + '</polygon>')
    trace = " ".join(("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}"
                     for i, (x, y) in enumerate(zip(px, py)))
    draw = delayed("stroke-dashoffset", 100, 0, 0.3, 2.4)
    # glow pass, then the crisp pass; both draw themselves so neither depends on the other
    for ident, extra in ((f'filter="url(#gs{uid})" opacity=".6"', ""),
                         (f'id="trc{uid}"', "")):
        o.append(f'<path d="{trace}" fill="none" stroke="{C["cyan"]}" stroke-width="1.8" '
                 f'stroke-linejoin="round" pathLength="100" stroke-dasharray="100" '
                 f'stroke-dashoffset="0" {ident}>{draw}</path>')
    o.append(f'<circle r="3.2" fill="{C["ink"]}" opacity="0">'
             f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.04;.96;1" '
             f'dur="8s" begin="2.7s" repeatCount="indefinite"/>'
             f'<animateMotion dur="8s" begin="2.7s" repeatCount="indefinite">'
             f'<mpath href="#trc{uid}" xlink:href="#trc{uid}"/></animateMotion></circle>')

    # peak crosshair
    o.append('<g opacity="1">' + delayed("opacity", 0, 1, 2.5, 0.6)
             + f'<circle cx="{px[peak_i]:.1f}" cy="{py[peak_i]:.1f}" r="4.5" fill="none" '
             f'stroke="{C["amber"]}" stroke-width="1.2"/>'
             f'<line x1="{px[peak_i]:.1f}" y1="{py[peak_i] - 9:.1f}" x2="{px[peak_i]:.1f}" '
             f'y2="{py[peak_i] - 17:.1f}" stroke="{C["amber"]}" stroke-width="1"/>'
             + txt(px[peak_i], py[peak_i] - 22, f"PEAK {vmax}", size=8, fill=C["amber"],
                   anchor="middle", ls=1.4) + "</g>")

    # month ruler
    seen, ml = None, []
    for i, (dt, _) in enumerate(weeks):
        if dt.month != seen:
            seen = dt.month
            ml.append(f'<line x1="{px[i]:.1f}" y1="{sy1}" x2="{px[i]:.1f}" y2="{sy1 + 5}" '
                      f'stroke="{C["rule"]}" stroke-width="1"/>'
                      + txt(px[i], sy1 + 16, MONTHS[dt.month - 1], size=7.5,
                            fill=C["muted"], anchor="middle", ls=1.2))
    o.append("".join(ml))

    # readout strip under the scope
    ro = [("WINDOW", f"{len(vals)} WEEKS"), ("ACTIVE", f"{active} WEEKS"),
          ("PEAK", f"{vmax} / WEEK"), ("REPOS", str(d["repos_total"]))]
    o.append(f'<line x1="{sx0}" y1="282" x2="{sx1}" y2="282" stroke="{C["rule"]}" '
             f'stroke-width="1"/>')
    for i, (lab, val) in enumerate(ro):
        x = sx0 + 6 + i * ((sx1 - sx0) / len(ro))
        o.append(label(x, 296, lab, size=7) + txt(x, 312, val, size=10.5, fill=C["ink"], ls=1))

    # language mix
    lx0, lx1 = 676, 970
    langs = d["languages"][:5]
    total = sum(v for _, v in d["languages"]) or 1
    shown = sum(v for _, v in langs)
    rows = [(k, v * 100.0 / total) for k, v in langs]
    if total - shown > 0:
        rows.append(("OTHER", (total - shown) * 100.0 / total))
    o.append(f'<rect x="{lx0 - 8}" y="{sy0}" width="{lx1 - lx0 + 16}" height="{316 - sy0}" '
             f'rx="2" fill="{C["panel"]}" stroke="{C["rule"]}" stroke-width="1"/>')
    o.append(f'<rect x="{lx0 - 8}" y="{sy0}" width="5" height="5" fill="{C["amber"]}"/>')
    o.append(label(lx0 + 4, sy0 + 20, "LANGUAGE MIX", fill=C["dim"], size=8.5, ls=2.8))

    cx = lx0
    for i, (k, pct) in enumerate(rows):
        seg = (lx1 - lx0) * pct / 100.0
        col = LANG_COLORS[i % len(LANG_COLORS)]
        o.append(f'<rect x="{cx:.1f}" y="{sy0 + 32}" width="{seg:.1f}" height="11" '
                 f'fill="{col}" opacity=".9">'
                 + delayed("width", 0, f"{seg:.1f}", 0.8 + i * 0.1, 0.9, "0.2 0 0 1")
                 + '</rect>')
        cx += seg
    for i, (k, pct) in enumerate(rows):
        y = sy0 + 74 + i * 30
        col = LANG_COLORS[i % len(LANG_COLORS)]
        o.append(f'<rect x="{lx0}" y="{y - 7}" width="6" height="6" rx="1" fill="{col}"/>')
        o.append(txt(lx0 + 14, y, k.upper(), size=10, fill=C["ink"], ls=1.1))
        o.append(txt(lx1, y, f"{pct:.1f}%", size=10, fill=C["dim"], anchor="end", ls=.6))
        o.append(f'<rect x="{lx0 + 14}" y="{y + 7}" width="{lx1 - lx0 - 14}" height="2.5" '
                 f'rx="1.2" fill="{C["grid2"]}"/>')
        bw = (lx1 - lx0 - 14) * pct / 100.0
        o.append(f'<rect x="{lx0 + 14}" y="{y + 7}" width="{bw:.1f}" height="2.5" rx="1.2" '
                 f'fill="{col}" opacity=".85">'
                 + delayed("width", 0, f"{bw:.1f}", 1.0 + i * 0.12, 1.1, "0.2 0 0 1")
                 + '</rect>')

    o.append(f'<line x1="{lx0}" y1="292" x2="{lx1}" y2="292" stroke="{C["grid2"]}" '
             f'stroke-width="1"/>')
    o.append(label(lx0, 306, f'{d["repos_own"]} SOURCE REPOSITORIES ANALYSED', size=7.5, ls=1.6))
    o.append(scanline(w, h, uid, dur="15s"))
    o.append("</svg>")
    return "\n".join(o)


# --------------------------------------------------------------- module blades

def module(idx, m, meta, d):
    w, h, uid = 1000, 104, f"m{idx}"
    accent = ACCENTS.get(m.get("accent", "cyan"), C["cyan"])
    o = [shell(w, h, uid, vignette=False, inset=0)]
    o.append(f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" fill="none" '
             f'stroke="{C["rule"]}" stroke-width="1"/>')
    o.append(f'<rect x="0" y="0" width="3.5" height="{h}" fill="{accent}" opacity=".8"/>')
    o.append(f'<rect x="0" y="-30" width="3.5" height="30" fill="{C["ink"]}" '
             f'opacity=".85">'
             f'<animate attributeName="y" values="-30;{h};{h}" dur="4.5s" '
             f'begin="{idx * 0.6}s" repeatCount="indefinite"/></rect>')
    o.append(txt(24, 58, f"{idx:02d}", size=17, fill=C["ghost"], ls=1))
    o.append(f'<line x1="60" y1="20" x2="60" y2="84" stroke="{C["grid2"]}" stroke-width="1"/>')

    o.append(txt(76, 43, m["repo"], size=18.5, fill=C["ink"], ls=.4))
    o.append(txt(76, 65, m["desc"], size=11.5, fill=C["dim"], ls=.2))
    cx = 76
    for t in m.get("tags", []):
        cw = 9 + tw(t, 8.5) + len(t) * 1.6 + 9
        o.append(f'<rect x="{cx:.1f}" y="76" width="{cw:.1f}" height="17" rx="2" '
                 f'fill="{C["chip"]}" stroke="{C["rule"]}" stroke-width="1"/>'
                 + txt(cx + 9, 88, t, size=8.5, fill=C["muted"], ls=1.6))
        cx += cw + 6

    lang = (meta.get("lang") or "MIXED").upper()
    lw = tw(lang, 10.5) + len(lang)
    o.append(f'<rect x="{940 - lw - 13:.1f}" y="36" width="6" height="6" rx="1" '
             f'fill="{accent}"/>')
    o.append(txt(940, 43, lang, size=10.5, fill=C["ink"], anchor="end", ls=1))
    o.append(txt(940, 65, f'UPDATED {meta.get("pushed", "")}', size=9, fill=C["muted"],
                 anchor="end", ls=1.1))
    if meta.get("stars"):
        star = f'{meta["stars"]} STAR' + ("" if meta["stars"] == 1 else "S")
        o.append(txt(940, 85, star, size=9, fill=C["muted"],
                     anchor="end", ls=1.1))
    o.append(f'<g><path d="M952,52 H972 M965,45 L972,52 L965,59" fill="none" '
             f'stroke="{accent}" stroke-width="1.6" stroke-linecap="square"/>'
             f'<animateTransform attributeName="transform" type="translate" '
             f'values="0 0;5 0;0 0" dur="2.6s" begin="{idx * 0.3}s" '
             f'repeatCount="indefinite" calcMode="spline" keyTimes="0;.5;1" '
             f'keySplines="0.4 0 0.2 1;0.4 0 0.2 1"/></g>')
    o.append("</svg>")
    return "\n".join(o)


# ---------------------------------------------------------------- link buttons

def button(i, link):
    lab = link["label"].upper()
    accent = ACCENTS.get(link.get("accent", "cyan"), C["cyan"])
    tws = tw(lab, 9.5) + len(lab) * 2.6
    w, h, uid = int(22 + tws + 44), 40, f"b{i}"
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
         f'viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" font-family="{MONO}">',
         f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="2" fill="{C["chip"]}" '
         f'stroke="{C["rule"]}" stroke-width="1"/>']
    for cx, cy, sx, sy in ((5, 5, 1, 1), (w - 5, 5, -1, 1), (5, h - 5, 1, -1),
                           (w - 5, h - 5, -1, -1)):
        o.append(f'<path d="M{cx},{cy + sy * 8}V{cy}H{cx + sx * 8}" fill="none" '
                 f'stroke="{accent}" stroke-width="1.4"/>')
    o.append(txt(20, h / 2 + 3.4, lab, size=9.5, fill=C["ink"], ls=2.6))
    ax = w - 26
    o.append(f'<g><path d="M{ax},{h / 2} H{ax + 12} M{ax + 7},{h / 2 - 4.5} '
             f'L{ax + 12},{h / 2} L{ax + 7},{h / 2 + 4.5}" fill="none" stroke="{accent}" '
             f'stroke-width="1.4"/><animateTransform attributeName="transform" '
             f'type="translate" values="0 0;4 0;0 0" dur="2.4s" begin="{i * 0.25}s" '
             f'repeatCount="indefinite" calcMode="spline" keyTimes="0;.5;1" '
             f'keySplines="0.4 0 0.2 1;0.4 0 0.2 1"/></g>')
    o.append("</svg>")
    return "\n".join(o)


# ------------------------------------------------------------------- readme out

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def ver(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:8]


def write_readme(cfg, d, links, mods):
    u = cfg["user"]
    def src(name):
        return f"assets/{name}?v={ver(os.path.join(ASSETS, name))}"

    L = ["<!-- Generated by scripts/generate.py from config.json. Edit config.json, not this file. -->",
         "", '<div align="center">', "",
         f'<img src="{src("hero.svg")}" width="100%" '
         f'alt="{esc(cfg["wordmark"].title())} — {esc(" / ".join(cfg["roles"]).lower())}">',
         "", ""]
    row = []
    for fn, link in links:
        row.append(f'<a href="{esc(link["url"])}"><img src="{src(fn)}" height="40" '
                   f'alt="{esc(link["label"].title())}"></a>')
    L.append("&nbsp;&nbsp;".join(row))
    L += ["", "</div>", "", f'<p align="center"><sub>{esc(cfg["bio"])}</sub></p>', "",
          f'<img src="{src("stack.svg")}" width="100%" '
          f'alt="Stack schematic: {esc(" · ".join(k.lower() for k in cfg["stack"]))}">', ""]
    for fn, m in mods:
        url = m.get("url") or f"https://github.com/{u}/{m['repo']}"
        L.append(f'<a href="{esc(url)}"><img src="{src(fn)}" width="100%" '
                 f'alt="{esc(m["repo"])} — {esc(m["desc"])}"></a>')
        L.append("")
    L += ["", f'<img src="{src("signal.svg")}" width="100%" '
              f'alt="Contribution activity over the last {len(d["weeks"])} weeks '
              f'and language mix across {d["repos_own"]} source repositories">', "",
          '<div align="center"><sub>',
          f'Panels are self-hosted SVG, redrawn daily by '
          f'<a href="https://github.com/{u}/{u}/actions">GitHub Actions</a> · '
          f'last sync {d["generated"]}',
          "</sub></div>", ""]
    with open(os.path.join(ROOT, "README.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))


# ------------------------------------------------------------------------- main

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
        except Exception as exc:                      # noqa: BLE001 - never fail the Action
            print(f"live fetch failed ({exc}); falling back to cache", file=sys.stderr)
            d = json.load(open(snap, encoding="utf-8"))

    def put(name, body):
        with open(os.path.join(ASSETS, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(body + "\n")
        print(f"  {name:<20} {len(body) // 1024 or 1} KB")

    put("hero.svg", hero(cfg, d))
    put("stack.svg", stack(cfg, d))
    put("signal.svg", signal(cfg, d))

    links = []
    for i, link in enumerate(cfg["links"]):
        fn = f"link-{slug(link['label'])}.svg"
        put(fn, button(i, link))
        links.append((fn, link))

    mods = []
    for i, m in enumerate(cfg["modules"], 1):
        fn = f"module-{i:02d}.svg"
        put(fn, module(i, m, d["repo_meta"].get(m["repo"], {}), d))
        mods.append((fn, m))

    write_readme(cfg, d, links, mods)
    print(f"README.md written · {len(d['weeks'])} weeks · "
          f"{len(d['languages'])} languages · sync {d['generated']}")


if __name__ == "__main__":
    main()
