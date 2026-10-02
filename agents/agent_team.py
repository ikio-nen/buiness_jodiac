"""Agent team -- specialist AI agents with their own persistent brains.

Each agent is a persona with:
  - its own memory file (agent_brains/<key>.json): facts learned + chat history
  - four tools it can call itself: web_search, read_url, vault_query,
    propose_draft (hands an email back into the user's pipeline)
  - a Gemini tool loop: it decides which tools to use, then answers

Agents are reached through chat: "ask scout ...", "ask strategist ...",
"ask analyst ...", or Gemini's ask_specialist tool. Everything they hear or
find is remembered for future conversations.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from agents.config import (OUTPUT_DIR, OBSIDIAN_VAULT, OBSIDIAN_CONTACTS,
                           OBSIDIAN_FOLLOWUPS, OBSIDIAN_PROJECTS,
                           OBSIDIAN_RESEARCH, OBSIDIAN_COMPETITORS,
                           OBSIDIAN_INDUSTRIES, OBSIDIAN_INSIGHTS,
                           OBSIDIAN_REPORTS)

AGENT_BRAIN_DIR = OUTPUT_DIR / "agent_brains"

WEB_SEARCH_DECL = {
    "name": "web_search",
    "description": "Search the public web for current information. Use when you "
                   "need facts you don't already know: market data, a business's "
                   "reputation, prices, news, or anything time-sensitive.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The web search query"},
        },
        "required": ["query"],
    },
}

READ_URL_DECL = {
    "name": "read_url",
    "description": "Open a specific web page and read its text. Use after a web "
                   "search when one result clearly matters, or when the user gives "
                   "you a link and wants its contents understood.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The full http(s) URL to read"},
        },
        "required": ["url"],
    },
}

VAULT_QUERY_DECL = {
    "name": "vault_query",
    "description": "Search the user's own Obsidian vault (notes about contacts, "
                   "follow-ups, projects, research, competitors). Use when a fact "
                   "about our own history might exist there: who we emailed, phone "
                   "numbers we saved, what a past session concluded. Areas: "
                   "contacts, followups, projects, research, competitors, industries, "
                   "insights, reports.",
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "What to look for, e.g. "
                         "'St John's phone number', 'which schools did we email'"},
            "area": {"type": "string", "description": "Optional vault folder to "
                     "restrict the search to (e.g. 'contacts', 'followups')"},
        },
        "required": ["question"],
    },
}

BRAIN_QUERY_DECL = {
    "name": "brain_query",
    "description": "Search the team's shared brain -- the accumulated knowledge "
                   "base built from every past session: per-business intel "
                   "(ratings, gaps, interactions), industry lessons, what outreach "
                   "worked and what failed. Use this FIRST for anything about "
                   "businesses we've contacted or industries we've worked, before "
                   "web_search -- it's our own history, not the public web's.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look up, e.g. "
                      "'Don Bosco School', 'what worked with coaching centers', "
                      "'businesses in Bandel'"},
            "area": {"type": "string", "description": "Optional: businesses, "
                     "industries, locations, strategies, insights, sessions, "
                     "profile, all"},
        },
        "required": ["query"],
    },
}

PROPOSE_DRAFT_DECL = {
    "name": "propose_draft",
    "description": "Write an email into the user's outreach pipeline for review "
                   "and sending. Use when the user asks you to draft/write an "
                   "email for a business. The draft lands in their review flow "
                   "-- they approve or edit it there. Requires an active session.",
    "parameters": {
        "type": "object",
        "properties": {
            "business_name": {"type": "string", "description": "The business the "
                              "email is for"},
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Full email body text"},
        },
        "required": ["business_name", "to", "subject", "body"],
    },
}

LEARN_SKILL_DECL = {
    "name": "learn_skill",
    "description": "Save a reusable technique you just discovered or refined so "
                   "the whole team keeps using it. Call this when you find a "
                   "method that works -- e.g. a search pattern that surfaced "
                   "great leads, a hook style that landed, a smarter way to "
                   "verify facts. Refining an existing skill name updates it.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short kebab-case name, e.g. "
                     "'festival-season-timing'"},
            "description": {"type": "string", "description": "One sentence: what this "
                            "technique is for and when to use it"},
            "steps": {"type": "array", "items": {"type": "string"},
                      "description": "2-5 concrete steps to follow"},
        },
        "required": ["name", "description", "steps"],
    },
}

# ── The team ─────────────────────────────────────────────────────────
# AGENTS is the built-in roster. It is NOT the team: the team is whatever
# get_agent()/all_agent_keys() resolve — built-ins plus any runtime hires
# (agents/hiring.py). Consumers must never import AGENTS directly; that
# bypasses the roster and a hired agent becomes invisible to that consumer.

# ── The roster: one owner per agent's identity ──────────────────────
# name, role, look and station live HERE and nowhere else. /api/agents
# serves exactly this record (built-ins and hires alike), and the web client
# renders whatever it is handed — it keeps no roster of its own. Adding an
# agent is an entry in this dict; nothing else needs to learn about it.
#
# `look` is the avatar schema the sprite renderer draws:
#   skin  face tone        hair      hair colour
#   hairStyle  short|buzz|bob|long|bun|curly|bald
#   shirt top colour       accessory none|glasses|headset|cap|tie
AGENTS = {
    "scout": {
        "name": "Scout",
        "role": "lead hunter",
        "station": "station-scout",
        "look": {"skin": "#f0c9a0", "hair": "#2b2b33", "hairStyle": "short",
                 "shirt": "#4e8f7d", "accessory": "headset"},
        "persona": (
            "You are Scout, senior lead-generation researcher on a business-"
            "outreach team. You work like a diligence analyst at a top firm: "
            "every claim you report is verified or explicitly labeled "
            "unverified. Your reports lead with the decision-relevant facts: "
            "who the decision-maker is, what the institution actually runs "
            "(courses, labs, machines, public reviews), the single biggest gap "
            "we can supply, and the best contact route. You quantify: review "
            "counts, ratings, how many lab machines or students are affected. "
            "Judge every prospect against what we sell, not against a generic "
            "marketing checklist. You never pad -- no disclaimers, "
            "no 'as an AI', no restating the question. Structure: a one-line "
            "verdict, then tight bullets. If information is thin, you say "
            "exactly what's missing and name the source you'd check next. "
            "When you discover a reusable search or verification technique, "
            "save it with learn_skill."
        ),
    },
    "strategist": {
        "name": "Strategist",
        "role": "outreach tactician",
        "station": "station-strategist",
        "look": {"skin": "#e8b98d", "hair": "#4a2c17", "hairStyle": "bob",
                 "shirt": "#c1666b", "accessory": "glasses"},
        "persona": (
            "You are Strategist, a senior outbound strategist who has written "
            "hundreds of cold emails and knows reply rates are earned in the "
            "first line. Your craft: find the ONE specific, checkable detail "
            "about the business that proves we did homework -- a recent review "
            "complaint, a lab that just expanded, software that is unlicensed "
            "or expiring -- and turn it into an opening hook about THEIR loss "
            "or opportunity, never our product. You write like a concise human: concrete nouns, no "
            'buzzwords (synergy, solutions, leverage), no feature lists. ' 
            "Every reply ends with a recommended next move: the hook itself, "
            "the follow-up angle, or the channel. When a hook angle was used "
            "before (check brain_query), you rotate to a fresh angle. When "
            "you find a technique that reliably lands, save it with learn_skill."
        ),
    },
    "analyst": {
        "name": "Analyst",
        "role": "numbers and learning",
        "station": "station-analyst",
        "look": {"skin": "#c98f66", "hair": "#111114", "hairStyle": "buzz",
                 "shirt": "#d9a441", "accessory": "glasses"},
        "persona": (
            "You are Analyst, the team's data scientist. You reason from "
            "evidence with a statistician's honesty: you distinguish counts "
            "from rates, correlation from causation, and 'not enough data' "
            "from a real trend -- and you say which is which. You never "
            "invent numbers; you compute from what the brain actually "
            "records, and you show your arithmetic. Your debriefs find the "
            "signal: which segment replies, which hook underperforms, what "
            "single change would most improve outcomes. You end with one "
            "testable recommendation, not a laundry list. When you spot a "
            "recurring pattern worth institutionalizing, save it with learn_skill."
        ),
    },
    "scraper": {
        "name": "Scraper",
        "role": "reads what they publish",
        "station": "station-scraper",
        "look": {"skin": "#f7d9b8", "hair": "#8a5a2b", "hairStyle": "long",
                 "shirt": "#6b8fa3", "accessory": "none"},
        "persona": (
            "You are Scraper, the team's web reader. You turn a business's "
            "public pages into facts we can stand behind. You separate what "
            "a page states from what it is selling: marketing adjectives are "
            "not evidence, a price list and a course catalogue are. You quote "
            "exactly and never strengthen a claim in the retelling. What a "
            "page omits is often your most useful finding -- no pricing, no "
            "staff page, a course list last updated years ago -- and you "
            "report omissions as omissions, not as facts. You say 'the page "
            "does not say' rather than guessing. Structure: what we learned, "
            "what is missing, what to check next. Save reusable extraction "
            "tricks with learn_skill."
        ),
    },
    "enricher": {
        "name": "Enricher",
        "role": "finds the decision-maker",
        "station": "station-enricher",
        "look": {"skin": "#d9a878", "hair": "#3a2a1a", "hairStyle": "curly",
                 "shirt": "#b07d4f", "accessory": "headset"},
        "persona": (
            "You are Enricher, the team's contact hunter. A generic inbox "
            "is a failure, not a result: your job is the human who decides. "
            "You know who signs for training institutes and colleges -- "
            "director, principal, placement officer, IT or lab head, "
            "administrator -- and you reason about which of several "
            "addresses is most likely to reach a person, and why. Every "
            "contact you report carries its provenance (an email on the "
            "contact page, a signature in a PDF, a registry entry) and a "
            "plain confidence word: confirmed, likely, or guesswork. You "
            "never present a pattern-matched guess as a real address. You "
            "also flag the reverse: a named person with no reachable channel, "
            "so the team stops hunting. Save what worked with learn_skill."
        ),
    },
    "builder": {
        "name": "Builder",
        "role": "makes the demo",
        "station": "station-builder",
        "look": {"skin": "#e5b48a", "hair": "#2f2f38", "hairStyle": "short",
                 "shirt": "#8e6fa8", "accessory": "none"},
        "persona": (
            "You are Builder, the team's demo maker. You take what a "
            "business already publishes and show them, concretely, the small "
            "change worth making -- a page, a one-pager, a catalogue layout, "
            "a better course listing. You use their real name, their real "
            "courses and their real details, taken from what the team "
            "collected, so the demo reads as theirs. You label a mockup a "
            "mockup, never a finished delivery, and you never invent "
            "testimonials, logos, accreditation or a customer list. You "
            "explain the ONE decision behind the design in a sentence a "
            "non-designer would repeat. Save design patterns that landed "
            "with learn_skill."
        ),
    },
    "librarian": {
        "name": "Librarian",
        "role": "keeps the brain",
        "station": "station-brain",
        "look": {"skin": "#f0c9a0", "hair": "#5a5a66", "hairStyle": "bun",
                 "shirt": "#7a6fa8", "accessory": "glasses"},
        "persona": (
            "You are Librarian, keeper of the brain. You answer from what "
            "the team has actually recorded, and you say plainly when the "
            "brain is silent instead of filling the gap with plausible "
            "general knowledge. Your first move on any question is brain "
            "query, not web search. You keep our vocabulary stable: one name "
            "per thing, and you call out when two notes describe the same "
            "business or industry under different spellings. You gather "
            "scattered notes into one entry and keep the entry point-to: "
            "what it is, what we know, what we still do not. You name things "
            "so a stranger can find them later."
        ),
    },
    "mailer": {
        "name": "Mailer",
        "role": "sends the mail",
        "station": "station-mailer",
        "look": {"skin": "#c98f66", "hair": "#3a2a1a", "hairStyle": "short",
                 "shirt": "#6f9e58", "accessory": "cap", "accColor": "#b7534a"},
        "persona": (
            "You are Mailer, who owns the send leg. Before anything goes "
            "out you check the boring things that actually matter: the "
            "recipient is a person and not a placeholder, the subject line "
            "is honest about what is inside, any attachment really exists on "
            "disk, and the draft has been approved. If a check fails you say "
            "which one failed and what you need, and you do not send. You "
            "report per recipient, exactly as it happened -- sent, skipped, "
            "failed -- and you never describe a send you did not observe. "
            "Bounces, out-of-office replies and wrong-person answers are "
            "findings you surface, not noise you swallow."
        ),
    },
}


# ── Per-agent memory ────────────────────────────────────────────────

def get_agent(key: str) -> dict | None:
    """Resolve one team member by key — built-ins first, then runtime hires.
    Returns the agent record (name, role, persona, ...) or None. This is the
    ONE roster interface: dispatch, chatbot, and the web API all resolve
    through here so a hired agent exists everywhere at once."""
    if not key:
        return None
    key = str(key).lower().strip()
    if key in AGENTS:
        return dict(AGENTS[key])
    try:
        from agents.hiring import get_hired
        return get_hired(key)
    except Exception:
        return None


def all_agent_keys() -> list[str]:
    """Every resolvable team member: built-ins + active hires, stable order."""
    keys = list(AGENTS)
    try:
        from agents.hiring import active_keys
        keys.extend(k for k in active_keys() if k not in AGENTS)
    except Exception:
        pass
    return keys


def _brain_path(key: str) -> Path:
    return AGENT_BRAIN_DIR / f"{key}.json"


def _load_brain(key: str) -> dict:
    p = _brain_path(key)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"facts": {}, "chats": [], "chat_count": 0}


def _save_brain(key: str, brain: dict):
    brain["updated_at"] = datetime.now().isoformat()
    AGENT_BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    _brain_path(key).write_text(
        json.dumps(brain, indent=2, ensure_ascii=True, default=str),
        encoding="utf-8",
    )


def _remember(key: str, topic: str, note: str):
    """Store a fact under a topic, deduped, newest first."""
    if not note or not note.strip():
        return
    brain = _load_brain(key)
    topic_key = re.sub(r"\s+", " ", topic.lower().strip())[:60] or "general"
    facts = brain.setdefault("facts", {}).setdefault(topic_key, [])
    if note.strip() not in [f["note"] for f in facts]:
        facts.insert(0, {"note": note.strip()[:300], "ts": datetime.now().isoformat()})
        del facts[40:]  # cap per topic
    # Global cap: drop oldest topics beyond 25
    all_topics = brain["facts"]
    if len(all_topics) > 25:
        for t in sorted(all_topics, key=lambda t: all_topics[t][0]["ts"] if all_topics[t] else "")[:-25]:
            del all_topics[t]
    _save_brain(key, brain)


def _recall(key: str, question: str) -> str:
    """Facts from matching topics + the last few chats, as prompt text."""
    brain = _load_brain(key)
    q_words = set(re.findall(r"[a-z]{3,}", question.lower()))
    scored = []
    for topic, facts in brain.get("facts", {}).items():
        t_words = set(topic.split())
        overlap = len(q_words & t_words)
        scored.append((overlap, topic, facts))
    scored.sort(key=lambda x: -x[0])
    lines = []
    for overlap, topic, facts in scored:
        if overlap == 0 and len(lines) >= 2:
            continue
        for f in facts[:2]:
            lines.append(f"- ({topic}) {f['note']}")
        if len(lines) >= 8:
            break
    chats = brain.get("chats", [])[-3:]
    for c in chats:
        lines.append(f"- earlier you were asked: {c['q'][:80]}")
    return "\n".join(lines) if lines else "(nothing yet -- this is a fresh relationship)"


# ── brain_query: search the team's shared brain ────────────────────


def brain_query(query: str, area: str = "") -> str:
    """Search the outreach brain (Brain) for anything relevant to a query.

    Keyword-scored over per-business records, industries, strategies,
    locations and insights. Returns a compact text block, best-effort.
    """
    from agents.brain import get_brain
    q = (query or "").strip()
    if not q:
        return "(empty query)"
    brain = get_brain()
    words = [w for w in re.findall(r"[a-z0-9']{3,}", q.lower())
             if w not in {"the", "what", "which", "who", "did", "have", "are",
                          "for", "and", "was", "were", "their", "about", "with"}]
    if not words:
        words = re.findall(r"[a-z0-9']{3,}", q.lower())[:2]

    # ── Per-business records (name + category + notes keyword match) ──
    biz_hits = []
    if area in ("", "all", "businesses"):
        for rec in brain.list_businesses():
            hay = " ".join(str(rec.get(k, "")) for k in
                           ("name", "category", "notes")).lower()
            matched = [w for w in words if w in hay]
            if not matched:
                continue
            score = len(matched) + (2 if rec.get("name", "").lower() in q.lower() else 0)
            parts = [f"{rec.get('name', '?')} ({rec.get('category', '?')})"]
            if rec.get("rating"):
                parts.append(f"rating={rec['rating']}")
            if rec.get("gaps"):
                parts.append("gaps: " + "; ".join(rec["gaps"][:2]))
            if rec.get("email_hook"):
                parts.append(f"hook: {rec['email_hook'][:100]}")
            inters = rec.get("interactions", [])
            if inters:
                last = inters[-1]
                parts.append(f"last: {last.get('type', '?')} {last.get('timestamp', '')[:10]}")
            biz_hits.append((score, " - ".join(parts)))
    biz_hits.sort(key=lambda t: -t[0])

    # ── Industry lessons ──
    ind_hits = []
    if area in ("", "all", "industries"):
        for name in brain.list_industries():
            data = brain.get_industry(name)
            hay = (name + " " + json.dumps(data, default=str)).lower()
            matched = [w for w in words if w in hay]
            if not matched:
                continue
            bits = [f"industry '{name}'"]
            if data.get("pain_points"):
                bits.append("pain: " + "; ".join(data["pain_points"][:2]))
            if data.get("what_worked"):
                bits.append("worked: " + ", ".join(data["what_worked"][:2]))
            if data.get("what_failed"):
                bits.append("failed: " + ", ".join(data["what_failed"][:2]))
            ind_hits.append((len(matched), " - ".join(bits)))
    ind_hits.sort(key=lambda t: -t[0])

    # ── Strategies (what worked/failed by category) ──
    strat_hits = []
    if area in ("", "all", "strategies"):
        try:
            strategies = brain.get_strategies(q)
        except Exception:
            strategies = {"successful": [], "failed": [], "total_attempts": 0}
        if strategies.get("total_attempts"):
            strat_hits.append((3, f"strategy record for '{q}': "
                                  f"{len(strategies.get('successful', []))} successes, "
                                  f"{len(strategies.get('failed', []))} failures, "
                                  f"{strategies['total_attempts']} attempts"))

    # ── Insights ──
    ins_hits = []
    if area in ("", "all", "insights"):
        for itype, entries in brain.get_insights().items():
            for e in entries[-3:]:
                low = (itype + " " + e.get("content", "")).lower()
                if any(w in low for w in words):
                    ins_hits.append((2, f"[{itype}] {e.get('content', '')[:160]}"))

    sections = []
    if biz_hits:
        sections.append("BUSINESS INTEL:\n" + "\n".join("- " + t for _, t in biz_hits[:5]))
    if ind_hits:
        sections.append("INDUSTRY LESSONS:\n" + "\n".join("- " + t for _, t in ind_hits[:3]))
    if strat_hits:
        sections.append("STRATEGY RECORDS:\n" + "\n".join("- " + t for _, t in strat_hits))
    if ins_hits:
        sections.append("INSIGHTS:\n" + "\n".join("- " + t for _, t in ins_hits[:3]))

    if not sections:
        return "(brain has nothing matching that yet -- it grows as we run sessions)"
    return "\n\n".join(sections)


# ── Web search tool (the agents' own eyes) ──────────────────────────

def web_search(query: str, timeout: int = 12) -> str:
    """Fetch Bing results for a query and return title+snippet lines.

    Best-effort: returns '' on any failure so the agent can answer without it.
    """
    if not query or not query.strip():
        return ""
    try:
        from scrapling.fetchers import Fetcher
        from urllib.parse import quote
        url = f"https://www.bing.com/search?q={quote(query.strip())}"
        page = Fetcher.get(url, timeout=timeout)
        if not page:
            return ""
        out = []
        for li in page.css("li.b_algo")[:6]:
            h2s = li.css("h2")
            if not h2s:
                continue
            title = h2s[0].get_all_text().strip()
            links = li.css("a[href]")
            href = links[0].attrib.get("href", "") if links else ""
            ps = li.css("p")
            snippet = ps[0].get_all_text().strip()[:220] if ps else ""
            out.append(f"{title} -- {snippet} ({href})")
        if not out:  # selector miss: fall back to raw body text
            bodies = page.css("body")
            return bodies[0].get_all_text()[:1500] if bodies else ""
        return "\n".join(out)
    except Exception:
        return ""


# ── read_url: open a specific page ─────────────────────────────────

def read_url(url: str, timeout: int = 12) -> str:
    """Fetch one URL and return its readable text. Best-effort: '' on failure."""
    url = (url or "").strip()
    if not url:
        return ""
    if not url.lower().startswith(("http://", "https://")):
        return ""
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url, timeout=timeout)
        if not page:
            return ""
        bodies = page.css("body")
        text = bodies[0].get_all_text() if bodies else ""
        return text[:6000] if text else ""
    except Exception:
        return ""


# ── vault_query: search the user's own Obsidian vault (read-only) ───

VAULT_AREAS = {
    "contacts": OBSIDIAN_CONTACTS, "followups": OBSIDIAN_FOLLOWUPS,
    "projects": OBSIDIAN_PROJECTS, "research": OBSIDIAN_RESEARCH,
    "competitors": OBSIDIAN_COMPETITORS, "industries": OBSIDIAN_INDUSTRIES,
    "insights": OBSIDIAN_INSIGHTS, "reports": OBSIDIAN_REPORTS,
}


def vault_query(question: str, area: str = "", limit: int = 6) -> str:
    """Keyword search over vault .md files. Returns matched snippets.

    Read-only by construction: we only ever glob and read. Best-effort:
    '(vault not available)' style messages on failure, never an exception.
    """
    q = (question or "").strip()
    if not q:
        return "(empty query)"
    words = [w for w in re.findall(r"[a-z0-9']{3,}", q.lower())
             if w not in {"the", "what", "which", "who", "did", "have", "are",
                          "for", "and", "was", "were", "their", "about"}]
    if not words:
        words = re.findall(r"[a-z0-9']{3,}", q.lower())[:2]
    base = VAULT_AREAS.get((area or "").lower().strip(), OBSIDIAN_VAULT)
    try:
        files = sorted(base.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return "(vault not available right now)"
    if not files:
        return "(no notes found)"
    hits, scanned = [], 0
    for f in files:
        if scanned >= 400 or len(hits) >= limit * 3:
            break
        scanned += 1
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        low = text.lower()
        # Score-based match: a note matching more query words ranks higher;
        # requiring ALL words made recall brittle ("phone" vs "phone number").
        matched = [w for w in words if w in low]
        if not matched:
            continue
        lines = text.splitlines()
        good = [ln.strip() for ln in lines
                if ln.strip() and any(w in ln.lower() for w in matched)][:4]
        if good:
            ctx = " / ".join(good)
            hits.append((len(matched), len(good), f"[{f.name}] {ctx[:240]}"))
    if not hits:
        return "(no notes matched; words tried: " + ", ".join(words[:4]) + ")"
    hits.sort(key=lambda t: (-t[0], -t[1]))
    return "\n".join(t[2] for t in hits[:limit])


# ── propose_draft: hand an email back into the pipeline ─────────────

def propose_draft(business_name: str, to: str, subject: str, body: str,
                  session=None, agent_key: str = "") -> dict:
    """Stage an agent-written email into the active session's draft queue.

    Returns {saved: bool, reason: str}. Saved drafts carry the same fields the
    pipeline's own drafts do, so 'review emails' / 'send all' pick them up.
    With no active session the draft is parked in a staging file instead of
    being dropped, and the agent says so.
    """
    if not (business_name or "").strip():
        return {"saved": False, "reason": "no business name given"}
    if not (to or "").strip() or "@" not in to:
        return {"saved": False, "reason": "no valid recipient address"}
    if not (subject or "").strip() or not (body or "").strip():
        return {"saved": False, "reason": "empty subject or body"}

    staged = {"to": to.strip(), "subject": subject.strip(), "body": body.strip(),
              "business": {"name": business_name.strip()},
              "source": "agent", "agent": agent_key,
              "ts": datetime.now().isoformat()}

    if session is not None and getattr(session, "active", False):
        try:
            data = session.load_data("email_drafts.json") or {"drafts": []}
            drafts = data.get("drafts", [])
            drafts.append(staged)
            session.save_data({"drafts": drafts}, "email_drafts.json")
            return {"saved": True, "reason": "added to session draft queue"}
        except Exception as e:
            return {"saved": False, "reason": f"save failed: {type(e).__name__}"}

    # No active session: park it so the work is never lost.
    try:
        staging_path = OUTPUT_DIR / "agent_drafts_staging.json"
        existing = []
        if staging_path.exists():
            try:
                existing = json.loads(staging_path.read_text(encoding="utf-8"))
            except Exception:
                existing = []
        existing.append(staged)
        staging_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=True, default=str),
            encoding="utf-8")
        return {"saved": False,
                "reason": "no active session -- draft saved to staging "
                          "(agent_drafts_staging.json), start a session to send it"}
    except Exception:
        return {"saved": False, "reason": "no active session and staging failed"}

MAX_TOOL_ROUNDS = 3


def _execute_tool(fname: str, fargs: dict, state: dict, key: str = "",
                  session=None) -> dict:
    """Run one tool the model asked for; the returned dict goes back to it.

    Which tools exist and what they do is team policy, so it lives with the
    team rather than in the seam. ``state`` accumulates what the run learned
    (used_web, tools_used, drafts_saved, search_text) so ask_agent can report
    it once the conversation finishes.
    """
    from agents.event_bus import emit

    if not fname:
        return {"result": ""}

    if fname == "brain_query":
        emit("bot", bot=key or "unknown", status="reading-brain",
             task=str(fargs.get("query", ""))[:80], source="ask_agent")
        brain_text = brain_query(fargs.get("query", ""),
                                 fargs.get("area", ""))
        state["tools_used"].append("brain_query")
        return {"result": brain_text}

    if fname == "web_search":
        query = fargs.get("query", state.get("message", ""))
        emit("bot", bot=key or "unknown", status="searching-web",
             task=str(query)[:80], source="ask_agent")
        found = web_search(query) or "(no results found for that)"
        state["search_text"] = found
        state["used_web"] = True
        state["tools_used"].append("web_search")
        return {"result": found}

    if fname == "read_url":
        page_text = read_url(fargs.get("url", "")) or "(could not read that URL)"
        state["tools_used"].append("read_url")
        state["used_web"] = True
        return {"result": page_text}

    if fname == "vault_query":
        vault_text = vault_query(fargs.get("question", ""),
                                 fargs.get("area", ""))
        state["tools_used"].append("vault_query")
        return {"result": vault_text}

    if fname == "propose_draft":
        res = propose_draft(
            fargs.get("business_name", ""), fargs.get("to", ""),
            fargs.get("subject", ""), fargs.get("body", ""),
            session=session, agent_key=key)
        state["tools_used"].append("propose_draft")
        if res.get("saved"):
            state["drafts_saved"] += 1
            emit("packet", from_="strategist" if key == "strategist" else (key or "agent"),
                 to="drafts", label=str(fargs.get("business_name", ""))[:30])
        return {"result": res}

    if fname == "learn_skill":
        from agents.skills import learn_skill
        saved = learn_skill(str(fargs.get("name", "")),
                            str(fargs.get("description", "")),
                            list(fargs.get("steps") or []),
                            agents=[key or "agent"])
        state["tools_used"].append("learn_skill")
        emit("brain", action="skill " + ("refined" if saved.get("refined") else "learned"),
             detail=str(fargs.get("name", ""))[:60], source="ask_agent")
        return {"result": {
            "saved": True, "name": saved.get("name"),
            "refined": bool(saved.get("refined")),
            "note": "skill is now in the team library"}}

    # Unknown tool name: feed an error back so the model can recover instead
    # of dead-ending the conversation.
    return {"error": f"tool '{fname}' is not available. Use brain_query, "
                     f"web_search, read_url, vault_query, or propose_draft -- "
                     f"or just answer directly."}


def ask_agent(key: str, message: str, chat_history: list[dict] = None,
              session=None, goal: str = "") -> dict:
    """Chat with one specialist agent. They remember, and they can act.

    Returns {agent, role, reply, used_web, learned, memory_count,
             tools_used, drafts_saved}.
    """
    from agents.event_bus import emit
    # Resolve through the roster seam, never the bare AGENTS dict: a runtime
    # hire is a team member too, and a direct AGENTS lookup silently skipped
    # them (they could be listed but never asked to work).
    spec = get_agent(key)
    if not spec:
        raise ValueError(f"Unknown agent: {key}")
    key = str(key or "").lower().strip()
    name = spec["name"]
    message = (message or "").strip() or "Introduce yourself and what you can help with."

    emit("bot", bot=key or "unknown", status="thinking",
         task=message[:80], source="ask_agent")

    memory_text = _recall(key, message)

    from agents import ai_engine
    if not ai_engine.is_available():
        # Offline: still honest, still memory-aware, no invention.
        reply = (f"{name} here ({spec['role']}). I can't think online right now "
                 f"-- no Gemini key configured. What I remember:\n{memory_text}\n\n"
                 f"Set the key in Setup and ask me again -- I'll pick up "
                 f"exactly where we left off.")
        _learn_from_chat(key, message, reply, used_web=False)
        return {"agent": name, "role": spec["role"], "reply": reply,
                "used_web": False, "learned": False,
                "memory_count": _memory_count(key)}

    from agents.skills import skills_prompt, skill_names_for, mark_used
    skills_block = skills_prompt(key or "")

    # What we sell and who buys it. Without this the specialists reason about
    # a generic marketing problem and hand back hooks about the wrong product.
    # ``goal`` is the goal of the batch being worked, so a website run does not
    # get advice about lab software licences.
    icp_block = ""
    try:
        from agents.icp import context as icp_context, resolve_goal, learned_type_rates
        goal_obj = resolve_goal(explicit=goal)
        icp_block = icp_context(goal_obj)
        # What THIS goal's own history taught: which types actually converted.
        # Rates only (min sample enforced in learned_type_rates), never vibes.
        rates = learned_type_rates(goal_obj["key"])
        if rates:
            best = sorted(rates.items(), key=lambda kv: -kv[1])[:4]
            judged = sorted(rates.items(), key=lambda kv: kv[1])[:2]
            learned_lines = ["WHAT THIS GOAL'S PAST SESSIONS TAUGHT US:"]
            learned_lines.append("  Types that converted best: "
                                 + ", ".join(f"{k} ({round(v * 100)}%)" for k, v in best))
            if judged and judged[-1][1] < 0.35:
                learned_lines.append("  Types that rarely converted: "
                                     + ", ".join(f"{k} ({round(v * 100)}%)" for k, v in judged))
            learned_lines.append("  Use this to pick hooks - but judge the specific "
                                 "business in front of you first.")
            icp_block = f"{icp_block}\n\n" + "\n".join(learned_lines)
    except Exception:
        pass

    system = (f"{spec['persona']}\n\n"
              + (skills_block + "\n\n" if skills_block else "")
              + (f"WHAT WE SELL AND WHO BUYS IT:\n{icp_block}\n\n" if icp_block else "")
              + f"WHAT YOU ALREADY KNOW (your own memory):\n{memory_text}\n\n"
              f"Your tools: brain_query (search the team's shared brain -- per-"
              f"business intel, industry lessons, what outreach worked or failed; "
              f"use this FIRST for anything about our own history), web_search "
              f"(current public facts), read_url (open a page you found or were "
              f"given), vault_query (search the user's Obsidian notes -- use this "
              f"before saying you don't know something about our past outreach), "
              f"propose_draft (write an email into the user's review queue when "
              f"they ask you to draft one), learn_skill (save a reusable "
              f"technique you discovered so the team keeps it forever). Call any "
              f"tool the moment you need it, then answer from what you got. "
              f"Never fabricate tool results.")

    contents = []
    for turn in (chat_history or [])[-6:]:
        role = "model" if turn.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": turn.get("content", "")}]})
    contents.append({"role": "user", "parts": [{"text": message}]})

    tool_decls = [{"function_declarations": [BRAIN_QUERY_DECL, WEB_SEARCH_DECL,
                                              READ_URL_DECL, VAULT_QUERY_DECL,
                                              PROPOSE_DRAFT_DECL, LEARN_SKILL_DECL]}]

    _injected_skills = skill_names_for(key or "")

    # The whole tool-using conversation runs through the seam: the SDK, the
    # model, the quota-aware retry policy and the call/result protocol belong
    # to agents/ai. What stays here is policy -- which tools exist, what each
    # does, and what the run learned.
    state = {"used_web": False, "tools_used": [], "drafts_saved": 0,
             "search_text": "", "message": message}
    from agents.ai import service as ai
    turn = ai.converse(
        "agent_chat", contents=contents, system=system, tools=tool_decls,
        temperature=0.4, max_rounds=MAX_TOOL_ROUNDS + 1,
        execute=lambda fname, fargs: _execute_tool(fname, fargs, state,
                                                   key=key, session=session))

    used_web = state["used_web"]
    tools_used = state["tools_used"]
    drafts_saved = state["drafts_saved"]
    search_text = state["search_text"]
    reply = turn.text

    if not reply:
        if search_text:
            # Search succeeded but the final answer didn't -- give the user
            # the raw findings instead of an error.
            reply = (f"{name} here. I searched the web before my thoughts got "
                     f"cut off -- here's what I found:\n{search_text[:600]}")
        elif turn.error:
            reply = f"{name} hit an error mid-thought ({turn.error_type}). Try again."
        else:
            reply = f"{name} couldn't finish that lookup. Ask again?"

    learned = _learn_from_chat(key, message, reply, used_web)
    if tools_used:
        mark_used([s for s in _injected_skills])
    emit("bot", bot=key or "unknown", status="done" if reply else "error",
         task=reply[:80] if reply else str(last_err)[:80], source="ask_agent")
    return {"agent": name, "role": spec["role"], "reply": reply,
            "used_web": used_web, "learned": learned,
            "memory_count": _memory_count(key),
            "tools_used": tools_used, "drafts_saved": drafts_saved}


def _learn_from_chat(key: str, question: str, answer: str, used_web: bool) -> bool:
    """Every chat is remembered; web-found answers become durable facts."""
    brain = _load_brain(key)
    brain["chat_count"] = brain.get("chat_count", 0) + 1
    brain.setdefault("chats", []).append(
        {"q": question[:200], "a": answer[:400], "ts": datetime.now().isoformat()})
    del brain["chats"][:-30]
    _save_brain(key, brain)
    if used_web:
        _remember(key, question, answer[:300])
        return True
    return False


def _memory_count(key: str) -> int:
    brain = _load_brain(key)
    return sum(len(v) for v in brain.get("facts", {}).values())


# ── Layer 1: the team acting inside the pipeline ────────────────────

def _topic_key(business_name: str) -> str:
    return re.sub(r"\s+", " ", business_name.lower().strip())[:60]


def get_hook_for(business_name: str) -> str:
    """Strategist's pre-written hook for a business, if one exists."""
    brain = _load_brain("strategist")
    for note in brain.get("facts", {}).get(_topic_key(business_name), []):
        n = note["note"]
        if n.startswith("Hook: "):
            return n[len("Hook: "):]
    return ""


def team_act(businesses: list[dict], session=None, top_n: int = 3,
             max_research: int = 2) -> dict:
    """The team works a batch of businesses unprompted.

    For the top prospects: Scout researches (web if needed), Strategist
    pre-writes an opening hook. Then Analyst debriefs on the whole batch.
    Everything lands in the team's own memories, the outreach brain
    (researched interactions), and an Obsidian insight note.

    Returns {researched: [{name, hook, scout_reply, used_web}],
             analyst_reply, vault_note, errors}.
    """
    targets = [b for b in (businesses or []) if b.get("name")][:top_n]
    out = {"researched": [], "analyst_reply": "", "vault_note": "", "errors": []}
    if not targets:
        out["errors"].append("no businesses to work")
        return out

    # The batch carries the verdict it was judged with; work it for that goal.
    batch_goal = ((targets[0].get("icp") or {}).get("goal")
                  or (businesses[0].get("icp") or {}).get("goal", ""))

    from agents import ai_engine
    if not ai_engine.is_available():
        out["errors"].append("no Gemini key -- team cannot think right now")
        return out

    # Mark this batch as handled so proactive notes stop nudging.
    try:
        _mark_batch_handled(targets)
    except Exception:
        pass

    from agents.event_bus import emit
    emit("team", team="all", status="briefing",
         task=f"Working {len(targets)} prospect(s)")

    for biz in targets[:max_research]:
        name = biz["name"]
        # ── Scout researches ──
        emit("packet", from_="pipeline", to="scout", label=name[:28])
        try:
            scout_out = ask_agent(
                "scout",
                f"Quickly research '{name}' (category: {biz.get('category', '?')}, "
                f"area: {biz.get('address', '?')}). Check your memory first -- only "
                f"use web_search if you need fresh facts. Reply with 2-3 concrete "
                f"facts: reputation, rating, and the biggest gap we can supply "
                f"here (for example how their computer lab is licensed today).",
                session=session, goal=batch_goal)
            scout_reply = scout_out["reply"]
        except Exception as e:
            out["errors"].append(f"scout/{name}: {type(e).__name__}")
            continue

        # ── Strategist writes the hook from Scout's findings ──
        emit("packet", from_="scout", to="strategist", label=f"intel on {name[:22]}")
        try:
            strat_out = ask_agent(
                "strategist",
                f"Write ONE opening hook line (max 25 words) for a cold email to "
                f"'{name}'. Scout found: {scout_reply[:300]} Reply with only the "
                f"hook -- no preamble, no quotes.",
                session=session, goal=batch_goal)
            hook = (strat_out["reply"].strip().splitlines() or [""])[0].strip('" ')
        except Exception as e:
            out["errors"].append(f"strategist/{name}: {type(e).__name__}")
            hook = ""

        out["researched"].append({"name": name, "hook": hook,
                                  "scout_reply": scout_reply[:400],
                                  "used_web": scout_out.get("used_web", False)})

        # ── Team memories grow ──
        try:
            _remember("scout", name, f"Researched: {scout_reply[:200]}")
            if hook:
                _remember("strategist", name, f"Hook: {hook}")
        except Exception:
            pass
        if hook:
            emit("packet", from_="strategist", to="drafts", label=f"hook: {name[:24]}")

        # ── Outreach brain records the research (guarded) ──
        try:
            from agents.brain import get_brain
            get_brain().learn_business(
                name, category=biz.get("category", ""),
                facts={"notes": scout_reply[:200]},
                interaction={"type": "researched", "summary": hook or scout_reply[:80]},
                source="agent_team")
        except Exception:
            pass

    # ── Analyst debriefs the whole batch ──
    emit("packet", from_="strategist", to="analyst", label="batch debrief")
    try:
        studied = "; ".join(f"{r['name']}{': ' + r['hook'] if r['hook'] else ''}"
                            for r in out["researched"]) or "nothing (research failed)"
        analyst_out = ask_agent(
            "analyst",
            f"Debrief: the team just worked {len(targets)} prospect(s) and researched "
            f"{len(out['researched'])}. Results: {studied[:500]}. Give a 2-sentence "
            f"read on the batch and the single best next move.",
            session=session)
        out["analyst_reply"] = analyst_out["reply"]
    except Exception as e:
        out["errors"].append(f"analyst: {type(e).__name__}")

    # ── Vault insight note (guarded, best-effort) ──
    try:
        from agents.obsidian_sync import create_insight_note
        insights = {}
        if out["analyst_reply"]:
            insights["team_debrief"] = out["analyst_reply"][:400]
        for r in out["researched"]:
            if r["hook"]:
                insights[f"hook: {r['name']}"] = r["hook"]
        out["vault_note"] = create_insight_note(
            "agent_team", "Agent Team Debrief", targets, insights)
    except Exception:
        pass

    return out


# ── Layer 3: the team speaking up unprompted ────────────────────────

def _batch_signature(targets: list[dict]) -> str:
    return "|".join(sorted(b.get("name", "").lower() for b in targets))[:500]


def _mark_batch_handled(targets: list[dict]):
    AGENT_BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    (AGENT_BRAIN_DIR / "_debriefed.json").write_text(
        json.dumps({"signature": _batch_signature(targets),
                    "ts": datetime.now().isoformat()}, ensure_ascii=True),
        encoding="utf-8")


def _latest_pending_batch(limit: int = 5) -> list[dict]:
    """No-site businesses from the most recent session that has them."""
    sessions_dir = OUTPUT_DIR / "sessions"
    if not sessions_dir.exists():
        return []
    for sdir in sorted(sessions_dir.iterdir(), key=lambda p: p.stat().st_mtime,
                       reverse=True)[:5]:
        data = _load_json_file(sdir / "search_results.json")
        batch = data.get("no_website") or []
        if batch:
            return batch[:limit]
    return []


def _load_json_file(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def team_proactive_notes() -> list[dict]:
    """What the team wants to say unprompted. Data-only, never raises."""
    try:
        batch = _latest_pending_batch()
        if not batch:
            return []
        marker = _load_json_file(AGENT_BRAIN_DIR / "_debriefed.json")
        if marker.get("signature") == _batch_signature(batch):
            return []  # already debriefed this batch -- don't nag
        names = ", ".join(b.get("name", "?") for b in batch[:3])
        more = f" and {len(batch) - 3} more" if len(batch) > 3 else ""
        return [{"priority": "info",
                 "text": f"Agent team hasn't reviewed {len(batch)} new prospect(s) "
                         f"({names}{more}) -- say 'team act' to put them on it."}]
    except Exception:
        return []
