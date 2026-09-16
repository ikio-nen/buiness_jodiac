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

    # One capped web search per business: short timeout, truncated results.
    _WEB_SEARCH_MAX_CHARS = 900

    def _draft_email(self, payload: dict, ctx: dict) -> dict:
        """Draft one email with every context layer we have.

        Raises on failure so the orchestrator's ai_* -> template fallback
        engages -- returning an {"error": ...} dict would flow into the
        drafts list as a fake success (handle() marks any dict a success).
        """
        from . import ai_engine

        biz_name = payload.get("business_name", "the business")
        contact_name = payload.get("contact_name", "")
        category = payload.get("category", "")
        sender_name = ctx.get("sender_name", "The Team")

        from .config import get_business_context, get_email_tone
        tone = get_email_tone() or "professional"

        # Learning context: research + brain memory, assembled by the workflow
        # with clear section markers.
        learning_ctx = payload.get("learning_context", "")
        learning_section = ""
        if learning_ctx:
            learning_section = (f"\n\nEverything we know about this business:\n{learning_ctx}\n"
                                "Reference their rating, strengths or gaps naturally -- "
                                "follow up if we've emailed them before.")

        # What this email sells. The goal changes per search, so it is resolved
        # here rather than assumed from the account profile.
        from .icp import resolve_goal, product_line
        goal = resolve_goal(explicit=payload.get("goal", ""))
        product = product_line(goal)

        biz_profile = get_business_context()
        # The saved product would contradict the goal on a search selling
        # something else, so that one line is replaced, not left to argue.
        biz_profile = "\n".join(
            line for line in (biz_profile or "").splitlines()
            if not line.startswith("What we sell:"))
        if product:
            biz_profile = f"What we sell on this search: {product}\n{biz_profile}".strip()
        profile_section = ""
        if biz_profile:
            profile_section = f"\n\nAbout our business:\n{biz_profile}\nTailor the email to what we actually sell and who we target."

        from .icp import context as icp_context
        from .industry_learner import build_industry_context
        industry_ctx = build_industry_context(category, product=product)
        industry_section = ""
        if industry_ctx:
            industry_section = f"\n\nIndustry insights:\n{industry_ctx}\nUse the pain points and approach in your email."

        icp_ctx = icp_context(goal)
        icp_section = ""
        if icp_ctx:
            icp_section = (f"\n\n{icp_ctx}\nWrite for exactly this customer, "
                           f"selling {product}. Never pitch anything outside it.")

        # One capped web search for public reputation -- best-effort.
        try:
            from .agent_team import web_search
            web_snippet = (web_search(
                f"{biz_name} {category} reviews reputation", timeout=10)
                or "")[:self._WEB_SEARCH_MAX_CHARS]
        except Exception:
            web_snippet = ""
        web_section = ""
        if web_snippet:
            web_section = f"\n\nRecent public web results about them:\n{web_snippet}\nUse anything concrete (news, reputation, offerings) -- ignore anything irrelevant."

        prompt = f"""Write a short, professional cold-outreach email to {contact_name or 'a business owner'} at {biz_name} ({category} business).

Goal: sell {product} to them, this search. Keep it:
- Under 150 words
- {tone} tone
- One clear call to action (quick 5-min chat)
- Specific to what we sell on this search ({product}) and why THIS business needs it
- Reference what we actually sell and why they need it{profile_section}{industry_section}{icp_section}{learning_section}{web_section}

From: {sender_name}

Return ONLY a JSON object with these keys:
{{"subject": "...", "body": "...", "greeting": "...", "hook": "..."}}"""

        result = ai_engine.generate_json(prompt)
        if not (result and result.get("subject") and result.get("body")):
            raise ValueError("AI email generation failed: empty or malformed response")

        result["to"] = payload.get("email", "")
        result["ai_powered"] = True
        return result

    # ── Proposal Content ───────────────────────────────────────────────

    def _generate_proposal(self, payload: dict, ctx: dict) -> dict:
        from . import ai_engine

        biz = payload.get("business", payload)
        name = biz.get("name", "Business")
        category = biz.get("category", "")

        from .icp import product_line, resolve_goal
        goal = resolve_goal(explicit=payload.get("goal", ""))
        product = product_line(goal)
        prompt = f"""Generate a proposal to supply {product} to {name}, a {category} business.

Create a concise proposal with these sections:
1. Understanding Their Requirement (2-3 sentences about what they need from {product})
2. What We Propose (5-7 specifics about the offer)
3. Why This Matters (4 concrete reasons they would switch - no invented statistics)
4. Packages (3 tiers, priced on quotation)
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
