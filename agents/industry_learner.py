#!/usr/bin/env python3
"""Industry Learner — when JARVIS encounters a new business type, it researches it.

Researches a vertical *for what we actually sell*: the product line and the
ideal customer profile are read from the merged business profile and injected
into the research prompt, so the pain points, hooks and budget that come back
are about our product instead of a generic software pitch.

Cached research is stamped with the product it was written for. Change the
product and the stale entries are re-researched instead of silently feeding
the old pitch into new emails.

Stores insights in the knowledge base so future emails are better.
"""
import json
from datetime import datetime

from agents.config import KB_DIR


def _product_line() -> str:
    """What we sell, according to the merged profile."""
    try:
        from agents.icp import product_line
        return product_line()
    except Exception:
        return "our product"


def _icp_line() -> str:
    try:
        from agents.icp import target_profile
        p = target_profile()
        return (p.get("ideal_customer_profile") or p.get("target_customers") or "").strip()
    except Exception:
        return ""


def _is_cad_product(product: str = "") -> bool:
    """True when the product line looks like CAD/drafting software.

    Takes the product of THIS search, not the saved one: the presets below are
    written for the licence pitch, so a website search must not pick them up.
    """
    line = (product or _product_line()).lower()
    return any(w in line for w in ("cad", "drafting", "draughting", "design software"))


# ── Known verticals (pre-researched, for our CAD-licensing product) ───
# Keyed by the OSM category the search returns, so a hit needs no API call.
# Only verticals we would actually sell to are listed — anything the ICP rules
# out never reaches an email, so it has no business being in this table.

KNOWN_INDUSTRIES = {
    "college": {
        "description": "Degree colleges running science, commerce and applied-science streams",
        "pain_points": [
            "Computer and drafting labs need licensed CAD software per seat",
            "Students install unlicensed copies at home and bring the risk onto campus",
            "Lab expansion is blocked by per-seat licence cost",
            "No single point of contact for licence renewals and support",
        ],
        "services_needed": [
            "Official licensed CAD seats for lab machines",
            "Bulk educational pricing per lab",
            "Installation and activation support for lab admins",
            "Renewal reminders so labs never run on expired licences",
        ],
        "approach": "Speak to the principal or the head of the computer/drawing lab. Lead with licence compliance and per-seat cost for a whole lab, not a single copy.",
        "avg_budget": "Institutional licence budgets, usually approved per lab or per department",
        "decision_maker": "Principal, Head of Department, Lab in-charge, IT coordinator",
    },
    "training": {
        "description": "Computer training centres and institutes running job-oriented courses",
        "pain_points": [
            "Adding a CAD/drafting course needs licensed software before students enrol",
            "Every added batch needs another activated seat",
            "Course fees cannot absorb full retail licence pricing",
            "Students ask for CAD certificates and centre-branded licences",
        ],
        "services_needed": [
            "Affordable per-seat licences that scale batch by batch",
            "Quick activation between batches",
            "Course-ready CAD setup for the lab",
            "Support when a machine is replaced or formatted",
        ],
        "approach": "Talk to the centre owner or course coordinator. Lead with the cost per student seat and how quickly a new CAD batch can start earning.",
        "decision_maker": "Centre owner, Director, Course coordinator",
    },
    "school": {
        "description": "Schools with senior-secondary vocational or computer streams",
        "pain_points": [
            "Vocational and computer streams need software the school can prove is licensed",
            "Lab machines are shared and get reinstalled every session",
            "Tight per-student budgets across the whole lab",
        ],
        "services_needed": [
            "Budget-friendly licensed seats for shared lab machines",
            "Simple re-activation after lab reimaging",
            "Documentation that satisfies school audits",
        ],
        "approach": "Reach the computer-lab in-charge or principal. Lead with audit-safe licensing at a per-lab price.",
        "decision_maker": "Principal, Computer lab in-charge, Vice-principal",
    },
    "university": {
        "description": "Universities and autonomous institutes with engineering/design departments",
        "pain_points": [
            "Multiple departments need licences, each with its own budget and timeline",
            "Procurement is slow: software must go through formal quotation cycles",
            "Compliance review demands proof of licensing before renewal",
        ],
        "services_needed": [
            "Department-wise licence quotations for procurement",
            "Volume licensing across labs",
            "Compliance paperwork and licence certificates",
        ],
        "approach": "Enter through the department head or central IT/procurement. Lead with formal quotes, licence certificates and multi-department volume pricing.",
        "decision_maker": "Registrar, Procurement officer, Head of Department, IT cell",
    },
    "educational_institution": {
        "description": "Education institutions with computer or drafting labs",
        "pain_points": [
            "Labs run on unlicensed or trial software that expires mid-session",
            "Per-seat cost blocks expanding the number of machines",
            "Nobody owns licence renewals, so labs break at the worst time",
        ],
        "services_needed": [
            "Licensed seats sized to the lab",
            "Education pricing for the whole institution",
            "One contact for installation, activation and renewal",
        ],
        "approach": "Speak to whoever owns the lab budget. Lead with compliance plus the cost of licensing the entire lab in one go.",
        "decision_maker": "Principal, Director, Lab in-charge",
    },
}


# ── Industry research via web ───────────────────────────────────────

def research_industry_web(category: str, product: str = "") -> dict | None:
    """Research a vertical for the product of THIS search using AI.

    Returns the insights dict, {"not_a_fit": True} when the model judged the
    vertical out of scope, or None when research failed and should be retried
    rather than cached.
    """
    try:
        from agents import ai_engine
        if not ai_engine.is_available():
            return None

        explicit = bool(product)
        product = product or _product_line()
        # The account ICP only applies when we fell back to the profile product.
        icp = "" if explicit else _icp_line()
        icp_line = f"\nTheir ideal customer: {icp}" if icp else ""

        prompt = f"""We sell: {product}.{icp_line}

Research the "{category}" vertical for B2B cold outreach selling {product}.

Return ONLY a JSON object with these keys:
{{
  "description": "One-line description of this vertical",
  "pain_points": ["a real problem they have that {product} solves", "...", "..."],
  "services_needed": ["what they would need from us", "...", "..."],
  "approach": "One sentence: how to approach this vertical to sell {product}",
  "avg_budget": "typical budget range they can commit",
  "decision_maker": "who makes the buying decision"
}}

Every pain point must relate to {product} specifically. Do not write generic
software, CRM or website advice. If this vertical would not buy {product} at
all, return {{"description": "", "not_a_fit": true}}."""

        result = ai_engine.generate_json(
            prompt=prompt,
            system=f"B2B sales researcher for a vendor of {product}. Be specific, practical and only about {product}.",
        )

        if result and result.get("not_a_fit"):
            return {"not_a_fit": True}
        if result and "description" in result:
            # Clean problematic characters for Windows encoding
            for key in result:
                if isinstance(result[key], str):
                    result[key] = result[key].replace(chr(8212), "-").replace(chr(8211), "-")
                elif isinstance(result[key], list):
                    result[key] = [s.replace(chr(8212), "-").replace(chr(8211), "-") if isinstance(s, str) else s for s in result[key]]
            return result
    except Exception:
        pass

    return None


def get_or_research_industry(category: str, product: str = "") -> dict:
    """Get industry data from knowledge base, or research it if new.

    ``product`` is what this search is selling; it scopes both the research and
    the cache stamp, so the same vertical researched for websites is not reused
    as advice for selling licences.
    """
    # Normalize category
    cat_key = category.lower().strip().replace(" ", "_").replace("-", "_")

    # Empty/whitespace category — return generic fallback
    if not cat_key:
        return _generic_insights(category, product)

    product = product or _product_line()

    # Check known verticals first — but only when they match what we sell.
    if cat_key in KNOWN_INDUSTRIES and _is_cad_product(product):
        return KNOWN_INDUSTRIES[cat_key]

    # Check knowledge base cache
    cache_file = KB_DIR / "industry_research.json"
    cache = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    cached = cache.get(cat_key)
    # A cached entry written for a different product is worse than no entry.
    if cached and cached.get("for_product") == product:
        if cached.get("not_a_fit"):
            return _generic_insights(category)
        return cached

    # Research via web
    print(f"  [LEARN] New industry detected: {cat_key} - researching...")
    insights = research_industry_web(cat_key, product=product)

    # The model judged this vertical out of scope. Remember that, so the same
    # non-fit question is not re-asked on every single run.
    if insights and insights.get("not_a_fit"):
        cache[cat_key] = {"not_a_fit": True, "for_product": product,
                          "researched_at": datetime.now().isoformat()}
        cache_file.write_text(json.dumps(cache, indent=2, ensure_ascii=True), encoding="utf-8")
        print(f"  [LEARN] {cat_key} is not a fit for {product} - remembered")
        return _generic_insights(category, product)

    if insights:
        # Clean any problematic characters before caching
        def _clean(obj):
            if isinstance(obj, str):
                return obj.replace(chr(8212), "-").replace(chr(8211), "-")
            if isinstance(obj, list):
                return [_clean(x) for x in obj]
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items()}
            return obj
        insights = _clean(insights)
        insights["for_product"] = product
        insights["researched_at"] = datetime.now().isoformat()
        cache[cat_key] = insights
        cache_file.write_text(json.dumps(cache, indent=2, ensure_ascii=True), encoding="utf-8")
        print(f"  [LEARN] Researched and cached: {cat_key}")
        return insights

    # Nothing usable: the AI judged this vertical a non-fit, or it failed.
    return _generic_insights(category, product)


def _generic_insights(category: str, product: str = "") -> dict:
    """Product-aware fallback when research is unavailable or inapplicable."""
    product = product or _product_line()
    return {
        "description": f"A {category} institution" if category else "An institution",
        "pain_points": [
            f"Computer labs may be running unlicensed copies instead of real {product}",
            "Per-seat cost makes equipping a whole lab expensive",
        ],
        "services_needed": [
            f"Genuine {product} sized to their lab",
            "Education pricing for the full lab",
            "Installation and activation support",
        ],
        "approach": f"Ask how their computer lab is licensed today, then offer genuine {product} for the whole lab at education pricing.",
        "avg_budget": "Institutional budget, approved per lab",
        "decision_maker": "Principal, Director, Lab in-charge",
    }


def build_industry_context(category: str, product: str = "") -> str:
    """Build a context string about an industry for email generation.

    Called by AI agents to make emails industry-aware.
    """
    insights = get_or_research_industry(category, product=product)
    if not insights:
        return ""

    parts = [f"Industry: {category}"]
    if insights.get("description"):
        parts.append(f"What they do: {insights['description']}")
    if insights.get("pain_points"):
        parts.append("Their pain points:")
        for pp in insights["pain_points"][:3]:
            parts.append(f"  - {pp}")
    if insights.get("approach"):
        parts.append(f"Best approach: {insights['approach']}")
    if insights.get("decision_maker"):
        parts.append(f"Decision maker: {insights['decision_maker']}")
    if insights.get("avg_budget"):
        parts.append(f"Typical budget: {insights['avg_budget']}")

    return "\n".join(parts)


# ── Cache access ────────────────────────────────────────────────────

def get_industry_cache() -> dict:
    """Get the full industry research cache."""
    cache_file = KB_DIR / "industry_research.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def get_all_known_industries() -> list[str]:
    """Get all industry names the system knows about."""
    known = list(KNOWN_INDUSTRIES.keys())
    cached = list(get_industry_cache().keys())
    return sorted(set(known + cached))
