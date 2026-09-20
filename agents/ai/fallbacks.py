"""Heuristic fallback for every capability — the caller never special-cases.

If Gemini is down, unkeyed, or returns garbage, each capability returns a
same-shaped answer from these heuristics instead. The pipeline gets slightly
dumber, never blocked (PRD §2: graceful degradation).

score_fit delegates to the deterministic ICP classifier (agents/icp.py),
which is the authoritative heuristic judgment — the AI pass may only
sharpen a rationale, never override the verdict (the double-judge lesson).
"""

from agents.ai.schemas import (
    Business, BusinessProfile, ContactCandidate, EmailDraft,
    FitScore, QueryExpansion, ReplyIntent,
)


def score_fit(business: Business) -> FitScore:
    """Deterministic ICP verdict as the floor under the AI pass."""
    from agents.icp import classify
    verdict = classify(business.model_dump(exclude={"snippets"}), goal=None)
    return FitScore(
        score=int(verdict.get("fit_score", 0)),
        fit=verdict.get("fit", "plausible"),
        institution_type=verdict.get("institution_type", ""),
        rationale="; ".join(verdict.get("fit_reasons", [])[:2]) or "deterministic ICP verdict",
        source="heuristic",
    )


def summarize_profile(business: Business) -> BusinessProfile:
    """Shrink to one line each from whatever snippets exist."""
    text = " ".join(business.snippets)[:600]
    industry = business.category or "unknown"
    return BusinessProfile(
        industry=industry,
        size_signal=(f"{business.review_count or '?'} reviews" if business.review_count else "unknown"),
        pain_point="unknown",
        hook=(f"their work as a {industry}" if industry != "unknown" else "their operations"),
        summary=text[:200],
        source="heuristic",
    )


def draft_email(profile: BusinessProfile, contact: ContactCandidate,
                product: str, tone: str) -> EmailDraft:
    """Template-grade fallback referencing the goal's product line."""
    name = contact.name or "there"
    return EmailDraft(
        subject=f"{product} for {profile.industry != 'unknown' and profile.industry or 'your team'}".strip(),
        body=(f"Hi {name},\n\nWe help teams like yours with {product}. "
              f"Quick 5-minute chat this week?\n\nBest"),
        greeting=f"Hi {name},",
        hook=profile.hook,
        ai_powered=False,
        source="fallback",
    )


def classify_reply(reply_text: str) -> ReplyIntent:
    """Keyword triage — cheap, conservative, same shape as the AI answer."""
    t = (reply_text or "").lower()
    if any(k in t for k in ("not interested", "no thanks", "unsubscribe", "stop")):
        intent, action = "not_interested", "mark dead"
    elif any(k in t for k in ("out of office", "on leave", "vacation", "away until")):
        intent, action = "out_of_office", "retry in 2 weeks"
    elif any(k in t for k in ("not the right person", "forwarded", "wrong person")):
        intent, action = "wrong_person", "ask for the right contact"
    elif any(k in t for k in ("too expensive", "budget", "price is high", "cost")):
        intent, action = "objection", "send pricing options"
    elif any(k in t for k in ("interested", "tell me more", "sounds good", "yes")):
        intent, action = "interested", "send case study + ask for a call"
    else:
        intent, action = "unknown", "manual review"
    return ReplyIntent(intent=intent, next_action=action, confidence=0.6, source="heuristic")


def expand_query(seed_query: str) -> QueryExpansion:
    """No-AI expansion is a no-op — the loop works without the assist."""
    return QueryExpansion(queries=[seed_query], rationale="no AI assist available",
                          source="heuristic")


def extract_contact(page_text: str) -> list[ContactCandidate]:
    """Regex pass over raw page text for mailto-style candidates."""
    import re
    out: list[ContactCandidate] = []
    for m in re.finditer(r"([A-Za-z][A-Za-z .'-]{2,40})\s*[—\-–|,]\s*([A-Za-z /&]{3,40})", page_text or ""):
        out.append(ContactCandidate(name=m.group(1).strip(), title=m.group(2).strip(),
                                    confidence=0.3, source="heuristic"))
    return out[:5]
