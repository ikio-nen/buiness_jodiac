"""Adapter: pipeline business dict -> typed Business model.

One place translates between the pipeline's free-form dicts and the seam's
typed models, so consumers never hand-build a Business from half-remembered
keys. ``snippets`` carries whatever scraped/descriptive text exists — the
grounding material for profile summarization and contact extraction.
"""

from agents.ai.schemas import Business


def to_business(b: dict) -> Business:
    snippets: list[str] = []
    for k in ("description", "about", "reviews_summary"):
        v = b.get(k)
        if isinstance(v, str) and v.strip():
            snippets.append(v.strip()[:800])
    for e in (b.get("emails_found") or [])[:3]:
        if isinstance(e, str):
            snippets.append(f"contact email on page: {e}")
    return Business(
        id=str(b.get("id") or b.get("name") or ""),
        name=str(b.get("name", "")),
        category=str(b.get("category", "")),
        location=str(b.get("location") or b.get("vicinity") or ""),
        website=str(b.get("website", "")),
        phone=str(b.get("phone", "")),
        email=str(b.get("email") or b.get("maps_email") or ""),
        rating=b.get("rating") if isinstance(b.get("rating"), (int, float)) else None,
        review_count=b.get("review_count") if isinstance(b.get("review_count"), int) else None,
        snippets=snippets,
    )
