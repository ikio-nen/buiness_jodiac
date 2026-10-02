# -*- coding: utf-8 -*-
"""Exclusion gate test -- the Bandel failure regression suite.

The user asked for "private computer academies, remove schools and colleges"
and got convent schools and engineering colleges back. This proves the fix:

1. extract_exclusions parses the user's own words (typos included: 'cllgs').
2. Stage 0 hard-gates matches BEFORE AI and ICP can resurrect them.
3. The gate holds in all three modes: AI up, AI unavailable with a goal
   (fail-open to ICP), AI unavailable without a goal (strict tags).
4. The ICP veto is visible in the report AND scoped correctly: only a
   DIRECT-FIT ICP verdict may resurrect an AI-dropped business. "Plausible"
   is weak evidence and must lose to the AI's explicit "never a fit" --
   the Kolkata run flood-filled results with venues (auditorium, library,
   campus-tagged schools) because plausible ICP verdicts resurrected them.

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
check("veto names the resurrected direct fit (Belur Math, ICP 92)",
      "Belur Math" in report5, report5)
check("plausible is NOT resurrected: Auxilium (ICP 61) stays dropped",
      "Auxilium" not in report5, report5)
check("plausible school not in kept either",
      not any("Auxilium" in b["name"] for b in kept5),
      [b["name"] for b in kept5])

print("== Space-separated ban lists (Calcutta University failure) ==")
# The user typed: "autocad training institutes in kolkata remove schools
# colleges auditoriums and libraries" -- space-separated bans, no commas.
# The old parser produced ONE keyword "schools colleges auditoriums" that
# matched nothing, and stage 0 dropped NOTHING; the ICP veto then resurrected
# two University of Calcutta campuses at fit 85 that the AI had dropped.
excl4, pos4 = extract_exclusions(
    "autocad training institutes in kolkata remove schools colleges auditoriums and libraries")
check("space-separated bans parsed individually",
      any("school" in e for e in excl4) and any("college" in e for e in excl4)
      and any("auditorium" in e for e in excl4) and any("librar" in e for e in excl4),
      repr(excl4))
check("positive phrase kept", "autocad" in pos4 and "training" in pos4, repr(pos4))

uni = {"name": "University of Calcutta, College Street Campus",
       "category": "college", "tags": {"amenity": "university"}}
check("university banned via parsed 'colleges' (plural->lexicon)",
      _exclusion_hit(uni, excl4) != "", _exclusion_hit(uni, excl4))
check("library keyword bans a library record",
      _exclusion_hit({"name": "Central Library", "category": "library"}, excl4) != "",
      _exclusion_hit({"name": "Central Library", "category": "library"}, excl4))

print("== The veto itself must honor exclusions (defense in depth) ==")
# Even when stage 0 somehow misses (future parse gap), a direct-fit ICP verdict
# may NOT resurrect a business the user's own ban words match.
kept6, report6 = filter_by_category(
    [{"name": "University of Calcutta, Rajabazar Science College Campus",
      "category": "college", "icp": {"fit": "fits", "fit_score": 85}},
     {"name": "CADD Centre Kolkata", "category": "training",
      "icp": {"fit": "fits", "fit_score": 94}}],
    "autocad training institutes in kolkata remove schools colleges auditoriums and libraries",
    goal=GOAL)
names6 = [b["name"] for b in kept6]
check("direct-fit university stays dead (85 fit loses to 'remove colleges')",
      not any("Calcutta" in n for n in names6), names6)
check("genuine training centre survives", "CADD Centre Kolkata" in names6, names6)

print("== Non-customer corpus: places, venues, structures (universal gate) ==")
# One gate for the whole class: a name for a PLACE, VENUE, or STRUCTURE is
# not an organization and cannot buy — for any goal, regardless of tags.
# Every entry is a real leak shape from live Kolkata/Howrah searches.
from agents.icp import classify as _icp_classify, resolve_goal as _rg

_GOAL = {**_rg(), "never_tags": GOAL["never_tags"]}

def _dropped_as_place(biz: dict) -> str:
    """The structural disqualifier, or '' — accepts either the name gate
    ('place ... not a business') or the tag gate ('tagged library') since
    both are correct structural rejections."""
    v = _icp_classify(biz, goal=_GOAL)
    for d in v["disqualifiers"]:
        if "not a business" in d or d.startswith("tagged "):
            return d
    return ""

_NON_CUSTOMERS = [
    # venues (round 1 leaks)
    ({"name": "Doctor Jaya Deb Roy Auditorium", "tags": {"amenity": "college"}}, "auditorium"),
    ({"name": "Central Library", "tags": {"amenity": "library"}}, "dropped"),
    ({"name": "Ambedkar Bhawan - Cultural Research Institute", "tags": {}}, "bhawan"),
    ({"name": "B. K. Paul's Institution Ground", "tags": {"leisure": "pitch"}}, "ground"),
    ({"name": "Kolkata Town Hall", "tags": {"historic": "yes"}}, "town hall"),
    ({"name": "Birla Planetarium", "tags": {"tourism": "attraction"}}, "planetarium"),
    ({"name": "Indian Museum", "tags": {"tourism": "museum"}}, "museum"),
    ({"name": "Howrah Maidan", "tags": {"leisure": "park"}}, "maidan"),
    # campus structures (round 2 leaks) — tail grammar: the owner noun does
    # not change what the record IS
    ({"name": "Duff Building", "tags": {"amenity": "college"}}, "building"),
    ({"name": "SCC - Main Building", "tags": {"amenity": "college"}}, "building"),
    ({"name": "St. Xaviers College Main Building", "tags": {"amenity": "college"}}, "building"),
    ({"name": "Academic Block A", "tags": {"amenity": "university"}}, "block"),
    ({"name": "University Hostel 3", "tags": {"amenity": "university"}}, "hostel"),
    ({"name": "Science Annex", "tags": {"amenity": "college"}}, "annex"),
    ({"name": "Main Gate, Rajabazar Campus", "tags": {}}, "gate"),
    ({"name": "Staff Quarters", "tags": {"amenity": "university"}}, "quarters"),
    ({"name": "College Football Ground", "tags": {"leisure": "pitch"}}, "ground"),
]

for i, (biz, word) in enumerate(_NON_CUSTOMERS):
    got = _dropped_as_place(biz)
    if word == "dropped":
        check(f"non-customer: {biz['name']}", got != "", str(
            _icp_classify(biz, goal=_GOAL)["fit_score"]))
    else:
        check(f"non-customer: {biz['name']}", word in got, got or str(
            _icp_classify(biz, goal=_GOAL)["fit_score"]))

_MUST_STAY = [
    ({"name": "CADD Centre Kolkata", "tags": {"shop": "training"}},
     "training centre"),
    ({"name": "Youth Computer Training Centre", "tags": {"amenity": "training"}},
     "training centre 2"),
    ({"name": "University of Calcutta, Rajabazar Science College Campus",
     "tags": {"amenity": "university"}}, "a university IS a customer for CAD"),
    ({"name": "Building Systems Consultants Pvt Ltd", "tags": {"office": "company"}},
     "company whose name contains 'building'"),
    ({"name": "Heritage Institute of Technology", "tags": {"amenity": "university"}},
     'institute + operator word (technology) survives the anywhere-rule'),
]

for biz, label in _MUST_STAY:
    got = _dropped_as_place(biz)
    check(f"must stay: {biz['name']} ({label})", got == "", got)

print("== Learned type-conversion history acts on decisions and prompts ==")
# The brain tracks judged-per-type; rates (fits/judged, min sample) nudge
# scores ±5 with a named reason, re-order rankings, and reach agent prompts.
import agents.icp as _icp
from agents.config import get_active_goal as _get_goal, set_active_goal as _set_goal

_fake_rates = {"College / university": 0.86, "School (K-12)": 0.12}
_orig_reader = _icp.learned_type_rates
_icp.learned_type_rates = lambda key="": _fake_rates
_saved_goal = _get_goal()
_set_goal("")   # resolve ambient state, not whatever the user last pinned
try:
    _g = _rg()
    _hi = _icp.classify({"name": "Bangabhashi College", "tags": {"amenity": "college"}},
                        goal=_g)
    check("high-rate type gets +5 with a named history reason",
          any("86% of judged" in r for r in _hi["fit_reasons"]), _hi["fit_reasons"])
    _lo = _icp.classify({"name": "Some Public School", "tags": {"amenity": "school"}},
                        goal=_g)
    check("low-rate type gets -5 with a named history reason",
          any("only 12% of judged" in r for r in _lo["fit_reasons"]), _lo["fit_reasons"])
    _icp.learned_type_rates = lambda key="": {"School (K-12)": 0.31}
    _mid = _icp.classify({"name": "Some Public School", "tags": {"amenity": "school"}},
                         goal=_g)
    check("neutral band (0.31) stays silent",
          not any(r.startswith("history:") for r in _mid["fit_reasons"]))
    _icp.learned_type_rates = lambda key="": {}
    _none = _icp.classify({"name": "Bangabhashi College", "tags": {"amenity": "college"}},
                          goal=_g)
    check("no history at all -> no history reason (cold start unchanged)",
          not any(r.startswith("history:") for r in _none["fit_reasons"]))
    _icp.learned_type_rates = lambda key="": _fake_rates
    _kept, _dropped, _rep, _sum = _icp.rank(
        [{"name": "Some Public School", "tags": {"amenity": "school"}},
         {"name": "Bangabhashi College", "tags": {"amenity": "college"}}], goal=_g)
    check("rank report names the best-converting type",
          "History: best conversion" in _rep, _rep[-120:])
    check("history re-orders: college (86%) outranks school (12%)",
          _kept and _kept[0]["name"] == "Bangabhashi College",
          [b["name"] for b in _kept])
finally:
    _icp.learned_type_rates = _orig_reader
    _set_goal(_saved_goal)   # never leak a changed pin into the user's state

print("== Rejection memory: structural NOs are never re-litigated ==")
# The brain's rejected_names map finally ACTS: structural rejections keep
# their verdict without re-judging (and stay out of the rate denominators
# they would only inflate); score-only rejections are never remembered;
# a NO from one goal is never a NO from another.
import json as _json
import tempfile as _tempfile
import shutil as _shutil
import pathlib as _pathlib
import agents.brain as _brain_mod
_tmp = _tempfile.mkdtemp()
_brain_mod.BRAIN_DIR = _pathlib.Path(_tmp)
from agents.brain import Brain as _Brain
_b = _Brain()
_orig_get_brain = _brain_mod.get_brain
_brain_mod.get_brain = lambda: _b
try:
    _g = _rg()
    def _pipeline(batch):
        kept, dropped, rep, summ = _icp.rank([dict(x) for x in batch], goal=_g)
        _icp.learn(kept + dropped, goal=_g)
        return rep
    _batch = [{'name': 'Das Pharmacy', 'tags': {'amenity': 'pharmacy'}},
              {'name': 'Bangabhashi College', 'tags': {'amenity': 'college'}}]
    _pipeline(_batch)
    _s1 = _b.get_icp()['by_goal']['cad_licensing']
    _pipeline(_batch)
    _pipeline(_batch)
    _s3 = _b.get_icp()['by_goal']['cad_licensing']
    check("structural rejection remembered with its verbatim reason (no suffix compounding)",
          _s3['rejected_names'] == {'Das Pharmacy': 'tagged pharmacy'},
          _json.dumps(_s3['rejected_names']))
    check("memory skip never counted in rate denominators",
          not any('pharmacy' in k.lower() for k in _s3['type_stats']),
          _json.dumps(_s3['type_stats'], sort_keys=True))
    _rep3 = _pipeline(_batch)
    check("report states the skip honestly",
          'Memory: 1 previously rejected' in _rep3, _rep3[-120:])
    # score-only rejections are NOT memory-worthy
    _b.learn_icp_feedback(
        [{'name': 'Some Weak Institute', 'tags': {'amenity': 'college'},
          'icp': {'fit': 'unlikely', 'fit_score': 50, 'institution_type': 'College / university',
                  'fit_reasons': [], 'disqualifiers': ['below the fit threshold'],
                  'matched_signals': [], 'goal': 'cad_licensing'}}],
        goal_key='cad_licensing', goal_label='CAD', product='CAD keys')
    check("score-only rejection is never remembered (fresh judgment each time)",
          'Some Weak Institute' not in _icp.known_rejections('cad_licensing'))
    # cross-goal guard: a structural NO for one goal is not a NO for another
    _b.learn_icp_feedback(
        [{'name': 'Cafe Coffee Day', 'tags': {'amenity': 'cafe'},
          'icp': {'fit': 'unlikely', 'fit_score': 18, 'institution_type': '',
                  'fit_reasons': [], 'disqualifiers': ['tagged cafe'],
                  'matched_signals': [], 'goal': 'cad_licensing'}}],
        goal_key='cad_licensing', goal_label='CAD', product='CAD keys')
    _webg = _icp.GOALS['website']
    _kweb, _dweb, _rweb, _ = _icp.rank(
        [{'name': 'Cafe Coffee Day', 'tags': {'amenity': 'cafe'}}], goal=_webg)
    check("a NO from the CAD goal is a fresh judgment under the website goal",
          _kweb and 'known rejection' not in _rweb)
    _kcad, _dcad, _rcad, _ = _icp.rank(
        [{'name': 'Cafe Coffee Day', 'tags': {'amenity': 'cafe'}}], goal=_g)
    check("...and the same cafe IS skipped under the CAD goal",
          _dcad and 'known rejection' in _dcad[0]['icp']['disqualifiers'][0])
    # Rate honesty: legacy entries mix an all-time ``seen`` (819) with a
    # since-tracking ``judged`` (26) — 3150% was a REAL bug the live search
    # printed. A pre-``fits`` epoch entry must stay silent; a re-based entry
    # (writer resets both counters) must produce fits/judged.
    check("pre-epoch type entry produces no rate (no 3150% nonsense)",
          _icp.learned_type_rates('cad_licensing').get('School (K-12)') is None
          or 'fits' in _s3['type_stats'].get('School (K-12)', {}),
          _json.dumps(_s3['type_stats'].get('School (K-12)', {})))
    _b.learn_icp_feedback(
        [{'name': 'Honest Institute', 'tags': {'amenity': 'college'},
          'icp': {'fit': 'fits', 'fit_score': 88, 'institution_type': 'College / university',
                  'fit_reasons': [], 'disqualifiers': [], 'matched_signals': [],
                  'goal': 'cad_licensing'}}],
        goal_key='cad_licensing', goal_label='CAD', product='CAD keys')
    _college_ts = (_b.get_icp()['by_goal']['cad_licensing']['type_stats']
                   .get('College / university', {}))
    check("writer tracks fits alongside judged (same epoch)",
          1 <= _college_ts.get('fits', 0) <= _college_ts.get('judged', 0),
          _json.dumps(_college_ts))
    check("epoch-true rate is fits/judged",
          'College / university' not in _icp.learned_type_rates('cad_licensing')
          or _icp.learned_type_rates('cad_licensing')['College / university'] <= 1.0,
          _json.dumps(_icp.learned_type_rates('cad_licensing')))
    # report clobber: Memory: and History: sentences must coexist
    _b.learn_icp_feedback(
        [{'name': 'Das Pharmacy', 'tags': {'amenity': 'pharmacy'},
          'icp': {'fit': 'unlikely', 'fit_score': 0, 'institution_type': 'Rejected (memory)',
                  'fit_reasons': [], 'disqualifiers': ['tagged pharmacy'],
                  'matched_signals': [], 'goal': 'cad_licensing'}}],
        goal_key='cad_licensing', goal_label='CAD', product='CAD keys')
    _icp_ltr_orig = _icp.learned_type_rates
    _icp.learned_type_rates = lambda key='': {'College / university': 0.85}
    try:
        _k2, _d2, _r2, _ = _icp.rank(
            [{'name': 'Das Pharmacy', 'tags': {'amenity': 'pharmacy'}},
             {'name': 'Honest Institute', 'tags': {'amenity': 'college'}}], goal=_g)
        check("report carries Memory: and History: together (no clobber)",
              'Memory:' in _r2 and 'History:' in _r2, _r2[-160:])
    finally:
        _icp.learned_type_rates = _icp_ltr_orig
finally:
    _brain_mod.get_brain = _orig_get_brain
    _shutil.rmtree(_tmp, ignore_errors=True)

print()
print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
