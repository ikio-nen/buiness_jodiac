"""Category filter -- judge search results against what the user actually asked for.

Design (post-mortem of the "hospitals for AutoCAD" failure):
1. Kill-list first: OSM tags that can NEVER match an intent, regardless of name.
   ("Calcutta Medical College" is a hospital; the name contains "college".)
2. AI as the primary reasoner: one Gemini call receives the user's full original
   phrasing (not a collapsed one-word category) plus every business, and judges
   fit in tiers: fits / plausible / unlikely.
3. Fail closed: if AI is unavailable or errors, fall back to a strict
   tag-based filter -- never return the unfiltered pile.
4. Every filter run produces a report so the UI can show its work
   ("dropped 14 hospitals, 9 computer stores") instead of the user auditing it.
"""

import re as _re

# OSM tags that disqualify a business for education intent no matter what its
# name says. Substring-matched against the OSM category tag (not the name).
TAG_KILL_LIST = (
    "hospital", "blood_bank", "post_office", "pharmacy", "dentist",
    "clinic", "doctors", "veterinary", "place_of_worship", "police",
    "fire_station", "bank", "atm", "fuel", "parking", "marketplace",
    "restaurant", "cafe", "fast_food", "bar", "pub", "bakery",
)

# Tags accepted when running strict (fail-closed) mode for an education intent.
STRICT_EDUCATION_TAGS = (
    "school", "college", "university", "training", "institute",
    "educational_institution", "kindergarten", "language_school",
    "music_school", "prep_school", "research_institute",
)

# What a user's "remove X" phrasing bans, by keyword: (tag tokens, name tokens).
# A business is excluded when the keyword hits its category tag OR its name.
EXCLUSION_LEXICON = {
    "school": {"tags": ("school", "kindergarten", "prep_school"),
               "names": ("school", "vidyalaya", "convent", "vidyamandir")},
    "college": {"tags": ("college", "university"),
                "names": ("college", "university", "mahavidyalaya", "vidyapith")},
    "university": {"tags": ("university", "college"),
                   "names": ("university", "college", "mahavidyalaya", "vidyapith")},
    "collg": {"tags": ("college", "university"), "names": ("college", "university")},
    "cllg": {"tags": ("college", "university"), "names": ("college", "university")},
    "colleges": {"tags": ("college", "university"),
                 "names": ("college", "university", "mahavidyalaya", "vidyapith")},
    "schools": {"tags": ("school", "kindergarten", "prep_school"),
                "names": ("school", "vidyalaya", "convent", "vidyamandir")},
    "universities": {"tags": ("university", "college"),
                     "names": ("university", "college")},
    "polytechnic": {"tags": ("college",), "names": ("polytechnic",)},
    "auditorium": {"tags": ("auditorium",), "names": ("auditorium", "bhawan", "sabha")},
    "library": {"tags": ("library",), "names": ("library", "granthaghar")},
    "engineering college": {"tags": (), "names": ("engineering college",
                                                  "college of engineering",
                                                  "institute of technology",
                                                  "school of engineering")},
    "hospital": {"tags": ("hospital", "clinic", "doctors"), "names": ("hospital",)},
    "clinic": {"tags": ("clinic", "doctors", "dentist"), "names": ("clinic",)},
    "pharmacy": {"tags": ("pharmacy",), "names": ("pharmacy", "chemist")},
    "restaurant": {"tags": ("restaurant", "cafe", "fast_food"), "names": ("restaurant",)},
    "cafe": {"tags": ("cafe", "fast_food"), "names": ("cafe", "coffee")},
}

# Words that mark the phrase before them as something the user does NOT want.
# "dont want"/"don't want" are here because that is how users actually phrase
# bans in chat ("i dont want cllgs").
_EXCLUDE_MARKERS = ("remove", "exclude", "no ", "without", "drop", "except",
                    "other than", "not ", "dont want", "don't want",
                    "do not want")


def extract_exclusions(category: str) -> tuple[list[str], str]:
    """Pull the user's 'remove X' terms out of their own phrasing.

    Returns (exclusion keywords, remaining phrase). Deterministic: the user's
    explicit exclusions must bind even when the AI is down, so they are parsed
    locally, never by the model. "remove schools and cllgs" ->
    (["school", "cllg"], "").
    """
    text = " ".join((category or "").lower().split())
    if not text:
        return [], ""
    if not any(m in text for m in _EXCLUDE_MARKERS):
        return [], category

    keep_parts: list[str] = []
    excluded: list[str] = []
    # Split on the markers; the segment after each marker up to the next
    # marker/punctuation is the ban list ("remove schools and colleges").
    import re as _re
    segments = _re.split(
        r"\b(?:other than|do not want|dont want|don't want|remove|exclude"
        r"|without|drop|except|not|no)\s+", text)
    # segments[0] is the positive phrase; every later segment starts with the
    # banned terms. Within a ban segment, "and"/","/"plus" separate items and
    # a repeated marker ("no X and no Y") starts another ban item. "no" MUST
    # carry a word boundary: "techno colleges" contains "no c" and must not
    # split. Property descriptions survive too: "with no website" is a target
    # spec, not a ban (lookbehind guards "with/has/have/having no").
    ban_seg_split = _re.compile(
        r"[,.]|\bthat\b|\bwhich\b|\bgive me\b|\bi want\b|\bshow me\b"
        r"|\bsearch\b|\bfind\b")
    item_split = _re.compile(r"\band\b|\bplus\b|,|/|\bno\b|\bnot\b")
    no_guard = _re.compile(
        r"(?<!with )(?<!has )(?<!have )(?<!having )\bno\s+")
    protected = no_guard.sub("\u0000no ", text)
    segments = _re.split(
        r"\b(?:other than|do not want|dont want|don't want|remove|exclude"
        r"|without|drop|except|not)\s+", protected)
    segments = [s.replace("\u0000", "") for s in no_guard.split(segments[0])] \
        + [s.replace("\u0000", "") for s in segments[1:]]
    for seg in segments[1:]:
        seg = ban_seg_split.split(seg)[0]
        for item in item_split.split(seg):
            item = item.strip(" .!?")
            if not item:
                continue
            if item in EXCLUSION_LEXICON or item in _KEYWORD_TYPOS or item[:-1] in EXCLUSION_LEXICON:
                excluded.append(item)
                continue
            # Space-separated ban lists ("remove schools colleges auditoriums")
            # arrive as ONE whitespace-joined "item" that matches nothing. A
            # non-lexicon multi-word item is therefore a LIST the separators
            # didn't catch: split it into words. Known multi-word lexicon
            # entries ("engineering college") never reach this branch.
            words = [w.strip(" .!?") for w in item.split() if w.strip(" .!?")]
            if len(words) > 1:
                excluded.extend(words)
            else:
                excluded.append(item)
    if segments[0].strip():
        keep_parts.append(segments[0].strip(" ,."))
    return excluded, ". ".join(keep_parts) if keep_parts else ""


# Common misspellings/abbreviations users type in exclusions, mapped into
# the lexicon ("cllgs" is exactly how the Bandel request was phrased).
_KEYWORD_TYPOS = {"cllgs": "cllg", "clgs": "cllg", "clge": "college",
                  "univs": "university", "collgs": "college", "skols": "school"}


def _exclusion_hit(business: dict, keywords: list[str]) -> str:
    """Return the keyword that bans this business, or ''. Tag OR name match."""
    import re as _re
    tag = (business.get("category") or "").lower()
    name = (business.get("name") or "").lower()
    # The FULL tag blob, not just the category string: Shri Shikshayatan
    # carries no ban token in its name or category, but its OSM tags say
    # amenity=school - Stage 0 must see what the ICP sees, or a user's
    # "remove schools" silently misses campus-tagged entities.
    tags = business.get("tags") or {}
    blob = " ".join([tag] + [f"{k} {v}" for k, v in tags.items()]).lower()
    for kw in keywords:
        lex = EXCLUSION_LEXICON.get(kw)
        if lex is None and kw.endswith("ies"):
            # -ies plural of a known ban word: "libraries" -> "library",
            # "universities" -> "university" (plain -s stripping misses
            # these: "libraries" -> "librarie" matches nothing)
            lex = EXCLUSION_LEXICON.get(kw[:-3] + "y")
        if lex is None and kw.endswith("s"):
            # plural of a known ban word: "schools" -> "school"

            lex = EXCLUSION_LEXICON.get(kw[:-1])
        if lex is None:
            lex = EXCLUSION_LEXICON.get(_KEYWORD_TYPOS.get(kw, ""))
        if lex is None:
            # Unknown keyword: match it as a raw substring against tag/name.
            if kw in tag or kw in name:
                return kw
            continue
        if any(t in tag for t in lex["tags"]):
            return kw
        if any(n in name for n in lex["names"]):
            return kw
        # lexicon tokens against the full blob (word-boundary for single
        # tokens so "school" fires on "amenity school" but not "schoolbag")
        for t in lex["tags"] + lex["names"]:
            if (" " in t and t in blob) or (" " not in t and
                    _re.search(rf"\b{_re.escape(t)}\b", blob)):
                return kw
    return ""


# Filler words that name no category. A phrase made ONLY of these
# ("businesses", "any local shops", "find me places near here") is not an
# intent -- it says "look around" and nothing more. Any specific word keeps the
# phrase out of this set ("coaching centres", "business consultants",
# "colleges that teach autocad"), so real intents still reach the AI judge.
_CATEGORY_FILLERS = {
    "a", "all", "an", "and", "any", "around", "at", "be", "best", "biz",
    "business", "businesses", "client", "clients", "companies", "company",
    "customer", "customers", "don", "dont", "enterprise", "enterprises",
    "establishment", "establishments", "every", "find", "firm", "firms",
    "for", "from", "get", "give", "good", "here", "i", "in", "is", "lead",
    "leads", "list", "local", "look", "looking", "me", "more", "near",
    "need", "new", "of", "on", "or", "other", "others", "outlet", "outlets",
    "place", "places", "please", "prospect", "prospects", "s", "search",
    "shop", "shops", "show", "some", "store", "stores", "t", "that", "the",
    "to", "up", "us", "vendor", "vendors", "want", "we", "which", "will",
    "with", "would",
}


def _no_category_signal(category: str) -> bool:
    """True when the phrase names nothing to filter BY ("businesses").

    The AI tier filter asks the model whether each lead fits what the user is
    looking for. Handed a filler phrase it can only answer one way -- a school
    is not what "businesses" means -- and it drops leads the ICP had just
    accepted; that is how a Bandel search returned 0 businesses while holding
    5 plausible schools. An EMPTY phrase never triggers this (the caller
    already treats that as "no filter applied"), and a phrase with even one
    specific word takes the normal path.
    """
    words = _re.findall(r"[a-z]+", (category or "").lower())
    return bool(words) and all(w in _CATEGORY_FILLERS for w in words)


def filter_by_category(businesses: list[dict], category: str,
                       goal: dict = None) -> tuple[list[dict], str]:
    """Filter businesses to match the user's stated intent.

    Args:
        businesses: List of business dicts with 'name' and 'category' keys.
        category: The user's own phrasing, e.g.
            "educational centers that teach autocad and will be suitable customers".
        goal: The active search goal (agents/icp.py). Its ``never_tags`` are the
            kill-list, so "never a fit" has one owner. Without it we fall back to
            the education-era list, which is wrong for e.g. a website goal where
            a clinic or a cafe is exactly the customer.

    Returns:
        (kept_businesses, report) where report is a human-readable one-liner
        explaining what was kept and dropped.
    """
    if not category:
        return businesses, "No category filter applied."

    # Stage 0: the user's own "remove X" phrasing. This is USER AUTHORITY: it
    # outranks the ICP verdict, the AI verdict, and every fallback below. A
    # user who says "remove schools and colleges" must never see a convent
    # school come back -- that was the Bandel failure.
    exclusions, positive_phrase = extract_exclusions(category)
    excl_dropped: dict[str, int] = {}
    if exclusions:
        survivors = []
        for b in businesses:
            hit = _exclusion_hit(b, exclusions)
            if hit:
                excl_dropped[hit] = excl_dropped.get(hit, 0) + 1
            else:
                survivors.append(b)
        businesses = survivors
        if not businesses:
            if excl_dropped:
                return [], (f"Filtered {len(excl_dropped)} -> 0 for \"{category}\": "
                            f"user exclusion removed everything "
                            f"({_fmt_counts(excl_dropped)}).")
            # Zero businesses ARRIVED here — the exclusions removed nothing.
            # Blaming the user's phrasing for an upstream empty was a lie that
            # read as "your query is wrong" when really the search found none.
            return [], (f"Filtered 0 -> 0 for \"{category}\": no businesses "
                        f"reached the filter, so the exclusions removed nothing.")

    kill_tags = tuple(goal.get("never_tags") or ()) if goal else TAG_KILL_LIST

    # Stage 1: tag kill-list -- never argue with these.
    kept, dropped = [], {}
    for b in businesses:
        tag = (b.get("category") or "").lower()
        killer = next((t for t in kill_tags if t in tag), None)
        if killer:
            dropped[killer] = dropped.get(killer, 0) + 1
        else:
            kept.append(b)

    if not kept:
        return [], f"Everything dropped by hard tags: {dropped}."

    # Stage 1b: the phrase names no category ("businesses in Bandel"). Stage 2
    # would ask the AI whether each survivor fits the word "businesses" -- and
    # the rubric's "unlikely" tier then eats real prospects. The ICP is the
    # authority on who is a customer (see the veto note in _ai_tier_filter);
    # with no category named, its verdict stands and nothing is re-judged.
    # User authority is untouched: Stage 0 exclusions and the hard tags above
    # already ran and are reported here.
    # Judged on the phrase LEFT after exclusions are stripped: "businesses
    # except cafes" names no category either, and its ban word must not look
    # like an intent. (A pure ban phrase leaves that empty -- and an empty
    # phrase is deliberately NOT signal-less here, so "remove schools" keeps
    # its existing path and report.)
    if _no_category_signal(positive_phrase):
        excl_txt = (f"user exclusions dropped {sum(excl_dropped.values())} "
                    f"({_fmt_counts(excl_dropped)}); " if excl_dropped else "")
        report = (f"Filtered {len(businesses) + sum(excl_dropped.values())} -> "
                  f"{len(kept)} for \"{category}\": {excl_txt}hard tags dropped "
                  f"{sum(dropped.values())} ({_fmt_drops(dropped) or 'none'}); "
                  f"no category named, so the ICP verdict stands as-is.")
        return kept, report

    # Stage 2: AI reasons about fit in tiers over everything that survived.
    judged = _ai_tier_filter(kept, category, exclusions=exclusions)
    if judged is not None:
        kept, ai_dropped, vetoed = judged
        ai_drops = ", ".join(f"{n} {tag}" for tag, n in _top_drops(ai_dropped)) or "nothing"
        veto_txt = ""
        if vetoed:
            veto_txt = (f" [ICP veto kept {len(vetoed)} AI-dropped: "
                        f"{', '.join(b.get('name', '?') for b in vetoed[:4])}]")
        excl_txt = (f"user exclusions dropped {sum(excl_dropped.values())} "
                    f"({_fmt_counts(excl_dropped)}); " if excl_dropped else "")
        report = (f"Filtered {len(businesses) + sum(excl_dropped.values())} -> {len(kept)} "
                  f"for \"{category}\": {excl_txt}"
                  f"hard tags dropped {sum(dropped.values())} ({_fmt_drops(dropped)}); "
                  f"AI dropped {ai_drops}.{veto_txt}")
        return kept, report

    # Stage 3: fail closed. For a goal-scoped search the ICP has already judged
    # fit, so strict tag matching against an unknown intent would only throw away
    # good prospects -- keep them. Otherwise fall back to strict education tags.
    if goal is not None:
        excl_txt = (f"user exclusions dropped {sum(excl_dropped.values())} "
                    f"({_fmt_counts(excl_dropped)}); " if excl_dropped else "")
        report = (f"Filtered {len(businesses) + sum(excl_dropped.values())} -> {len(kept)} "
                  f"by goal tags (AI unavailable): {excl_txt}hard tags dropped "
                  f"{sum(dropped.values())} ({_fmt_drops(dropped)}).")
        return kept, report

    strict = [b for b in kept if _is_strict_tag_match(b, category)]
    report = (f"Filtered {len(businesses)} -> {len(strict)} by strict tags "
              f"(AI unavailable): hard tags dropped {sum(dropped.values())} ({_fmt_drops(dropped)}).")
    return strict, report


def _ai_tier_filter(businesses: list[dict], category: str,
                    exclusions: list[str] | None = None
                    ) -> tuple[list[dict], dict, list[dict]] | None:
    """Ask Gemini to judge fit in tiers. Returns (kept, dropped_counts, vetoed) or None on failure.

    Chunked past 50 businesses so nothing is silently unread. Any failure
    returns None so the caller fails closed to strict tags. ``vetoed`` lists
    the businesses the AI dropped but the ICP verdict resurrected, so the
    report can say who they are instead of hiding behind "AI dropped nothing".
    """
    exclusions = exclusions or []
    excl_note = ""
    if exclusions:
        excl_note = (f"\nABSOLUTE EXCLUSIONS the user demanded: {', '.join(exclusions)}. "
                     "Any business matching these (a school, a college, etc.) must "
                     "be marked \"unlikely\" no matter how well it otherwise fits.")
    try:
        from agents import ai_engine
        if not ai_engine.is_available():
            return None

        kept: list[dict] = []
        dropped: dict[str, int] = {}
        all_vetoed: list[dict] = []
        CHUNK = 50
        for i in range(0, len(businesses), CHUNK):
            chunk = businesses[i:i + CHUNK]
            biz_list = "\n".join(
                f"{j+1}. {b.get('name', '?')} [{b.get('category', '?')}]"
                f"{_evidence_note(b)}"
                for j, b in enumerate(chunk)
            )
            result = ai_engine.generate_json(
                prompt=f"""The user is looking for: "{category}"{excl_note}

For each business below, judge whether it fits what the user is looking for.
Use the tag in [brackets] as the ground truth for what it IS, not just the name
(names can be misleading: "Calcutta Medical College" is a hospital).

{biz_list}

Rubric -- judge by these rules, not impressions (an "evidence:" line carries
what the data source knows about the business -- e.g. a description naming
AutoCAD courses is strong proof it teaches CAD):
- "fits": the business's core activity serves the user's intent directly (e.g. for AutoCAD: an institute or college where CAD/engineering/design is taught or practiced as a core activity).
- "plausible": a genuine education institution in a related field that could have a use for the product/service, even if the intent field is not its core activity.
- "unlikely": its core activity cannot serve the intent (hospitals, cafes, shops, hostels, post offices...).
If the tag is missing or meaningless (e.g. "yes", "other"), judge by the name; if the name also gives no evidence of serving the intent, mark it "unlikely".
Every business must appear in exactly one list. Be consistent: apply the rubric uniformly to every business.

Return JSON: {{"fits": [numbers], "plausible": [numbers], "unlikely": [numbers]}}""",
                system="You are a precise business classifier. Judge fit against the user's actual intent, not name keywords. Apply the rubric uniformly and deterministically.",
                temperature=0.1,
            )
            if not result:
                return None

            def collect(key: str) -> list[int]:
                # Accept floats too: a model that answers 4.0 used to have the
                # index silently dropped, which failed the whole chunk closed.
                vals = result.get(key, [])
                if not isinstance(vals, list):
                    return []
                return [int(v) for v in vals
                        if isinstance(v, (int, float)) and not isinstance(v, bool)]

            fits = collect("fits")
            plausible = collect("plausible")
            unlikely = collect("unlikely")

            total = len(fits) + len(plausible) + len(unlikely)
            if total != len(chunk):
                # AI skipped or duplicated businesses -- reject the chunk, fail closed.
                return None

            for idx in fits + plausible:
                kept.append(chunk[idx - 1])
            vetoed: list[dict] = []
            for idx in unlikely:
                biz = chunk[idx - 1]
                # The goal verdict is the authority on "is this a customer":
                # a business the ICP scored a DIRECT FIT may not be dropped by
                # this pass. (The ICP is deterministic and knows what we're
                # selling; re-judging borderline prospects here with a fuzzy
                # rubric made the same search keep 5 prospects on one run and
                # 0 on the next.) "Plausible" is NOT enough to resurrect: the
                # Kolkata run flood-filled the results with venues the AI had
                # correctly dropped (auditorium, library, institutes' halls)
                # because their campus carried a college tag -> ICP 55-70.
                # Weak evidence loses to the AI's explicit "never a fit".
                # Exclusions are the user's word and outrank even the ICP --
                # enforced HERE as well as stage 0: the Calcutta University
                # run had campuses resurrected at fit 85 because a ban-list
                # parse miss left stage 0 blind. The veto re-checks the
                # user's own ban words; a direct fit is NOT user authority.
                if (biz.get("icp") or {}).get("fit") == "fits" and not _exclusion_hit(biz, exclusions):
                    kept.append(biz)
                    vetoed.append(biz)
                    continue
                tag = (biz.get("category") or "unknown").lower()
                dropped[tag] = dropped.get(tag, 0) + 1

            all_vetoed.extend(vetoed)

        return kept, dropped, all_vetoed

    except Exception:
        return None


def _is_strict_tag_match(b: dict, category: str) -> bool:
    """Strict tag check for fail-closed mode with no goal. Education intent ->
    education tags only."""
    tag = (b.get("category") or "").lower()
    cat = category.lower()
    if any(w in cat for w in ("school", "college", "education", "training", "academy",
                              "institute", "autocad", "cad", "engineering", "learn")):
        return any(t in tag for t in STRICT_EDUCATION_TAGS)
    # Non-education intents: fall back to name/category word overlap.
    words = [w for w in cat.replace(",", " ").split() if len(w) > 3]
    return any(w in tag or w in (b.get("name") or "").lower() for w in words)


# OSM tag keys that can carry the evidence a judge needs ("teaches AutoCAD",
# "government run", course lists). Substring-matched against tag keys.
_EVIDENCE_TAG_KEYS = ("description", "operator", "brand", "courses",
                      "subject", "note")


def _evidence_note(b: dict) -> str:
    """Compact evidence line from the business's own tags, for the AI judge.

    '... [training] — evidence: operator=Youth Computer Centre; description=AutoCAD
    courses'. Empty when the record carries nothing beyond name+tag.
    """
    tags = b.get("tags") or {}
    parts = []
    for key, val in tags.items():
        k = str(key).lower()
        if any(t in k for t in _EVIDENCE_TAG_KEYS) and val:
            parts.append(f"{key}={str(val)[:80]}")
    return f" -- evidence: {'; '.join(parts[:3])}" if parts else ""


def _top_drops(dropped: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(dropped.items(), key=lambda kv: -kv[1])[:5]


def _fmt_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{v} {k}" for k, v in
                     sorted(counts.items(), key=lambda kv: -kv[1])[:5]) or "none"


def _fmt_drops(dropped: dict[str, int]) -> str:
    return ", ".join(f"{n} {tag}" for tag, n in _top_drops(dropped))
