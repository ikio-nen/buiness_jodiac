"""Business research — scrapes Google Maps reviews, analyzes with Gemini.

After the user selects businesses, this module researches each one to find:
- Google Maps rating and review count
- What customers praise (strengths)
- What customers complain about (gaps)
- A personalized email hook based on real reviews
- An improvement suggestion tailored to the business

Research results are stored in session data and injected into email drafts.
"""
import json
import re
from pathlib import Path
from typing import Optional

from agents.business_enricher import scrape_google_maps_reviews, scrape_business
from agents.industry_learner import get_or_research_industry
from agents import ai_engine


# ── Core research function ─────────────────────────────────────────

def research_business(business: dict) -> dict:
    """Research a single business using web scraping + AI analysis.

    Input: business dict with 'name', 'category', optionally 'address', 'website'.
    Output: dict with rating, strengths, gaps, email_hook, improvement_suggestion.
    """
    name = business.get("name", "")
    category = business.get("category", "")
    location = business.get("address", "")

    # 1. Scrape Google Maps for rating and reviews
    maps_data = scrape_google_maps_reviews(name, location)

    # 2. Get industry context for this category
    industry = get_or_research_industry(category)

    # 3. Scrape website if available (for additional context)
    website_data = {}
    if business.get("website"):
        try:
            website_data = scrape_business(business)
        except Exception:
            pass

    # 4. Analyze with Gemini (if available) or use basic analysis
    if ai_engine.is_available():
        insights = _analyze_with_ai(name, category, maps_data, industry, website_data)
    else:
        insights = _analyze_basic(name, category, maps_data, industry)

    # 5. Build research result
    return {
        "name": name,
        "category": category,
        "rating": maps_data.get("rating", 0),
        "review_count": maps_data.get("review_count", 0),
        "strengths": insights.get("strengths", []),
        "gaps": insights.get("gaps", []),
        "email_hook": insights.get("email_hook", ""),
        "improvement_suggestion": insights.get("improvement_suggestion", ""),
        "industry_context": industry.get("description", ""),
    }


def research_batch(businesses: list[dict]) -> list[dict]:
    """Research multiple businesses. Returns list of research results.

    Each result corresponds to the business at the same index.
    Errors are caught per-business so one failure doesn't block others.
    """
    results = []
    for biz in businesses:
        try:
            result = research_business(biz)
            results.append(result)
        except Exception as e:
            results.append({
                "name": biz.get("name", "?"),
                "category": biz.get("category", ""),
                "error": str(e),
                "rating": 0,
                "review_count": 0,
                "strengths": [],
                "gaps": [],
                "email_hook": "",
                "improvement_suggestion": "",
            })
    return results


# ── AI analysis ────────────────────────────────────────────────────

def _analyze_with_ai(name: str, category: str, maps_data: dict,
                      industry: dict, website_data: dict) -> dict:
    """Use Gemini to analyze a business and find improvement opportunities.

    Sends the business data, Google Maps info, and industry context to Gemini.
    Returns structured insights for email personalization.
    """
    rating = maps_data.get("rating", 0)
    review_count = maps_data.get("review_count", 0)
    industry_desc = industry.get("description", "Unknown industry")
    pain_points = ", ".join(industry.get("pain_points", [])[:3])
    website_desc = website_data.get("description", "No website data")

    prompt = f"""Analyze this business for cold outreach email personalization.

Business: {name}
Category: {category}
Industry: {industry_desc}
Industry pain points: {pain_points}
Google Maps rating: {rating} ({review_count} reviews)
Website description: {website_desc}

Based on this information, provide:
1. strengths (2-3 things they likely do well based on their rating/category)
2. gaps (2-3 improvement opportunities based on industry pain points)
3. email_hook (a personalized opening line for a cold email that references something specific about their business)
4. improvement_suggestion (a concrete suggestion for how they could improve, tied to their industry)

Return JSON with exactly these 4 keys. Be specific and actionable, not generic."""

    result = ai_engine.generate_json(prompt)

    # Ensure all keys exist with defaults
    return {
        "strengths": result.get("strengths", [f"Established {category} business with {rating} rating"]),
        "gaps": result.get("gaps", industry.get("pain_points", ["No website"])[:2]),
        "email_hook": result.get("email_hook", f"I noticed {name} could benefit from a stronger online presence"),
        "improvement_suggestion": result.get("improvement_suggestion", industry.get("outreach_approach", "")),
    }


def _analyze_basic(name: str, category: str, maps_data: dict, industry: dict) -> dict:
    """Fallback analysis without AI — uses industry templates and basic heuristics."""
    rating = maps_data.get("rating", 0)
    review_count = maps_data.get("review_count", 0)

    # Pick strengths based on rating
    if rating >= 4.0:
        strengths = [f"High customer satisfaction ({rating}/5)", f"Established with {review_count} reviews"]
    elif rating >= 3.0:
        strengths = [f"Decent reputation ({rating}/5)", "Room for improvement"]
    else:
        strengths = ["Active business", "Opportunity to stand out"]

    # Pick gaps from industry pain points
    pain_points = industry.get("pain_points", ["No online presence"])
    gaps = pain_points[:2] if pain_points else ["No online presence"]

    # Build email hook from industry context
    hooks = industry.get("email_hooks", [])
    email_hook = hooks[0] if hooks else f"I noticed {name} could benefit from a stronger online presence"

    return {
        "strengths": strengths,
        "gaps": gaps,
        "email_hook": email_hook,
        "improvement_suggestion": industry.get("approach", industry.get("outreach_approach", "")),
    }


# ── Format for email injection ─────────────────────────────────────

def format_research_for_email(research: dict) -> str:
    """Format research insights as a string for injection into email prompts.

    This is what gets passed to the AI/template agent as context.
    """
    parts = []

    if research.get("rating"):
        parts.append(f"Google rating: {research['rating']}/5 ({research.get('review_count', 0)} reviews)")

    if research.get("strengths"):
        parts.append("Their strengths: " + ", ".join(research["strengths"][:3]))

    if research.get("gaps"):
        parts.append("Improvement opportunities: " + ", ".join(research["gaps"][:3]))

    if research.get("email_hook"):
        parts.append(f"Suggested opening: {research['email_hook']}")

    if research.get("improvement_suggestion"):
        parts.append(f"Improvement suggestion: {research['improvement_suggestion']}")

    return "\n".join(parts)


def get_research_for_business(business: dict, all_research: list[dict]) -> Optional[dict]:
    """Find research results for a specific business by name."""
    name = business.get("name", "")
    for r in all_research:
        if r.get("name") == name:
            return r
    return None
