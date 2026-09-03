#!/usr/bin/env python3
"""Lightweight agent — handles easy, fast tasks.

Covers:
  • Text classification / categorisation
  • Format conversion (e.g. dict → CSV row)
  • Simple data look-ups and validations
  • Keyword extraction
  • Sentiment scoring
"""

import json
import re
from typing import Any

from .base import BaseAgent, Complexity, Task


class LightweightAgent(BaseAgent):
    """Fast, cheap agent for simple deterministic tasks.

    Does NOT call any LLM — uses rule-based heuristics so it's fast and free.
    """

    def __init__(self):
        super().__init__(model="rule-based")
        self.supported_tasks = {
            "classify_text", "validate_email",
            "extract_keywords", "score_sentiment", "format_address",
            "parse_business_tags", "summarise_counts",
        }

    @property
    def agent_id(self) -> str:
        return "lightweight"

    @property
    def max_complexity(self) -> Complexity:
        return Complexity.LIGHT

    # ------------------------------------------------------------------ #
    #  Task dispatch by name                                              #
    # ------------------------------------------------------------------ #

    def _execute(self, task: Task) -> Any:
        handlers = {
            "classify_text":       self._classify_text,
            "validate_email":      self._validate_email,
            "extract_keywords":    self._extract_keywords,
            "score_sentiment":     self._score_sentiment,
            "format_address":      self._format_address,
            "parse_business_tags": self._parse_osm_tags,
            "summarise_counts":    self._summarise_counts,
        }
        handler = handlers.get(task.name)
        if handler is None:
            raise ValueError(f"LightweightAgent has no handler for task '{task.name}'")
        return handler(task.payload)

    # ------------------------------------------------------------------ #
    #  Handlers                                                           #
    # ------------------------------------------------------------------ #

    def _classify_text(self, payload: dict) -> dict:
        """Classify a business name / description into a rough category."""
        text = (payload.get("text") or "").lower()

        CATEGORIES = {
            "food_and_drink":  ["cafe", "restaurant", "bar", "pub", "bakery", "coffee", "food", "pizza", "pasta", "diner"],
            "retail":          ["shop", "store", "boutique", "market", "mall"],
            "healthcare":      ["clinic", "hospital", "pharmacy", "dentist", "doctor", "medical"],
            "professional":    ["lawyer", "accountant", "consulting", "agency", "studio"],
            "education":       ["school", "academy", "tutor", "training", "college"],
            "fitness":         ["gym", "yoga", "fitness", "sport", "wellness"],
            "technology":      ["tech", "software", "digital", "computer", "it"],
            "home_services":   ["plumber", "electrician", "cleaning", "landscaping", "repair"],
        }

        scores: dict[str, int] = {}
        for cat, keywords in CATEGORIES.items():
            scores[cat] = sum(1 for kw in keywords if re.search(r'\b' + re.escape(kw) + r'\b', text))

        best = max(scores, key=scores.get) if any(scores.values()) else "unknown"
        return {"category": best, "scores": scores, "text": text}

    def _validate_email(self, payload: dict) -> dict:
        """Simple regex-based email validation."""
        email = payload.get("email", "")
        pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{1,}$"
        valid = bool(re.match(pattern, email))
        domain = email.split("@")[1] if valid and "@" in email else ""
        return {"email": email, "valid": valid, "domain": domain}

    def _extract_keywords(self, payload: dict) -> dict:
        """Pull top keywords from text by frequency."""
        text = payload.get("text", "")
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "is", "it", "that", "this",
            "was", "are", "be", "has", "had", "have", "we", "our", "you",
        }
        words = re.findall(r"[a-z]{3,}", text.lower())
        freq: dict[str, int] = {}
        for w in words:
            if w not in stop_words:
                freq[w] = freq.get(w, 0) + 1
        top = sorted(freq.items(), key=lambda x: -x[1])[:10]
        return {"keywords": [w for w, _ in top], "counts": dict(top)}

    def _score_sentiment(self, payload: dict) -> dict:
        """Naive word-based sentiment score in [-1, 1]."""
        text = payload.get("text", "").lower()
        positive = {"good", "great", "excellent", "amazing", "best", "love", "wonderful", "fantastic", "happy", "awesome"}
        negative = {"bad", "terrible", "worst", "hate", "awful", "poor", "horrible", "ugly", "slow", "broken"}
        words = set(re.findall(r"[a-z]+", text))
        pos = len(words & positive)
        neg = len(words & negative)
        total = pos + neg
        score = (pos - neg) / total if total else 0.0
        return {"score": round(score, 3), "positive_hits": pos, "negative_hits": neg, "label": "positive" if score > 0 else "negative" if score < 0 else "neutral"}

    def _format_address(self, payload: dict) -> dict:
        """Pretty-print a flat address string."""
        raw = payload.get("address", "")
        # Simple cleanup
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return {"formatted": ", ".join(parts), "parts": parts}

    def _parse_osm_tags(self, payload: dict) -> dict:
        """Extract useful info from raw OSM tags."""
        tags = payload.get("tags", {})
        return {
            "name": tags.get("name", ""),
            "category": tags.get("shop") or tags.get("amenity") or tags.get("office") or "other",
            "website": tags.get("website", tags.get("contact:website", "")),
            "phone": tags.get("phone", tags.get("contact:phone", "")),
            "email": tags.get("email", tags.get("contact:email", "")),
            "opening_hours": tags.get("opening_hours", ""),
            "has_social": any(k.startswith("contact:") for k in tags),
        }

    def _summarise_counts(self, payload: dict) -> dict:
        """Summarise a list of businesses by category."""
        businesses = payload.get("businesses", [])
        cat_counts: dict[str, int] = {}
        with_email = 0
        with_phone = 0
        for b in businesses:
            cat = b.get("category", "unknown")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
            if b.get("email") or b.get("enrichment", {}).get("email"):
                with_email += 1
            if b.get("phone"):
                with_phone += 1
        return {
            "total": len(businesses),
            "by_category": cat_counts,
            "with_email": with_email,
            "with_phone": with_phone,
            "contact_rate": round(with_email / len(businesses) * 100, 1) if businesses else 0,
        }
