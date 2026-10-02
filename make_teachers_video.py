"""
Teachers' Day 2026 tribute video generator.

Pipeline:
  1. Collect one photo per teacher from G:/TeacherFaceAI/teacher_ai/output/named
     (first image per folder, deterministic; skips 'unassigned').
  2. Generate one HTML card per slide, screenshot at 1920x1080 with headless Chrome:
     2 intro cards, one title card per department, one themed card per teacher, end card.
  3. Render each card as a clip with slow zoom (ffmpeg zoompan), fade in/out,
     xfade-concat, and mux audio.

Music: drop ANY audio file (mp3/m4a/wav/aac/ogg/flac) into the output folder, or pass
  --audio "path". Teacher slides auto-stretch so the video matches the audio length.

Usage:
  python make_teachers_video.py            # full render (silent if no audio found)
  python make_teachers_video.py --cards    # only regenerate card images
"""
import os
import subprocess
import sys
from html import escape

ROOT = r"G:\TeacherFaceAI\teacher_ai\output\named"
OUT = r"G:\TeacherFaceAI\teacher_ai\output\teachers_day_video"
CARDS = os.path.join(OUT, "cards")
WORK = os.path.join(OUT, "build")
AUDIO = os.path.join(OUT, "music.mp3")
FINAL = os.path.join(OUT, "teachers_day_2026.mp4")

W, H = 1920, 1080
INTRO_DUR = 6.0
DEPT_DUR = 2.2
SLIDE_DUR = 1.3
FADE_DUR = 0.45

INTRO_1 = ["\u201cYou weren\u2019t expecting this,", "ladies and gentlemen\u2026\u201d"]
INTRO_MAIN = "HAPPY TEACHERS\u2019 DAY 2026"
INTRO_SUB = "In honour of the mentors who shape us"
INTRO_DATE = "8th September 2026"
END_HEAD = "TO THE ONES WHO TEACH"
END_SUB = "With gratitude, from all of us"
END_THANKS = "Thank you for everything."

# Palette per department: label, bg, accent, muted
DEPT_STYLES = {
    "computer-science-and-engineering": (
        "Computer Science & Engineering", "#14161e", "#6cb4ff", "#96a5c3"),
    "basic-science-and-humanities": (
        "Basic Science & Humanities", "#1c1826", "#d8b4fe", "#aca0c6"),
    "electrical-engineering": (
        "Electrical Engineering", "#161a26", "#ffca5c", "#b2ac96"),
    "electronics-and-communications-engineering": (
        "Electronics & Communication Engg.", "#121a20", "#6ee7b7", "#8cb2a6"),
    "mechanical-engineering": (
        "Mechanical Engineering", "#1a1816", "#e6a86a", "#b8a694"),
    "civil-engineering": (
        "Civil Engineering", "#181a1e", "#96cde0", "#9cacb6"),
}
DEPT_STYLES.setdefault(
    "unassigned", ("Faculty", "#18181a", "#d6bc82", "#aaa096"))

DEPT_SYMBOLS = {
    "computer-science-and-engineering": ["{ }", ";", "=", "< / >", "(/)", "*", "#", "_", "[ ]", "=>", "if", "&&", "0x1F", "++"],
    "basic-science-and-humanities": ["\u2211", "\u222b", "\u03c0", "\u221e", "\u221a", "\u0394", "\u03bb", "\u03b8", "\u03c6", "\u00b1", "\u2202", "\u2207", "\u03a9", "\u03bc"],
    "electrical-engineering": ["\u26a1", "V", "\u03a9", "\u00b5F", "AC", "DC", "LED", "R", "L", "C", "I\u00b2R", "Hz"],
    "electronics-and-communications-engineering": ["\u2533", "\u2248", "dB", "MHz", "IC", "TX", "RX", "FFT", "\u03bb/2", "Si", "\u25b3\u03c3", "AM"],
    "mechanical-engineering": ["\u2699", "\u29c9", "\u21c4", "N\u00b7m", "MPa", "\u03c4", "\u03c1", "RPM", "CAD", "FEA", "\u2261"],
    "civil-engineering": ["\u25e2", "\u25e3", "\u25b3", "\u25a1", "\u01c0", "\u23bc", "kN", "MPa", "\u00b5\u03b5", "RCC", "\u2220", "BBS"],
}
DEPT_SYMBOLS.setdefault(
    "unassigned", ["\u2726", "\u2727", "\u272a", "\u2736", "\u273d", "+", "\u00d7"])

IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac", ".wma")

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def chrome_path():
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    print("ERROR: no Chrome/Edge found", file=sys.stderr)
    sys.exit(1)


def collect_photos():
    """One deterministic first-image-per-teacher; skips the 'unassigned' folder."""
    photos, skipped = [], []
    for dept in sorted(os.listdir(ROOT)):
        dpath = os.path.join(ROOT, dept)
        if not os.path.isdir(dpath) or dept == "unassigned":
            continue
        for teacher in sorted(os.listdir(dpath)):
            tpath = os.path.join(dpath, teacher)
            if not os.path.isdir(tpath):
                continue
            pics = sorted(
                f for f in os.listdir(tpath)
                if f.lower().endswith(IMG_EXTS) and not f.startswith("."))
            if pics:
                photos.append((teacher, dept, os.path.join(tpath, pics[0])))
            else:
                skipped.append(teacher)
    return photos, skipped


def find_audio():
    """Explicit --audio path > music.mp3 > any audio file in the output folder."""
    if "--audio" in sys.argv:
        p = sys.argv[sys.argv.index("--audio") + 1]
        if os.path.exists(p):
            return p
        print(f"ERROR: --audio file not found: {p}", file=sys.stderr)
        sys.exit(1)
    if os.path.exists(AUDIO):
        return AUDIO
    for f in sorted(os.listdir(OUT)):
        if f.lower().endswith(AUDIO_EXTS):
            return os.path.join(OUT, f)
    return None


# ---------------------------------------------------------------- html cards
BASE_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { width:1920px; height:1080px; overflow:hidden; position:relative;
       font-family: Georgia, 'Times New Roman', serif; color:#f2ead8; }
.bg { position:absolute; inset:0;
      background: radial-gradient(ellipse at center, var(--bg) 0%%, #060607 100%%); }
.syms span { position:absolute; font-style:italic; user-select:none; }
.rules { position:absolute; left:130px; right:130px; height:0;
         border-top:1px solid color-mix(in srgb, var(--accent) 40%%, transparent); }
.rules.top { top:64px; } .rules.bot { bottom:64px; }
.credits { position:absolute; bottom:26px; width:100%%; text-align:center;
           font-family:'Felix Titling','Copperplate',Georgia,serif;
           letter-spacing:.5em; font-size:20px; opacity:.65;
           color:var(--accent); }
/* every card's content lives in one centered flex stack - always balanced */
.stack { position:absolute; inset:0 0 40px 0; display:flex; flex-direction:column;
         align-items:center; justify-content:center; gap:24px; text-align:center; }
.quote { font-style:italic; font-size:58px; line-height:1.4; color:#f0e4ca; }
.date  { font-size:32px; color:var(--accent); opacity:.9; }
.kicker { font-family:'Felix Titling','Copperplate',Georgia,serif;
          letter-spacing:.6em; font-size:26px; opacity:.6; color:var(--muted); }
h1.main { font-family:'Felix Titling','Copperplate',Georgia,serif;
          font-size:88px; font-weight:400; letter-spacing:.06em; }
.sub { font-style:italic; font-size:38px; color:var(--accent); opacity:.92; }
.sub2 { font-size:30px; opacity:.85; color:var(--muted); line-height:1.55; }
.frame { width:552px; height:672px; padding:6px; flex:none;
         border:1px solid color-mix(in srgb, var(--accent) 70%%, transparent);
         border-radius:10px; }
.frame img { width:540px; height:660px; object-fit:cover; border-radius:6px;
             display:block; filter:saturate(.92) contrast(1.04); }
.tname { font-size:60px; line-height:1.1; color:#f5eedd; }
.tdept { font-family:'Felix Titling','Copperplate',Georgia,serif;
         letter-spacing:.35em; font-size:24px; color:var(--accent); opacity:.9; }
.dept-kick { font-family:'Felix Titling','Copperplate',Georgia,serif;
             letter-spacing:.7em; font-size:26px; opacity:.6; color:var(--muted); }
.dept-big { font-family:'Felix Titling','Copperplate',Georgia,serif;
            font-size:78px; letter-spacing:.1em; color:var(--accent); line-height:1.25; }
"""


def syms_html(symbols, seed, count):
    """Deterministic pseudo-random scattered symbols from a string seed.
    Kept out of the middle band so centered content stays clean."""
    def rnd(seed, n):
        x = 2166136261
        for ch in (seed + str(n)):
            x = ((x ^ ord(ch)) * 16777619) & 0xFFFFFFFF
        return x
    out = []
    i = 0
    while len(out) < count:
        i += 1
        r1, r2, r3, r4 = (rnd(seed, i * 4 + k) for k in range(4))
        x = 50 + r1 % (W - 100)
        y = 110 + r2 % (H - 220)   # decorative frame band only
        if 0.30 * H < y < 0.72 * H and 0.24 * W < x < 0.76 * W:
            continue               # center stage reserved for content
        fs = 26 + r3 % 21
        op = 0.28 + (r4 % 40) / 100.0
        out.append(f"<span style='left:{x}px;top:{y}px;font-size:{fs}px;"
                   f"opacity:{op:.2f}'>{escape(symbols[r3 % len(symbols)])}</span>")
    return "".join(out)


def page(body, bg, accent, muted, symbols, seed, sym_count):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
    :root {{ --bg:{bg}; --accent:{accent}; --muted:{muted}; }}
    {BASE_CSS}
    </style></head><body>
    <div class="bg"></div>
    <div class="syms">{syms_html(symbols, seed, sym_count)}</div>
    {body}
    <div class="rules top"></div>
    <div class="rules bot"></div>
    <div class="credits">TEACHERS&rsquo; DAY 2026</div>
    </body></html>"""


def html_quote_card():
    body = (f"<div class='stack'>"
            f"<div class='quote'>{'<br>'.join(escape(l) for l in INTRO_1)}</div>"
            f"<div class='date'>&mdash; 8th September 2026 &mdash;</div></div>")
    return page(body, "#181616", "#d6ba80", "#a89c8c",
                DEPT_SYMBOLS["basic-science-and-humanities"], "intro1", 12)


def html_intro_card():
    body = (f"<div class='stack'>"
            f"<div class='kicker'>A TRIBUTE</div>"
            f"<h1 class='main'>{escape(INTRO_MAIN)}</h1>"
            f"<div class='sub'>{escape(INTRO_SUB)}</div>"
            f"<div class='sub2'>{escape(INTRO_DATE)}</div></div>")
    return page(body, "#181616", "#d6ba80", "#a89c8c",
                DEPT_SYMBOLS["basic-science-and-humanities"], "intro2", 14)


def html_dept_card(dept):
    label, bg, accent, muted = DEPT_STYLES[dept]
    body = (f"<div class='stack'>"
            f"<div class='dept-kick'>DEPARTMENT OF</div>"
            f"<div class='dept-big'>{escape(label.upper())}</div></div>")
    return page(body, bg, accent, muted, DEPT_SYMBOLS[dept], "dept-" + dept, 12)


def html_teacher_card(name, dept, photo_path):
    label, bg, accent, muted = DEPT_STYLES[dept]
    fname = name if len(name) <= 24 else name.replace("Dr. ", "").replace("Prof. ", "").replace("Dr.", "").replace("Prof.", "")
    fs = 60 if len(fname) <= 20 else 48
    body = (f"<div class='stack'>"
            f"<div class='frame'><img src='file:///{photo_path.replace(chr(92), '/')}'></div>"
            f"<div class='tname' style='font-size:{fs}px'>{escape(fname)}</div>"
            f"<div class='tdept'>{escape(label.upper())}</div></div>")
    return page(body, bg, accent, muted, DEPT_SYMBOLS[dept], name, 9)


def html_end_card():
    body = (f"<div class='stack'>"
            f"<h1 class='main' style='font-size:72px'>{escape(END_HEAD)}</h1>"
            f"<div class='sub'>{escape(END_SUB)}</div>"
            f"<div class='sub2'>{escape(END_THANKS)}<br>{escape(INTRO_DATE)}</div></div>")
    return page(body, "#181616", "#d6ba80", "#a89c8c",
                DEPT_SYMBOLS["basic-science-and-humanities"], "endcard", 14)


def shoot(html_path, png_path):
    """Screenshot with an isolated throwaway Chrome profile (fast, no handshake).
    Skips only when the png is newer than its html source."""
    import tempfile
    if os.path.exists(png_path) and \
            os.path.getmtime(png_path) >= os.path.getmtime(html_path):
        return
    with tempfile.TemporaryDirectory() as prof:
        run([chrome_path(),
             f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
             "--headless=new", "--disable-gpu", "--hide-scrollbars",
             f"--screenshot={png_path}", f"--window-size={W},{H}",
             "--default-background-color=00000000", html_path])


def build_cards(photos):
    os.makedirs(CARDS, exist_ok=True)
    pages = [("card_00", html_quote_card(), INTRO_DUR, False),
             ("card_01", html_intro_card(), INTRO_DUR, False)]

    seen_depts = set()
    for name, dept, photo in photos:
        if dept not in seen_depts:                    # department title card first
            seen_depts.add(dept)
            pages.append((f"card_{len(pages):02d}", html_dept_card(dept), DEPT_DUR, False))
        pages.append((f"card_{len(pages):02d}",
                      html_teacher_card(name, dept, photo), SLIDE_DUR, True))

    pages.append((f"card_{len(pages):02d}", html_end_card(), 4.5, False))

    cards, stretch_idx = [], []
    for stem, html, dur, stretch in pages:
        hp = os.path.join(CARDS, stem + ".html")
        pp = os.path.join(CARDS, stem + ".png")
        with open(hp, "w", encoding="utf-8") as f:
            f.write(html)
        shoot(hp, pp)
        if not os.path.exists(pp):
            print(f"ERROR: screenshot failed for {pp}", file=sys.stderr)
            sys.exit(1)
        if stretch:
            stretch_idx.append(len(cards))
        cards.append((pp, dur))
    print(f"built {len(cards)} cards in {CARDS}")
    return cards, stretch_idx


# ---------------------------------------------------------------- render
def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print((r.stderr or r.stdout)[-4000:])
        sys.exit(1)


def probe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def fit_durations(cards, stretch_idx, audio_dur):
    """Stretch teacher slides so timeline (minus crossfade overlaps) matches audio."""
    n = len(cards)
    durs = [d for _, d in cards]
    if not audio_dur:
        return durs
    f = FADE_DUR
    needed_sum = audio_dur + (n - 1) * f
    delta = (needed_sum - sum(durs)) / max(len(stretch_idx), 1)
    if delta < -0.5 * SLIDE_DUR:  # audio far too short - keep readable minimum
        delta = -0.5 * SLIDE_DUR
    for i in stretch_idx:
        durs[i] = max(1.0, durs[i] + delta)
    return durs


def render(cards, stretch_idx):
    os.makedirs(WORK, exist_ok=True)
    audio_path = find_audio()
    audio_dur = probe_duration(audio_path) if audio_path else None
    durs = fit_durations(cards, stretch_idx, audio_dur)

    clips, real = [], []
    for i, ((card, _), dur) in enumerate(zip(cards, durs)):
        out = os.path.join(WORK, f"clip_{i:02d}.mp4")
        frames = max(2, round(dur * 30))
        # single-image input; zoom accumulates over d frames (centered Ken Burns)
        vf = (f"scale={W * 2}:{H * 2},"
              f"zoompan=z='min(1+0.08*on/{frames - 1},1.08)':"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
              f"d={frames}:s={W}x{H}:fps=30,format=yuv420p")
        run(["ffmpeg", "-y", "-i", card, "-vf", vf,
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", out])
        clips.append(out)
        real.append(probe_duration(out) or dur)

    n = len(clips)
    concat_in = []
    for c in clips:
        concat_in += ["-i", c]
    fades = "".join(
        f"[{i}:v]fade=t=in:st=0:d={FADE_DUR},fade=t=out:st={durs[i] - FADE_DUR:.2f}:d={FADE_DUR}[v{i}];"
        for i in range(n))
    xparts = []
    for i in range(n - 1):
        # chained xfade offset from PROBED durations minus all overlaps so far
        offset = sum(real[:i + 1]) - (i + 1) * FADE_DUR
        out_lbl = "vout" if i == n - 2 else f"x{i + 1}"
        xparts.append(f"[{'v' + str(i) if i == 0 else 'x' + str(i)}][v{i + 1}]"
                      f"xfade=transition=fade:duration={FADE_DUR}:"
                      f"offset={offset:.3f}[{out_lbl}];")
    fc = fades + "".join(xparts)

    if audio_path:
        run(["ffmpeg", "-y", *concat_in, "-i", audio_path,
             "-filter_complex", fc, "-map", "[vout]", "-map", f"{n}:a",
             "-c:v", "libx264", "-preset", "medium", "-crf", "19",
             "-c:a", "aac", "-b:a", "192k", "-shortest", FINAL])
    else:
        print(f"NOTE: no audio file found - rendering silent preview "
              f"({sum(durs) - (n - 1) * FADE_DUR:.1f}s). "
              f"Drop any mp3/m4a/wav into {OUT} and re-run.")
        run(["ffmpeg", "-y", *concat_in, "-filter_complex", fc,
             "-map", "[vout]", "-c:v", "libx264", "-preset", "medium",
             "-crf", "19", FINAL])
    print("final video:", FINAL)


def main():
    photos, skipped = collect_photos()
    print(f"{len(photos)} teachers in {len({d for _, d, _ in photos})} departments;"
          f" skipped (no photo): {skipped or 'none'}")
    cards, stretch_idx = build_cards(photos)
    if "--cards" not in sys.argv:
        render(cards, stretch_idx)


if __name__ == "__main__":
    main()
