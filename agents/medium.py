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

# ── Goal-specific copy ──────────────────────────────────────────────
# The pitch changes with what this search is selling, so hooks and subjects are
# selected by goal. {biz} and {product} are filled in per business.

HOOKS_BY_GOAL = {
    "cad_licensing": {
        "training": "How does {biz} license the software when a new batch starts? We supply genuine {product} seat by seat, so a CAD batch can start the moment students enrol.",
        "college": "Does {biz} license a seat for every lab machine, or just the main lab? We quote the whole department at education pricing.",
        "polytechnic": "Across {biz}'s trades, how many drafting seats are being licensed this year? We can cover all of them on one quotation.",
        "school": "If {biz} runs a computer stream, keeping those lab machines on real licences is the usual headache. We cover a whole classroom at per-lab pricing.",
        "university": "How does {biz} manage licences across departments? We handle volume licensing and the compliance paperwork that comes with it.",
        "computer": "How is the lab at {biz} licensed for software the students actually need? We supply genuine {product} for the machines you already have.",
        "*": "Most institutes we work with were running trial software until it expired mid-session. For {biz}, we would supply genuine {product} licensed for every machine in the lab.",
    },
    "website": {
        "school": "Parents compare {biz} with three other institutes before they ever call. We build the site that makes that comparison come out in your favour.",
        "college": "Admissions, results and enquiries all start online. {biz} should own that first impression instead of leaving it to a directory listing.",
        "clinic": "When someone searches for a clinic near them, {biz} should be the first result with hours, doctors and a booking form on it.",
        "hospital": "Patients check online before they call. A clear, current site for {biz} turns those searches into appointments.",
        "pharmacy": "People near {biz} search for what you stock every day. A simple site puts your shelves in front of them.",
        "hotel": "Right now {biz}'s rooms are only bookable through platforms that take a cut. A site of your own takes direct bookings.",
        "restaurant": "Your menu, timings and location should live somewhere you own - not only on someone else's listing.",
        "cafe": "Your menu, timings and photos deserve a home of your own. We build a simple site for {biz} that shows up in local search.",
        "shop": "Customers within a few kilometres of {biz} search for exactly what you stock. A site puts that stock in front of them.",
        "*": "I took a look at how {biz} shows up online and saw a few things worth fixing. We build the site that turns those searches into customers.",
    },
    "custom": {
        "*": "I came across {biz} and thought {product} might be worth a short conversation.",
    },
}

SUBJECTS_BY_GOAL = {
    "cad_licensing": (
        "{product} for {biz}'s lab",
        "Licensed {product} - institutional pricing",
        "Quick question about {biz}'s computer lab",
        "Genuine {product} for {biz}",
        "5-min chat about lab licensing at {biz}?",
    ),
    "website": (
        "A website for {biz}",
        "Quick idea for {biz}'s online presence",
        "Found {biz} online - a thought on your site",
        "{biz} + a modern website = more enquiries",
        "5-min chat about {biz}'s website?",
    ),
    "custom": (
        "{product} for {biz}",
        "Quick idea for {biz}",
        "Saw {biz} - had an idea to share",
        "5-min chat about {product}?",
    ),
}


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
        tone = payload.get("tone", "professional")

        # What this search sells drives every line of copy below. The goal is
        # resolved from the action payload, not assumed from the account profile.
        from .icp import target_profile, product_line, resolve_goal
        profile = target_profile()
        goal = resolve_goal(explicit=payload.get("goal", ""))
        product = product_line(goal)

        greeting = f"Hi {contact_name}," if contact_name else f"Hi there,"

        # Vertical hook, enhanced by learning context if we have any.
        template = (HOOKS_BY_GOAL.get(goal["key"]) or HOOKS_BY_GOAL["custom"])
        raw = template.get(category) or template["*"]
        hook = raw.format(biz=biz_name, product=product)
        learning_ctx = payload.get("learning_context", "")
        if learning_ctx:
            # First try: research-specific hook ("Suggested opening: ...")
            for line in learning_ctx.split("\n"):
                if "suggested opening:" in line.lower():
                    research_hook = line.split(":", 1)[1].strip()
                    if len(research_hook) > 10:
                        hook = research_hook
                        break
            # Second try: learned hooks from past sessions
            if hook == raw.format(biz=biz_name, product=product) and "best hooks" in learning_ctx:
                for line in learning_ctx.split("\n"):
                    if line.strip().startswith('- "'):
                        learned_hook = line.strip().strip('- "').rstrip('"')
                        if len(learned_hook) > 10:
                            hook = learned_hook.format(biz_name=biz_name) if '{biz_name}' in learned_hook else f"{learned_hook} That's why I thought of {biz_name}."
                            break

        value_prop = (profile.get("value_proposition") or profile.get("what_makes_special")
                      or f"{product} supplied directly, with support included.")

        # Per-business brain memory (rating, gaps, past contact): cite what we
        # know about THIS business, and follow up if we already emailed them.
        brain_facts = {}
        in_brain = False
        for line in learning_ctx.split("\n"):
            if "--- Brain memory" in line:
                in_brain = True
                continue
            if in_brain:
                s = line.strip()
                if s.startswith("---"):
                    break
                if ":" in s:
                    k, v = s.split(":", 1)
                    brain_facts[k.strip().lower()] = v.strip()

        memory_lines = []
        rating = brain_facts.get("google rating", "").split(" (")[0]
        if rating:
            memory_lines.append(f"I see {biz_name} holds a {rating} rating on Google - clearly a business people trust.")
        gaps = brain_facts.get("gaps", "")
        if gaps:
            first_gap = gaps.split(";")[0].strip().rstrip(".")
            memory_lines.append(f"One thing I noticed: {first_gap.lower()} - that's exactly what we help with.")
        memory_section = ("\n" + "\n".join(memory_lines) + "\n") if memory_lines else ""

        cta = "Would you be open to a quick 5-minute chat this week?"
        if brain_facts.get("last interaction", "").startswith("emailed"):
            cta = "I reached out recently and wanted to follow up - would a quick 5-minute chat this week work?"

        # Get industry pain points for a more relevant email
        from .industry_learner import get_or_research_industry
        industry = get_or_research_industry(category, product=product)
        pain_point = industry.get("pain_points", [""])[0] if industry.get("pain_points") else ""
        pain_section = f"\nI understand that {pain_point.lower()}" if pain_point else ""

        body = f"""{greeting}

{hook}{pain_section}

We supply {product} for institutions. {value_prop}{memory_section}
{cta}

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

        from .icp import product_line, resolve_goal
        goal = resolve_goal(explicit=payload.get("goal", ""))
        product = product_line(goal)
        raws = SUBJECTS_BY_GOAL.get(goal["key"]) or SUBJECTS_BY_GOAL["custom"]
        templates = [t.format(biz=biz_name, product=product) for t in raws]

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
