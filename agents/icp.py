"""ICP -- what we are selling on THIS search, and whether a business fits it.

The goal changes with every search: one run is AutoCAD licences for
institutions with labs, the next is websites for local businesses, the next is
something new. So the target is per-search, not per-account. Judging every
business against the account profile would rank a training centre as a great
lead for a website pitch and a cafe as worthless for a licence pitch.

A goal is a named target: what we sell, which kinds of business can buy it,
which can never buy it, and whether having no website is a plus or a minus.
Built-in goals: cad_licensing, website, plus a "custom" fallback that judges
whether a business is a real, contactable prospect at all.

Boundaries -- NOT this module's job:
  * category_filter.py   -- does a business match the user's stated search intent?
  * industry_learner.py  -- what sales angle works for a vertical?
This module answers only: is this the kind of business that buys this goal?

Judgement is deterministic (OSM tags + name signals) because a classifier that
needs an API call stops differentiating the moment the quota runs out. Signal
statistics learned per goal from the brain promote signals that keep fitting
and demote ones that keep failing.
"""
import re

# ── Shared signal vocabulary ─────────────────────────────────────────
# Tags that never describe a customer for any goal: civic infrastructure,
# transport, utilities. Everything else is goal-specific.

NOT_A_PRODUCT = (
    "toilets", "shelter", "bench", "waste_basket", "drinking_water", "fountain",
    "parking", "fuel", "bus_station", "taxi", "bicycle_parking", "recycling",
    "post_box", "telephone", "clock", "atm", "grave_yard", "prison",
)

EDUCATION_TAGS = (
    "college", "university", "school", "training", "educational_institution",
    "research_institute", "kindergarten", "language_school", "music_school",
    "prep_school", "driving_school",
)


def _type(key, label, base, name_signals=(), tag_signals=(), why=""):
    return {"key": key, "label": label, "base": base,
            "name_signals": name_signals, "tag_signals": tag_signals, "why": why}


# ── Goal: CAD / drafting software licences ──────────────────────────
# Buyers are institutions with classrooms and computer labs.

_CAD_VERTICALS = (
    _type("cad_training", "CAD / drafting training centre", 95,
          ("autocad", "auto cad", "cad training", "cad centre", "cad center",
           "drafting", "draughtsman", "design institute", "technical training"),
          why="Teaches CAD as a core subject - every student needs a licensed seat"),
    _type("polytechnic", "Polytechnic / diploma institute", 92,
          ("polytechnic", "polytecnic", "polytechnique", "diploma institute",
           "diploma college"),
          why="Diploma engineering labs run AutoCAD across multiple semesters"),
    _type("engineering_college", "Engineering / technology college", 92,
          ("engineering college", "college of engineering", "institute of technology",
           "school of engineering", "engineering and technology",
           "engineering & technology", "engineering institute", "b.tech"),
          why="Mechanical, civil and electrical departments teach CAD in labs"),
    _type("architecture", "Architecture / planning institute", 90,
          ("architecture", "architectural", "school of planning", "planning institute"),
          why="AutoCAD is the primary drafting tool taught in the curriculum"),
    _type("iti", "ITI / vocational training", 88,
          ("industrial training institute", "iti", "vocational", "skill development",
           "skill centre", "skill center", "skill training"),
          why="Draughtsman and technician trades are built on CAD software"),
    _type("computer_training", "Computer training centre", 88,
          ("computer training", "youth computer", "computer centre", "computer center",
           "computer academy", "computer institute", "computer education",
           "computer courses", "nielit", "doeacc", "ccc", "o level"),
          why="Runs computer labs and adds CAD as a course to win more students"),
    _type("govt_technical", "Government technical / research institute", 86,
          ("research institute", "technical institute", "government polytechnic",
           "regional institute", "technical education"),
          ("research_institute",),
          why="Government technical bodies license software centrally for labs"),
    _type("animation_design", "Animation / design / multimedia institute", 82,
          ("animation", "multimedia", "vfx", "gaming", "interior design",
           "fashion design", "design academy"),
          why="Design courses have overlapping CAD/drafting modules"),
    _type("college", "College / university", 64,
          ("college", "university", "mahavidyalaya", "vidyapith", "campus",
           "institute of science"),
          ("college", "university"),
          why="Science and commerce streams are a lighter fit - fewer CAD seats"),
    _type("coaching", "Coaching / tutorial centre", 60,
          ("coaching", "tutorial", "tuition", "classes", "study centre",
           "study center", "guidance"),
          why="Only a fit when they run a computer or technical stream"),
    _type("youth_centre", "Youth / community centre", 58,
          ("youth centre", "youth center", "youth club", "community hall"),
          ("community_centre",),
          why="Youth centres with a computer room are a fit; without one, they are not"),
    _type("school", "School (K-12)", 55,
          ("school", "high school", "vidyalaya", "academy", "public school",
           "convent", "secondary", "primary"),
          ("school", "kindergarten"),
          why="Senior-secondary vocational streams use CAD; most schools do not"),
)

_CAD_NEVER_TAGS = (
    "hospital", "clinic", "doctors", "dentist", "veterinary", "pharmacy", "blood_bank",
    "bank", "bureau_de_change", "insurance", "post_office",
    "restaurant", "cafe", "fast_food", "bar", "pub", "bakery", "food",
    "car_repair", "car_wash", "car_rental",
    "marketplace", "supermarket", "grocery", "convenience", "florist", "butcher",
    "salon", "hairdresser", "beauty", "tailor", "laundry", "optician",
    "hotel", "guest_house", "lodge", "travel_agency",
    "place_of_worship", "police", "fire_station",
    "jeweller", "furniture", "hardware", "paint", "mobile_phone", "estate_agent",
    "lawyer", "notary", "accountant", "attraction", "viewpoint", "theme_park",
    "fitness_centre", "massage", "industrial", "warehouse", "workshop",
)

_CAD_NEVER_NAMES = (
    "hospital", "nursing home", "clinic", "pharmacy", "chemist", "diagnostic",
    "restaurant", "cafe", "coffee", "dhaba", "hotel", "lodge", "resort",
    "bank", "finance", "insurance", "chit fund",
    "supermarket", "grocery", "provision", "mart", "showroom",
    "salon", "parlour", "spa", "tailors", "boutique", "gym", "fitness",
    "petrol", "fuel", "garage", "motors", "tyres", "automobiles",
)

# ── Goal: websites / web design ─────────────────────────────────────
# Buyers are real local businesses that need a better presence, so the
# disqualifier list is much narrower and having NO website is a plus.

_WEB_VERTICALS = (
    _type("education", "School / college / institute", 82,
          ("school", "college", "university", "academy", "institute", "vidyalaya",
           "coaching", "training", "tutorial"),
          ("school", "college", "university", "training", "educational_institution"),
          why="Admissions, results and parent communication all live online"),
    _type("healthcare", "Clinic / hospital / pharmacy", 78,
          ("clinic", "hospital", "nursing home", "diagnostic", "pharmacy",
           "physiotherapy", "dental", "doctor"),
          ("clinic", "hospital", "doctors", "pharmacy", "dentist"),
          why="Patients search and book online before they call"),
    _type("hotel_guesthouse", "Hotel / guest house / lodge", 76,
          ("hotel", "guest house", "guesthouse", "lodge", "resort", "banquet"),
          ("hotel", "guest_house"),
          why="Bookings come from search and third-party listings they do not own"),
    _type("restaurant_cafe", "Restaurant / cafe / bakery", 72,
          ("restaurant", "cafe", "coffee", "biryani", "kitchen", "dhaba",
           "bakery", "sweets", "bengali food"),
          ("restaurant", "cafe", "fast_food", "bakery", "bar", "pub"),
          why="Menus, hours and delivery links need one owned home"),
    _type("professional", "Professional / consultative office", 72,
          ("consultant", "associates", "law", "chartered", "accountant",
           "advisory", "services", "solutions", "enterprises"),
          ("lawyer", "notary", "accountant", "insurance", "estate_agent", "office"),
          why="Credibility and lead capture are the whole sale"),
    _type("retail_shop", "Retail shop / store", 70,
          ("shop", "store", "showroom", "traders", "enterprise", "bazar", "mart",
           "electronics", "furniture", "garments", "hardware"),
          ("shop", "supermarket", "grocery", "convenience", "furniture", "hardware"),
          why="Local search plus a product catalogue brings customers back"),
    _type("fitness_beauty", "Gym / salon / spa", 68,
          ("gym", "fitness", "yoga", "salon", "parlour", "spa", "beauty",
           "hair", "unisex"),
          ("fitness_centre", "beauty", "hairdresser", "massage", "salon"),
          why="Bookings and packages sell through a simple site"),
    _type("craft_industrial", "Workshop / manufacturer / supplier", 66,
          ("workshop", "manufacturer", "industries", "engineering works",
           "fabrication", "suppliers", "traders", "packaging"),
          ("craft", "industrial", "workshop", "warehouse"),
          why="B2B buyers check whether a supplier exists online"),
    _type("local_service", "Local service provider", 64,
          ("plumber", "electrician", "contractor", "caterers", "travels",
           "tours", "packers", "courier", "security"),
          ("travel_agency", "car_rental", "craft"),
          why="Being findable when someone searches locally is the whole channel"),
)

_WEB_NEVER_TAGS = ("place_of_worship", "police", "fire_station", "prison",
                   "grave_yard", "townhall", "public_building")

_WEB_NEVER_NAMES = ("ward office", "municipal", "police station", "jail")

# ── The registry ────────────────────────────────────────────────────

GOALS = {
    "cad_licensing": {
        "key": "cad_licensing",
        "label": "CAD / drafting software licences",
        "product": "AutoCAD keys",
        "keywords": ("autocad", "auto cad", "cad", "drafting", "draughting",
                     "solidworks", "catia", "revit", "licence", "license",
                     "software keys", "design software"),
        "map_keywords": ("cad training", "cad institute", "autocad training",
                          "engineering college", "polytechnic", "drafting services",
                          "cad design"),
        "verticals": _CAD_VERTICALS,
        "never_tags": _CAD_NEVER_TAGS,
        "never_names": _CAD_NEVER_NAMES,
        "no_website_bonus": 0,
        "has_website_penalty": 0,
        "fit_threshold": 78,
        "plausible_threshold": 48,
    },
    "website": {
        "key": "website",
        "label": "Websites / web design",
        "product": "websites",
        "keywords": ("website", "web site", "web design", "web development",
                     "web developer", "landing page", "seo", "online presence",
                     "web app", "site"),
        "map_keywords": ("web design agency", "marketing agency", "digital agency",
                          "clinic", "hotel", "school", "restaurant"),
        "verticals": _WEB_VERTICALS,
        "never_tags": _WEB_NEVER_TAGS,
        "never_names": _WEB_NEVER_NAMES,
        # No website at all is the strongest buying signal for this goal.
        "no_website_bonus": 20,
        "has_website_penalty": 8,
        "fit_threshold": 78,
        "plausible_threshold": 50,
    },
    "custom": {
        "key": "custom",
        "label": "Custom goal",
        "product": "",
        "keywords": (),
        "map_keywords": (),
        "verticals": (),
        "never_tags": NOT_A_PRODUCT,
        "never_names": (),
        "no_website_bonus": 0,
        "has_website_penalty": 0,
        "fit_threshold": 60,
        "plausible_threshold": 40,
    },
}

# Name/tag signals that are real businesses of some kind, for a goal we have
# no taxonomy for. Enough to separate "a business" from a bench or a bus stop.
_GENERIC_VERTICALS = (
    _type("business", "Local business", 62,
          ("shop", "store", "traders", "enterprises", "services", "agency",
           "academy", "institute", "clinic", "workshop", "industries",
           "consultant", "associates", "company", "centre", "center"),
          why="Appears to be a business we could contact"),
)


def goal_of(key: str) -> dict:
    """Look a goal up by key, falling back to the custom goal."""
    return GOALS.get((key or "").strip().lower(), GOALS["custom"])


def resolve_goal(request: str = "", explicit: str = "") -> dict:
    """Work out which goal this search is for.

    Order: an explicit goal key, then the user's own search phrasing, then the
    business profile's product. Falls back to the custom goal, which judges
    only "is this a contactable business" instead of misapplying a taxonomy
    for something we are not selling.
    """
    explicit = (explicit or "").strip().lower()
    if explicit:
        if explicit in GOALS:
            return GOALS[explicit]
        # An explicit goal may itself be a phrase ("web design clients").
        hit = _goal_from_text(explicit)
        if hit:
            return hit
        # They told us what they are selling and we have no taxonomy for it:
        # use it as a custom goal rather than pretending it is the saved product.
        return _custom_goal(explicit)

    hit = _goal_from_text(request or "")
    if hit:
        return hit

    profile_product = (target_profile().get("product")
                       or target_profile().get("what_we_sell") or "")
    hit = _goal_from_text(profile_product)
    if hit:
        return hit

    return _custom_goal(request or profile_product)


def _custom_goal(label: str) -> dict:
    """A goal we have no taxonomy for: judge whether it is a real business."""
    custom = dict(GOALS["custom"])
    label = (label or "").strip()
    if label:
        custom["label"] = label[:80]
        custom["product"] = label[:80]
    custom["verticals"] = _GENERIC_VERTICALS
    return custom


def _goal_from_text(text: str) -> dict | None:
    """Pick the goal whose keywords the text names. Longest match wins."""
    text = (text or "").lower()
    if not text:
        return None
    best, best_len = None, 0
    for goal in GOALS.values():
        for kw in goal["keywords"]:
            if kw in text and len(kw) > best_len:
                best, best_len = goal, len(kw)
    return best


# ── Profile ──────────────────────────────────────────────────────────

def target_profile() -> dict:
    """The merged business profile: config is the base, the brain fills it out."""
    profile: dict = {}
    try:
        from agents.config import get_business_profile
        profile.update({k: v for k, v in get_business_profile().items() if v})
    except Exception:
        pass
    try:
        from agents.brain import get_brain
        for k, v in get_brain().get_profile().items():
            if v and not profile.get(k):
                profile[k] = v
    except Exception:
        pass
    return profile


def product_line(goal: dict | None = None) -> str:
    """What we sell for this goal (falls back to the profile product)."""
    if goal and goal.get("product"):
        return goal["product"]
    profile = target_profile()
    return (profile.get("product") or profile.get("product_name")
            or profile.get("what_we_sell") or "our product").strip()


# ── Classification ───────────────────────────────────────────────────

def classify(business: dict, goal: dict | None = None,
             stats: dict | None = None) -> dict:
    """Judge one business against one goal.

    Returns {fit, fit_score, institution_type, fit_reasons, disqualifiers,
             matched_signals, goal}. Deterministic: same input, same verdict.
    """
    goal = goal or resolve_goal()
    if stats is None:
        stats = learned_signal_stats(goal["key"])

    name = (business.get("name") or "").lower()
    tags = business.get("tags") or {}
    tag_blob = " ".join(
        [str(business.get("category") or "")] +
        [f"{k} {v}" for k, v in tags.items()]
    ).lower()

    verdict = {
        "fit": "unlikely",
        "fit_score": 0,
        "institution_type": "",
        "fit_reasons": [],
        "disqualifiers": [],
        "matched_signals": [],
        "goal": goal["key"],
    }

    for bad in tuple(goal["never_tags"]) + NOT_A_PRODUCT:
        if _tag_has(tag_blob, bad):
            verdict.update(fit_score=18, disqualifiers=[f"tagged {bad}"])
            return verdict
    for bad in goal["never_names"]:
        if _name_has(name, bad):
            verdict.update(fit_score=18, disqualifiers=[f"name says '{bad}'"])
            return verdict

    # Best matching vertical: the highest base among those that match.
    matched = []
    for spec in goal["verticals"]:
        hits = [s for s in spec["name_signals"] if _name_has(name, s)]
        tag_hits = [t for t in spec["tag_signals"] if _tag_has(tag_blob, t)]
        if hits or tag_hits:
            matched.append({"spec": spec, "hits": hits, "tag_hits": tag_hits})

    if not matched:
        educ = next((t for t in EDUCATION_TAGS if _tag_has(tag_blob, t)), "")
        if not educ:
            # Covers the custom goal too: no evidence this is a business at all.
            verdict.update(fit_score=25,
                           disqualifiers=["no signal this is a business we can serve"])
            return verdict

    if matched:
        best = max(matched, key=lambda m: m["spec"]["base"])
        spec = best["spec"]
        score = spec["base"]
        reasons = [f"name says '{h}'" for h in best["hits"]]
        reasons += [f"tagged '{t}'" for t in best["tag_hits"]]
    else:
        spec = {"label": "Education institution", "base": 55}
        score = 55
        reasons = [f"tagged '{educ}'"]

    matched_signals = sorted({s for m in matched for s in m["hits"]})

    educ_tag = next((t for t in EDUCATION_TAGS if _tag_has(tag_blob, t)), "")
    if educ_tag and spec["label"] != "Education institution":
        score += 6
        reasons.append(f"education tag: {educ_tag}")

    # Goal-specific presence rule: for a website pitch, having no site at all
    # is the buying signal; for a licence pitch it is irrelevant.
    has_site = bool(business.get("website"))
    if has_site and goal.get("has_website_penalty"):
        score -= goal["has_website_penalty"]
        reasons.append("already has a website")
    elif not has_site and goal.get("no_website_bonus"):
        score += goal["no_website_bonus"]
        reasons.append("no website found - the gap we sell against")

    # Learned adjustments, per goal: signals that historically produce rejects.
    for sig in matched_signals:
        st = (stats or {}).get(sig) or {}
        seen = st.get("fits", 0) + st.get("unlikely", 0)
        if seen >= 4:
            rate = st.get("fits", 0) / seen
            if rate < 0.25:
                score -= 10
                reasons.append(f"'{sig}' has mostly led to rejects ({st.get('unlikely', 0)}x)")
            elif rate > 0.75:
                score += 5
                reasons.append(f"'{sig}' has mostly led to fits ({st.get('fits', 0)}x)")

    score = max(0, min(100, score))
    fit = ("fits" if score >= goal["fit_threshold"]
           else "plausible" if score >= goal["plausible_threshold"]
           else "unlikely")

    verdict.update(fit=fit, fit_score=score, institution_type=spec["label"],
                   fit_reasons=reasons, matched_signals=matched_signals)
    return verdict


def classify_all(businesses: list[dict], goal: dict | None = None) -> list[dict]:
    """Attach a verdict to every business (mutates and returns the list)."""
    goal = goal or resolve_goal()
    stats = learned_signal_stats(goal["key"])
    for biz in businesses:
        biz["icp"] = classify(biz, goal=goal, stats=stats)
    return businesses


def rank(businesses: list[dict], goal: dict | None = None,
         keep_unlikely: bool = False) -> tuple[list[dict], list[dict], str, dict]:
    """Classify for this goal, sort best-fit first, split keepers from rejects.

    Returns (kept, dropped, report, summary).
    """
    goal = goal or resolve_goal()
    classify_all(businesses, goal=goal)
    ordered = sorted(businesses,
                     key=lambda b: (-b["icp"]["fit_score"], b.get("name", "").lower()))
    kept = [b for b in ordered if keep_unlikely or b["icp"]["fit"] != "unlikely"]
    dropped = [b for b in ordered if b["icp"]["fit"] == "unlikely"]

    by_type: dict[str, int] = {}
    for b in kept:
        label = b["icp"]["institution_type"] or "unclassified"
        by_type[label] = by_type.get(label, 0) + 1

    fits = sum(1 for b in kept if b["icp"]["fit"] == "fits")
    plausible = sum(1 for b in kept if b["icp"]["fit"] == "plausible")
    product = product_line(goal)
    summary = {
        "goal": goal["key"],
        "goal_label": goal["label"],
        "total": len(businesses),
        "fits": fits,
        "plausible": plausible,
        "dropped": len(dropped),
        "by_type": [{"label": k, "count": v}
                    for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])],
        "dropped_sample": [{"name": b.get("name", "?"),
                            "why": (b["icp"]["disqualifiers"] or ["low fit"])[0]}
                           for b in dropped[:6]],
        "product": product,
    }

    if not businesses:
        report = f"ICP [{goal['label']}]: nothing to judge."
    else:
        types = ", ".join(f"{v} {k}" for k, v in list(by_type.items())[:4]) or "none"
        drop_reasons: dict[str, int] = {}
        for b in dropped:
            why = (b["icp"]["disqualifiers"] or ["low fit"])[0]
            drop_reasons[why] = drop_reasons.get(why, 0) + 1
        dropped_txt = ", ".join(f"{v} {k}" for k, v in
                                sorted(drop_reasons.items(), key=lambda kv: -kv[1])[:4]) or "none"
        report = (f"ICP [{goal['label']}] kept {len(kept)}/{len(businesses)} for "
                  f"\"{product}\" ({fits} direct fits, {plausible} plausible) - {types}; "
                  f"dropped {len(dropped)} ({dropped_txt}).")
    summary["report"] = report
    return kept, dropped, report, summary


# ── Learning ─────────────────────────────────────────────────────────

def learned_signal_stats(goal_key: str = "") -> dict:
    """Signal -> {fits, unlikely} counts accumulated for this goal."""
    try:
        from agents.brain import get_brain
        return ((get_brain().get_icp().get("by_goal") or {})
                .get(goal_key or GOALS["cad_licensing"]["key"], {})
                .get("signal_stats") or {})
    except Exception:
        return {}


def learn(businesses: list[dict], goal: dict | None = None) -> None:
    """Feed this batch's verdicts back into the brain. Never raises."""
    goal = goal or resolve_goal()
    try:
        from agents.brain import get_brain
        get_brain().learn_icp_feedback(businesses, goal_key=goal["key"],
                                       goal_label=goal["label"],
                                       product=product_line(goal))
    except Exception:
        pass


# ── Prompt context ───────────────────────────────────────────────────

def context(goal: dict | None = None) -> str:
    """Prompt-ready block: what we sell for THIS goal and who buys it."""
    goal = goal or resolve_goal()
    product = product_line(goal)
    profile = target_profile()

    lines = [f"WHAT WE ARE SELLING ON THIS SEARCH: {product}"]
    if goal["key"] == "custom":
        lines.append("  (No built-in targeting profile for this goal - judge each "
                     "business on whether it plausibly needs what we sell.)")

    verticals = goal["verticals"] or _GENERIC_VERTICALS
    strong = [s["label"] for s in verticals if s["base"] >= 80]
    weak = [s["label"] for s in verticals if s["base"] < 80]
    if strong:
        lines.append(f"  Strong fit: {', '.join(strong)}.")
    if weak:
        lines.append(f"  Possible fit: {', '.join(weak)}.")

    never = goal["never_tags"][:12]
    if never:
        lines.append(f"  Never a fit: {', '.join(never)}.")
    if goal["key"] == "website":
        lines.append("  A business with no website at all is the best prospect.")

    # The account profile still supplies the why and the hooks.
    if goal["key"] == "cad_licensing":
        if profile.get("ideal_customer_profile"):
            lines.append(f"  Ideal customer: {profile['ideal_customer_profile']}")
        pains = profile.get("customer_pain_points")
        if pains:
            lines.append("  Why they buy:")
            for pp in (pains if isinstance(pains, list) else [pains])[:3]:
                lines.append(f"    - {pp}")
        hooks = profile.get("attention_hooks")
        if hooks:
            lines.append("  What lands:")
            for h in (hooks if isinstance(hooks, list) else [hooks])[:4]:
                lines.append(f"    - {h}")
    return "\n".join(lines)


def goals_overview() -> str:
    """Compact list of the goals we know how to target, for chat context.

    Deliberately NOT one goal's context: the goal is chosen per search, so a
    chat session must not be told it is permanently selling the default product.
    """
    default = resolve_goal()
    lines = ["WHAT WE CAN SELL (the goal is chosen per search, not fixed):"]
    for key, goal in GOALS.items():
        if key == "custom":
            continue
        mark = "  <- default" if key == default["key"] else ""
        lines.append(f"  {goal['label']}: sells {goal['product']}{mark}")
    lines.append("  Anything else: a custom goal, judged on whether the business "
                 "is a real prospect for what is being sold.")
    return "\n".join(lines)


def is_fit(business: dict, goal: dict | None = None) -> bool:
    """Convenience for gates that only need a yes/no."""
    verdict = business.get("icp") or classify(business, goal=goal)
    return verdict.get("fit") in ("fits", "plausible")


def delivers_websites(goal: dict | None = None) -> bool:
    """True when this goal IS selling websites.

    Gates the website-generation leg of the draft workflow: a licensing pitch
    should not build prospects a website they never asked for. For the website
    goal it is the product, so the leg runs.
    """
    goal = goal or resolve_goal()
    if goal["key"] == "website":
        return True
    line = product_line(goal).lower()
    return any(w in line for w in ("website", "web design", "web development", "web app"))


# ── Signal matching helpers ──────────────────────────────────────────

def _name_has(name: str, signal: str) -> bool:
    """Match a signal against a business name.

    Short acronyms (iti, ccc, vfx) match whole words only -- otherwise "iti"
    would fire inside "Citibank".
    """
    if not name or not signal:
        return False
    if " " not in signal and len(signal) <= 4:
        return re.search(rf"\b{re.escape(signal)}\b", name) is not None
    return signal in name


def _tag_has(tag_blob: str, tag: str) -> bool:
    """Match an OSM tag token against the flattened tag blob."""
    if not tag_blob or not tag:
        return False
    if " " in tag:
        return tag in tag_blob
    return re.search(rf"\b{re.escape(tag)}\b", tag_blob) is not None
