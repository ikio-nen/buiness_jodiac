"""Real-time progress display for agent tasks.

Shows live updates as tasks execute:
  [SEARCH]    Querying Overpass API...
  [SEARCH]    Found 47 businesses, 32 without website
  [VERIFY]    Checking Don Bosco School... Found: donboschool.com
  [SCRAPE]    Scraping 5 websites...
  [SCRAPE]    Scraped: Manchester Coffee Shop (social: fb, ig)
  [DRAFT]     Drafting 3 personalized emails...
  [DRAFT]     Done: AI email for Coffee Corner
  [PDF]       Generating proposal for Tech Solutions
  [WEBSITE]   Building demo site for Style Studio
  [ENRICH]    Hunter.io: 2/3 emails found
  [OBSIDIAN]  Created 12 notes, 47 wikilinks
  [SEND]      Sending 3 emails... Done: 2 sent, 1 skipped
"""
import sys
import time
from datetime import datetime

from agents.ui import C, p, success, error, warn, info


class LiveUpdates:
    """Tracks and displays real-time task progress."""

    def __init__(self):
        self.steps: list[dict] = []
        self.start_time = time.time()

    def _elapsed(self) -> str:
        secs = time.time() - self.start_time
        if secs < 60:
            return f"{secs:.0f}s"
        return f"{secs/60:.1f}m"

    def _log(self, tag: str, message: str, color: str = C.CYAN):
        timestamp = datetime.now().strftime("%H:%M:%S")
        p(f"[{timestamp}] [{tag}] {message}", color)
        self.steps.append({"tag": tag, "message": message, "time": timestamp})

    # ── Search ────────────────────────────────────────────────────────

    def search_start(self, location: str):
        self._log("SEARCH", f"Geocoding '{location}'...", C.CYAN)

    def search_overpass(self, location: str):
        self._log("SEARCH", f"Querying Overpass API for '{location}'...", C.CYAN)

    def search_results(self, total: int, no_site: int, with_site: int):
        self._log("SEARCH", f"Found {total} businesses: {no_site} without website, {with_site} with", C.GREEN)

    def search_error(self, msg: str):
        self._log("SEARCH", f"Error: {msg}", C.RED)

    # ── Verify ────────────────────────────────────────────────────────

    def verify_start(self, count: int):
        self._log("VERIFY", f"Verifying {count} businesses via Wikidata...", C.YELLOW)

    def verify_found(self, name: str, url: str):
        self._log("VERIFY", f"{name} -> {url[:50]}", C.GREEN)

    def verify_done(self, found: int, checked: int):
        self._log("VERIFY", f"Verified: found {found}/{checked} websites", C.GREEN)

    # ── Scrape ────────────────────────────────────────────────────────

    def scrape_start(self, count: int):
        self._log("SCRAPE", f"Scraping {count} websites with Scrapling...", C.CYAN)

    def scrape_result(self, name: str, social: dict):
        platforms = ", ".join(social.keys()) if social else "none"
        self._log("SCRAPE", f"{name} (social: {platforms})", C.GREEN)

    def scrape_done(self, count: int):
        self._log("SCRAPE", f"Scraped {count} websites", C.GREEN)

    # ── Enrich ────────────────────────────────────────────────────────

    def enrich_start(self, count: int):
        self._log("ENRICH", f"Hunter.io: looking up {count} domains...", C.CYAN)

    def enrich_result(self, name: str, email: str, found: bool):
        if found:
            self._log("ENRICH", f"{name}: {email}", C.GREEN)
        else:
            self._log("ENRICH", f"{name}: no email found", C.DIM)

    def enrich_done(self, found: int, total: int):
        self._log("ENRICH", f"Found {found}/{total} email addresses", C.GREEN)

    # ── Draft ─────────────────────────────────────────────────────────

    def draft_start(self, count: int, ai: bool = False):
        mode = "AI" if ai else "template"
        self._log("DRAFT", f"Drafting {count} personalized emails ({mode})...", C.CYAN)

    def draft_result(self, name: str, subject: str, ai: bool = False):
        tag = "AI" if ai else "DRAFT"
        self._log(tag, f"{name}: '{subject[:45]}...'", C.GREEN)

    def draft_done(self, count: int, ai_count: int = 0):
        msg = f"Drafted {count} emails"
        if ai_count:
            msg += f" ({ai_count} AI-powered)"
        self._log("DRAFT", msg, C.GREEN)

    # ── PDF ───────────────────────────────────────────────────────────

    def pdf_start(self, count: int):
        self._log("PDF", f"Generating {count} proposal PDFs...", C.CYAN)

    def pdf_result(self, name: str):
        self._log("PDF", f"Proposal: {name}", C.GREEN)

    def pdf_done(self, count: int):
        self._log("PDF", f"Generated {count} PDFs", C.GREEN)

    # ── Website ───────────────────────────────────────────────────────

    def website_start(self, count: int, ai: bool = False):
        mode = "AI" if ai else "template"
        self._log("WEB", f"Building {count} demo websites ({mode})...", C.CYAN)

    def website_result(self, name: str, path: str):
        self._log("WEB", f"{name} -> {path[-35:]}", C.GREEN)

    def website_done(self, count: int):
        self._log("WEB", f"Built {count} websites", C.GREEN)

    # ── Obsidian ──────────────────────────────────────────────────────

    def obsidian_start(self):
        self._log("OBSIDIAN", "Syncing to vault...", C.YELLOW)

    def obsidian_note(self, note_type: str, name: str):
        self._log("OBSIDIAN", f"Created {note_type}: {name}", C.GREEN)

    def obsidian_done(self, file_count: int):
        self._log("OBSIDIAN", f"Synced {file_count} notes to Obsidian", C.GREEN)

    # ── Send ──────────────────────────────────────────────────────────

    def send_start(self, count: int):
        self._log("SEND", f"Sending {count} emails via Gmail SMTP...", C.CYAN)

    def send_result(self, name: str, to: str, success: bool):
        if success:
            self._log("SEND", f"Sent to {to} ({name})", C.GREEN)
        else:
            self._log("SEND", f"Failed: {to} ({name})", C.RED)

    def send_done(self, sent: int, skipped: int, errors: int):
        self._log("SEND", f"Done: {sent} sent, {skipped} skipped, {errors} failed", C.GREEN)

    # ── Status ────────────────────────────────────────────────────────

    def status(self, msg: str):
        self._log("STATUS", msg, C.CYAN)

    def summary(self, report: dict):
        """Print a final summary of everything that happened."""
        print()
        p(f"{'='*50}", C.DIM)
        p(f"  PIPELINE COMPLETE ({self._elapsed()})", C.BOLD + C.GREEN)
        p(f"{'='*50}", C.DIM)

        if report.get("search"):
            s = report["search"]
            p(f"  Businesses found:    {s.get('total', 0)}", C.WHITE)
            p(f"  Without website:     {s.get('no_site', 0)}", C.WHITE)

        if report.get("enrich"):
            e = report["enrich"]
            p(f"  Emails found:        {e.get('enriched', 0)}/{e.get('total', 0)}", C.WHITE)

        if report.get("drafts"):
            p(f"  Emails drafted:      {len(report['drafts'])}", C.WHITE)

        if report.get("sync"):
            paths = report["sync"].get("paths", [])
            p(f"  Obsidian notes:      {len(paths)}", C.WHITE)

        if report.get("errors"):
            p(f"  Errors:              {len(report['errors'])}", C.RED)

        p(f"{'='*50}", C.DIM)
        print()


# Global instance
live = LiveUpdates()
