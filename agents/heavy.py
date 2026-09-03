#!/usr/bin/env python3
"""Heavy agent — handles the most complex, multi-step tasks.

Covers:
  • Full website generation from business data
  • Deep competitive analysis
  • Multi-step outreach strategy planning
  • Report / proposal generation
  • Data pipeline orchestration with branching logic
"""

import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import BaseAgent, Complexity, Task

from .config import SITES_DIR as _CFG_SITES_DIR
REPORTS_DIR = Path(__file__).parent.parent


class HeavyAgent(BaseAgent):
    """Top-tier agent for the most demanding tasks.

    Uses template engines and multi-step reasoning to produce
    complete deliverables — websites, reports, strategies.
    """

    def __init__(self):
        super().__init__(model="template-engine+v2")
        self.supported_tasks = {
            "generate_website", "deep_analysis",
            "generate_full_report",
        }

    @property
    def agent_id(self) -> str:
        return "heavy"

    @property
    def max_complexity(self) -> Complexity:
        return Complexity.HEAVY

    # ------------------------------------------------------------------ #
    #  Task dispatch                                                      #
    # ------------------------------------------------------------------ #

    def _execute(self, task: Task) -> Any:
        handlers = {
            "generate_website":       self._generate_website,
            "deep_analysis":          self._deep_analysis,
            "generate_full_report":   self._generate_full_report,
        }
        handler = handlers.get(task.name)
        if handler is None:
            raise ValueError(f"HeavyAgent has no handler for task '{task.name}'")
        return handler(task.payload, task.context)

    # ------------------------------------------------------------------ #
    #  Website generation                                                 #
    # ------------------------------------------------------------------ #

    def _generate_website(self, payload: dict, ctx: dict) -> dict:
        """Generate a complete one-page website for a business.

        Accepts flat business data at the top level (matching how the
        orchestrator's run() passes payload) with optional overrides.
        """
        # Accept both flat (orchestrator) and nested (legacy) payloads
        biz = payload.get("business", payload)
        template = payload.get("template", "modern")
        color_scheme = payload.get("color_scheme", "auto")

        name = biz.get("name", "Business")
        category = biz.get("category", "")
        address = biz.get("address", "")
        phone = biz.get("phone", "")
        email = biz.get("email") or biz.get("enrichment", {}).get("email", "")
        hours = biz.get("opening_hours", "")
        tags = biz.get("tags", {})

        # Auto-detect color scheme from category
        if color_scheme == "auto":
            color_scheme = self._auto_color(category)

        # Generate slug
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

        # Build HTML
        html = self._build_html(
            name=name, category=category, address=address,
            phone=phone, email=email, hours=hours,
            description=tags.get("description", ""),
            color_scheme=color_scheme, template=template,
        )

        # Save to file
        _CFG_SITES_DIR.mkdir(exist_ok=True)
        output_path = _CFG_SITES_DIR / f"{slug}.html"
        output_path.write_text(html, encoding="utf-8")

        return {
            "path": str(output_path),
            "slug": slug,
            "name": name,
            "size_bytes": len(html.encode("utf-8")),
            "template": template,
            "color_scheme": color_scheme,
        }

    def _auto_color(self, category: str) -> dict:
        """Pick a color palette based on business category."""
        palettes = {
            "food_and_drink":  {"primary": "#D32F2F", "accent": "#FF8A65", "bg": "#FFF8F0"},
            "retail":          {"primary": "#7B1FA2", "accent": "#CE93D8", "bg": "#F8F0FF"},
            "healthcare":      {"primary": "#0288D1", "accent": "#81D4FA", "bg": "#F0F8FF"},
            "professional":    {"primary": "#37474F", "accent": "#90A4AE", "bg": "#F5F5F5"},
            "fitness":         {"primary": "#388E3C", "accent": "#81C784", "bg": "#F0FFF0"},
            "technology":      {"primary": "#1565C0", "accent": "#64B5F6", "bg": "#F0F4FF"},
            "home_services":   {"primary": "#E65100", "accent": "#FFB74D", "bg": "#FFF8E1"},
            "education":       {"primary": "#6A1B9A", "accent": "#BA68C8", "bg": "#F8F0FF"},
        }
        cat_lower = category.lower() if category else ""
        for key, palette in palettes.items():
            if key in cat_lower:
                return palette
        return {"primary": "#1976D2", "accent": "#64B5F6", "bg": "#FAFAFA"}

    def _build_html(self, name, category, address, phone, email, hours,
                    description, color_scheme, template) -> str:
        """Build a complete HTML page for the business."""
        c = color_scheme

        # Escape all user data to prevent HTML injection
        e = html.escape
        safe_name = e(str(name))
        safe_category = e(str(category))
        safe_address = e(str(address))
        safe_phone = e(str(phone))
        safe_email = e(str(email))
        safe_hours = e(str(hours))
        safe_desc = e(str(description))

        contact_items = []
        if phone:
            contact_items.append(f'<a href="tel:{safe_phone}" class="contact-link">📞 {safe_phone}</a>')
        if email:
            contact_items.append(f'<a href="mailto:{safe_email}" class="contact-link">✉️ {safe_email}</a>')
        if address:
            maps_q = address.replace(" ", "+")
            safe_maps_q = e(maps_q)
            contact_items.append(f'<a href="https://maps.google.com/?q={safe_maps_q}" target="_blank" class="contact-link">📍 {safe_address}</a>')
        if hours:
            contact_items.append(f'<div class="contact-link">🕐 {safe_hours}</div>')

        contact_html = "\n            ".join(contact_items)
        about_html = f"<div class='section'><h2>About Us</h2><p>{safe_desc}</p></div>" if description else ""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{safe_name}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: {c['bg']}; color: #333; }}
        .hero {{
            background: linear-gradient(135deg, {c['primary']}, {c['accent']});
            color: white; text-align: center; padding: 80px 20px;
        }}
        .hero h1 {{ font-size: 2.5rem; margin-bottom: 10px; }}
        .hero .tagline {{ font-size: 1.2rem; opacity: 0.9; }}
        .container {{ max-width: 800px; margin: 0 auto; padding: 40px 20px; }}
        .section {{ background: white; border-radius: 12px; padding: 30px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
        .section h2 {{ color: {c['primary']}; margin-bottom: 15px; font-size: 1.4rem; }}
        .contact-link {{ display: block; padding: 10px 0; color: #555; text-decoration: none; font-size: 1rem; border-bottom: 1px solid #eee; }}
        .contact-link:last-child {{ border-bottom: none; }}
        .contact-link:hover {{ color: {c['primary']}; }}
        .footer {{ text-align: center; padding: 30px; color: #999; font-size: 0.85rem; }}
        @media (max-width: 600px) {{ .hero h1 {{ font-size: 1.8rem; }} }}
    </style>
</head>
<body>
    <div class="hero">
        <h1>{safe_name}</h1>
        <p class="tagline">{safe_category or "Welcome"}</p>
    </div>
    <div class="container">
        {about_html}
        <div class="section">
            <h2>Contact Us</h2>
            {contact_html}
        </div>
    </div>
    <div class="footer">
        &copy; {datetime.now().year} {safe_name}. All rights reserved.
    </div>
</body>
</html>"""

    # ------------------------------------------------------------------ #
    #  Deep analysis                                                      #
    # ------------------------------------------------------------------ #

    def _deep_analysis(self, payload: dict, ctx: dict) -> dict:
        """Perform deep analysis on a set of businesses."""
        businesses = payload.get("businesses", [])

        from .medium import MediumAgent
        from .lightweight import LightweightAgent
        medium = MediumAgent()
        light = LightweightAgent()

        # Category distribution
        from .base import Task as T, Complexity as C
        count_result = light.handle(T("c1", "summarise_counts", C.LIGHT, {"businesses": businesses}))

        # Lead scoring
        ranked_result = medium._rank_leads({"businesses": businesses}, ctx)

        # Contact completeness
        complete_profiles = 0
        partial_profiles = 0
        no_contact = 0

        for biz in businesses:
            has_email = bool(biz.get("email") or biz.get("enrichment", {}).get("email"))
            has_phone = bool(biz.get("phone"))
            has_website = bool(biz.get("website"))
            has_address = bool(biz.get("address"))

            fields = sum([has_email, has_phone, has_website, has_address])
            if fields >= 3:
                complete_profiles += 1
            elif fields >= 1:
                partial_profiles += 1
            else:
                no_contact += 1

        # Opportunity sizing
        hot_count = len(ranked_result.get("hot", []))
        conversion_estimate = max(1, int(hot_count * 0.15))

        return {
            "total": len(businesses),
            "category_breakdown": count_result.output.get("by_category", {}),
            "contact_rate": count_result.output.get("contact_rate", 0),
            "lead_tiers": {
                "hot": hot_count,
                "warm": len(ranked_result.get("warm", [])),
                "cold": len(ranked_result.get("cold", [])),
            },
            "profile_completeness": {
                "complete": complete_profiles,
                "partial": partial_profiles,
                "no_contact": no_contact,
            },
            "opportunity": {
                "hot_leads": hot_count,
                "estimated_conversions": conversion_estimate,
                "estimated_revenue": conversion_estimate * 999,  # avg $999/site
            },
            "recommendation": self._generate_recommendation(hot_count, complete_profiles, len(businesses)),
        }

    def _generate_recommendation(self, hot: int, complete: int, total: int) -> str:
        """Generate a strategic recommendation based on analysis."""
        if hot >= 10:
            return (f"Strong pipeline with {hot} hot leads. Prioritise immediate outreach "
                    f"to hot leads. Target the {complete} complete profiles first for "
                    f"fastest results.")
        elif hot >= 5:
            return (f"Moderate pipeline with {hot} hot leads. Focus on enriching "
                    f"warm leads to move them to hot. Consider a drip campaign for "
                    f"the complete profiles.")
        elif total > 0:
            return (f"Pipeline needs enrichment - only {hot} hot leads out of {total}. "
                    f"Run Hunter.io enrichment on the top {min(50, total)} businesses "
                    f"to find more contact details.")
        return "No businesses to analyse. Run discovery first."

    # ------------------------------------------------------------------ #
    #  Full report generation                                             #
    # ------------------------------------------------------------------ #

    def _generate_full_report(self, payload: dict, ctx: dict) -> dict:
        """Generate a comprehensive outreach report."""
        businesses = payload.get("businesses", [])
        results = payload.get("results", {})

        sections = []
        sections.append(f"# Outreach Report - {datetime.now().strftime('%B %d, %Y')}\n")

        # Summary
        sections.append("## Executive Summary\n")
        sections.append(f"- **Total businesses discovered:** {len(businesses)}")
        sections.append(f"- **Emails found:** {results.get('emails_found', 'N/A')}")
        sections.append(f"- **Websites generated:** {results.get('sites_generated', 'N/A')}")
        sections.append(f"- **Emails sent:** {results.get('emails_sent', 'N/A')}\n")

        # Top leads
        if businesses:
            sections.append("## Top 10 Leads\n")
            sections.append("| # | Name | Category | Email | Phone |")
            sections.append("|---|------|----------|-------|-------|")
            for i, biz in enumerate(businesses[:10], 1):
                email = biz.get("email") or biz.get("enrichment", {}).get("email", "N/A")
                phone = biz.get("phone", "N/A") or "N/A"
                sections.append(f"| {i} | {biz.get('name', '?')} | {biz.get('category', '?')} | {email} | {phone} |")
            sections.append("")

        # Recommendations
        sections.append("## Recommendations\n")
        sections.append("1. Follow up with hot leads within 24 hours")
        sections.append("2. Enrich warm leads with additional data")
        sections.append("3. Send second followup to cold leads after 5 days")
        sections.append("4. Generate personalised websites for top 10 leads\n")

        report = "\n".join(sections)

        # Save report
        report_path = REPORTS_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        report_path.write_text(report, encoding="utf-8")

        return {
            "report": report,
            "path": str(report_path),
            "sections": len(sections),
        }


