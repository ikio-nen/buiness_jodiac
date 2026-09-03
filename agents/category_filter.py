"""Category filter -- filter search results by business category.

Two-stage approach:
1. Keyword matching (instant, no API) — matches common categories
2. AI fallback (Gemini) — for complex/ambiguous categories

Extracted from workflows.py to keep search logic separate from workflow orchestration.
"""

# Keyword groups for fast local filtering
KEYWORD_MAP = {
    "education": ["school", "college", "university", "training", "coaching",
                   "institute", "academy", "tutoring", "education", "computer",
                   "autocad", "engineering", "polytechnic", "it training"],
    "healthcare": ["hospital", "clinic", "pharmacy", "medical", "nursing",
                    "dental", "health", "diagnostic", "lab"],
    "food": ["restaurant", "cafe", "coffee", "hotel", "bar", "bakery",
             "dining", "eatery", "food", "pizza", "biryani"],
    "shop": ["shop", "store", "retail", "market", "mall", "boutique",
             "emporium", "trading"],
    "office": ["office", "company", "firm", "agency", "consultant",
               "services", "solutions", "tech", "software"],
}


def filter_by_category(businesses: list[dict], category: str) -> list[dict]:
    """Filter businesses to match a category description.

    Args:
        businesses: List of business dicts with 'name' and 'category' keys.
        category: User's category description (e.g., "educational hubs").

    Returns:
        Filtered list of businesses matching the category.
    """
    if not category:
        return businesses

    cat = category.lower().strip()

    # Stage 1: Keyword matching (no API call)
    result = _keyword_filter(businesses, cat)
    if result is not None:
        return result

    # Stage 2: AI-powered filter for complex categories
    return _ai_filter(businesses, category)


def _keyword_filter(businesses: list[dict], category: str) -> list[dict] | None:
    """Fast keyword-based filter. Returns None if no match found (fall through to AI)."""
    for group, keywords in KEYWORD_MAP.items():
        if any(k in category for k in [group] + keywords):
            filtered = []
            for b in businesses:
                name_lower = (b.get("name", "") + " " + b.get("category", "")).lower()
                if any(k in name_lower for k in keywords):
                    filtered.append(b)
            return filtered if filtered else None
    return None


def _ai_filter(businesses: list[dict], category: str) -> list[dict]:
    """AI-powered filter using Gemini. Falls back to returning all businesses."""
    try:
        from agents import ai_engine
        if not ai_engine.is_available():
            return businesses

        biz_list = "\n".join([
            f"{i+1}. {b.get('name', '?')} ({b.get('category', '?')})"
            for i, b in enumerate(businesses[:50])
        ])

        result = ai_engine.generate_json(
            prompt=f"""The user is searching for: "{category}"

Here are the businesses found in the area:
{biz_list}

Return a JSON list of business numbers (1-indexed) that match what the user is looking for.
Only include businesses that clearly fit the category.
Example: {{"matching": [1, 3, 5]}}""",
            system="You are a business classifier. Be precise about which businesses match the user's search intent.",
        )

        if result and "matching" in result:
            indices = result["matching"]
            return [businesses[i-1] for i in indices if 0 < i <= len(businesses)]

    except Exception:
        pass

    return businesses
