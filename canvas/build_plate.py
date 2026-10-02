# -*- coding: utf-8 -*-
"""PLATE XIV — SURVEY OF AN UNSEEN FLOOR

One specimen plate: a pinned plan above, a register of patient accumulation
below, in the palette of the office it quietly documents.

Authored in design units on an 1800x2400 sheet, rendered supersampled, and
checked: the script refuses to call itself finished while any two elements
overlap or anything crosses the trim.
"""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1800, 2400
S = 2
FONTS = "C:/Users/Zyphr/AppData/Local/Temp/canvas-fonts"

PAPER      = (243, 236, 220)
PAPER_DEEP = (231, 220, 196)
INK        = (61, 53, 41)
INK_SOFT   = (133, 122, 99)
INK_FAINT  = (179, 168, 143)
GRID       = (229, 220, 198)
HATCH      = (224, 215, 192)
ROUTE      = (156, 145, 121)
ACCENT     = (224, 149, 79)
MOSS       = (157, 185, 138)
ROSE       = (193, 102, 107)

ML, MR, MT, MB = 140, 140, 150, 130
FL, FR = 170, 1630
FT, FB = 380, 2020
SPLIT = 1200
TINT_MOSS = (233, 238, 226)
TINT_WARM = (243, 232, 214)

# registry of placed elements — every mark is checked against every other
BOXES = []          # (x0, y0, x1, y1, tag) — everything drawn with text sigils
RECTS = []          # station rectangles only
BLOCKS = []         # every zone a margin note may not enter


def inter(a, b, pad=0.0):
    """Do two boxes touch, allowing `pad` units of breathing space?"""
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or
                a[3] + pad <= b[1] or b[3] + pad <= a[1])


def f(name, size):
    return ImageFont.truetype(f"{FONTS}/{name}", max(6, int(round(size * S))))


F_TITLE = f("Italiana-Regular.ttf", 74)
F_LABEL = f("PoiretOne-Regular.ttf", 24)
F_SECT  = f("PoiretOne-Regular.ttf", 28)
F_MONO  = f("IBMPlexMono-Light.ttf", 14)
F_MONOS = f("IBMPlexMono-Light.ttf", 12)
F_PIX   = f("Silkscreen-Regular.ttf", 12)

img = Image.new("RGB", (W * S, H * S), PAPER)
d = ImageDraw.Draw(img)


# ── primitives (design units in, pixels out) ────────────────────────────
def line(x0, y0, x1, y1, fill=INK, w=1.0):
    d.line([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill, width=max(1, int(round(w * S))))


def rect(x0, y0, x1, y1, fill=None, outline=INK, w=1.0):
    if fill:
        d.rectangle([x0 * S, y0 * S, x1 * S - 1, y1 * S - 1], fill=fill)
    if outline:
        d.rectangle([x0 * S, y0 * S, x1 * S, y1 * S], outline=outline,
                    width=max(1, int(round(w * S))))


def poly(pts, fill=None, outline=None, w=1.0):
    p = [(x * S, y * S) for x, y in pts]
    if fill:
        d.polygon(p, fill=fill)
    if outline:
        d.line(p + [p[0]], fill=outline, width=max(1, int(round(w * S))))


def circle(cx, cy, r, fill=None, outline=None, w=1.0):
    b = [(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S]
    if fill:
        d.ellipse(b, fill=fill)
    if outline:
        d.ellipse(b, outline=outline, width=max(1, int(round(w * S))))


def dot(cx, cy, r, fill=INK):
    circle(cx, cy, r, fill=fill)


def tw(s, font, track=0.0):
    return sum(d.textlength(ch, font=font) / S for ch in s) + track * max(0, len(s) - 1)


def text(x, y, s, font, fill=INK, track=0.0, anchor="la", check=True, tag=""):
    """Letter-spaced text; registers its box so overlaps can be proven absent."""
    if track == 0:
        d.text((x * S, y * S), s, font=font, fill=fill, anchor=anchor)
        w = d.textlength(s, font=font) / S
    else:
        cx = x
        for ch in s:
            d.text((cx * S, y * S), ch, font=font, fill=fill, anchor=anchor)
            cx += d.textlength(ch, font=font) / S + track
        w = cx - x - track
    asc, desc = font.getmetrics()
    h = (asc + desc) / S
    x0 = x - w if anchor == "ra" else x
    if check:
        BOXES.append((x0, y, x0 + w, y + h, tag or s[:22]))
    return w


def sigil(kind, cx, cy, r=13):
    if kind == 0:
        circle(cx, cy, r, outline=INK, w=0.9); line(cx, cy - r, cx, cy + r, INK, 0.8)
    elif kind == 1:
        poly([(cx, cy - r), (cx + r, cy + r * .7), (cx - r, cy + r * .7)], outline=INK, w=0.9)
        dot(cx, cy + 2, 2.2)
    elif kind == 2:
        poly([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], outline=INK, w=0.9)
        line(cx - r * .55, cy, cx + r * .55, cy, INK, 0.7)
    elif kind == 3:
        circle(cx, cy, r, outline=INK, w=0.9)
        circle(cx, cy, r * .5, outline=INK, w=0.7)
        line(cx, cy - r, cx + r * .75, cy - r * .75, INK, 0.7)
    elif kind == 4:
        line(cx - r, cy, cx + r, cy, INK, 0.9); line(cx, cy - r, cx, cy + r, INK, 0.9)
        circle(cx + r * .8, cy - r * .8, 3.4, outline=INK, w=0.7)
    elif kind == 5:
        pts = [(cx + r * math.cos(math.pi / 3 * i - math.pi / 6),
                cy + r * math.sin(math.pi / 3 * i - math.pi / 6)) for i in range(6)]
        poly(pts, outline=INK, w=0.9); line(cx - r * .5, cy, cx + r * .5, cy, INK, 0.7)
    elif kind == 6:
        arc = [(cx + r * math.cos(math.pi * .25 + math.pi * 1.5 * i / 24),
                cy + r * math.sin(math.pi * .25 + math.pi * 1.5 * i / 24)) for i in range(25)]
        d.line([(p[0] * S, p[1] * S) for p in arc], fill=INK, width=max(1, int(round(0.9 * S))))
        dot(cx + r * .7, cy - r * .7, 2.6)
    else:
        for k in range(3):
            line(cx - r * .7, cy - 8 + k * 8, cx + r * .7, cy - 13 + k * 8, INK, 0.8)
    BOXES.append((cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2, "sigil"))


def bez(p0, p1, p2, n=46):
    out = []
    for i in range(n + 1):
        t = i / n; u = 1 - t
        out.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return out


# ── paper ground ────────────────────────────────────────────────────────
# The ground has to read as material — fibrous, uneven, handled — not as flat
# digital fill. Measuring the old single-pass blend gave a std deviation of
# 0.32 levels on a mean of 227: invisible. This lays three separate strata
# instead: slow cloudy mottling, long horizontal fibres, and per-pixel tooth.
def _noise(w, h, cx, cy, rng, blur=0.0):
    """Value noise on a cx x cy cell grid, interpolated smoothly to full size.

    A non-square cell grid is what makes fibres: wide cells stretched to the
    sheet become long strands, square cells become speckle.
    """
    g = rng.random((cy + 1, cx + 1))
    im = Image.fromarray((g * 255).astype("uint8"), "L").resize((w, h), Image.BICUBIC)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(im, np.float32) / 255.0 - 0.5


PW, PH = W * S, H * S
_rng = np.random.default_rng(14)
_cloud = (_noise(PW, PH, 7, 7, _rng, 46) * 4.4        # where the sheet was handled
          + _noise(PW, PH, 21, 21, _rng, 16) * 2.0)   # secondary unevenness
_fibre = _noise(PW, PH, 210, 15, _rng, 2.4) * 1.7     # long horizontal strands
_tooth = _rng.normal(0.0, 1.45, (PH, PW)).astype(np.float32)
_ground = _cloud + _fibre + _tooth
_arr = np.asarray(img, np.float32) + _ground[..., None]
img = Image.fromarray(np.clip(_arr, 0, 255).astype("uint8"), "RGB")
d = ImageDraw.Draw(img)


# ── header ──────────────────────────────────────────────────────────────
text(ML, MT - 56, "PLATE XIV", F_MONO, INK_SOFT, track=5.5)
text(ML, MT, "SURVEY OF AN UNSEEN FLOOR", F_TITLE, INK, track=6.0)
text(ML + 3, MT + 94, "a continuous register of work performed where no one watches",
     F_LABEL, INK_SOFT, track=1.1)
for i, (k, v) in enumerate([("SERIES", "08 NODES"), ("PERIOD", "CONTINUOUS"),
                            ("STATE", "IN PROGRESS")]):
    text(FR, MT - 6 + i * 36, k, F_MONOS, INK_FAINT, track=2.4, anchor="ra")
    text(FR, MT + 13 + i * 36, v, F_MONOS, INK_SOFT, track=1.6, anchor="ra")
line(ML, MT + 130, FR, MT + 130, INK_FAINT, 0.8)


# ── field frame, rulers, registration ───────────────────────────────────
rect(FL, FT, FR, FB, outline=INK, w=1.0)
rect(FL + 7, FT + 7, FR - 7, FB - 7, outline=INK_FAINT, w=0.6)
# Registration marks point outward only, so nothing intrudes on the plate.
for cx, cy, ox, oy in ((FL, FT, -1, -1), (FR, FT, 1, -1), (FL, FB, -1, 1), (FR, FB, 1, 1)):
    line(cx + ox * 7, cy, cx + ox * 21, cy, INK, 0.9)
    line(cx, cy + oy * 7, cx, cy + oy * 21, INK, 0.9)

rx = FL - 26
line(rx, FT, rx, FB, INK_FAINT, 0.7)
for i, y in enumerate(range(int(FT), int(FB) + 1, 10)):
    major = (i % 5 == 0)
    line(rx, y, rx - (11 if major else 5), y, INK_SOFT if major else INK_FAINT, 0.7)
for i, y in enumerate(range(int(FT) + 500, int(FB), 500)):
    text(rx - 16, y - 7, str((i + 1) * 5), F_MONOS, INK_SOFT, track=0.8, anchor="ra")

# section rubrics, hung in the margin clear of frame and crosses
def rubric(y, title, after):
    """A section rubric in the margin; its whole span becomes a no-go zone."""
    w1 = text(FL, y, title, F_SECT, INK, track=5.0)
    x2 = FL + w1 + 22
    w2 = text(x2, y + 10, after, F_MONOS, INK_FAINT, track=1.2)
    asc, desc = F_SECT.getmetrics()
    BLOCKS.append((FL - 4, y - 8, max(FL + w1, x2 + w2) + 8, y + (asc + desc) / S + 8))


rubric(FT - 72, "PLAN", "a pinned arrangement of eight stations")
rubric(SPLIT - 72, "REGISTER", "one mark for each event, laid down in patience")
line(FL, SPLIT - 6, FR, SPLIT - 6, INK_FAINT, 0.8)


# ── upper register: the plan ────────────────────────────────────────────
GX = 65
gx0, gy0 = FL + 10, FT + 54

for c in range(1, 22):
    x = gx0 + c * GX
    if x < FR - 10:
        line(x, FT + 14, x, SPLIT - 14, GRID, 0.6)
for r in range(1, 11):
    y = gy0 + r * GX
    if y < SPLIT - 14:
        line(FL + 14, y, FR - 14, y, GRID, 0.6)

STATIONS = [
    (1,  1, 4, 3, 1, 0, PAPER_DEEP),
    (6,  2, 3, 4, 2, 1, None),
    (11, 1, 5, 3, 3, 2, None),
    (17, 2, 4, 3, 4, 3, TINT_MOSS),
    (2,  6, 5, 3, 5, 4, None),
    (8,  7, 4, 4, 6, 5, PAPER_DEEP),
    (13, 6, 4, 3, 7, 6, None),
    (18, 7, 3, 3, 8, 7, TINT_WARM),
]

def hatch(x0, y0, x1, y1, step, col, w=0.5):
    """A surveyed zone reads as built space once it carries a hatch.

    This is the register's striation repeated at another scale — the two
    registers are meant to be held in tension, and sharing one motif is what
    ties the hard plan to the soft field instead of leaving two panels that
    happen to sit on the same sheet.
    """
    wd, h = x1 - x0, y1 - y0
    k = -h
    while k < wd:
        xs, xe = max(0.0, k), min(wd, k + h)
        if xe > xs:
            line(x0 + xs, y0 + (xs - k), x0 + xe, y0 + (xe - k), col, w)
        k += step


centers = {}
STN_RECTS = []                               # (x0, y0, x1, y1, node)
for (c, r, wc, hc, node, kind, tint) in STATIONS:
    x0, y0 = gx0 + c * GX, gy0 + r * GX
    x1, y1 = x0 + wc * GX, y0 + hc * GX
    rect(x0, y0, x1, y1, fill=tint, outline=INK, w=1.0)
    hatch(x0 + 1, y0 + 1, x1 - 1, y1 - 1, 7.0, HATCH, 0.5)
    rect(x0 + 10, y0 + 10, x1 - 10, y1 - 10, outline=INK_FAINT, w=0.5)
    RECTS.append((x0, y0, x1, y1, f"station {node}"))
    STN_RECTS.append((x0, y0, x1, y1, node))
    BLOCKS.append((x0, y0, x1, y1))
    sigil(kind, x0 + 25, y0 + 25)
    text(x0 + 46, y0 + 17, f"NODE {node:02d}", F_MONOS, INK, track=1.8)
    text(x0 + 8, y1 - 21, f"STATION {c:02d}·{r:02d}", F_MONOS, INK_SOFT, track=1.2)
    centers[node] = ((x0 + x1) / 2, (y0 + y1) / 2)

def _inside(p, box):
    return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]


def _crossing(seq, box):
    """Index of the boundary crossing where a polyline leaves `box`."""
    k = 0
    while k < len(seq) and _inside(seq[k], box):
        k += 1
    if k == 0 or k >= len(seq):
        return None
    a, b = seq[k - 1], seq[k]
    lo, hi = 0.0, 1.0
    for _ in range(26):                       # bisect the exact exit point
        t = (lo + hi) / 2
        if _inside((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), box):
            lo = t
        else:
            hi = t
    t = (lo + hi) / 2
    edge = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return [edge] + seq[k:]


def _nudge(p, toward, gap):
    dx, dy = toward[0] - p[0], toward[1] - p[1]
    L = math.hypot(dx, dy) or 1.0
    if L <= gap * 2:
        return p
    return (p[0] + dx / L * gap, p[1] + dy / L * gap)


def trim_route(pts):
    """Draw a route edge-to-edge, never centre-to-centre.

    A centre-to-centre line was drawn over the station fill, so every node
    showed a cut-off stub inside its own box — the strongest tell that the
    plan was wiring rather than drawn. Routes now terminate clear of the
    frame with a small breathing gap.
    """
    out = pts
    src = next((r for r in RECTS if _inside(pts[0], r)), None)
    dst = next((r for r in RECTS if _inside(pts[-1], r)), None)
    if src:
        cut = _crossing(out, src)
        if cut:
            out = cut
    if dst:
        cut = _crossing(list(reversed(out)), dst)
        if cut:
            out = list(reversed(cut))
    if len(out) > 2:
        out = [_nudge(out[0], out[1], 7)] + list(out[1:-1]) + [_nudge(out[-1], out[-2], 7)]
    return out


def clears(pts, a, b):
    """True when a route touches no station except the two it joins.

    The plan is a fixed arrangement, so rather than hand-tuning one bowed
    curve until it happened to miss, the router searches the bow that clears
    the occupied stations — the constraint is satisfied by construction and
    the guard below only ever has to confirm it.
    """
    for (sx0, sy0, sx1, sy1, node) in STN_RECTS:
        if node in (a, b):
            continue
        for q in pts:
            if sx0 + 2 < q[0] < sx1 - 2 and sy0 + 2 < q[1] < sy1 - 2:
                return False
            if not (FL + 8 < q[0] < FR - 8 and FT + 8 < q[1] < SPLIT - 8):
                return False
    return True


ROUTES = []                                  # trimmed polylines, for the guard
for a, b in [(1, 3), (3, 2), (2, 6), (6, 7), (7, 8), (5, 6), (4, 8), (1, 5), (3, 4)]:
    p0, p2 = centers[a], centers[b]
    dx, dy = p2[0] - p0[0], p2[1] - p0[1]
    L = math.hypot(dx, dy) or 1
    midx, midy = (p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2
    pts = None
    for bow in (0.13, -0.13, 0.20, -0.20, 0.28, -0.28, 0.36, -0.36, 0.0):
        trial = trim_route(bez(p0, (midx - dy * bow, midy + dx * bow), p2))
        if pts is None:
            pts = trial                       # fall back to the least bow
        if clears(trial, a, b):
            pts = trial
            break
    ROUTES.append((f"{a}-{b}", pts))
    d.line([(q[0] * S, q[1] * S) for q in pts], fill=ROUTE,
           width=max(1, int(round(0.9 * S))), joint="curve")
    for t in (0.34, 0.68):
        q = pts[int(t * (len(pts) - 1))]
        dot(q[0], q[1], 2.6, ACCENT)

# Annotations are placed, not guessed: each takes the first candidate berth
# that is genuinely clear of every station and of the notes already hung.
ANNOT_SLOTS = [(250, 726), (800, 726), (1180, 726), (250, 1112),
               (760, 1112), (1180, 1112), (250, 470), (1180, 470)]
placed_notes = []


def note(lab):
    w = tw(lab, F_MONO, 1.4)
    asc, desc = F_MONO.getmetrics()
    h = (asc + desc) / S
    for (sx, sy) in ANNOT_SLOTS:
        box = (sx, sy, sx + w, sy + h, lab[:24])
        if any(inter(box, r, 14) for r in BLOCKS):
            continue
        if any(inter(box, p, 30) for p in placed_notes):
            continue
        placed_notes.append(box)
        text(sx, sy, lab, F_MONO, INK_SOFT, track=1.4)
        return
    print(f"  ! no free berth for annotation: {lab}")


for lab in ("IN TRANSIT · TWO MARKERS PER ROUTE",
            "RESOLVED AGAINST THE REGISTER",
            "PATIENCE, MEASURED"):
    note(lab)


# ── lower register ──────────────────────────────────────────────────────
RX0, RX1 = FL + 12, FR - 12
RY0, RY1 = SPLIT + 44, FB - 14

# Tighter cores than the first pass, so the register has real peaks and
# valleys — a landscape of where the work accumulated, not a single mass.
BLOBS = [(470, 1520, 132, 1.00), (900, 1770, 160, 0.88), (1330, 1600, 118, 0.80),
         (640, 1930, 108, 0.74), (1440, 1950, 96, 0.58), (248, 1885, 92, 0.48)]


def raw(x, y):
    v = 0.0
    for (bx, by, sg, wt) in BLOBS:
        v += wt * math.exp(-(((x - bx) ** 2 + (y - by) ** 2) / (2 * sg * sg)))
    v += 0.13 * (y - RY0) / (RY1 - RY0)
    v += 0.05 * math.sin(x / 90.0) * math.cos(y / 140.0)
    return max(0.0, v)


# Normalise against the true peak, never a fixed divisor: a fixed divisor
# clipped a plateau flat, which flattened the landscape and made "peaks"
# meaningless. The gamma then deepens the valleys between accumulations.
MAXV = max(raw(x, y)
           for x in [RX0 + i * 8 for i in range(int((RX1 - RX0) / 8) + 1)]
           for y in [RY0 + j * 8 for j in range(int((RY1 - RY0) / 8) + 1)])


def field(x, y):
    v = max(0.0, min(1.0, raw(x, y) / MAXV)) ** 1.25
    # dissolve at the edges rather than being cropped by the frame
    fx = min(x - RX0, RX1 - x) / 78.0
    fy = min(y - RY0, RY1 - y) / 58.0
    return v * max(0.0, min(1.0, min(fx, fy))) ** 0.7


STEPX, STEPY = 3.1, 6.2
yy = RY0 - 8
while yy <= RY1 + 8:
    xx = RX0 - 4
    while xx <= RX1 + 4:
        v = field(xx, yy)
        if v > 0.04:
            hgt = 1.2 + 13.0 * v
            a = 0.14 + 0.86 * v
            col = tuple(int(PAPER[i] + (INK[i] - PAPER[i]) * a) for i in range(3))
            line(xx, yy, xx, yy - hgt, col, 0.5)
        xx += STEPX
    yy += STEPY

gxs = [RX0 + i * 6 for i in range(int((RX1 - RX0) / 6) + 1)]
gys = [RY0 + j * 6 for j in range(int((RY1 - RY0) / 6) + 1)]
grid = [[field(x, y) for y in gys] for x in gxs]


def segments(thr):
    out = []
    for i in range(len(gxs) - 1):
        for j in range(len(gys) - 1):
            v0, v1, v2, v3 = grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]
            if thr > max(v0, v1, v2, v3) or thr < min(v0, v1, v2, v3):
                continue
            x0, x1, y0, y1 = gxs[i], gxs[i + 1], gys[j], gys[j + 1]

            def ip(a, b, va, vb):
                t = (thr - va) / (vb - va) if vb != va else 0.5
                return a + (b - a) * t
            e = []
            if (v0 > thr) != (v1 > thr): e.append((ip(x0, x1, v0, v1), y0))
            if (v1 > thr) != (v2 > thr): e.append((x1, ip(y0, y1, v1, v2)))
            if (v3 > thr) != (v2 > thr): e.append((ip(x0, x1, v3, v2), y1))
            if (v0 > thr) != (v3 > thr): e.append((x0, ip(y0, y1, v0, v3)))
            if len(e) == 2:
                out.append((e[0], e[1]))
            elif len(e) == 4:
                out.append((e[0], e[1])); out.append((e[2], e[3]))
    return out


def stitch(segs):
    k = lambda p: (round(p[0]), round(p[1]))
    pool = {}
    for a, b in segs:
        pool.setdefault(k(a), []).append((a, b))
        pool.setdefault(k(b), []).append((b, a))
    paths, used = [], set()
    for a, b in segs:
        if (k(a), k(b)) in used:
            continue
        path = [a, b]; used.add((k(a), k(b))); cur = b
        while True:
            nxt = None
            for (p, q) in pool.get(k(cur), []):
                if (k(p), k(q)) not in used and k(q) != k(path[-2]):
                    nxt = (p, q); break
            if not nxt:
                break
            used.add((k(nxt[0]), k(nxt[1]))); cur = nxt[1]; path.append(cur)
            if len(path) > 3000:
                break
        if len(path) > 2:
            paths.append(path)
    return paths


for thr, col, lw in ((0.16, (200, 191, 167), 0.65), (0.40, (152, 142, 118), 0.7),
                     (0.66, (112, 102, 82), 0.75)):
    for path in stitch(segments(thr)):
        d.line([(p[0] * S, p[1] * S) for p in path], fill=col,
               width=max(1, int(round(lw * S))), joint="curve")

# Single out one peak per accumulation — derived from the field, not chosen.
#
# A lattice local-maximum test silently found nothing here: the crest sat
# between two sampled rows (global max at i=48, stride 3 starting at 2), so
# every sampled cell had a higher neighbour and the register went unmarked.
# Connectivity is immune to that phase problem, and it is also the truer
# reading — a "peak" is wherever one accumulation culminates.
THRESH = 0.55
seen = [[False] * len(gys) for _ in gxs]
peaks = []
for i0 in range(len(gxs)):
    for j0 in range(len(gys)):
        if seen[i0][j0] or grid[i0][j0] < THRESH:
            continue
        stack, cells = [(i0, j0)], []
        seen[i0][j0] = True
        while stack:
            i, j = stack.pop()
            cells.append((i, j))
            for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + a, j + b
                if (0 <= ni < len(gxs) and 0 <= nj < len(gys) and not seen[ni][nj]
                        and grid[ni][nj] >= THRESH):
                    seen[ni][nj] = True
                    stack.append((ni, nj))
        if len(cells) >= 25:                 # skip stray specks
            i, j = max(cells, key=lambda c: grid[c[0]][c[1]])
            peaks.append((grid[i][j], gxs[i], gys[j]))
peaks.sort(reverse=True)
for v, px, py in peaks[:6]:
    line(px, py, px, py - 17, ACCENT, 1.1)
    dot(px, py - 17, 2.1, ACCENT)

line(RX0, RY1 + 20, RX1, RY1 + 20, INK_FAINT, 0.7)
text(RX0, RY1 + 28, "BASELINE 0.15", F_MONOS, INK_FAINT, track=1.4)
text(RX1, RY1 + 28, "THRESHOLDS 0.16 · 0.40 · 0.66", F_MONOS, INK_FAINT, track=1.4, anchor="ra")


# ── footer ──────────────────────────────────────────────────────────────
FY = FB + 52
line(ML, FY, FR, FY, INK, 0.9)

kx = ML
for kind, lab in [("mark", "ONE MARK, ONE EVENT"), ("line", "DENSITY THRESHOLD"),
                  ("dot", "IN TRANSIT")]:
    if kind == "mark":
        line(kx, FY + 40, kx, FY + 26, INK, 1.0)
    elif kind == "line":
        xs = [kx + i * 1.2 for i in range(22)]
        ys = [FY + 40 - 15 * math.sin((i / 21) * math.pi) ** 1.6 for i in range(22)]
        d.line([(x * S, y * S) for x, y in zip(xs, ys)], fill=INK, width=max(1, 2))
    else:
        dot(kx, FY + 33, 3.2, ACCENT)
    text(kx + 26, FY + 26, lab, F_MONO, INK_SOFT, track=1.6)
    kx += 26 + tw(lab, F_MONO, 1.6) + 56

sx0, sy, seg = FR - 296, FY + 40, 50
for i in range(5):
    rect(sx0 + i * seg, sy - 6, sx0 + (i + 1) * seg, sy,
         fill=INK if i % 2 == 0 else PAPER, outline=INK, w=0.6)
text(sx0, sy - 26, "0", F_MONOS, INK_SOFT)
text(sx0 + 5 * seg, sy - 26, "5", F_MONOS, INK_SOFT, anchor="ra")
text(sx0 + 5 * seg + 10, sy - 10, "×10³", F_MONOS, INK_FAINT, track=1.2)

text(ML, FY + 92, "Q U I E T   I N S T R U M E N T A T I O N", F_MONO, INK_SOFT, track=2.2)
text(FR, FY + 88, "08 NODES", F_PIX, INK_FAINT, track=2.0, anchor="ra")


# ── the check: prove nothing overlaps, nothing crosses the trim ─────────
problems = []
for i in range(len(BOXES)):
    for j in range(i + 1, len(BOXES)):
        if inter(BOXES[i], BOXES[j]):
            bi, bj = BOXES[i], BOXES[j]
            problems.append(f"overlap: '{bi[4]}' [{int(bi[0])},{int(bi[1])}-{int(bi[2])},{int(bi[3])}]"
                            f" × '{bj[4]}' [{int(bj[0])},{int(bj[1])}-{int(bj[2])},{int(bj[3])}]")
for r in RECTS:
    for b in BOXES:
        if b[4] == "sigil" and inter(r, b, 1.0):
            continue                                    # sigils live inside
        if b[0] >= r[0] - 1 and b[2] <= r[2] + 1 and b[1] >= r[1] - 1 and b[3] <= r[3] + 1:
            continue                                    # labels seated in a station
        if inter(r, b):
            problems.append(f"station clash: {r[4]} × '{b[4]}'")
for a in range(len(RECTS)):
    for b in range(a + 1, len(RECTS)):
        if inter(RECTS[a], RECTS[b]):
            problems.append(f"station on station: {RECTS[a][4]} × {RECTS[b][4]}")
for (x0, y0, x1, y1, tag) in BOXES:
    if x0 < 20 or y0 < 20 or x1 > W - 20 or y1 > H - 12:
        problems.append(f"off-trim: '{tag}' at {int(x0)},{int(y0)}")
# A route must stop clear of every station frame. This is the defect that made
# the first pass read as unfinished wiring, so the script defends it rather
# than trusting the eye at 33% scale.
for rname, pts in ROUTES:
    for (sx0, sy0, sx1, sy1, stag) in RECTS:
        for q in pts:
            if sx0 + 2 < q[0] < sx1 - 2 and sy0 + 2 < q[1] < sy1 - 2:
                problems.append(f"route {rname} intrudes into {stag} at {int(q[0])},{int(q[1])}")
                break

final = img.resize((W, H), Image.LANCZOS).filter(ImageFilter.SMOOTH)

# ── final press pass ────────────────────────────────────────────────────
# One last whisper of tooth across everything already drawn, so the ink sits
# on the sheet rather than floating above it. Applied AFTER the downscale: at
# supersampled resolution the resample and SMOOTH would have averaged this
# away, so tooth laid down earlier never reaches the finished sheet at all.
_press = (_rng.normal(0.0, 1.15, (H, W)).astype(np.float32)
          + _noise(W, H, 6, 6, _rng, 30) * 1.15
          + _noise(W, H, 150, 6, _rng, 1.4) * 0.55)
_a2 = np.asarray(final, np.float32) + _press[..., None]
final = Image.fromarray(np.clip(_a2, 0, 255).astype("uint8"), "RGB")
final.save("canvas/plate-xiv-survey-of-an-unseen-floor.png", "PNG", optimize=True)
final.save("canvas/plate-xiv-survey-of-an-unseen-floor.pdf", "PDF", resolution=300.0)

print(f"rendered {final.size}  elements={len(BOXES)}  stations={len(RECTS)}  "
      f"register peaks marked={len(peaks[:6])}")
if problems:
    print("LAYOUT PROBLEMS:")
    for p in sorted(set(problems)):
        print("  -", p)
else:
    print("LAYOUT CLEAN — no overlaps, nothing off-trim")
