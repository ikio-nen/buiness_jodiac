"""AI Brain -- a growing knowledge store that learns from every interaction.

The brain is a directory of JSON files that the AI builds up over time:
  brain/
    profile.json          -- what we sell, who we target, our story
    industries/           -- one file per industry we've encountered
      education.json      -- pain points, hooks, what worked, what failed
      healthcare.json
      ...
    locations/            -- one file per location we've searched
      bandel.json         -- businesses found, categories, success rate
      kolkata.json
    strategies/           -- what outreach approaches worked
      email_patterns.json -- best subjects, best hooks, by category
      failed_approaches.json -- what didn't work, avoid repeating
    sessions/             -- what we learned from each session
      20260903_120000.json -- summary of what happened, what we learned
    insights/             -- AI-generated insights and recommendations
      recommendations.json -- what to try next, what to avoid
      market_gaps.json     -- opportunities we've identified

The brain is queried by the chatbot and email generators to make
smarter decisions over time. It gets bigger with every session.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from agents.config import OUTPUT_DIR

BRAIN_DIR = OUTPUT_DIR / "brain"

# Ensure directories exist
for subdir in ["industries", "locations", "strategies", "sessions", "insights", "businesses"]:
    (BRAIN_DIR / subdir).mkdir(parents=True, exist_ok=True)


class Brain:
    """The AI's growing knowledge store."""

    def __init__(self):
        self._ensure_dirs()

    def _ensure_dirs(self):
        for subdir in ["industries", "locations", "strategies", "sessions", "insights", "businesses"]:
            (BRAIN_DIR / subdir).mkdir(parents=True, exist_ok=True)

    # ── Per-business knowledge (one file per business) ────────────

    def _biz_path(self, name: str) -> Path:
        key = name.lower().strip().replace(" ", "_").replace("'", "").replace(".", "").replace("&", "and")
        return BRAIN_DIR / "businesses" / f"{key}.json"

    def get_business(self, name: str) -> dict:
        return self._read(self._biz_path(name))

    def learn_business(self, name: str, category: str = "",
                       facts: dict = None, interaction: dict = None,
                       source: str = "") -> dict:
        """Accumulate knowledge about one specific business.

        facts: research/scrape findings (rating, reviews, gaps, strengths...)
        interaction: what happened between us (sent, replied, call planned...)
        Returns the updated record.
        """
        rec = self.get_business(name)
        rec["name"] = name
        if category:
            rec["category"] = category
        rec["updated_at"] = datetime.now().isoformat()
        rec["times_seen"] = rec.get("times_seen", 0) + 1

        for k, v in (facts or {}).items():
            if v in (None, "", []):
                continue
            existing = rec.get(k)
            if isinstance(existing, list) and isinstance(v, list):
                merged = list(dict.fromkeys(existing + v))
                rec[k] = merged[:10]
            else:
                rec[k] = v

        if interaction:
            interaction["timestamp"] = datetime.now().isoformat()
            if source:
                interaction["source"] = source
            rec.setdefault("interactions", []).append(interaction)
            rec["interactions"] = rec["interactions"][-20:]

        self._write(self._biz_path(name), rec)
        try:
            from agents.event_bus import emit
            emit("brain", action="learn", detail=name[:60])
        except Exception:
            pass
        return rec

    def get_business_context(self, name: str) -> str:
        """Compact per-business context for AI prompts."""
        rec = self.get_business(name)
        if not rec:
            return ""
        parts = [f"What we know about {rec.get('name', name)}:"]
        if rec.get("category"):
            parts.append(f"  Category: {rec['category']}")
        if rec.get("rating"):
            parts.append(f"  Google rating: {rec['rating']} ({rec.get('review_count', 0)} reviews)")
        for k in ("strengths", "gaps"):
            if rec.get(k):
                parts.append(f"  {k.title()}: " + "; ".join(rec[k][:3]))
        if rec.get("email_hook"):
            parts.append(f"  Hook that fits: {rec['email_hook']}")
        if rec.get("phone"):
            parts.append(f"  Phone on file: {rec['phone']}")
        if rec.get("email"):
            parts.append(f"  Email on file: {rec['email']}")
        interactions = rec.get("interactions", [])
        if interactions:
            last = interactions[-1]
            parts.append(f"  Last interaction: {last.get('type', '?')} at {last.get('timestamp', '?')[:10]}")
        if rec.get("notes"):
            parts.append(f"  Notes: {rec['notes'][:200]}")
        return "\n".join(parts)

    def list_businesses(self) -> list[dict]:
        """All businesses the brain knows, newest-updated first."""
        out = []
        for f in (BRAIN_DIR / "businesses").glob("*.json"):
            rec = self._read(f)
            if rec:
                out.append(rec)
        out.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
        return out

    def _read(self, path: Path) -> dict:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _write(self, path: Path, data: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=True, default=str),
                        encoding="utf-8")

    # ── Profile (what we sell, who we target) ─────────────────────

    def get_profile(self) -> dict:
        return self._read(BRAIN_DIR / "profile.json")

    def save_profile(self, profile: dict):
        existing = self.get_profile()
        existing.update(profile)
        existing["updated_at"] = datetime.now().isoformat()
        self._write(BRAIN_DIR / "profile.json", existing)

    def get_profile_context(self) -> str:
        """Build a context string from the brain's profile for AI prompts."""
        p = self.get_profile()
        if not p:
            return ""
        parts = []
        for key in ["company_name", "product", "what_we_sell", "target_customers",
                     "ideal_customer", "value_proposition", "our_story",
                     "email_tone", "communication_style", "goals", "competitors"]:
            if p.get(key):
                label = key.replace("_", " ").title()
                parts.append(f"{label}: {p[key]}")
        return "\n".join(parts)

    # ── Industries (one file per business type) ───────────────────

    def get_industry(self, name: str) -> dict:
        key = name.lower().strip().replace(" ", "_").replace("/", "_")
        return self._read(BRAIN_DIR / "industries" / f"{key}.json")

    def save_industry(self, name: str, data: dict):
        key = name.lower().strip().replace(" ", "_").replace("/", "_")
        existing = self.get_industry(name)
        existing.update(data)
        existing["updated_at"] = datetime.now().isoformat()
        # Track interaction count
        existing["times_encountered"] = existing.get("times_encountered", 0) + 1
        self._write(BRAIN_DIR / "industries" / f"{key}.json", existing)

    def learn_industry(self, name: str, pain_points: list = None,
                       hooks: list = None, what_worked: list = None,
                       what_failed: list = None, notes: str = ""):
        """Learn something new about an industry."""
        data = {}
        if pain_points:
            existing = self.get_industry(name)
            old_pp = existing.get("pain_points", [])
            data["pain_points"] = list(set(old_pp + pain_points))
        if hooks:
            existing = self.get_industry(name)
            old_hooks = existing.get("hooks", [])
            data["hooks"] = list(set(old_hooks + hooks))
        if what_worked:
            existing = self.get_industry(name)
            old_ww = existing.get("what_worked", [])
            data["what_worked"] = list(set(old_ww + what_worked))
        if what_failed:
            existing = self.get_industry(name)
            old_wf = existing.get("what_failed", [])
            data["what_failed"] = list(set(old_wf + what_failed))
        if notes:
            existing = self.get_industry(name)
            old_notes = existing.get("notes", "")
            data["notes"] = f"{old_notes}\n{notes}".strip() if old_notes else notes
        self.save_industry(name, data)

    def get_industry_context(self, name: str) -> str:
        """Get brain context for an industry."""
        data = self.get_industry(name)
        if not data:
            return ""
        parts = [f"Industry: {name}"]
        if data.get("pain_points"):
            parts.append("Pain points we've identified:")
            for pp in data["pain_points"][:5]:
                parts.append(f"  - {pp}")
        if data.get("hooks"):
            parts.append("Hooks that worked:")
            for h in data["hooks"][:3]:
                parts.append(f'  - "{h}"')
        if data.get("what_worked"):
            parts.append("What worked: " + ", ".join(data["what_worked"][:3]))
        if data.get("what_failed"):
            parts.append("What failed: " + ", ".join(data["what_failed"][:3]))
        if data.get("notes"):
            parts.append(f"Notes: {data['notes'][:200]}")
        parts.append(f"Encountered {data.get('times_encountered', 0)} times")
        return "\n".join(parts)

    def list_industries(self) -> list[str]:
        """List all industries in the brain."""
        industries_dir = BRAIN_DIR / "industries"
        return [f.stem for f in industries_dir.glob("*.json")]

    # ── Locations (one file per area searched) ────────────────────

    def get_location(self, name: str) -> dict:
        key = name.lower().strip().replace(" ", "_")
        return self._read(BRAIN_DIR / "locations" / f"{key}.json")

    def save_location(self, name: str, data: dict):
        key = name.lower().strip().replace(" ", "_")
        existing = self.get_location(name)
        existing.update(data)
        existing["updated_at"] = datetime.now().isoformat()
        existing["times_searched"] = existing.get("times_searched", 0) + 1
        self._write(BRAIN_DIR / "locations" / f"{key}.json", existing)

    def learn_location(self, name: str, businesses_found: int = 0,
                       categories: list = None, best_categories: list = None,
                       notes: str = ""):
        """Learn something about a location."""
        data = {}
        if businesses_found:
            data["total_businesses_found"] = businesses_found
        if categories:
            existing = self.get_location(name)
            old_cats = existing.get("categories_found", [])
            data["categories_found"] = list(set(old_cats + categories))
        if best_categories:
            existing = self.get_location(name)
            old_bc = existing.get("best_categories", [])
            data["best_categories"] = list(set(old_bc + best_categories))
        if notes:
            existing = self.get_location(name)
            old_notes = existing.get("notes", "")
            data["notes"] = f"{old_notes}\n{notes}".strip() if old_notes else notes
        self.save_location(name, data)

    # ── Strategies (what worked, what failed) ─────────────────────

    def add_strategy(self, category: str, approach: str, outcome: str,
                     details: str = ""):
        """Record an outreach strategy and its outcome."""
        strategies = self._read(BRAIN_DIR / "strategies" / "email_patterns.json")
        cat_strategies = strategies.setdefault(category, {
            "successful": [], "failed": [], "total_attempts": 0
        })
        cat_strategies["total_attempts"] += 1

        entry = {
            "approach": approach,
            "details": details,
            "timestamp": datetime.now().isoformat(),
        }

        if outcome == "success":
            cat_strategies["successful"].append(entry)
            cat_strategies["successful"] = cat_strategies["successful"][-10:]
        elif outcome == "failure":
            cat_strategies["failed"].append(entry)
            cat_strategies["failed"] = cat_strategies["failed"][-10:]

        self._write(BRAIN_DIR / "strategies" / "email_patterns.json", strategies)
        try:
            from agents.event_bus import emit
            emit("brain", action="strategy", detail=f"{category}: {outcome}")
        except Exception:
            pass

    def get_strategies(self, category: str) -> dict:
        """Get strategies for a category."""
        strategies = self._read(BRAIN_DIR / "strategies" / "email_patterns.json")
        return strategies.get(category, {"successful": [], "failed": [], "total_attempts": 0})

    # ── Sessions (what we learned from each session) ──────────────

    def save_session_summary(self, session_id: str, summary: dict):
        """Save what we learned from a session."""
        summary["saved_at"] = datetime.now().isoformat()
        self._write(BRAIN_DIR / "sessions" / f"{session_id}.json", summary)

    def get_recent_sessions(self, limit: int = 10) -> list[dict]:
        """Get recent session summaries."""
        sessions_dir = BRAIN_DIR / "sessions"
        files = sorted(sessions_dir.glob("*.json"), reverse=True)[:limit]
        return [self._read(f) for f in files]

    # ── Insights (AI-generated recommendations) ───────────────────

    def add_insight(self, insight_type: str, content: str, context: str = ""):
        """Add an AI-generated insight."""
        insights = self._read(BRAIN_DIR / "insights" / "recommendations.json")
        entries = insights.setdefault(insight_type, [])
        entries.append({
            "content": content,
            "context": context,
            "timestamp": datetime.now().isoformat(),
        })
        # Keep last 20 per type
        insights[insight_type] = entries[-20:]
        self._write(BRAIN_DIR / "insights" / "recommendations.json", insights)

    def get_insights(self, insight_type: str = None) -> dict:
        """Get insights, optionally filtered by type."""
        insights = self._read(BRAIN_DIR / "insights" / "recommendations.json")
        if insight_type:
            return {insight_type: insights.get(insight_type, [])}
        return insights

    # ── Full context (everything the AI should know) ──────────────

    def get_full_context(self) -> str:
        """Build a complete context string from the entire brain.

        This is injected into the chatbot's system prompt so Gemini
        knows everything the brain has learned.
        """
        parts = []

        # Profile
        profile_ctx = self.get_profile_context()
        if profile_ctx:
            parts.append(f"BUSINESS PROFILE:\n{profile_ctx}")

        # Industries
        industries = self.list_industries()
        if industries:
            parts.append(f"\nINDUSTRIES WE'VE LEARNED ABOUT ({len(industries)}):")
            for ind in industries[:8]:
                ctx = self.get_industry_context(ind)
                if ctx:
                    parts.append(ctx)

        # Known businesses (the ones we've actually interacted with)
        known = self.list_businesses()
        if known:
            parts.append(f"\nBUSINESSES WE KNOW ({len(known)}):")
            for rec in known[:10]:
                line = f"  {rec.get('name', '?')} ({rec.get('category', '?')})"
                if rec.get("phone"):
                    line += f" phone={rec['phone']}"
                if rec.get("interactions"):
                    line += f" last={rec['interactions'][-1].get('type', '?')}"
                parts.append(line)

        # Recent insights
        insights = self.get_insights()
        if insights:
            parts.append("\nRECENT INSIGHTS:")
            for itype, entries in insights.items():
                if entries:
                    latest = entries[-1]
                    parts.append(f"  {itype}: {latest['content'][:100]}")

        # Brain stats
        parts.append(f"\nBRAIN STATS:")
        parts.append(f"  Industries learned: {len(self.list_industries())}")
        parts.append(f"  Locations explored: {len(list((BRAIN_DIR / 'locations').glob('*.json')))}")
        parts.append(f"  Session summaries: {len(list((BRAIN_DIR / 'sessions').glob('*.json')))}")

        return "\n".join(parts)

    # ── Brain stats ───────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get brain statistics."""
        return {
            "industries": len(self.list_industries()),
            "locations": len(list((BRAIN_DIR / "locations").glob("*.json"))),
            "sessions": len(list((BRAIN_DIR / "sessions").glob("*.json"))),
            "insights": sum(len(v) for v in self.get_insights().values()),
            "has_profile": bool(self.get_profile()),
            "total_files": sum(1 for _ in BRAIN_DIR.rglob("*.json")),
        }


# ── Singleton ───────────────────────────────────────────────────────

_brain = None

def get_brain() -> Brain:
    global _brain
    if _brain is None:
        _brain = Brain()
    return _brain
