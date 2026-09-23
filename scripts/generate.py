#!/usr/bin/env python3
"""
Draw the profile panels -- an engineering-drawing identity plate, a stack
schematic and a contribution scope -- each inside a macOS window frame.

Stdlib only, so the GitHub Action needs no install step, and every endpoint it
reads is public, so it needs no token either.

    python scripts/generate.py            # fetch live data and render
    python scripts/generate.py --offline  # render from data/snapshot.json
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

# ------------------------------------------------------------------- palette

C = {
    "bg":     "#0b0e14",
    "bar":    "#0f141c",
    "grid":   "#141b26",
    "rule":   "#223041",
    "track":  "#1a2430",
    "ink":    "#e6edf3",
    "dim":    "#93a4b5",
    "muted":  "#64788a",
    "ghost":  "#3b4b5c",
    "cyan":   "#4dd8e8",
    "cyand":  "#1f7c8f",
    "amber":  "#f0a868",
    "violet": "#b39ffb",
    "green":  "#56d364",
    "rose":   "#f787a4",
    "close":  "#ff5f57",
    "min":    "#febc2e",
    "zoom":   "#28c840",
}
ACCENTS = {k: C[k] for k in ("cyan", "amber", "violet", "green", "rose")}
LANG_COLORS = [C["cyan"], C["amber"], C["violet"], C["green"], C["rose"], C["muted"]]

MONO = ("ui-monospace,'SF Mono',SFMono-Regular,Menlo,Monaco,'Cascadia Mono',"
        "'Segoe UI Mono','Roboto Mono','DejaVu Sans Mono',monospace")

# --------------------------------------------------------------------- frame

W = 1000                 # panel width
FX, FY = 12, 10          # frame origin
FW = W - FX * 2          # frame width
BAR = 50                 # macOS title bar height
R = 11                   # corner radius
PAD = 22                 # content padding inside the frame


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def tw(text, size, ls=0.0):
    """Width of a monospace run. 0.6em is the widest advance in the font stack."""
    return len(str(text)) * (size * 0.6 + ls)


def txt(x, y, s, size=12.5, fill=None, anchor="start", ls=0, opacity=None):
    a = [f'x="{x:.1f}"', f'y="{y:.1f}"', f'font-size="{size}"',
         f'fill="{fill or C["ink"]}"']
    if anchor != "start":
        a.append(f'text-anchor="{anchor}"')
    if ls:
        a.append(f'letter-spacing="{ls}"')
    if opacity is not None:
        a.append(f'opacity="{opacity}"')
    return f'<text {" ".join(a)}>{esc(s)}</text>'


def label(x, y, s, fill=None, size=10, ls=1.4):
    return txt(x, y, s, size=size, fill=fill or C["muted"], ls=ls)


# Motion rule: animation may only ADD, never hide.
#
# A README image can be painted with its SMIL timeline still sitting at t=0 --
# offscreen, throttled, scaled, captured as a still, or under reduced motion.
# Anything whose first keyframe is invisible therefore renders as an empty panel
# in exactly the cases nobody can reproduce. So there are no reveal fades and no
# draw-on strokes here: every mark is in its final place at t=0, and the moving
# parts (the encoder, the bus flow, the status LED, the peak ripple) all read
# correctly frozen at their first frame.


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
    return {
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%MZ"),
        "user": user,
        "since": prof["created_at"][:4],
        "repos_total": prof["public_repos"],
        "repos_own": sum(1 for r in repos if not r["fork"]),
        "weeks": [[str(k), v] for k, v in weekly(contributions(user))],
        "languages": langs.most_common(12),
    }


# ------------------------------------------------------------------ wordmark
# Stroke glyphs on a 90-unit cap height (y 20..110), straight segments only, so
# the logotype is identical everywhere and needs no font.

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


def wordmark(text, x, cap_top, height, uid):
    """Returns (markup, rendered width). Falls back to outlined text if unmapped."""
    text = text.upper()
    s = height / 90.0
    if any(ch not in GLYPHS for ch in text):
        return (f'<text x="{x}" y="{cap_top + height}" font-size="{height}" fill="none" '
                f'stroke="{C["ink"]}" stroke-width="2">{esc(text)}</text>',
                tw(text, height))
    strokes, cur = [], 0.0
    for ch in text:
        adv, paths = GLYPHS[ch]
        for p in paths:
            strokes.append((cur, p))
        cur += adv + GAP
    native = cur - GAP
    body = "".join(f'<path transform="translate({off:.1f},0)" d="{p}"/>'
                   for off, p in strokes)
    # userSpaceOnUse: a purely horizontal or vertical stroke has a zero-area
    # bounding box, and an objectBoundingBox gradient drops it entirely.
    grad = (f'<defs><linearGradient id="wm{uid}" gradientUnits="userSpaceOnUse" '
            f'x1="0" y1="0" x2="{native:.0f}" y2="0">'
            f'<stop offset="0" stop-color="{C["ink"]}"/>'
            f'<stop offset="1" stop-color="{C["cyan"]}"/>'
            f'<animate attributeName="x2" values="{native:.0f};{native * 2.6:.0f};'
            f'{native:.0f}" dur="12s" repeatCount="indefinite" calcMode="spline" '
            f'keyTimes="0;0.5;1" keySplines="0.4 0 0.6 1;0.4 0 0.6 1"/>'
            f'</linearGradient></defs>')
    g = (f'{grad}<g transform="translate({x:.1f},{cap_top - 20 * s:.1f}) '
         f'scale({s:.4f})" fill="none" stroke="url(#wm{uid})" stroke-width="7" '
         f'stroke-linecap="square" stroke-linejoin="miter">{body}</g>')
    return g, native * s


# --------------------------------------------------------------- window frame

def frame_open(h, uid, title):
    """macOS window chrome: rounded surface, three lights, centred title."""
    svg_h = int(FY + h + 22)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {svg_h}" '
        f'width="{W}" height="{svg_h}" role="img" font-family="{MONO}" '
        f'text-rendering="geometricPrecision">'
        f'<defs>'
        f'<pattern id="gr{uid}" width="50" height="50" patternUnits="userSpaceOnUse">'
        f'<path d="M50 0V50M0 50H50" stroke="{C["grid"]}" stroke-width="1" '
        f'fill="none"/></pattern>'
        f'<filter id="sh{uid}" x="-10%" y="-10%" width="120%" height="126%">'
        f'<feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#000" '
        f'flood-opacity=".32"/></filter>'
        f'<filter id="gl{uid}" x="-160%" y="-160%" width="420%" height="420%">'
        f'<feGaussianBlur stdDeviation="2.4"/></filter>'
        f'</defs>'
        f'<rect x="{FX}" y="{FY}" width="{FW}" height="{h:.0f}" rx="{R}" '
        f'fill="{C["bg"]}" filter="url(#sh{uid})"/>'
        f'<rect x="{FX}" y="{FY}" width="{FW}" height="{h:.0f}" rx="{R}" '
        f'fill="url(#gr{uid})"/>'
        f'<path d="M{FX},{FY + R} a{R},{R} 0 0 1 {R},-{R} h{FW - 2 * R} '
        f'a{R},{R} 0 0 1 {R},{R} v{BAR - R} h-{FW} z" fill="{C["bar"]}"/>'
        f'<line x1="{FX}" y1="{FY + BAR}" x2="{FX + FW}" y2="{FY + BAR}" '
        f'stroke="{C["rule"]}" stroke-width="1"/>'
        + "".join(f'<circle cx="{FX + 24 + i * 21}" cy="{FY + BAR / 2:.0f}" r="6.5" '
                  f'fill="{C[k]}"/>' for i, k in enumerate(("close", "min", "zoom")))
        + txt(W / 2, FY + BAR / 2 + 4.5, title, size=11.5, fill=C["muted"],
              anchor="middle", ls=0.6))


def frame_close(h, uid):
    return (f'<rect x="{FX}.5" y="{FY}.5" width="{FW - 1}" height="{h - 1:.0f}" '
            f'rx="{R}" fill="none" stroke="{C["rule"]}" stroke-width="1"/></svg>')


# ------------------------------------------------------------------ panel 01

def hero(cfg, d):
    uid, h = "a", 316
    o = []
    mark, mw = wordmark(cfg["wordmark"], 56, 96, 76, uid)
    o.append(mark)
    right = 56 + mw

    o.append(f'<rect x="56" y="187" width="6" height="6" fill="{C["cyan"]}"/>'
             f'<line x1="62" y1="190" x2="{right:.0f}" y2="190" '
             f'stroke="{C["cyand"]}" stroke-width="1.4"/>')

    # the role readout cycles; the first one is also the resting frame
    roles, cyc = cfg["roles"][:3], len(cfg["roles"][:3]) * 3.0
    for i, r in enumerate(roles):
        o.append(f'<g opacity="{1 if i == 0 else 0}">'
                 f'<animate attributeName="opacity" values="0;1;1;0;0" '
                 f'keyTimes="0;0.05;0.30;0.35;1" dur="{cyc}s" begin="{i * 3.0}s" '
                 f'repeatCount="indefinite"/>'
                 + txt(56, 218, r, size=13.5, fill=C["dim"], ls=1.8) + "</g>")

    # drafting callouts pointing back at the logotype
    for cy, ly, text in ((128, 106, cfg["callout_a"]), (150, 172, cfg["callout_b"])):
        o.append(f'<path d="M{right + 20:.0f},{cy} L{right + 68:.0f},{ly} '
                 f'H{right + 124:.0f}" fill="none" stroke="{C["rule"]}" '
                 f'stroke-width="1"/>'
                 f'<circle cx="{right + 20:.0f}" cy="{cy}" r="2.6" fill="{C["cyan"]}"/>'
                 + label(right + 132, ly + 4, text, fill=C["dim"], size=10.5, ls=0.9))

    # rotary encoder
    ecx, ecy = 836, 150
    o.append(f'<circle cx="{ecx}" cy="{ecy}" r="78" fill="none" stroke="{C["rule"]}" '
             f'stroke-width="1"/>'
             f'<circle cx="{ecx}" cy="{ecy}" r="42" fill="none" stroke="{C["rule"]}" '
             f'stroke-width="1" opacity=".8"/>')
    ticks = []
    for i in range(36):
        a = math.radians(i * 10)
        ln = 9 if i % 3 == 0 else 5
        col = C["cyand"] if i % 3 == 0 else C["ghost"]
        ticks.append(f'<line x1="{ecx + 70 * math.sin(a):.1f}" '
                     f'y1="{ecy - 70 * math.cos(a):.1f}" '
                     f'x2="{ecx + (70 - ln) * math.sin(a):.1f}" '
                     f'y2="{ecy - (70 - ln) * math.cos(a):.1f}" stroke="{col}" '
                     f'stroke-width="1"/>')
    o.append("".join(ticks))
    seg, step = [], 360.0 / 20
    for i in range(20):
        a0, a1 = math.radians(i * step), math.radians(i * step + step * 0.44)
        seg.append(f'<path d="M{ecx + 50 * math.sin(a0):.1f},{ecy - 50 * math.cos(a0):.1f} '
                   f'L{ecx + 62 * math.sin(a0):.1f},{ecy - 62 * math.cos(a0):.1f} '
                   f'L{ecx + 62 * math.sin(a1):.1f},{ecy - 62 * math.cos(a1):.1f} '
                   f'L{ecx + 50 * math.sin(a1):.1f},{ecy - 50 * math.cos(a1):.1f} Z" '
                   f'fill="{C["cyand"]}" opacity=".55"/>')
    o.append(f'<g>{"".join(seg)}<animateTransform attributeName="transform" '
             f'type="rotate" from="0 {ecx} {ecy}" to="360 {ecx} {ecy}" dur="38s" '
             f'repeatCount="indefinite"/></g>')
    sx = ecx + 68 * math.sin(math.radians(54))
    sy = ecy - 68 * math.cos(math.radians(54))
    o.append(f'<g><path d="M{ecx},{ecy} L{ecx},{ecy - 68} A68,68 0 0,1 {sx:.1f},{sy:.1f} Z" '
             f'fill="{C["cyan"]}" opacity=".07"/>'
             f'<line x1="{ecx}" y1="{ecy}" x2="{ecx}" y2="{ecy - 72}" '
             f'stroke="{C["cyan"]}" stroke-width="1.2" opacity=".5"/>'
             f'<animateTransform attributeName="transform" type="rotate" '
             f'from="0 {ecx} {ecy}" to="360 {ecx} {ecy}" dur="7s" '
             f'repeatCount="indefinite"/></g>')
    o.append(f'<circle cx="{ecx}" cy="{ecy}" r="5" fill="{C["cyan"]}" '
             f'filter="url(#gl{uid})"/>'
             f'<circle cx="{ecx}" cy="{ecy}" r="3" fill="{C["ink"]}"/>'
             f'<path d="M{ecx - 5},{ecy - 84} H{ecx + 5} L{ecx},{ecy - 76} Z" '
             f'fill="{C["cyand"]}"/>')

    # drawing title block
    o.append(f'<rect x="{FX}" y="243" width="104" height="3" fill="{C["cyan"]}"/>'
             f'<line x1="{FX}" y1="246" x2="{FX + FW}" y2="246" stroke="{C["rule"]}" '
             f'stroke-width="1"/>')
    edges = [FX, 256, 500, 744, FX + FW]
    for i, (lab, val) in enumerate(cfg["titleblock"][:4]):
        x = edges[i] + PAD
        if i:
            o.append(f'<line x1="{edges[i]}" y1="246" x2="{edges[i]}" y2="{FY + h}" '
                     f'stroke="{C["rule"]}" stroke-width="1"/>')
        o.append(label(x, 274, lab))
        if lab.upper() == "STATUS":
            o.append(f'<circle cx="{x + 5}" cy="{300 - 4.5}" r="4.5" '
                     f'fill="{C["green"]}" filter="url(#gl{uid})">'
                     f'<animate attributeName="opacity" values="1;.3;1" dur="2.6s" '
                     f'repeatCount="indefinite"/></circle>'
                     + txt(x + 19, 300, val, size=14.5))
        else:
            o.append(txt(x, 300, val, size=14.5))

    return (frame_open(h, uid, f'{cfg["shell_user"]} — ~ — profile')
            + "".join(o) + frame_close(h, uid))


# ------------------------------------------------------------------ panel 02

def chip(x, y, text, accent):
    w = 14 + tw(text, 12.5) + 15
    return (f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="30" rx="4" '
            f'fill="{C["track"]}" stroke="{C["rule"]}" stroke-width="1"/>'
            f'<rect x="{x:.1f}" y="{y}" width="3" height="30" rx="1.5" fill="{accent}"/>'
            + txt(x + 14, y + 20, text, size=12.5), w)


def group(gx, gy, gw, name, items, accent):
    """Returns (markup, row count). Chips wrap inside gw."""
    m = [f'<rect x="{gx}" y="{gy - 8}" width="6" height="6" fill="{accent}"/>',
         label(gx + 14, gy, name, fill=C["dim"], size=10.5, ls=1.8)]
    lw = tw(name, 10.5, 1.8) + 28
    m.append(f'<line x1="{gx + lw:.0f}" y1="{gy - 4}" x2="{gx + gw}" y2="{gy - 4}" '
             f'stroke="{C["grid"]}" stroke-width="1"/>')
    cxp, cyp, rows = gx, gy + 18, 1
    for item in items:
        mk, w = chip(cxp, cyp, item, accent)
        if cxp > gx and cxp + w > gx + gw:
            cyp += 40
            rows += 1
            cxp = gx
            mk, w = chip(cxp, cyp, item, accent)
        m.append(mk)
        cxp += w + 9
    return "".join(m), rows


def stack_panel(cfg, d):
    uid = "b"
    groups = list(cfg["stack"].items())
    accents = [C["cyan"], C["violet"], C["amber"], C["green"]]
    cols = [FX + PAD, 512]
    gw = 454

    top, top_rows = [], 1
    for i in range(min(2, len(groups))):
        mk, rows = group(cols[i], FY + BAR + 38, gw, groups[i][0], groups[i][1],
                         accents[i])
        top.append(mk)
        top_rows = max(top_rows, rows)

    bus = FY + BAR + 38 + 18 + top_rows * 40 + 14
    lower = bus + 34
    bot, bot_rows = [], 1
    for i in range(2, min(4, len(groups))):
        mk, rows = group(cols[i - 2], lower, gw, groups[i][0], groups[i][1], accents[i])
        bot.append(mk)
        bot_rows = max(bot_rows, rows)

    h = lower + 18 + bot_rows * 40 + 10 - FY
    o = list(top)
    o.append(f'<line x1="{FX + PAD}" y1="{bus}" x2="{FX + FW - PAD}" y2="{bus}" '
             f'stroke="{C["rule"]}" stroke-width="2"/>'
             f'<line x1="{FX + PAD}" y1="{bus}" x2="{FX + FW - PAD}" y2="{bus}" '
             f'stroke="{C["cyan"]}" stroke-width="1.4" stroke-dasharray="18 14" '
             f'opacity=".42">'
             f'<animate attributeName="stroke-dashoffset" from="64" to="0" dur="2.2s" '
             f'repeatCount="indefinite"/></line>')
    for x in (261, 739):
        o.append(f'<line x1="{x}" y1="{bus - 15}" x2="{x}" y2="{bus + 15}" '
                 f'stroke="{C["rule"]}" stroke-width="1"/>'
                 f'<rect x="{x - 3}" y="{bus - 3}" width="6" height="6" '
                 f'fill="{C["cyand"]}"/>')
    o.extend(bot)
    return (frame_open(h, uid, f'{cfg["shell_user"]} — ~/stack')
            + "".join(o) + frame_close(h, uid))


# ------------------------------------------------------------------ panel 03

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def signal(cfg, d):
    uid, h = "c", 344
    weeks = [(datetime.date.fromisoformat(k), v) for k, v in d["weeks"]]
    vals = [v for _, v in weeks]
    vmax = max(vals) or 1
    active = sum(1 for v in vals if v > 0)
    peak_i = vals.index(vmax)

    sx0, sx1 = FX + PAD, 636
    sy0, sy1 = FY + BAR + 26, FY + BAR + 196
    base, top = sy1 - 14, sy0 + 22
    px = [sx0 + 14 + (sx1 - sx0 - 28) * i / max(1, len(vals) - 1)
          for i in range(len(vals))]
    py = [base - (v / vmax) * (base - top) for v in vals]

    o = [f'<defs><linearGradient id="ar{uid}" x1="0" y1="0" x2="0" y2="1">'
         f'<stop offset="0" stop-color="{C["cyan"]}" stop-opacity=".28"/>'
         f'<stop offset="1" stop-color="{C["cyan"]}" stop-opacity="0"/>'
         f'</linearGradient></defs>',
         f'<rect x="{sx0}" y="{sy0}" width="{sx1 - sx0}" height="{sy1 - sy0}" rx="4" '
         f'fill="#080b10" stroke="{C["rule"]}" stroke-width="1"/>']
    for i in range(1, 4):
        y = sy0 + (sy1 - sy0) * i / 4
        o.append(f'<line x1="{sx0}" y1="{y:.1f}" x2="{sx1}" y2="{y:.1f}" '
                 f'stroke="{C["grid"]}" stroke-width="1"/>')
    o.append(f'<line x1="{sx0}" y1="{base}" x2="{sx1}" y2="{base}" '
             f'stroke="{C["ghost"]}" stroke-width="1"/>')
    o.append("".join(f'<line x1="{px[i]:.1f}" y1="{base}" x2="{px[i]:.1f}" '
                     f'y2="{py[i]:.1f}" stroke="{C["cyand"]}" stroke-width="1" '
                     f'opacity=".5"/>' for i, v in enumerate(vals) if v > 0))
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(px, py))
    o.append(f'<polygon points="{px[0]:.1f},{base} {pts} {px[-1]:.1f},{base}" '
             f'fill="url(#ar{uid})"/>')
    o.append('<path d="' + " ".join(("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}"
                                    for i, (x, y) in enumerate(zip(px, py)))
             + f'" fill="none" stroke="{C["cyan"]}" stroke-width="1.8" '
               f'stroke-linejoin="round"/>')
    o.append(f'<circle cx="{px[peak_i]:.1f}" cy="{py[peak_i]:.1f}" r="4" fill="none" '
             f'stroke="{C["amber"]}" stroke-width="1.3" opacity=".45">'
             f'<animate attributeName="r" values="4;14" dur="2.8s" '
             f'repeatCount="indefinite"/>'
             f'<animate attributeName="opacity" values=".45;0" dur="2.8s" '
             f'repeatCount="indefinite"/></circle>'
             f'<circle cx="{px[peak_i]:.1f}" cy="{py[peak_i]:.1f}" r="4" '
             f'fill="{C["bg"]}" stroke="{C["amber"]}" stroke-width="1.8"/>'
             + txt(sx1 - 12, sy0 + 20, f"peak {vmax}/week", size=11,
                   fill=C["muted"], anchor="end"))

    seen, ml = None, []
    for i, (dt, _) in enumerate(weeks):
        if dt.month != seen:
            ml.append((px[i], MONTHS[dt.month - 1]))
        seen = dt.month
    # the window opens mid-month, so its first label crowds the next one
    if len(ml) > 1 and ml[1][0] - ml[0][0] < 34:
        ml.pop(0)
    o.append("".join(txt(x, sy1 + 18, m, size=10.5, fill=C["muted"],
                         anchor="middle") for x, m in ml))

    ro = [("WINDOW", f"{len(vals)} weeks"), ("ACTIVE", f"{active} weeks"),
          ("PEAK", f"{vmax}/week"), ("REPOS", str(d["repos_total"]))]
    ry = sy1 + 42
    o.append(f'<line x1="{sx0}" y1="{ry}" x2="{sx1}" y2="{ry}" stroke="{C["rule"]}" '
             f'stroke-width="1"/>')
    for i, (lab, val) in enumerate(ro):
        x = sx0 + 6 + i * ((sx1 - sx0) / len(ro))
        o.append(label(x, ry + 20, lab, size=9.5) + txt(x, ry + 42, val, size=13.5))
    panel_bottom = ry + 40          # keeps the mix panel clear of the frame edge

    lx0, lx1 = 672, FX + FW - PAD
    langs = d["languages"][:5]
    total = sum(v for _, v in d["languages"]) or 1
    rows = [(k, v * 100.0 / total) for k, v in langs]
    rest = total - sum(v for _, v in langs)
    if rest > 0:
        rows.append(("Other", rest * 100.0 / total))
    o.append(f'<rect x="{lx0 - 10}" y="{sy0}" width="{lx1 - lx0 + 20}" '
             f'height="{panel_bottom - sy0}" rx="4" fill="{C["track"]}" '
             f'stroke="{C["rule"]}" stroke-width="1"/>'
             f'<rect x="{lx0 - 10}" y="{sy0}" width="6" height="6" fill="{C["amber"]}"/>'
             + label(lx0 + 4, sy0 + 24, "LANGUAGE MIX", fill=C["dim"], size=10.5, ls=1.8))
    seg_x = lx0
    for i, (k, pct) in enumerate(rows):
        seg = (lx1 - lx0) * pct / 100.0
        o.append(f'<rect x="{seg_x:.1f}" y="{sy0 + 38}" width="{seg:.1f}" height="10" '
                 f'fill="{LANG_COLORS[i % len(LANG_COLORS)]}" opacity=".9"/>')
        seg_x += seg
    for i, (k, pct) in enumerate(rows):
        y = sy0 + 76 + i * 27
        col = LANG_COLORS[i % len(LANG_COLORS)]
        o.append(f'<rect x="{lx0}" y="{y - 8}" width="7" height="7" rx="1.5" '
                 f'fill="{col}"/>'
                 + txt(lx0 + 17, y, k, size=12.5)
                 + txt(lx1, y, f"{pct:.1f}%", size=12, fill=C["dim"], anchor="end")
                 + f'<rect x="{lx0 + 17}" y="{y + 7}" width="{lx1 - lx0 - 17}" '
                   f'height="3" rx="1.5" fill="{C["grid"]}"/>'
                   f'<rect x="{lx0 + 17}" y="{y + 7}" '
                   f'width="{(lx1 - lx0 - 17) * pct / 100.0:.1f}" height="3" rx="1.5" '
                   f'fill="{col}" opacity=".85"/>')
    o.append(txt(lx1, panel_bottom - 14, f'sync {d["generated"]}', size=10,
                 fill=C["ghost"], anchor="end"))

    return (frame_open(h, uid, f'{cfg["shell_user"]} — ~/activity')
            + "".join(o) + frame_close(h, uid))


# ------------------------------------------------------------------- buttons

def button(link):
    lab = link["label"].upper()
    accent = ACCENTS.get(link.get("accent", "cyan"), C["cyan"])
    w, h = int(40 + tw(lab, 11.5, 1.6) + 40), 40
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}" role="img" font-family="{MONO}">'
            f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="8" '
            f'fill="{C["bg"]}" stroke="{C["rule"]}" stroke-width="1"/>'
            f'<circle cx="20" cy="{h / 2:.0f}" r="4.5" fill="{accent}"/>'
            + txt(34, h / 2 + 4.2, lab, size=11.5, fill=C["ink"], ls=1.6)
            + f'<path d="M{w - 26},{h / 2} h12 M{w - 19},{h / 2 - 4.5} '
              f'L{w - 14},{h / 2} L{w - 19},{h / 2 + 4.5}" fill="none" '
              f'stroke="{accent}" stroke-width="1.5" stroke-linecap="round"/></svg>')


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

    who = ", ".join(r.lower() for r in cfg["roles"])
    row = "&nbsp;&nbsp;".join(
        f'<a href="{esc(l["url"])}"><img src="{src(fn)}" height="40" '
        f'alt="{esc(l["label"].title())}"></a>' for fn, l in links)
    L = ["<!-- Generated by scripts/generate.py from config.json. "
         "Edit config.json, not this file. -->", "",
         '<div align="center">', "",
         f'<img src="{src("hero.svg")}" width="100%" '
         f'alt="{esc(cfg["wordmark"].title())} — {esc(who)}">', "", row, "",
         "</div>", "",
         f'<img src="{src("stack.svg")}" width="100%" '
         f'alt="Stack schematic — {esc(", ".join(k.lower() for k in cfg["stack"]))}">',
         "",
         f'<img src="{src("signal.svg")}" width="100%" '
         f'alt="Contribution activity over {len(d["weeks"])} weeks, and language mix '
         f'across {d["repos_own"]} source repositories">', "",
         '<div align="center"><sub>',
         f'Self-hosted SVG, redrawn daily by '
         f'<a href="https://github.com/{u}/{u}/actions">GitHub Actions</a>',
         "</sub></div>", ""]
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
        print(f"  {name:<18} {len(body) // 1024 or 1} KB")

    put("hero.svg", hero(cfg, d))
    put("stack.svg", stack_panel(cfg, d))
    put("signal.svg", signal(cfg, d))
    links = []
    for link in cfg["links"]:
        fn = f"link-{slug(link['label'])}.svg"
        put(fn, button(link))
        links.append((fn, link))

    write_readme(cfg, d, links)
    print(f"README.md written · {len(d['weeks'])} weeks · "
          f"{len(d['languages'])} languages · sync {d['generated']}")


if __name__ == "__main__":
    main()
