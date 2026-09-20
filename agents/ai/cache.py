"""Per-business memoization — score_fit and summarize_profile only.

A business is scored once and reused; drafts and reply classifications are
never cached (one-shot, or tied to a specific reply). Keys on the same
identifier icp.py uses to dedupe: name + location, lowercased. Invalidation
is a deliberate ``rescore()`` — a meaningful business change is rare enough
to be explicit (ARCH §6).
"""

from agents.ai.schemas import BusinessProfile, FitScore

_cache: dict[str, FitScore | BusinessProfile] = {}


def key(business_id: str, capability: str) -> str:
    return f"{capability}:{(business_id or '').strip().lower()}"


def business_id(b: dict) -> str:
    """Stable id: name + location, the dedupe pair the search already uses."""
    return f"{(b.get('name') or '?')}|{(b.get('location') or b.get('vicinity') or '')}".strip()


def get(capability: str, bid: str):
    return _cache.get(key(bid, capability))


def put(capability: str, bid: str, value) -> None:
    _cache[key(bid, capability)] = value


def rescore(business_id: str = "") -> int:
    """Drop one business's entries, or all when no id given. Returns count."""
    if not business_id:
        n = len(_cache)
        _cache.clear()
        return n
    drop = [k for k in _cache if k.endswith(f":{business_id.strip().lower()}")]
    for k in drop:
        _cache.pop(k, None)
    return len(drop)
