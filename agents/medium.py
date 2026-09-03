#!/usr/bin/env python3
"""Medium agent — handles moderate tasks that need some intelligence.

Covers:
  • Cold-email / outreach copy drafting
  • Data enrichment via external APIs
  • Summarisation of business profiles
  • Lead scoring / ranking
  • Follow-up sequence generation
"""

import json
import os
import subprocess
from typing import Any
from pathlib import Path

from .base import BaseAgent, Complexity, Task


class MediumAgent(BaseAgent):
    """Mid-tier agent — uses templates + heuristics, no LLM calls.

    Produces good-quality drafts without the cost of a heavy model.
    Falls back to rule-based generation for speed.
    """

    def __init__(self):
        super().__init__(model="template+heuristic")
        self._hunter_key = os.environ.get("HUNTER_API_KEY", "")
        self.supported_tasks = {
            "draft_email", "enrich_with_hunter",
            "score_lead", "summarise_business", "generate_subject",
            "rank_leads", "extract_icebreaker",
        }

    @property
    def agent_id(self) -> str:
        return "medium"

    @property
    def max_complexity(self) -> Complexity:
        return Complexity.MEDIUM

    # ------------------------------------------------------------------ #
    #  Task dispatch                                                      #
    # ------------------------------------------------------------------ #

    def _execute(self, task: Task) -> Any:
        handlers = {
            "draft_email":          self._draft_email,
            "enrich_with_hunter":   self._enrich_hunter,
            "score_lead":           self._score_lead,
            "summarise_business":   self._summarise_business,
            "generate_subject":     self._generate_subject,
            "rank_leads":           self._rank_leads,
            "extract_icebreaker":   self._extract_icebreaker,
        }
        handler = handlers.get(task.name)
        if handler is None:
            raise ValueError(f"MediumAgent has no handler for task '{task.name}'")
        return handler(task.payload, task.context)

    # ------------------------------------------------------------------ #
    #  Email drafting                                                     #
    # ------------------------------------------------------------------ #

    def _draft_email(self, payload: dict, ctx: dict) -> dict:
        """Generate a cold-outreach email for a business."""
        import re as _re
        # Strip HTML tags and excessive special chars from user-provided names
        def _safe(s: str) -> str:
            s = _re.sub(r"<[^>]+>", "", s)  # strip HTML tags
            s = s.replace("&", "and")
            return s.strip()

        biz_name = _safe(payload.get("business_name", "your business"))
        contact_name = _safe(payload.get("contact_name", ""))
        category = payload.get("category", "")
        sender_name = ctx.get("sender_name", "the team")
        service = ctx.get("service", "a professional website")
        tone = payload.get("tone", "professional")

        greeting = f"Hi {contact_name}," if contact_name else f"Hi there,"

        # Category-specific hook — enhanced by learning context
        hooks = {
            "food_and_drink": f"I noticed {biz_name} has great reviews online, and I thought a fresh website could bring in even more customers.",
            "retail": f"I came across {biz_name} while researching local businesses - an online presence could really help you reach more shoppers.",
            "healthcare": f"As a healthcare provider, {biz_name} could benefit from a professional site that makes it easy for patients to find and book you.",
            "professional": f"For a professional services firm like {biz_name}, credibility online is everything - let me help with that.",
            "home_services": f"I saw that {biz_name} is active in the area. A clean website with booking could streamline your workflow.",
            "education": f"As an educational institution, {biz_name} could reach more families and students with a professional online presence.",
            "shop": f"I came across {biz_name} while researching local shops - a modern website could help you reach customers beyond the neighborhood.",
        }
        # Use learning context for better hooks if available
        learning_ctx = payload.get("learning_context", "")
        hook = hooks.get(category, f"I came across {biz_name} and was impressed by what you do.")
        if learning_ctx:
            # First try: research-specific hook ("Suggested opening: ...")
            for line in learning_ctx.split("\n"):
                if "suggested opening:" in line.lower():
                    research_hook = line.split(":", 1)[1].strip()
                    if len(research_hook) > 10:
                        hook = research_hook
                        break
            # Second try: learned hooks from past sessions
            if hook == hooks.get(category, "") and "best hooks" in learning_ctx:
                for line in learning_ctx.split("\n"):
                    if line.strip().startswith('- "'):
                        learned_hook = line.strip().strip('- "').rstrip('"')
                        if len(learned_hook) > 10:
                            hook = learned_hook.format(biz_name=biz_name) if '{biz_name}' in learned_hook else f"{learned_hook} That's why I thought of {biz_name}."
                            break

        # Get business profile for personalized body
        from .config import get_business_profile
        profile = get_business_profile()
        product = profile.get("product", "professional websites")
        value_prop = profile.get("value_proposition", "Most of our clients see a noticeable uptick in calls and visits within the first month.")

        # Get industry pain points for a more relevant email
        from .industry_learner import get_or_research_industry
        industry = get_or_research_industry(category)
        pain_point = industry.get("pain_points", [""])[0] if industry.get("pain_points") else ""
        pain_section = f"\nI understand that {pain_point.lower()}" if pain_point else ""

        body = f"""{greeting}

{hook}{pain_section}

We offer {product} - no templates, no hassle. {value_prop}

Would you be open to a quick 5-minute chat this week?

Best,
{sender_name}"""

        return {
            "to": payload.get("email", ""),
            "subject": self._generate_subject({"business_name": biz_name, "category": category}, ctx)["subject"],
            "body": body.strip(),
            "greeting": greeting,
            "hook": hook,
            "tone": tone,
        }

    def _generate_subject(self, payload: dict, ctx: dict) -> dict:
        """Generate email subject lines."""
        biz_name = payload.get("business_name", "")
        category = payload.get("category", "")

        templates = [
            f"Quick idea for {biz_name}'s online presence",
            f"Free website mockup for {biz_name}?",
            f"{biz_name} + a modern website = more customers",
            f"Saw {biz_name} - had an idea to share",
            f"5-min chat about {biz_name}'s website?",
        ]

        return {
            "subject": templates[0],
            "alternatives": templates[1:],
        }

    # ------------------------------------------------------------------ #
    #  Enrichment                                                         #
    # ------------------------------------------------------------------ #

    def _enrich_hunter(self, payload: dict, ctx: dict) -> dict:
        """Look up emails for a business domain via Hunter.io."""
        domain = payload.get("domain", "")
        if not domain:
            return {"error": "No domain provided"}

        if not self._hunter_key:
            return {"error": "HUNTER_API_KEY not set", "email": ""}

        url = f"https://api.hunter.io/v2/domain-search?domain={domain}&api_key={self._hunter_key}"
        result = subprocess.run(
            ["curl", "-s", url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", timeout=15,
        )
        if result.returncode != 0:
            return {"error": f"curl failed: {result.stderr}"}

        data = json.loads(result.stdout)
        emails = data.get("data", {}).get("emails", [])

        best = None
        for e in emails:
            position = (e.get("position", "") or "").lower()
            if any(role in position for role in ["ceo", "founder", "owner", "director"]):
                best = e
                break
        if not best and emails:
            best = emails[0]

        if best:
            return {
                "email": best.get("value", ""),
                "first_name": best.get("first_name", ""),
                "last_name": best.get("last_name", ""),
                "position": best.get("position", ""),
                "confidence": best.get("confidence", 0),
                "all_emails": [e.get("value") for e in emails[:5]],
            }
        return {"email": "", "all_emails": [], "confidence": 0}

    # ------------------------------------------------------------------ #
    #  Lead scoring                                                       #
    # ------------------------------------------------------------------ #

    def _score_lead(self, payload: dict, ctx: dict) -> dict:
        """Score a business as a lead (0-100)."""
        biz = payload.get("business", {})
        score = 0
        reasons = []

        # Has email → big boost
        email = biz.get("email") or biz.get("enrichment", {}).get("email", "")
        if email:
            score += 35
            reasons.append("has_email")

        # Has phone
        if biz.get("phone"):
            score += 15
            reasons.append("has_phone")

        # Has website (they need upgrading)
        if biz.get("website"):
            score += 10
            reasons.append("has_website")

        # Category bonuses
        high_value = ["professional", "healthcare", "technology"]
        cat = biz.get("category", "")
        if any(h in cat.lower() for h in high_value):
            score += 15
            reasons.append("high_value_category")

        # Has address (local business)
        if biz.get("address"):
            score += 10
            reasons.append("has_address")

        # Has opening hours (active business)
        tags = biz.get("tags", {})
        if tags.get("opening_hours"):
            score += 5
            reasons.append("has_hours")

        # Has social media
        if any(k.startswith("contact:") for k in tags):
            score += 10
            reasons.append("has_social")

        return {"score": min(score, 100), "reasons": reasons, "tier": "hot" if score >= 60 else "warm" if score >= 30 else "cold"}

    # ------------------------------------------------------------------ #
    #  Summarisation                                                       #
    # ------------------------------------------------------------------ #

    def _summarise_business(self, payload: dict, ctx: dict) -> dict:
        """Create a structured summary of a business."""
        biz = payload.get("business", {})
        email = biz.get("email") or biz.get("enrichment", {}).get("email", "")
        enrichment = biz.get("enrichment", {})

        lines = []
        lines.append(f"**{biz.get('name', 'Unknown')}**")
        if biz.get("category"):
            lines.append(f"Category: {biz['category']}")
        if biz.get("address"):
            lines.append(f"Address: {biz['address']}")
        if email:
            contact_info = f"Email: {email}"
            if enrichment.get("position"):
                contact_info += f" ({enrichment['position']})"
            lines.append(contact_info)
        if biz.get("phone"):
            lines.append(f"Phone: {biz['phone']}")
        if biz.get("website"):
            lines.append(f"Website: {biz['website']}")
        if biz.get("opening_hours"):
            lines.append(f"Hours: {biz['opening_hours']}")

        return {
            "summary": "\n".join(lines),
            "name": biz.get("name", ""),
            "has_email": bool(email),
            "has_phone": bool(biz.get("phone")),
            "has_website": bool(biz.get("website")),
        }

    # ------------------------------------------------------------------ #
    #  Lead ranking                                                       #
    # ------------------------------------------------------------------ #

    def _rank_leads(self, payload: dict, ctx: dict) -> dict:
        """Rank a list of businesses by lead quality."""
        businesses = payload.get("businesses", [])

        scored = []
        for biz in businesses:
            result = self._score_lead({"business": biz}, ctx)
            scored.append({"business": biz, "score": result["score"], "tier": result["tier"]})

        scored.sort(key=lambda x: -x["score"])

        return {
            "ranked": scored,
            "hot": [s for s in scored if s["tier"] == "hot"],
            "warm": [s for s in scored if s["tier"] == "warm"],
            "cold": [s for s in scored if s["tier"] == "cold"],
        }

    def _extract_icebreaker(self, payload: dict, ctx: dict) -> dict:
        """Extract a personalised icebreaker from business data."""
        biz = payload.get("business", {})
        tags = biz.get("tags", {})
        name = biz.get("name", "")

        icebreakers = []

        if tags.get("opening_hours"):
            icebreakers.append(f"I see you're open {tags['opening_hours']} — that's a lot of dedication!")

        if tags.get("cuisine"):
            icebreakers.append(f"Your {tags['cuisine']} cuisine looks amazing!")

        if tags.get("description"):
            desc = tags["description"][:100]
            icebreakers.append(f"I loved reading about: \"{desc}\"")

        if tags.get("brand"):
            icebreakers.append(f"I'm familiar with the {tags['brand']} brand — great quality.")

        if not icebreakers:
            icebreakers.append(f"I came across {name} while researching businesses in the area.")

        return {"icebreakers": icebreakers, "best": icebreakers[0]}
