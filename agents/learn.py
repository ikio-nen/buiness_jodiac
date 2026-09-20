#!/usr/bin/env python3
"""Self-learning module — JARVIS learns from every interaction.

Tracks:
  - Business type patterns (what works for schools vs cafes vs shops)
  - Email template performance (approved/rejected/sent)
  - Scraping insights (what data we find for each type)
  - Outcome tracking (replies, conversions, bounce rates)

Each session, the system reads past patterns and uses them to:
  - Generate better emails for each business type
  - Suggest which businesses to prioritize
  - Improve website generation per category
  - Build a knowledge base of what works in each industry
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.config import OUTPUT_DIR, load_config, save_config
from agents.industry_templates import get_template_context, match_category_to_template, get_all_with_custom


# ── Knowledge base path ──────────────────────────────────────────────

KB_DIR = OUTPUT_DIR / "knowledge_base"
KB_DIR.mkdir(exist_ok=True)

PATTERNS_FILE = KB_DIR / "business_patterns.json"
EMAIL_PERF_FILE = KB_DIR / "email_performance.json"
INSIGHTS_FILE = KB_DIR / "industry_insights.json"
FEEDBACK_FILE = KB_DIR / "feedback_history.json"


# ── Core knowledge base ─────────────────────────────────────────────

class KnowledgeBase:
    """Persistent knowledge store that learns from every outreach session."""

    def __init__(self):
        self.patterns = self._load(PATTERNS_FILE, {"categories": {}, "total_interactions": 0})
        self.email_perf = self._load(EMAIL_PERF_FILE, {"templates": {}, "by_category": {}})
        self.insights = self._load(INSIGHTS_FILE, {"industries": {}, "locations": {}})
        self.feedback = self._load(FEEDBACK_FILE, {"history": []})

    def _load(self, path: Path, default: Any) -> Any:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return default
        return default

    def _save_all(self):
        self._save(PATTERNS_FILE, self.patterns)
        self._save(EMAIL_PERF_FILE, self.email_perf)
        self._save(INSIGHTS_FILE, self.insights)
        self._save(FEEDBACK_FILE, self.feedback)

    def _save(self, path: Path, data: Any):
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # ── Pattern tracking ────────────────────────────────────────────

    def learn_from_business(self, biz: dict, email_draft: dict = None,
                            action: str = "discovered"):
        """Record what we learned from a business interaction."""
        category = biz.get("category", "unknown")
        cat_data = self.patterns["categories"].setdefault(category, {
            "count": 0,
            "total_found": 0,
            "has_website_pct": 0,
            "has_email_pct": 0,
            "avg_lead_score": 0,
            "common_tags": {},
            "best_hooks": [],
            "email_open_rate": 0,
            "email_reply_rate": 0,
            "locations": [],
            "sample_names": [],
        })

        cat_data["count"] += 1
        cat_data["total_found"] += 1

        # Track website/email availability rates
        has_site = bool(biz.get("website"))
        has_email = bool(biz.get("email") or biz.get("enrichment", {}).get("email"))

        n = cat_data["count"]
        cat_data["has_website_pct"] = (
            (cat_data["has_website_pct"] * (n - 1) + (100 if has_site else 0)) / n
        )
        cat_data["has_email_pct"] = (
            (cat_data["has_email_pct"] * (n - 1) + (100 if has_email else 0)) / n
        )

        # Track common tags
        tags = biz.get("tags", {})
        for key, val in tags.items():
            if val:
                cat_data["common_tags"][key] = cat_data["common_tags"].get(key, 0) + 1

        # Track location patterns
        loc = biz.get("address", "").split(",")[-1].strip() if biz.get("address") else ""
        if loc and loc not in cat_data["locations"]:
            cat_data["locations"].append(loc)

        # Track sample names (up to 10)
        name = biz.get("name", "")
        if name and name not in cat_data["sample_names"]:
            cat_data["sample_names"].append(name)
            cat_data["sample_names"] = cat_data["sample_names"][-10:]

        # Track successful email hooks
        if email_draft and email_draft.get("hook"):
            hook = email_draft["hook"]
            if hook not in cat_data["best_hooks"]:
                cat_data["best_hooks"].append(hook)
                cat_data["best_hooks"] = cat_data["best_hooks"][-5:]

        self.patterns["total_interactions"] += 1
        self._save_all()

    def learn_from_email_result(self, category: str, subject: str,
                                body_preview: str, outcome: str):
        """Track email template performance.

        outcome: 'sent', 'opened', 'replied', 'bounced', 'rejected_draft'
        """
        # Per-template tracking
        template_key = f"{category}:{subject[:50]}"
        tmpl = self.email_perf["templates"].setdefault(template_key, {
            "category": category,
            "subject": subject,
            "body_preview": body_preview[:200],
            "sent": 0, "opened": 0, "replied": 0, "bounced": 0, "rejected": 0,
        })
        if outcome == "sent":
            tmpl["sent"] += 1
        elif outcome == "opened":
            tmpl["opened"] += 1
        elif outcome == "replied":
            tmpl["replied"] += 1
        elif outcome == "bounced":
            tmpl["bounced"] += 1
        elif outcome == "rejected_draft":
            tmpl["rejected"] += 1
        # "drafted" tracks template creation without counting as sent

        # Per-category aggregate
        cat_perf = self.email_perf["by_category"].setdefault(category, {
            "total_sent": 0, "total_opened": 0, "total_replied": 0,
            "total_bounced": 0, "total_rejected": 0, "best_subjects": [],
        })
        if outcome in ("sent", "opened", "replied", "bounced"):
            cat_perf[f"total_{outcome}"] += 1
        if outcome == "rejected_draft":
            cat_perf["total_rejected"] += 1
        if outcome in ("opened", "replied") and subject not in cat_perf["best_subjects"]:
            cat_perf["best_subjects"].append(subject)
            cat_perf["best_subjects"] = cat_perf["best_subjects"][-5:]

        self._save_all()

    def record_feedback(self, biz_name: str, category: str,
                        email_subject: str, rating: int, notes: str = ""):
        """User rates an email draft 1-5 stars or approves/rejects."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "business": biz_name,
            "category": category,
            "subject": email_subject,
            "rating": max(1, min(5, rating)),
            "notes": notes,
        }
        self.feedback["history"].append(entry)
        # Keep last 500 feedback entries
        self.feedback["history"] = self.feedback["history"][-500:]
        self._save_all()

    # ── Pattern queries ─────────────────────────────────────────────

    def get_category_context(self, category: str) -> str:
        """Build a context string about what we've learned for this business type.

        Used by AI agents to generate better emails/websites.
        Starts with template baseline, then layers on real interaction data.
        """
        # Start with template baseline
        template_key = match_category_to_template(category)
        template_context = get_template_context(template_key) if template_key else ""

        cat_data = self.patterns["categories"].get(category)
        if not cat_data:
            return template_context

        parts = [f"Industry: {category}"]

        if cat_data["count"] > 0:
            parts.append(f"Businesses encountered: {cat_data['count']}")
        if cat_data["has_website_pct"] > 0:
            parts.append(f"Typically have websites: {cat_data['has_website_pct']:.0f}%")
        if cat_data["has_email_pct"] > 0:
            parts.append(f"Typically have email: {cat_data['has_email_pct']:.0f}%")
        if cat_data["best_hooks"]:
            parts.append("Hooks that worked before:")
            for hook in cat_data["best_hooks"][:3]:
                parts.append(f'  - "{hook}"')
        if cat_data["common_tags"]:
            top_tags = sorted(cat_data["common_tags"].items(), key=lambda x: -x[1])[:5]
            parts.append("Common attributes: " + ", ".join(f"{k}" for k, _ in top_tags))

        # Email performance
        cat_perf = self.email_perf["by_category"].get(category, {})
        if cat_perf.get("total_sent", 0) > 0:
            sent = cat_perf["total_sent"]
            opened = cat_perf.get("total_opened", 0)
            replied = cat_perf.get("total_replied", 0)
            bounced = cat_perf.get("total_bounced", 0)
            parts.append(f"Email stats: {sent} sent, {opened} opened ({opened/sent*100:.0f}%), "
                         f"{replied} replied ({replied/sent*100:.0f}%), {bounced} bounced")
            if cat_perf.get("best_subjects"):
                parts.append("Best performing subjects:")
                for subj in cat_perf["best_subjects"][:3]:
                    parts.append(f'  - "{subj}"')

        learned_context = "\n".join(parts)

        # Combine template baseline + learned data
        if template_context and learned_context:
            return f"{template_context}\n\n--- From real interactions ---\n{learned_context}"
        elif template_context:
            return template_context
        else:
            return learned_context

    def get_best_email_patterns(self, category: str, top_n: int = 3) -> list[dict]:
        """Get the best-performing email patterns for a category."""
        patterns = []
        for key, tmpl in self.email_perf["templates"].items():
            if tmpl["category"] != category:
                continue
            if tmpl["sent"] == 0 and tmpl["rejected"] == 0:
                continue
            # Score: (opened + replied*3) / (sent + 1) - bounced*0.5
            score = (
                (tmpl.get("opened", 0) + tmpl.get("replied", 0) * 3) /
                max(tmpl.get("sent", 0), 1) -
                tmpl.get("bounced", 0) * 0.5
            )
            patterns.append({
                "subject": tmpl["subject"],
                "body_preview": tmpl["body_preview"],
                "score": score,
                "sent": tmpl["sent"],
                "opened": tmpl.get("opened", 0),
                "replied": tmpl.get("replied", 0),
            })

        patterns.sort(key=lambda x: -x["score"])
        return patterns[:top_n]

    def get_location_insights(self, location: str) -> dict:
        """Get insights about a location from past sessions."""
        loc_data = self.insights["locations"].setdefault(location, {
            "sessions": 0,
            "total_found": 0,
            "categories_found": [],
            "avg_no_site_pct": 0,
        })
        return loc_data

    def update_location(self, location: str, total: int, no_site: int,
                        categories: list[str]):
        """Record search results for a location."""
        loc = self.insights["locations"].setdefault(location, {
            "sessions": 0, "total_found": 0,
            "categories_found": [], "avg_no_site_pct": 0,
        })
        loc["sessions"] += 1
        loc["total_found"] += total
        no_site_pct = (no_site / total * 100) if total else 0
        n = loc["sessions"]
        loc["avg_no_site_pct"] = (
            (loc["avg_no_site_pct"] * (n - 1) + no_site_pct) / n
        )
        for cat in categories:
            if cat not in loc["categories_found"]:
                loc["categories_found"].append(cat)
        self._save(INSIGHTS_FILE, self.insights)

    # ── Learning summary ────────────────────────────────────────────

    def get_summary(self) -> dict:
        """Get a summary of what the system has learned."""
        total = self.patterns["total_interactions"]
        categories = self.patterns["categories"]

        total_sent = sum(c.get("total_sent", 0) for c in self.email_perf["by_category"].values())
        total_opened = sum(c.get("total_opened", 0) for c in self.email_perf["by_category"].values())
        total_replied = sum(c.get("total_replied", 0) for c in self.email_perf["by_category"].values())

        return {
            "total_businesses_seen": total,
            "categories_learned": len(categories),
            "top_categories": sorted(
                categories.items(), key=lambda x: -x[1]["count"]
            )[:5],
            "emails_sent": total_sent,
            "emails_opened": total_opened,
            "emails_replied": total_replied,
            "open_rate": f"{total_opened/total_sent*100:.0f}%" if total_sent else "N/A",
            "reply_rate": f"{total_replied/total_sent*100:.0f}%" if total_sent else "N/A",
            "locations_explored": len(self.insights.get("locations", {})),
            "feedback_entries": len(self.feedback.get("history", [])),
        }

    def print_summary(self):
        """Print a human-readable learning summary."""
        s = self.get_summary()
        lines = [
            f"  Total businesses analyzed: {s['total_businesses_seen']}",
            f"  Categories learned: {s['categories_learned']}",
            f"  Emails sent: {s['emails_sent']}",
            f"  Open rate: {s['open_rate']}",
            f"  Reply rate: {s['reply_rate']}",
            f"  Locations explored: {s['locations_explored']}",
            f"  Feedback entries: {s['feedback_entries']}",
        ]
        if s["top_categories"]:
            lines.append("  Top categories:")
            for cat, data in s["top_categories"]:
                lines.append(f"    {cat}: {data['count']} businesses, "
                             f"{data.get('has_email_pct', 0):.0f}% have email")
        return "\n".join(lines)


# ── Singleton ───────────────────────────────────────────────────────

_kb = None

def get_kb() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb


# ── Convenience functions (used by workflows.py) ───────────────────

def learn_from_search(businesses: list[dict], location: str):
    """Learn from a batch of search results."""
    kb = get_kb()
    categories = set()
    for biz in businesses:
        kb.learn_from_business(biz, action="discovered")
        cat = biz.get("category", "unknown")
        categories.add(cat)
    no_site = len([b for b in businesses if not b.get("website")])
    kb.update_location(location, len(businesses), no_site, list(categories))


def suggest_refined_query(seed_query: str, businesses: list[dict],
                          goal_label: str = "") -> str:
    """Optional AI assist: what should we search for NEXT?

    Wraps the Gemini seam's expand_query with what this batch taught us.
    Returns '' when the AI is unavailable — the calling loop simply works
    without it (PRD §4.5: the loop must not depend on the assist).
    """
    try:
        from agents.ai import service as ai_service
        fits = [b.get("category", "?") for b in businesses if (b.get("icp") or {}).get("fit") == "fits"]
        junk = [b.get("category", "?") for b in businesses if (b.get("icp") or {}).get("fit") == "unlikely"]
        learnings = [f"goal: {goal_label or 'n/a'}",
                     f"categories that fit: {', '.join(sorted(set(fits))[:6]) or 'none'}",
                     f"categories to avoid: {', '.join(sorted(set(junk))[:6]) or 'none'}"]
        out = ai_service.expand_query(seed_query, learnings)
        return (out.queries or [""])[0] if out.source == "gemini" else ""
    except Exception:
        return ""


def learn_from_draft(category: str, subject: str, body: str):
    """Learn that a draft was created (not yet sent)."""
    kb = get_kb()
    kb.learn_from_email_result(category, subject, body[:100], "drafted")


def learn_from_send(category: str, subject: str, body: str, success: bool):
    """Learn from an email send result."""
    kb = get_kb()
    outcome = "sent" if success else "bounced"
    kb.learn_from_email_result(category, subject, body[:100], outcome)


def learn_from_rejection(category: str, subject: str, body: str):
    """Learn that user rejected a draft — avoid this pattern."""
    kb = get_kb()
    kb.learn_from_email_result(category, subject, body[:100], "rejected_draft")


def record_draft_feedback(biz_name: str, category: str, subject: str,
                          approved: bool, notes: str = ""):
    """Record user feedback on a draft."""
    kb = get_kb()
    rating = 5 if approved else 1
    kb.record_feedback(biz_name, category, subject, rating, notes)


def get_learning_context(category: str) -> str:
    """Get learning context for AI prompt generation."""
    return get_kb().get_category_context(category)


def get_learning_summary() -> str:
    """Get human-readable learning summary."""
    return get_kb().print_summary()


def get_learning_dashboard() -> dict:
    """Get structured dashboard data for display."""
    kb = get_kb()
    s = kb.get_summary()
    
    # Build detailed category info
    categories = []
    for cat, data in kb.patterns.get("categories", {}).items():
        cat_perf = kb.email_perf.get("by_category", {}).get(cat, {})
        categories.append({
            "name": cat,
            "count": data.get("count", 0),
            "website_pct": data.get("has_website_pct", 0),
            "email_pct": data.get("has_email_pct", 0),
            "emails_sent": cat_perf.get("total_sent", 0),
            "emails_opened": cat_perf.get("total_opened", 0),
            "emails_replied": cat_perf.get("total_replied", 0),
            "emails_rejected": cat_perf.get("total_rejected", 0),
            "top_hooks": data.get("best_hooks", [])[:3],
            "top_subjects": cat_perf.get("best_subjects", [])[:3],
            "sample_names": data.get("sample_names", [])[:3],
            "common_tags": list(data.get("common_tags", {}).keys())[:5],
        })
    categories.sort(key=lambda x: -x["count"])
    
    # Build email performance data
    email_templates = []
    for key, tmpl in kb.email_perf.get("templates", {}).items():
        email_templates.append({
            "category": tmpl.get("category", ""),
            "subject": tmpl.get("subject", ""),
            "sent": tmpl.get("sent", 0),
            "opened": tmpl.get("opened", 0),
            "replied": tmpl.get("replied", 0),
            "bounced": tmpl.get("bounced", 0),
            "rejected": tmpl.get("rejected", 0),
        })
    email_templates.sort(key=lambda x: -(x["opened"] + x["replied"] * 3))
    
    # Build location data
    locations = []
    for loc, data in kb.insights.get("locations", {}).items():
        locations.append({
            "name": loc,
            "sessions": data.get("sessions", 0),
            "total_found": data.get("total_found", 0),
            "no_site_pct": data.get("avg_no_site_pct", 0),
            "categories": data.get("categories_found", []),
        })
    locations.sort(key=lambda x: -x["total_found"])
    
    # Build feedback data
    feedback = kb.feedback.get("history", [])
    recent_feedback = feedback[-5:] if feedback else []
    avg_rating = 0
    if feedback:
        avg_rating = sum(f.get("rating", 0) for f in feedback) / len(feedback)
    
    return {
        "summary": s,
        "categories": categories,
        "email_templates": email_templates[:10],
        "locations": locations,
        "recent_feedback": recent_feedback,
        "avg_feedback_rating": avg_rating,
        "total_feedback": len(feedback),
    }
