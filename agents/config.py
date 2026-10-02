"""Configuration for the multi-agent system."""
import json
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
# Portable roots: JODIAC_HOME replaces the F:/jodiac drive letter and
# JODIAC_OBSIDIAN replaces D:/brain, so the project runs on machines without
# those drives. Unset/empty = previous behavior (the F:/D:/ laptop is
# unaffected). Note the `or`, not a default arg: an EMPTY env var would
# otherwise resolve to Path('.') and drop the data dirs into the cwd.
_JODIAC_HOME = Path(os.environ.get("JODIAC_HOME") or "F:/jodiac")
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = _JODIAC_HOME / "agent_output"
SITES_DIR = OUTPUT_DIR / "sites"
REPORTS_DIR = OUTPUT_DIR / "reports"
EMAILS_DIR = OUTPUT_DIR / "emails"
DATA_DIR = OUTPUT_DIR / "data"
SESSIONS_DIR = OUTPUT_DIR / "sessions"
PDF_DIR = OUTPUT_DIR / "pdfs"
OBSIDIAN_VAULT = Path(os.environ.get("JODIAC_OBSIDIAN") or "D:/brain/brain")
OBSIDIAN_PROJECTS = OBSIDIAN_VAULT / "projects"
OBSIDIAN_CONTACTS = OBSIDIAN_VAULT / "contacts"
OBSIDIAN_REPORTS = OBSIDIAN_VAULT / "reports"
OBSIDIAN_INDUSTRIES = OBSIDIAN_VAULT / "industries"
OBSIDIAN_RESEARCH = OBSIDIAN_VAULT / "research"
OBSIDIAN_COMPETITORS = OBSIDIAN_VAULT / "competitors"
OBSIDIAN_FOLLOWUPS = OBSIDIAN_VAULT / "followups"
OBSIDIAN_INSIGHTS = OBSIDIAN_VAULT / "insights"

# ── Knowledge base ──────────────────────────────────────────────────
KB_DIR = OUTPUT_DIR / "knowledge_base"

for d in [OUTPUT_DIR, SITES_DIR, REPORTS_DIR, EMAILS_DIR, DATA_DIR,
          SESSIONS_DIR, PDF_DIR, KB_DIR, OBSIDIAN_PROJECTS, OBSIDIAN_CONTACTS,
          OBSIDIAN_REPORTS, OBSIDIAN_INDUSTRIES, OBSIDIAN_RESEARCH,
          OBSIDIAN_COMPETITORS, OBSIDIAN_FOLLOWUPS, OBSIDIAN_INSIGHTS]:
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OSError(
            f"Cannot create JODIAC data dir '{d}' ({e}). "
            "Set JODIAC_HOME to a writable folder, e.g. "
            "JODIAC_HOME=D:\\jodiac (Windows) or JODIAC_HOME=~/jodiac."
        ) from e

# ── Config file ────────────────────────────────────────────────────────
CONFIG_FILE = OUTPUT_DIR / "config.json"

def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}

def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

def get_hunter_key() -> str:
    return load_config().get("hunter_api_key", "")

def set_hunter_key(key: str):
    cfg = load_config()
    cfg["hunter_api_key"] = key
    save_config(cfg)

def get_gmail_user() -> str:
    return load_config().get("gmail_user", "")

def get_gmail_app_password() -> str:
    return load_config().get("gmail_app_password", "")

def set_gmail(user: str, app_password: str):
    cfg = load_config()
    cfg["gmail_user"] = user
    cfg["gmail_app_password"] = app_password
    save_config(cfg)

def get_sender_name() -> str:
    return load_config().get("sender_name", "The Team")

def set_sender_name(name: str):
    cfg = load_config()
    cfg["sender_name"] = name
    save_config(cfg)

# ── Gemini AI ─────────────────────────────────────────────────────────
def get_gemini_key() -> str:
    return load_config().get("gemini_api_key", "")

def set_gemini_key(key: str):
    cfg = load_config()
    cfg["gemini_api_key"] = key
    save_config(cfg)

def get_ai_model() -> str:
    return load_config().get("ai_model", "gemini-3.5-flash-lite")


def get_ai_provider() -> str:
    return load_config().get("ai_provider", "gemini")


def set_ai_provider(provider: str):
    cfg = load_config()
    cfg["ai_provider"] = provider
    save_config(cfg)


def get_ai_provider_model() -> str:
    return load_config().get("ai_provider_model", "")


def set_ai_provider_model(model: str):
    cfg = load_config()
    cfg["ai_provider_model"] = model
    save_config(cfg)


def get_ai_provider_fallbacks() -> list:
    """Ordered fallback providers tried after the primary fails.

    Stored as a list of provider names, e.g. ["groq", "openrouter", "zai"].
    Unknown names are ignored by the cascade in agents/ai/providers.py."""
    raw = load_config().get("ai_provider_fallbacks", [])
    if not isinstance(raw, list):
        return []
    return [str(p).strip().lower() for p in raw
            if isinstance(p, str) and p.strip()]


def set_ai_provider_fallbacks(providers: list):
    cfg = load_config()
    cfg["ai_provider_fallbacks"] = [str(p).strip().lower() for p in providers
                                    if isinstance(p, str) and p.strip()]
    save_config(cfg)


def get_ai_provider_base_url() -> str:
    return load_config().get("ai_provider_base_url", "")


def set_ai_provider_base_url(url: str):
    cfg = load_config()
    cfg["ai_provider_base_url"] = url
    save_config(cfg)


def get_ai_provider_key() -> str:
    # Env var wins so a key never has to touch config.json on disk.
    import os
    env = os.environ.get("AI_PROVIDER_KEY", "")
    if env:
        return env
    return load_config().get("ai_provider_key", "")


# NOTE: no set_ai_provider_key here is deliberate — keys arrive via env var
# (AI_PROVIDER_KEY) or manual config.json edit, never through code paths that
# could log or persist them accidentally.


def set_ai_model(model: str):
    cfg = load_config()
    cfg["ai_model"] = model
    save_config(cfg)

# ── Business Profile ─────────────────────────────────────────────────
def get_business_profile() -> dict:
    """Get the business profile — what we sell, who we target."""
    cfg = load_config()
    return cfg.get("business_profile", {
        "company_name": "",
        "product": "",
        "target_customers": "",
        "value_proposition": "",
        "sender_name": cfg.get("sender_name", "The Team"),
    })

def set_business_profile(profile: dict):
    """Save the business profile."""
    cfg = load_config()
    cfg["business_profile"] = profile
    save_config(cfg)

# ── Active goal ──────────────────────────────────────────────────────
def get_active_goal() -> str:
    """The user's pinned selling goal (a goal key, or '' = infer per search).

    The goal is what JARVIS is selling RIGHT NOW — the user changes it per
    search, so it lives here (persisted) instead of being guessed from each
    query's wording."""
    return load_config().get("active_goal", "")

def set_active_goal(name: str):
    """Pin the selling goal (a goal key, or '' to clear back to auto-infer)."""
    cfg = load_config()
    cfg["active_goal"] = name or ""
    save_config(cfg)

def get_email_tone() -> str:
    """Get the preferred email tone (professional/friendly/casual)."""
    return get_business_profile().get("email_tone", "professional")

def set_email_tone(tone: str):
    """Set the email tone preference."""
    profile = get_business_profile()
    profile["email_tone"] = tone
    set_business_profile(profile)

def get_communication_style() -> str:
    """Get the communication style description."""
    return get_business_profile().get("communication_style", "")

def set_communication_style(style: str):
    """Set the communication style."""
    profile = get_business_profile()
    profile["communication_style"] = style
    set_business_profile(profile)

def get_business_context() -> str:
    """Get a text summary of the business for AI prompts."""
    p = get_business_profile()
    parts = []
    if p.get("company_name"):
        parts.append(f"Company: {p['company_name']}")
    if p.get("product"):
        parts.append(f"What we sell: {p['product']}")
    if p.get("target_customers"):
        parts.append(f"Target customers: {p['target_customers']}")
    if p.get("value_proposition"):
        parts.append(f"Value proposition: {p['value_proposition']}")
    if p.get("sender_name"):
        parts.append(f"From: {p['sender_name']}")
    if p.get("email_tone"):
        parts.append(f"Email tone: {p['email_tone']}")
    if p.get("communication_style"):
        parts.append(f"Style: {p['communication_style']}")
    return "\n".join(parts)

# ── Overpass API ───────────────────────────────────────────────────────
# Tried in order; if the primary blocks or dies, the next mirror takes over.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# ── Google Maps discovery sources (optional, per-key) ─────────────────
# OSM/Overpass is free but has real gaps for Indian institutions and small
# firms. When one of these keys is set, a search that comes up empty on
# Overpass fails over to Google Maps via that provider instead.

def get_apify_token() -> str:
    return load_config().get("apify_token", "")

def set_apify_token(token: str):
    cfg = load_config()
    cfg["apify_token"] = token
    save_config(cfg)

def get_outscraper_key() -> str:
    return load_config().get("outscraper_key", "")

def set_outscraper_key(key: str):
    cfg = load_config()
    cfg["outscraper_key"] = key
    save_config(cfg)

def get_apollo_key() -> str:
    return load_config().get("apollo_key", "")

def set_apollo_key(key: str):
    cfg = load_config()
    cfg["apollo_key"] = key
    save_config(cfg)

# ── Session management ─────────────────────────────────────────────────
def new_session_id() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def session_dir(session_id: str) -> Path:
    d = SESSIONS_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def save_session_data(session_id: str, data: dict, filename: str):
    path = session_dir(session_id) / filename
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path

def load_session_data(session_id: str, filename: str) -> dict:
    path = session_dir(session_id) / filename
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}
