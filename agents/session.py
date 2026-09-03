"""Session state management. Owns all session read/write."""
import json
from datetime import datetime
from pathlib import Path
from agents.config import SESSIONS_DIR, save_session_data, load_session_data, new_session_id


class Session:
    """Manages the current session state."""

    def __init__(self):
        self.id: str | None = None
        self.name: str = ""

    @property
    def active(self) -> bool:
        return self.id is not None

    def create(self, name: str) -> str:
        """Create a new session. Returns session ID."""
        self.id = new_session_id()
        self.name = name or f"project_{self.id}"
        save_session_data(self.id, {
            "name": self.name,
            "started": datetime.now().isoformat(),
            "businesses": [],
            "approached": [],
        }, "session.json")
        return self.id

    def create_with_wizard(self, name: str, product: str = "",
                           target: str = "", tone: str = "") -> str:
        """Create session with profile. Product/target/tone are optional."""
        self.create(name)
        profile = {
            "project_name": name,
            "product": product,
            "target_customers": target,
            "email_tone": tone or "professional",
            "created_at": datetime.now().isoformat(),
        }
        self.save_profile(profile)
        return self.id

    def save_profile(self, profile: dict):
        """Save session-level profile."""
        self.save_data(profile, "profile.json")

    def load_profile(self) -> dict:
        """Load session-level profile."""
        return self.load_data("profile.json")

    def get_effective_profile(self) -> dict:
        """Session profile + main memory defaults.

        Session overrides main memory. Main memory provides defaults.
        """
        from agents.config import get_business_profile
        main = get_business_profile()
        session_profile = self.load_profile()
        # Merge: session values override main, but only if non-empty
        merged = dict(main)
        for k, v in session_profile.items():
            if v:  # Only override with non-empty session values
                merged[k] = v
        return merged

    def save_research(self, research_data: list[dict]):
        """Save research results for businesses in this session."""
        self.save_data({"research": research_data}, "research.json")

    def load_research(self) -> list[dict]:
        """Load research results from this session."""
        data = self.load_data("research.json")
        return data.get("research", [])

    def save_attachments(self, attachments: dict):
        """Save file attachments per business. {business_name: file_path}"""
        self.save_data({"attachments": attachments}, "attachments.json")

    def load_attachments(self) -> dict:
        """Load file attachments from this session."""
        data = self.load_data("attachments.json")
        return data.get("attachments", {})

    def load(self, session_id: str, session_data: dict):
        """Resume an existing session."""
        self.id = session_id
        self.name = session_data.get("name", "")

    def clear(self):
        self.id = None
        self.name = ""

    def save_data(self, data: dict, filename: str):
        if self.id:
            save_session_data(self.id, data, filename)

    def load_data(self, filename: str) -> dict:
        if self.id:
            return load_session_data(self.id, filename)
        return {}

    def get_session_state(self) -> str:
        """Build a compact state summary for Gemini context.

        Returns a string like:
          Session: Bandel AutoCAD Outreach
          Businesses found: 15 (12 without website)
          Research done: 8 businesses
          Drafts ready: 5 emails
          Emails sent: 3
          Profile: selling AutoCAD keys to educational centers
        """
        lines = []
        lines.append(f"Session: {self.name or 'None'}")

        # Search results
        search = self.load_data("search_results.json")
        businesses = search.get("businesses", [])
        no_site = search.get("no_website", [])
        location = search.get("location", "")
        if businesses:
            lines.append(f"Location searched: {location}")
            lines.append(f"Businesses found: {len(businesses)} ({len(no_site)} without website)")
            # List first 5 business names
            names = [b.get("name", "?") for b in no_site[:5]]
            if names:
                lines.append(f"Top targets: {', '.join(names)}")
        else:
            lines.append("No search results yet.")

        # Research
        research = self.load_research()
        if research:
            lines.append(f"Research done: {len(research)} businesses")

        # Drafts
        drafts_data = self.load_data("email_drafts.json")
        drafts = drafts_data.get("drafts", [])
        if drafts:
            lines.append(f"Drafts ready: {len(drafts)} emails")
        else:
            lines.append("No drafts yet.")

        # Sent
        sent_data = self.load_data("sent_emails.json")
        sent = sent_data.get("sent", [])
        if sent:
            lines.append(f"Emails sent: {len(sent)}")

        # Profile
        profile = self.get_effective_profile()
        product = profile.get("product", "")
        target = profile.get("target", "") or profile.get("target_customers", "")
        if product or target:
            parts = []
            if product:
                parts.append(f"selling {product}")
            if target:
                parts.append(f"to {target}")
            lines.append(f"Profile: {' '.join(parts)}")

        return "\n".join(lines)


def list_sessions() -> list[dict]:
    """List all existing sessions."""
    sessions = []
    if SESSIONS_DIR.exists():
        for d in sorted(SESSIONS_DIR.iterdir(), reverse=True):
            if d.is_dir():
                sf = d / "session.json"
                if sf.exists():
                    data = json.loads(sf.read_text(encoding="utf-8"))
                    sessions.append({"id": d.name, **data})
    return sessions
