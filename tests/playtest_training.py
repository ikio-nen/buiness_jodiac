"""Playtest: does the CAD-licence search find PRIVATE TRAINING INSTITUTES?

Runs the real search workflow across a slate of locations with the phrasing a
user would actually type, sorts every result into training / college / school /
other, then enriches the training ones and records which produced a usable
email. Writes a JSON and a Markdown report under jodiac_data/playtests/.

No email is ever sent: the harness only calls the discovery and enrichment
steps. DRY_RUN is deliberately NOT set, because that flag also short-circuits
the web/Maps sources into mock rows -- which would make the playtest measure a
fixture instead of the internet.

Usage:
    E:/python.exe -X utf8 tests/playtest_training.py --limit 3
    E:/python.exe -X utf8 tests/playtest_training.py --no-enrich
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("JODIAC_HOME", str(ROOT / "jodiac_data"))

# (location, radius_m, phrase) -- the phrase is the user's own words.
SCENARIOS = [
    ("Salt Lake, Kolkata", 2500, "CAD training institute, not colleges or schools"),
    ("Bidhannagar, Kolkata", 2500, "private CAD coaching centres"),
    ("Park Street, Kolkata", 2500, "autocad training institute, not colleges or schools"),
    ("Garia, Kolkata", 3000, "CAD drafting coaching centre"),
    ("Behala, Kolkata", 3000, "autocad computer training institute"),
    ("Howrah Station, Howrah", 2500, "CAD training centre, not colleges or schools"),
    ("Serampore, Hooghly", 3000, "CAD training institute"),
    ("Chandannagar, Hooghly", 3000, "autocad coaching centre"),
    ("Bandel, Hooghly", 3000, "CAD training institute, not colleges or schools"),
    ("Barrackpore, North 24 Parganas", 3000, "CAD drafting training centre"),
    ("Dum Dum, Kolkata", 3000, "autocad training institute"),
    ("Kharagpur, West Bengal", 4000, "CAD training institute, not colleges or schools"),
    ("Durgapur, West Bengal", 4000, "CADD coaching centre"),
    ("Siliguri, West Bengal", 4000, "autocad training institute, not colleges"),
    ("Asansol, West Bengal", 4000, "CAD drafting training institute"),
    ("Berhampore, Murshidabad", 3500, "autocad coaching centre"),
    ("Noida Sector 18, Uttar Pradesh", 3000, "MEP HVAC drafting training institute, not colleges"),
    ("Shivaji Nagar, Pune", 3000, "CNC CAM tool design CAD training institute"),
    ("Marathahalli, Bangalore", 3000, "Revit BIM architectural drafting coaching centre"),
    ("Ameerpet, Hyderabad", 3000, "piping design and structural drafting training institute"),
]

_COLLEGE = ("college", "university", "mahavidyalaya", "vidyapith", "polytechnic",
            "institute of technology", "school of engineering", "iit ", "nit ",
            "iiit", "iim", "b.tech", "btech")
_SCHOOL = ("school", "vidyalaya", "convent", "high school", "secondary",
           "primary school", "public school")
_TRAINING = ("cad", "cadd", "autocad", "draft", "draught", "design", "training",
             "coaching", "institute", "academy", "computer", "technical",
             "multimedia", "animation", "skill", "classes", "centre", "center")


def bucket(biz: dict) -> str:
    """Classify a result independently of the app so the test measures reality."""
    name = (biz.get("name") or "").lower()
    tag = (biz.get("category") or "").lower()
    # Coaching / tutorial / classes for college/school subjects is still private coaching
    if any(k in name for k in ("coaching", "tutorial", "classes", "tuition")) and not any(k in name for k in ("college", "university", "polytechnic")):
        return "training"
    if any(k in name for k in _COLLEGE) or "college" in tag or "university" in tag:
        return "college"
    if any(k in name for k in _SCHOOL) or "school" in tag:
        return "school"
    if any(k in name for k in _TRAINING):
        return "training"
    return "other"


def run_scenario(location: str, radius: int, phrase: str,
                 enrich: bool = True, enrich_budget: float = 70.0,
                 enrich_max: int = 6) -> dict:
    from agents.workflows import search_businesses_workflow
    row = {"location": location, "radius": radius, "phrase": phrase,
           "started": datetime.now().isoformat(timespec="seconds")}
    t0 = time.monotonic()
    try:
        res = search_businesses_workflow(location, radius, category=phrase)
    except Exception:
        row.update(error=traceback.format_exc(limit=3))
        return row

    if res.get("error"):
        row.update(error=res["error"], seconds=round(time.monotonic() - t0, 1))
        return row

    kept = res.get("businesses") or []
    buckets = {"training": [], "college": [], "school": [], "other": []}
    for b in kept:
        buckets[bucket(b)].append(b)

    row.update(
        raw=res.get("found_raw"),
        kept=len(kept),
        source=res.get("source"),
        web_added=res.get("web_added", 0),
        counts={k: len(v) for k, v in buckets.items()},
        training=[b.get("name") for b in buckets["training"]],
        colleges=[b.get("name") for b in buckets["college"]],
        schools=[b.get("name") for b in buckets["school"]],
        others=[b.get("name") for b in buckets["other"]],
        filter_report=(res.get("filter_report") or "")[:600],
    )

    # Emails: the point of the exercise. Enrich only the training institutes;
    # colleges are not the customer and their addresses would flatter the score.
    if enrich and buckets["training"]:
        # Institutes with their own site, then CAD-named ones: both are the
        # likeliest to publish an address.
        targets = sorted(
            buckets["training"],
            key=lambda b: (0 if b.get("website") else 1,
                           0 if "cad" in (b.get("name") or "").lower() else 1),
        )[:enrich_max]
        try:
            from agents.contact_enricher import enrich_businesses
            stats = enrich_businesses(targets, log=lambda *_: None,
                                      budget=enrich_budget)
            emails = {b.get("name"): b.get("email") for b in targets if b.get("email")}
            phones = {b.get("name"): b.get("phone") for b in targets if b.get("phone")}
            row["enrich"] = {"searched": stats.get("searched"),
                             "emails_found": stats.get("emails_found"),
                             "deliverable": stats.get("deliverable")}
            row["emails"] = emails
            row["phones"] = phones
        except Exception as e:
            row["enrich"] = {"error": f"{type(e).__name__}: {e}"}

    row["seconds"] = round(time.monotonic() - t0, 1)
    return row


def summarise(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("error")]
    tot = {k: sum((r.get("counts") or {}).get(k, 0) for r in ok)
           for k in ("training", "college", "school", "other")}
    kept = sum(r.get("kept", 0) for r in ok)
    emails = {}
    for r in ok:
        emails.update(r.get("emails") or {})
    analysed = sum((r.get("enrich") or {}).get("searched", 0) for r in ok)
    return {
        "scenarios": len(rows), "ok": len(ok),
        "errors": [r["error"][:120] for r in rows if r.get("error")],
        "kept_total": kept, "buckets": tot,
        "precision_training": round(tot["training"] / kept, 3) if kept else 0.0,
        "college_leak": tot["college"] + tot["school"],
        "institutes_enriched": analysed,
        "institutes_with_email": len(emails),
        "email_yield": round(len(emails) / analysed, 3) if analysed else 0.0,
        "emails": emails,
        "web_rows_added": sum(r.get("web_added", 0) for r in ok),
        "slowest_s": max((r.get("seconds", 0) for r in ok), default=0),
        "total_s": round(sum(r.get("seconds", 0) for r in ok), 1),
    }


def to_markdown(rows: list[dict], s: dict) -> str:
    lines = ["# Playtest - private CAD training institutes", "",
             f"Run: {datetime.now().isoformat(timespec='seconds')}", "",
             "## Summary", "",
             f"- Scenarios: {s['ok']}/{s['scenarios']} completed",
             f"- Results kept by the pipeline: {s['kept_total']}",
             f"- Training institutes: {s['buckets']['training']} "
             f"({s['precision_training']:.0%} of kept)",
             f"- Colleges + schools leaked: {s['college_leak']}",
             f"- Rows added by web discovery: {s['web_rows_added']}",
             f"- Institutes enriched: {s['institutes_enriched']}, with email: "
             f"{s['institutes_with_email']} ({s['email_yield']:.0%})",
             f"- Wall clock: {s['total_s']}s (slowest scenario {s['slowest_s']}s)",
             ""]
    if s["errors"]:
        lines += ["Errors:", *[f"- {e}" for e in s["errors"]], ""]

    lines += ["## Per scenario", "",
              "| location | raw | kept | training | college | school | emails | s |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r.get("error"):
            lines.append(f"| {r['location']} | - | - | - | - | - | ERROR | - |")
            continue
        c = r.get("counts") or {}
        lines.append(
            f"| {r['location']} | {r.get('raw')} | {r.get('kept')} | "
            f"{c.get('training', 0)} | {c.get('college', 0)} | {c.get('school', 0)} | "
            f"{len(r.get('emails') or {})} | {r.get('seconds')} |")

    lines += ["", "## Training institutes found", ""]
    for r in rows:
        if r.get("training"):
            lines.append(f"**{r['location']}** - {r['phrase']}")
            for n in r["training"]:
                em = (r.get("emails") or {}).get(n)
                lines.append(f"- {n}" + (f" - {em}" if em else ""))
            lines.append("")

    leaks = [(r["location"], n) for r in rows for n in (r.get("colleges") or [])
             + (r.get("schools") or [])]
    if leaks:
        lines += ["## College / school leaks", ""]
        lines += [f"- {loc}: {n}" for loc, n in leaks]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="comma-separated 1-based scenario numbers")
    ap.add_argument("--no-enrich", action="store_true")
    ap.add_argument("--enrich-budget", type=float, default=70.0)
    ap.add_argument("--radius", type=int, default=0)
    args = ap.parse_args()

    picks = SCENARIOS
    if args.only:
        idx = [int(x) for x in args.only.split(",") if x.strip()]
        picks = [SCENARIOS[i - 1] for i in idx if 0 < i <= len(SCENARIOS)]
    if args.limit:
        picks = picks[:args.limit]

    rows = []
    for i, (loc, radius, phrase) in enumerate(picks, 1):
        r = args.radius or radius
        print(f"[{i}/{len(picks)}] {loc} ({r}m) :: {phrase}", flush=True)
        row = run_scenario(loc, r, phrase, enrich=not args.no_enrich,
                           enrich_budget=args.enrich_budget)
        if row.get("error"):
            print(f"    ERROR {row['error'][:140]}", flush=True)
        else:
            c = row["counts"]
            print(f"    raw={row['raw']} kept={row['kept']} "
                  f"training={c['training']} college={c['college']} "
                  f"school={c['school']} web+={row.get('web_added')} "
                  f"emails={len(row.get('emails') or {})} ({row['seconds']}s)",
                  flush=True)
        rows.append(row)

    s = summarise(rows)
    out_dir = Path(os.environ["JODIAC_HOME"]) / "playtests"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (out_dir / f"training_{stamp}.json").write_text(
        json.dumps({"summary": s, "rows": rows}, indent=2, default=str),
        encoding="utf-8")
    md = to_markdown(rows, s)
    (out_dir / f"training_{stamp}.md").write_text(md, encoding="utf-8")
    print("\n" + md[:4000])
    print(f"\nReport: {out_dir / f'training_{stamp}.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
