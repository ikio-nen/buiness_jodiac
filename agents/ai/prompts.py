"""Prompt files for the ai seam — one versioned .md per capability.

A prompt edit is a diff to one file, not a code change. Each file's first
line MUST be a ``<!-- version: N -->`` comment; the usage log records it
with every call so a capability's answers can be traced to its prompt rev.
"""

from pathlib import Path

_PROMPTS = Path(__file__).parent / "prompts"

# Capability name -> file stem (1:1 with the service methods).
FILES = {
    "score_fit": "score_fit.md",
    "summarize_profile": "summarize_profile.md",
    "draft_email": "draft_email.md",
    "classify_reply": "classify_reply.md",
    "expand_query": "expand_query.md",
    "extract_contact": "extract_contact.md",
}

_cache: dict[str, tuple[str, str]] = {}   # capability -> (version, body)


def load(capability: str) -> tuple[str, str]:
    """Return (version, body) for a capability's prompt, cached."""
    if capability in _cache:
        return _cache[capability]
    path = _PROMPTS / FILES[capability]
    raw = path.read_text(encoding="utf-8")
    version, body = "0", raw
    if raw.startswith("<!--"):
        head, _, rest = raw.partition("-->")
        for token in head.split():
            if token.startswith("version:"):
                version = token.split(":", 1)[1]
        body = rest.lstrip("\n")
    _cache[capability] = (version, body)
    return _cache[capability]
