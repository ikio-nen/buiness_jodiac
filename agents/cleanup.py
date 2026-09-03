#!/usr/bin/env python3
"""Cleanup: Generate a single PDF of chosen businesses, then delete scraped data.

Flow:
  1. User selects businesses (or uses session data)
  2. Generate ONE PDF with all business details
  3. Warn: "Rest businesses data will be deleted"
  4. Auto-delete: sites/*.html, individual pdfs, old session data
  5. Keep: knowledge_base/, config.json, the summary PDF
"""
import json
import os
import shutil
from pathlib import Path
from datetime import datetime

from agents.config import OUTPUT_DIR, SITES_DIR, PDF_DIR, KB_DIR, SESSIONS_DIR


def generate_business_pdf(businesses: list[dict], session_id: str = "") -> str:
    """Generate a single PDF with details of the chosen businesses.

    Args:
        businesses: List of business dicts with name, category, address, etc.
        session_id: Optional session ID for the report title

    Returns:
        Path to the generated PDF
    """
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # ── Title page ───────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 20, "Business Outreach Report", ln=True, align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 10, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align="C")
    if session_id:
        pdf.cell(0, 10, f"Session: {session_id}", ln=True, align="C")
    pdf.cell(0, 10, f"Total Businesses: {len(businesses)}", ln=True, align="C")
    pdf.ln(20)

    # ── Business details ─────────────────────────────────────────────
    for i, biz in enumerate(businesses, 1):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, f"{i}. {biz.get('name', 'Unknown')}", ln=True)
        pdf.set_font("Helvetica", "", 11)

        # Basic info
        fields = [
            ("Category", biz.get("category", "N/A")),
            ("Address", biz.get("address", "N/A")),
            ("Phone", biz.get("phone", "N/A")),
            ("Email", biz.get("email") or biz.get("enrichment", {}).get("email", "N/A")),
            ("Website", biz.get("website", "None (no site)")),
            ("Hours", biz.get("opening_hours", "N/A")),
        ]

        for label, value in fields:
            if value and value != "N/A":
                pdf.cell(0, 8, f"  {label}: {value}", ln=True)

        # Tags
        tags = biz.get("tags", {})
        if tags:
            tag_str = ", ".join(f"{k}: {v}" for k, v in tags.items() if v)
            if tag_str:
                pdf.cell(0, 8, f"  Tags: {tag_str}", ln=True)

        # Enrichment data
        enrich = biz.get("enrichment", {})
        if enrich:
            pdf.ln(5)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, "  Enrichment Data:", ln=True)
            pdf.set_font("Helvetica", "", 10)
            if enrich.get("first_name"):
                pdf.cell(0, 7, f"    Contact: {enrich.get('first_name', '')} {enrich.get('last_name', '')}", ln=True)
            if enrich.get("position"):
                pdf.cell(0, 7, f"    Position: {enrich['position']}", ln=True)
            if enrich.get("confidence"):
                pdf.cell(0, 7, f"    Confidence: {enrich['confidence']}%", ln=True)
            all_emails = enrich.get("all_emails", [])
            if all_emails:
                pdf.cell(0, 7, f"    All emails: {', '.join(all_emails[:3])}", ln=True)

        # Social links from scraping
        social = biz.get("social_links", {})
        if social:
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 8, "  Social Media:", ln=True)
            pdf.set_font("Helvetica", "", 10)
            for platform, url in social.items():
                if url:
                    pdf.cell(0, 7, f"    {platform}: {url}", ln=True)

        # AI-generated website path
        if biz.get("website_path"):
            pdf.ln(3)
            pdf.set_font("Helvetica", "I", 10)
            pdf.cell(0, 7, f"  Generated website: {biz['website_path']}", ln=True)

    # ── Save PDF ─────────────────────────────────────────────────────
    output_path = OUTPUT_DIR / "business_report.pdf"
    pdf.output(str(output_path))
    return str(output_path)


def cleanup_scraped_data():
    """Delete all scraped/generated data. Shows warning first.

    Preserves: knowledge_base/, config.json, the summary PDF, recent sessions
    Deletes: sites/*.html, individual pdfs/*.pdf, old sessions
    """
    print()
    print("  " + "="*50)
    print("  WARNING: Rest businesses data will be deleted!")
    print("  " + "="*50)
    print()
    print("  The following will be permanently removed:")
    print(f"    - {len(list(SITES_DIR.glob('*.html')))} HTML site files")
    print(f"    - {len(list(PDF_DIR.glob('proposal_*.pdf')))} individual PDF proposals")

    # Count old sessions
    old_sessions = 0
    if SESSIONS_DIR.exists():
        cutoff = datetime.now().timestamp() - (7 * 86400)
        for d in SESSIONS_DIR.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                old_sessions += 1
    if old_sessions:
        print(f"    - {old_sessions} old session folders")

    print()
    print("  Preserved:")
    print("    - Business report PDF (summary)")
    print("    - Knowledge base (learning data)")
    print("    - Config (API keys, business profile)")
    print("    - Recent sessions (last 7 days)")
    print()

    deleted = {"sites": 0, "pdfs": 0, "sessions": 0}

    # Delete HTML sites — only test/legacy files, keep user-generated ones
    if SITES_DIR.exists():
        for f in SITES_DIR.glob("*.html"):
            name = f.stem.lower()
            # Only delete test files, legacy files, and XSS test files
            if any(name.startswith(p) for p in ["test", "legacy", "flat-", "nested-", "nosite-", "script-"]):
                f.unlink()
                deleted["sites"] += 1

    # Delete individual PDF proposals — only test/legacy ones
    if PDF_DIR.exists():
        for f in PDF_DIR.glob("proposal_*.pdf"):
            name = f.stem.lower()
            # Only delete proposals for test/legacy businesses
            if any(p in name for p in ["test", "legacy", "flat_", "nested_", "nosite_", "script_"]):
                f.unlink()
                deleted["pdfs"] += 1

    # Delete old sessions (7+ days)
    if SESSIONS_DIR.exists():
        cutoff = datetime.now().timestamp() - (7 * 86400)
        for d in SESSIONS_DIR.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d)
                deleted["sessions"] += 1

    print(f"  Deleted: {deleted['sites']} sites, {deleted['pdfs']} PDFs, {deleted['sessions']} sessions")
    print()

    return deleted


def run_cleanup(businesses: list[dict], session_id: str = "") -> str:
    """Run full cleanup: generate PDF, then delete scraped data.

    Args:
        businesses: The user's chosen businesses to include in the PDF
        session_id: Optional session ID

    Returns:
        Path to the generated PDF
    """
    print("\n  CLEANUP PIPELINE")
    print("  " + "="*50)

    # 1. Generate single PDF with chosen businesses
    print(f"\n  [1/2] Generating PDF report for {len(businesses)} businesses...")
    try:
        pdf_path = generate_business_pdf(businesses, session_id)
        pdf_size = os.path.getsize(pdf_path) / 1024
        print(f"  [OK] Report saved: {pdf_path} ({pdf_size:.0f} KB)")
    except Exception as e:
        print(f"  [ERR] PDF generation failed: {e}")
        return ""

    # 2. Delete scraped data with warning
    print(f"\n  [2/2] Cleaning up scraped data...")
    cleanup_scraped_data()

    print("  " + "="*50)
    print(f"  Done! Report: {pdf_path}")
    print("  " + "="*50)

    return pdf_path
