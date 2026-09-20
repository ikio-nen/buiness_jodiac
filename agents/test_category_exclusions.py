# -*- coding: utf-8 -*-
"""Exclusion gate test -- the Bandel failure regression suite.

The user asked for "private computer academies, remove schools and colleges"
and got convent schools and engineering colleges back. This proves the fix:

1. extract_exclusions parses the user's own words (typos included: 'cllgs').
2. Stage 0 hard-gates matches BEFORE AI and ICP can resurrect them.
3. The gate holds in all three modes: AI up, AI unavailable with a goal
   (fail-open to ICP), AI unavailable without a goal (strict tags).
4. The ICP veto is now visible in the report instead of hiding as
   "AI dropped nothing".

Run:  E:/python.exe -X utf8 agents/test_category_exclusions.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.category_filter import (
    extract_exclusions, filter_by_category, _exclusion_hit, _evidence_note,
)

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


# A Bandel-shaped batch: exactly the kinds the user kept getting back.
BATCH = [
    {"name": "Auxilium Convent School", "category": "school",
     "icp": {"fit": "plausible", "fit_score": 61}},
    {"name": "Bandel St. John's High School", "category": "school",
     "icp": {"fit": "plausible", "fit_score": 61}},
    {"name": "Belur Math Polytechnic College", "category": "college",
     "icp": {"fit": "fits", "fit_score": 92}},
    {"name": "Government College of Engineering and Technology", "category": "college",
     "icp": {"fit": "fits", "fit_score": 92}},
    {"name": "Milan Park GSFP Primary school", "category": "school",
     "icp": {"fit": "plausible", "fit_score": 61}},
    {"name": "Youth Computer Training Centre", "category": "training",
     "icp": {"fit": "fits", "fit_score": 94}},
    {"name": "NIIT Bandel", "category": "training",
     "icp": {"fit": "fits", "fit_score": 88}},
]

CATEGORY = ("private computer academy that teaches autocad, "
            "remove schools and cllgs")
GOAL = {"never_tags": ("hospital", "clinic", "pharmacy", "restaurant", "cafe")}


def fresh():
    # filter_by_category mutates via list ops but not dicts; copy for safety.
    return [dict(b) for b in BATCH]


print("== extract_exclusions parses the user's words ==")
excl, positive = extract_exclusions(CATEGORY)
check("school excluded", any("school" in e for e in excl), repr(excl))
check("typo 'cllgs' present (matcher maps it to college ban)",
      any("cllg" in e for e in excl), repr(excl))
check("positive phrase keeps the ask",
      "computer academy" in positive or "autocad" in positive, repr(positive))

excl2, _ = extract_exclusions("educational centers that teach autocad")
check("no markers -> no exclusions", excl2 == [], repr(excl2))

excl3, pos3 = extract_exclusions("training centers remove colleges and universities")
check("multi-item ban parsed",
      any("college" in e for e in excl3) and any("universit" in e for e in excl3),
      repr(excl3))

print("== _exclusion_hit matches tag OR name ==")
check("tag hit", _exclusion_hit({"name": "X", "category": "school"}, ["school"]) == "school")
check("name hit on tag-less record",
      _exclusion_hit({"name": "Auxilium Convent", "category": "yes"},
                     ["school"]) == "school")
check("unknown keyword falls back to substring",
      _exclusion_hit({"name": "Coaching Hub", "category": "training"},
                     ["coaching"]) == "coaching")
check("clean business untouched",
      _exclusion_hit({"name": "Youth Computer Centre", "category": "training"},
                     ["school", "college"]) == "")

print("== evidence notes carry source data to the judge ==")
note = _evidence_note({"name": "Y", "category": "training",
                       "tags": {"description": "AutoCAD courses",
                                "phone": "+91..."}})
check("description flows into evidence", "AutoCAD courses" in note, repr(note))
check("irrelevant tags stay out", "phone" not in note, repr(note))
check("no evidence -> empty note",
      _evidence_note({"name": "Z", "category": "school", "tags": {"phone": "1"}}) == "")

print("== Stage 0 gate, AI unavailable, goal present (fail-open to ICP) ==")
import agents.ai_engine as ai_engine
ai_engine.is_available = lambda: False  # force the deterministic path

kept, report = filter_by_category(fresh(), CATEGORY, goal=GOAL)
names = [b["name"] for b in kept]
check("no school survives", not any("School" in n or "school" in n for n in names), names)
check("no college survives (incl. 92-fit polytechnic)",
      not any("College" in n or "Polytechnic" in n for n in names), names)
check("training centres kept", "Youth Computer Training Centre" in names, names)
check("report names the exclusions", "user exclusions" in report, report)

kept2, report2 = filter_by_category(fresh(), CATEGORY, goal=None)
names2 = [b["name"] for b in kept2]
check("no-goal strict mode also drops schools/colleges",
      not any("School" in n or "College" in n for n in names2), names2)
check("no-goal strict mode keeps training", "NIIT Bandel" in names2, names2)

print("== Exclusion ban-all edge ==")
kept3, report3 = filter_by_category(
    [{"name": "St. John's High School", "category": "school",
      "icp": {"fit": "plausible"}}],
    "remove schools", goal=GOAL)
check("everything banned -> empty list, honest report",
      kept3 == [] and "removed everything" in report3, (kept3, report3))

print("== Veto transparency (AI up, mock the tiers) ==")
ai_engine.is_available = lambda: True


def fake_generate_json(*args, **kwargs):
    # Simulated Gemini: echo the prompt back so we can also assert what the
    # judge was told, then classify exactly per the exclusion rubric.
    prompt = kwargs.get("prompt", "") or (args[0] if args else "")
    if "remove schools" in prompt.replace("CLLGS", "schools").lower() or \
            ("ABSOLUTE EXCLUSIONS" in prompt and "school" in prompt.lower()):
        banned_names = ["Auxilium", "St. John", "Milan Park",
                        "Belur Math", "Government College"]
        unlikely = []
        for line in prompt.splitlines():
            if line[:2].strip(".").isdigit():
                idx = int(line.split(".")[0])
                if any(bn in line for bn in banned_names):
                    unlikely.append(idx)
        fits = [int(l.split(".")[0]) for l in prompt.splitlines()
                if l[:2].strip(".").isdigit()
                and int(l.split(".")[0]) not in unlikely]
        return {"fits": fits, "plausible": [], "unlikely": unlikely}
    return {"fits": [6, 7], "plausible": [], "unlikely": [1, 2, 3, 4, 5]}


ai_engine.generate_json = fake_generate_json
kept4, report4 = filter_by_category(fresh(), CATEGORY, goal=GOAL)
names4 = [b["name"] for b in kept4]
check("exclusion still wins over AI+ICP: no school in kept",
      not any("School" in n or "school" in n for n in names4), names4)
check("colleges dropped too", not any("College" in n for n in names4), names4)
check("clean fits survive", "Youth Computer Training Centre" in names4, names4)

# The prompt the judge receives must carry the absolute-exclusion instruction.
prompt_holder = {}


def capture_generate_json(*args, **kwargs):
    prompt_holder["p"] = kwargs.get("prompt", "") or (args[0] if args else "")
    return {"fits": [6, 7], "plausible": [], "unlikely": [1, 2, 3, 4, 5]}


ai_engine.generate_json = capture_generate_json
filter_by_category(fresh(), CATEGORY, goal=GOAL)
p = prompt_holder["p"]
check("judge briefed on absolute exclusions", "ABSOLUTE EXCLUSIONS" in p, p[:200])
check("judge sees the user's own ban words", "cllgs" in p.lower(), p[:200])
check("judge receives the exclusion rubric line",
      "no matter how well it otherwise fits" in p, p[:300])

# Without any exclusion phrase the veto path must be VISIBLE, not silent.
CATEGORY_NO_EXCL = "institutes for autocad"
kept5, report5 = filter_by_category(fresh(), CATEGORY_NO_EXCL, goal=GOAL)
check("veto surfaced in report when AI drops an ICP fit",
      "ICP veto kept" in report5, report5)
check("veto names the resurrected school",
      "Auxilium" in report5, report5)

print()
print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
