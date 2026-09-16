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

    # Stage 2: AI reasons about fit in tiers over everything that survived.
    judged = _ai_tier_filter(kept, category)
    if judged is not None:
        kept, ai_dropped = judged
        ai_drops = ", ".join(f"{n} {tag}" for tag, n in _top_drops(ai_dropped)) or "nothing"
        report = (f"Filtered {len(businesses)} -> {len(kept)} for \"{category}\": "
                  f"hard tags dropped {sum(dropped.values())} ({_fmt_drops(dropped)}); "
                  f"AI dropped {ai_drops}.")
        return kept, report

    # Stage 3: fail closed. For a goal-scoped search the ICP has already judged
    # fit, so strict tag matching against an unknown intent would only throw away
    # good prospects -- keep them. Otherwise fall back to strict education tags.
    if goal is not None:
        report = (f"Filtered {len(businesses)} -> {len(kept)} by goal tags "
                  f"(AI unavailable): hard tags dropped "
                  f"{sum(dropped.values())} ({_fmt_drops(dropped)}).")
        return kept, report

    strict = [b for b in kept if _is_strict_tag_match(b, category)]
    report = (f"Filtered {len(businesses)} -> {len(strict)} by strict tags "
              f"(AI unavailable): hard tags dropped {sum(dropped.values())} ({_fmt_drops(dropped)}).")
    return strict, report


def _ai_tier_filter(businesses: list[dict], category: str) -> tuple[list[dict], dict] | None:
    """Ask Gemini to judge fit in tiers. Returns (kept, dropped_counts) or None on failure.

    Chunked past 50 businesses so nothing is silently unread. Any failure
    returns None so the caller fails closed to strict tags.
    """
    try:
        from agents import ai_engine
        if not ai_engine.is_available():
            return None

        kept: list[dict] = []
        dropped: dict[str, int] = {}
        CHUNK = 50
        for i in range(0, len(businesses), CHUNK):
            chunk = businesses[i:i + CHUNK]
            biz_list = "\n".join(
                f"{j+1}. {b.get('name', '?')} [{b.get('category', '?')}]"
                for j, b in enumerate(chunk)
            )
            result = ai_engine.generate_json(
                prompt=f"""The user is looking for: "{category}"

For each business below, judge whether it fits what the user is looking for.
Use the tag in [brackets] as the ground truth for what it IS, not just the name
(names can be misleading: "Calcutta Medical College" is a hospital).

{biz_list}

Rubric -- judge by these rules, not impressions:
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
            for idx in unlikely:
                biz = chunk[idx - 1]
                # The goal verdict is the authority on "is this a customer":
                # a business the ICP scored fits or plausible may not be
                # dropped by this pass. (The ICP is deterministic and knows
                # what we're selling; re-judging borderline prospects here
                # with a fuzzy rubric made the same search keep 5 prospects
                # on one run and 0 on the next.) Businesses with no ICP
                # verdict are still this pass's to judge.
                if (biz.get("icp") or {}).get("fit") in ("fits", "plausible"):
                    kept.append(biz)
                    continue
                tag = (biz.get("category") or "unknown").lower()
                dropped[tag] = dropped.get(tag, 0) + 1

        return kept, dropped

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


def _top_drops(dropped: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(dropped.items(), key=lambda kv: -kv[1])[:5]


def _fmt_drops(dropped: dict[str, int]) -> str:
    return ", ".join(f"{n} {tag}" for tag, n in _top_drops(dropped))
