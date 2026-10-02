"""AI Brain -- a growing knowledge store that learns from every interaction.

The brain is a directory of JSON files that the AI builds up over time:
  brain/
    profile.json          -- what we sell, who we target, our story
    icp.json              -- who actually turned out to be a fit, signal by signal
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

    # ── ICP (who our kind of customer is, learned from every search) ──

    def _icp_path(self) -> Path:
        return BRAIN_DIR / "icp.json"

    def get_icp(self) -> dict:
        """Everything learned about which businesses are actually our customers."""
        return self._migrate_icp(self._read(self._icp_path()))

    def _migrate_icp(self, data: dict) -> dict:
        """Fold pre-goal learning into the per-goal shape, once.

        Before goals existed there was a single product, so the old top-level
        counters are the cad_licensing goal's history. Throwing them away would
        silently discard everything learned so far.
        """
        if not data:
            return data
        legacy = bool(data.get("signal_stats") or data.get("type_stats"))
        by_goal = data.get("by_goal") or {}
        if not legacy or "cad_licensing" in by_goal:
            return data
        product = data.get("product", "")
        data["by_goal"] = {**by_goal, "cad_licensing": {
            "label": "CAD / drafting software licences",
            "product": product,
            "signal_stats": data.get("signal_stats", {}),
            "type_stats": data.get("type_stats", {}),
            "rejected_names": data.get("rejected_names", {}),
            "total_judged": data.get("total_judged", 0),
            "total_fits": data.get("total_fits", 0),
            "total_rejects": data.get("total_rejects", 0),
            "updated_at": data.get("updated_at", ""),
        }}
        runs = data.setdefault("goals_seen", {})
        runs.setdefault("cad_licensing", {
            "runs": 1, "label": "CAD / drafting software licences",
            "product": product, "last_used": data.get("updated_at", "")})
        # The legacy keys are now represented per goal; leaving them would read
        # as a third, goal-less bucket of stats.
        for stale in ("signal_stats", "type_stats", "rejected_names",
                      "total_judged", "total_fits", "total_rejects", "product"):
            data.pop(stale, None)
        self._write(self._icp_path(), data)
        return data

    def learn_icp_feedback(self, judged: list[dict], goal_key: str = "",
                           goal_label: str = "", product: str = "") -> dict:
        """Accumulate which signals actually turned out to be a fit FOR ONE GOAL.

        Expects businesses carrying a verdict in ``biz['icp']``. Everything is
        counted per goal: the same signal means different things when we are
        selling licences than when we are selling websites, so blending the two
        would make the learning worse than none.
        """
        goal_key = goal_key or "custom"
        data = self.get_icp()
        by_goal: dict = data.setdefault("by_goal", {})
        g = by_goal.setdefault(goal_key, {"signal_stats": {}, "type_stats": {},
                                           "rejected_names": {}})
        if goal_label:
            g["label"] = goal_label
        if product:
            g["product"] = product
        g.setdefault("signal_stats", {})
        g.setdefault("type_stats", {})
        rejected: dict = g.setdefault("rejected_names", {})

        fits = rejects = 0
        for biz in judged:
            verdict = biz.get("icp") or {}
            if not verdict:
                continue
            is_fit = verdict.get("fit") in ("fits", "plausible")
            fits += 1 if is_fit else 0
            rejects += 0 if is_fit else 1
            bucket = "fits" if is_fit else "unlikely"
            for sig in verdict.get("matched_signals") or []:
                st = g["signal_stats"].setdefault(sig, {"fits": 0, "unlikely": 0})
                st[bucket] = st.get(bucket, 0) + 1
            label = verdict.get("institution_type")
            if label and not label.startswith("Rejected (memory)"):
                # Carried verdicts are SKIPS, not judgments: counting them
                # would double-charge every re-searched pile against the
                # learned rates. (Known rejections whose reason is not a
                # structural one were never counted before either — see
                # the memory filter in icp.known_rejections.)
                # Both sides of the conversion story: judged counts let later
                # runs compute a RATE (fits/judged), not just raw fit counts.
                # ``fits`` starts the epoch ``judged`` measures: legacy entries
                # mix an all-time ``seen`` with a since-tracking ``judged``,
                # so their rate is re-based here (all-time ``seen`` stays for
                # display in get_icp_context).
                ts = g["type_stats"].setdefault(label, {"seen": 0, "judged": 0})
                ts.setdefault("judged", 0)
                if "fits" not in ts:
                    ts["fits"] = 0
                    ts["judged"] = 0
                ts["judged"] += 1
                if is_fit:
                    ts["seen"] += 1
                    ts["fits"] += 1
            # Remember who we already ruled out for this goal, so the same piles
            # are not re-litigated on every future search of the same area.
            # Store the FIRST structural reason verbatim: a re-learned skip
            # arrives with "(known rejection)" appended, and storing that
            # would compound the suffix on every future search.
            if not is_fit and verdict.get("disqualifiers"):
                reason = verdict["disqualifiers"][0]
                if reason not in rejected and not reason.endswith(
                        "(known rejection)"):
                    rejected[biz.get("name", "?")] = reason
        for stale in list(rejected)[:-200]:
            del rejected[stale]

        g["total_judged"] = g.get("total_judged", 0) + len(judged)
        g["total_fits"] = g.get("total_fits", 0) + fits
        g["total_rejects"] = g.get("total_rejects", 0) + rejects
        g["updated_at"] = datetime.now().isoformat()

        # Which goals we have run, newest last -- so the system remembers that
        # targeting moves around instead of assuming one product.
        seen = data.setdefault("goals_seen", {})
        entry = seen.setdefault(goal_key, {"runs": 0})
        entry["runs"] = entry.get("runs", 0) + 1
        entry["label"] = goal_label or entry.get("label", goal_key)
        entry["product"] = product or entry.get("product", "")
        entry["last_used"] = datetime.now().isoformat()
        data["updated_at"] = datetime.now().isoformat()
        self._write(self._icp_path(), data)
        return data

    def get_rejected_names(self, goal_key: str = "") -> dict:
        """name -> first disqualifier, for one goal (empty key = all goals).

        Readers must pass the goal of their search: a "no" from selling
        websites is not a "no" from selling licences.
        """
        data = self.get_icp()
        by_goal: dict = data.get("by_goal") or {}
        if not goal_key:
            return {}
        return dict((by_goal.get(goal_key) or {}).get("rejected_names") or {})

    def get_icp_context(self, goal_key: str = "") -> str:
        """What we have learned about who fits, for one goal (or all goals)."""
        data = self.get_icp()
        if not data:
            return ""
        by_goal = data.get("by_goal") or {}
        if not by_goal:
            return ""

        parts = []
        keys = [goal_key] if goal_key in by_goal else list(by_goal)
        for key in keys:
            g = by_goal.get(key) or {}
            label = g.get("label") or key
            head = f"Target learning for {g.get('product') or label}:"
            lines = [head]
            judged = g.get("total_judged", 0)
            if judged:
                fits = g.get("total_fits", 0)
                lines.append(f"  {fits}/{judged} businesses judged have been a fit "
                             f"({round(100 * fits / judged)}%)")
            types = sorted((g.get("type_stats") or {}).items(),
                           key=lambda kv: -kv[1].get("seen", 0))[:6]
            if types:
                lines.append("  Fits seen by type: " +
                             ", ".join(f"{k} ({v.get('seen', 0)})" for k, v in types))
            # Signals that keep producing rejects are worth naming explicitly.
            noise = []
            for sig, st in (g.get("signal_stats") or {}).items():
                seen_n = st.get("fits", 0) + st.get("unlikely", 0)
                if seen_n >= 3 and st.get("fits", 0) == 0:
                    noise.append(f"{sig} ({st.get('unlikely', 0)}x)")
            if noise:
                lines.append("  Signals that never fitted: " + ", ".join(noise[:6]))
            parts.append("\n".join(lines))

        seen = data.get("goals_seen") or {}
        if len(seen) > 1:
            parts.append("Goals we have searched for: " + ", ".join(
                f"{v.get('label', k)} ({v.get('runs', 0)})" for k, v in seen.items()))
        return "\n".join(parts)

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

        # Who actually buys from us: the target profile plus what we've learned
        # from judging every business we've ever searched.
        try:
            from agents.icp import goals_overview
            goals_ctx = goals_overview()
            if goals_ctx:
                parts.append(f"\n{goals_ctx}")
        except Exception:
            pass
        icp_learned = self.get_icp_context()
        if icp_learned:
            parts.append(f"\n{icp_learned}")

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
