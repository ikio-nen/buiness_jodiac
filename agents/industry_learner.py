#!/usr/bin/env python3
"""Industry Learner — when JARVIS encounters a new business type, it researches it.

Uses web search to learn:
  - What the industry is about
  - Common pain points
  - What services they need
  - How to approach them
  - Average pricing in the industry

Stores insights in the knowledge base so future emails are better.
"""
import json
import re
from pathlib import Path
from datetime import datetime

from agents.config import KB_DIR


# ── Known industries (pre-researched) ───────────────────────────────

KNOWN_INDUSTRIES = {
    "education": {
        "description": "Schools, colleges, training institutes, coaching centers",
        "pain_points": [
            "Need online presence for admissions",
            "Parents research schools online before enrolling",
            "Competing with nearby institutions for students",
            "Need to showcase facilities and results",
        ],
        "services_needed": [
            "Website with admission forms",
            "Online class scheduling",
            "Student portal",
            "Parent communication system",
        ],
        "approach": "Focus on admissions growth and parent trust. Show how a website increases enrollment.",
        "avg_budget": "500-2000 USD",
        "decision_maker": "Principal, Director, Admin Head",
    },
    "food_and_drink": {
        "description": "Restaurants, cafes, canteens, food stalls, bakeries",
        "pain_points": [
            "Need online ordering system",
            "Competing with food delivery apps",
            "Want to showcase menu and ambiance",
            "Need reviews and ratings management",
        ],
        "services_needed": [
            "Website with menu and ordering",
            "Google Maps optimization",
            "Social media integration",
            "Online reservation system",
        ],
        "approach": "Focus on online orders and foot traffic. Show how a website brings in more customers.",
        "avg_budget": "300-1500 USD",
        "decision_maker": "Owner, Manager",
    },
    "shop": {
        "description": "Retail stores, pharmacies, electronics shops, clothing stores",
        "pain_points": [
            "Losing customers to online stores",
            "Need e-commerce capability",
            "Want to showcase products catalog",
            "Need Google visibility for local search",
        ],
        "services_needed": [
            "E-commerce website",
            "Product catalog online",
            "Google My Business optimization",
            "WhatsApp ordering integration",
        ],
        "approach": "Focus on competing with online retail. Show how a website brings local customers back.",
        "avg_budget": "400-2000 USD",
        "decision_maker": "Owner, Store Manager",
    },
    "healthcare": {
        "description": "Hospitals, clinics, nursing homes, pharmacies, diagnostic centers",
        "pain_points": [
            "Patients need to find and book online",
            "Need to showcase doctors and specialties",
            "Competing with other healthcare providers",
            "Need appointment scheduling",
        ],
        "services_needed": [
            "Website with doctor profiles",
            "Online appointment booking",
            "Patient portal",
            "Health blog for SEO",
        ],
        "approach": "Focus on patient acquisition and trust. Show how a professional site builds credibility.",
        "avg_budget": "800-3000 USD",
        "decision_maker": "Director, Hospital Admin, Doctor",
    },
    "professional": {
        "description": "Law firms, consulting, accounting, IT services, marketing agencies",
        "pain_points": [
            "Need to establish credibility online",
            "Competing with larger firms",
            "Want to showcase portfolio and case studies",
            "Need lead generation",
        ],
        "services_needed": [
            "Professional portfolio website",
            "Case studies and testimonials",
            "Contact forms and lead capture",
            "Blog for thought leadership",
        ],
        "approach": "Focus on credibility and lead generation. Show how a professional site wins clients.",
        "avg_budget": "1000-5000 USD",
        "decision_manager": "Partner, Owner, Managing Director",
    },
    "home_services": {
        "description": "Plumbers, electricians, painters, cleaning services, repair shops",
        "pain_points": [
            "Need to be found when people search locally",
            "Want online booking and scheduling",
            "Competing with other local service providers",
            "Need reviews and reputation management",
        ],
        "services_needed": [
            "Website with service listings",
            "Online booking system",
            "Google Maps and local SEO",
            "Review management",
        ],
        "approach": "Focus on being found locally. Show how a website brings more service calls.",
        "avg_budget": "300-1200 USD",
        "decision_maker": "Owner",
    },
}


# ── Industry research via web ───────────────────────────────────────

def research_industry_web(category: str) -> dict:
    """Research a new business type using web search.

    Returns industry insights dict, or empty dict on failure.
    """
    try:
        from agents import ai_engine
        if not ai_engine.is_available():
            return {}

        prompt = f"""Research the "{category}" business industry for B2B cold outreach purposes.

Return ONLY a JSON object with these keys:
{{
  "description": "One-line description of this industry",
  "pain_points": ["pain point 1", "pain point 2", "pain point 3"],
  "services_needed": ["service 1", "service 2", "service 3"],
  "approach": "One sentence: how to approach this industry for website/software sales",
  "avg_budget": "typical budget range in USD",
  "decision_maker": "who makes the buying decision"
}}

Focus on: what problems do they have that a website/software can solve?
Who do you talk to? What's their budget? What hooks work for cold email?"""

        result = ai_engine.generate_json(
            prompt=prompt,
            system="You are a B2B sales research analyst. Be specific and practical.",
        )

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

    return {}


def get_or_research_industry(category: str) -> dict:
    """Get industry data from knowledge base, or research it if new.

    This is the main entry point — checks cache first, then web.
    """
    # Normalize category
    cat_key = category.lower().strip().replace(" ", "_").replace("-", "_")

    # Empty/whitespace category — return generic fallback
    if not cat_key:
        return {
            "description": "A local business",
            "pain_points": ["Need online presence", "Want more customers", "Competing locally"],
            "services_needed": ["Professional website", "Google visibility", "Contact forms"],
            "approach": "Approach with a focus on local visibility and customer acquisition.",
            "avg_budget": "500-2000 USD",
            "decision_maker": "Owner, Manager",
        }

    # Check known industries first
    if cat_key in KNOWN_INDUSTRIES:
        return KNOWN_INDUSTRIES[cat_key]

    # Check knowledge base cache
    cache_file = KB_DIR / "industry_research.json"
    cache = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    if cat_key in cache:
        return cache[cat_key]

    # Research via web
    print(f"  [LEARN] New industry detected: {cat_key} - researching...")
    insights = research_industry_web(cat_key)

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
        # Cache it
        cache[cat_key] = insights
        cache[cat_key]["researched_at"] = datetime.now().isoformat()
        cache_file.write_text(json.dumps(cache, indent=2, ensure_ascii=True), encoding="utf-8")
        print(f"  [LEARN] Researched and cached: {cat_key}")
        return insights

    # Fallback: generic insights
    return {
        "description": f"A {category} business",
        "pain_points": ["Need online presence", "Want more customers", "Competing locally"],
        "services_needed": ["Professional website", "Google visibility", "Contact forms"],
        "approach": f"Approach {category} businesses with a focus on local visibility and customer acquisition.",
        "avg_budget": "500-2000 USD",
        "decision_maker": "Owner, Manager",
    }


def build_industry_context(category: str) -> str:
    """Build a context string about an industry for email generation.

    Called by AI agents to make emails industry-aware.
    """
    insights = get_or_research_industry(category)
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


# ── Singleton cache ─────────────────────────────────────────────────

_research_cache = {}


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
