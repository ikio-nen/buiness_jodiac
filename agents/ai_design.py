#!/usr/bin/env python3
"""AI Design agent — uses Gemini to generate websites, emails, and PDF content.

Upgrades the template-based agents with actual AI generation.
Falls back to template agents if Gemini is not configured.
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import BaseAgent, Complexity, Task, TaskResult


class AIDesignAgent(BaseAgent):
    """AI-powered agent for design tasks: websites, emails, proposals."""

    def __init__(self):
        super().__init__(model="gemini-ai")
        self.supported_tasks = {
            "ai_generate_website", "ai_draft_email",
            "ai_generate_proposal", "ai_generate_pdf_content",
        }

    @property
    def agent_id(self) -> str:
        return "ai_design"

    @property
    def max_complexity(self) -> Complexity:
        return Complexity.HEAVY

    def _execute(self, task: Task) -> Any:
        from . import ai_engine
        if not ai_engine.is_available():
            return self._fallback(task)
        handlers = {
            "ai_generate_website":    self._generate_website,
            "ai_draft_email":         self._draft_email,
            "ai_generate_proposal":   self._generate_proposal,
            "ai_generate_pdf_content": self._generate_pdf_content,
        }
        handler = handlers.get(task.name)
        if handler is None:
            raise ValueError(f"AIDesignAgent has no handler for '{task.name}'")
        return handler(task.payload, task.context)

    def _fallback(self, task: Task) -> dict:
        """Fall back to template agents when Gemini is unavailable."""
        from .medium import MediumAgent
        from .heavy import HeavyAgent
        fallback_map = {
            "ai_draft_email": ("draft_email", MediumAgent()),
            "ai_generate_website": ("generate_website", HeavyAgent()),
        }
        mapped_name, agent = fallback_map.get(task.name, (None, None))
        if mapped_name:
            fb_task = Task(
                id=task.id, name=mapped_name,
                complexity=agent.max_complexity,
                payload=task.payload, context=task.context,
            )
            result = agent.handle(fb_task)
            if result.success:
                result.output["ai_powered"] = False
                return result.output
        return {"error": "AI unavailable and no fallback", "ai_powered": False}

    # ── Website Generation ─────────────────────────────────────────────

    def _generate_website(self, payload: dict, ctx: dict) -> dict:
        from . import ai_engine
        from .config import SITES_DIR

        biz = payload.get("business", payload)
        name = biz.get("name", "Business")
        category = biz.get("category", "")
        address = biz.get("address", "")
        phone = biz.get("phone", "")
        email = biz.get("email", "")
        hours = biz.get("opening_hours", "")

        prompt = f"""Generate a complete, modern, single-page HTML website for this business.
Requirements:
- Professional design with CSS (no external files, all inline/embedded)
- Hero section with business name and category
- Contact section with phone, email, address, hours
- Mobile responsive
- Use the color scheme based on category: {category}
- Clean, modern typography (system fonts)
- NO JavaScript needed
- Output ONLY the complete HTML document, nothing else

Business details:
- Name: {name}
- Category: {category}
- Address: {address}
- Phone: {phone}
- Email: {email}
- Hours: {hours}
"""

        html = ai_engine.generate(
            prompt=prompt,
            system="You are an expert web designer. Generate clean, modern, professional HTML/CSS.",
            temperature=0.5,
        )

        if not html:
            return {"error": "AI generation failed", "ai_powered": False}

        # Clean up: strip markdown fences
        html = html.strip()
        if html.startswith("```"):
            lines = html.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            html = "\n".join(lines)

        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        SITES_DIR.mkdir(exist_ok=True)
        output_path = SITES_DIR / f"{slug}.html"
        output_path.write_text(html, encoding="utf-8")

        return {
            "path": str(output_path),
            "slug": slug,
            "name": name,
            "size_bytes": len(html.encode("utf-8")),
            "ai_powered": True,
        }

    # ── Email Drafting ─────────────────────────────────────────────────

    def _draft_email(self, payload: dict, ctx: dict) -> dict:
        from . import ai_engine

        biz_name = payload.get("business_name", "the business")
        contact_name = payload.get("contact_name", "")
        category = payload.get("category", "")
        sender_name = ctx.get("sender_name", "The Team")

        # Build learning-enhanced prompt
        learning_ctx = payload.get("learning_context", "")
        learning_section = ""
        research_section = ""
        if learning_ctx:
            # Check if research data is included
            if "Research on this specific business" in learning_ctx:
                parts = learning_ctx.split("--- Research on this specific business ---")
                industry_ctx = parts[0].strip() if parts[0].strip() else ""
                research_ctx = parts[1].strip() if len(parts) > 1 else ""
                if industry_ctx:
                    learning_section = f"\n\nWhat we've learned about {category} businesses:\n{industry_ctx}\n\nUse this knowledge to make the email more relevant and effective."
                if research_ctx:
                    research_section = f"\n\nResearch on {biz_name} specifically:\n{research_ctx}\n\nUse these specific insights to personalize the email. Reference their rating, strengths, or improvement opportunities."
            else:
                learning_section = f"\n\nWhat we've learned about {category} businesses:\n{learning_ctx}\n\nUse this knowledge to make the email more relevant and effective."

        # Get business profile for personalized emails
        from .config import get_business_context
        biz_profile = get_business_context()
        profile_section = ""
        if biz_profile:
            profile_section = f"\n\nAbout our business:\n{biz_profile}\n\nTailor the email to what we actually sell and who we target."

        # Get industry insights for this business type
        from .industry_learner import build_industry_context
        industry_ctx = build_industry_context(category)
        industry_section = ""
        if industry_ctx:
            industry_section = f"\n\nIndustry insights:\n{industry_ctx}\n\nUse the pain points and approach in your email."

        prompt = f"""Write a short, professional cold-outreach email to {contact_name or 'a business owner'} 
at {biz_name} ({category} business).

Goal: Reach out with a relevant offer based on what we sell. Keep it:
- Under 150 words
- Friendly but professional
- One clear call to action (quick 5-min chat)
- Personalised to their industry ({category})
- Reference what we actually sell and why they need it{learning_section}{research_section}{profile_section}{industry_section}

From: {sender_name}

Return ONLY a JSON object with these keys:
{{"subject": "...", "body": "...", "greeting": "...", "hook": "..."}}"""

        result = ai_engine.generate_json(prompt)
        if result and "subject" in result:
            result["to"] = payload.get("email", "")
            result["ai_powered"] = True
            return result

        return {"error": "AI generation failed", "ai_powered": False}

    # ── Proposal Content ───────────────────────────────────────────────

    def _generate_proposal(self, payload: dict, ctx: dict) -> dict:
        from . import ai_engine

        biz = payload.get("business", payload)
        name = biz.get("name", "Business")
        category = biz.get("category", "")

        prompt = f"""Generate a professional website proposal for {name} ({category}).

Create a concise proposal with these sections:
1. Understanding Your Business (2-3 sentences about their needs)
2. What We Propose (5-7 specific features tailored to {category})
3. Why You Need This (3 compelling statistics)
4. Pricing (3 tiers: Starter $499, Professional $999, Premium $1,999)
5. Next Steps (3 clear steps)

Return ONLY a JSON object:
{{"title": "...", "sections": [{{"heading": "...", "content": "..."}}], "sender_name": "..."}}"""

        result = ai_engine.generate_json(prompt)
        if result and "sections" in result:
            result["ai_powered"] = True
            return result
        return {"error": "AI generation failed", "ai_powered": False}

    # ── PDF Content ────────────────────────────────────────────────────

    def _generate_pdf_content(self, payload: dict, ctx: dict) -> dict:
        from . import ai_engine

        biz = payload.get("business", payload)
        name = biz.get("name", "Business")
        category = biz.get("category", "")

        prompt = f"""Generate PDF proposal content for {name}, a {category} business.

Return ONLY JSON with:
{{"understanding": "2-3 sentences about their business needs", 
  "features": ["feature 1", "feature 2", ...],
  "reasons": ["stat/reason 1", "stat/reason 2", ...],
  "pricing": [{{"tier": "Starter - $499", "desc": "..."}}, ...],
  "next_steps": ["step 1", "step 2", "step 3"]}}"""

        result = ai_engine.generate_json(prompt)
        if result and "understanding" in result:
            result["ai_powered"] = True
            return result
        return {"error": "AI generation failed", "ai_powered": False}
