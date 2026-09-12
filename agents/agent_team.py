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

# ── The team ─────────────────────────────────────────────────────────

AGENTS = {
    "scout": {
        "name": "Scout",
        "role": "lead hunter",
        "persona": (
            "You are Scout, the lead hunter on a small business-outreach team. "
            "You find and vet businesses and markets: who's out there, what "
            "their reputation is like, what they're missing online. You're "
            "curious and concrete -- you'd rather report one verified fact than "
            "five vague ones. When you don't know something current, use "
            "web_search before answering. Keep replies under 130 words, plain "
            "and direct, like a sharp teammate talking to their boss."
        ),
    },
    "strategist": {
        "name": "Strategist",
        "role": "outreach tactician",
        "persona": (
            "You are Strategist, the outreach tactician. You turn facts about a "
            "business into an angle: what to open with, what to offer, when to "
            "follow up. You think in hooks and timing, and you remember which "
            "approaches worked before. Use web_search when you need fresh "
            "context on an industry or company. Keep replies under 130 words "
            "and always end with one concrete recommended next move."
        ),
    },
    "analyst": {
        "name": "Analyst",
        "role": "numbers and learning",
        "persona": (
            "You are Analyst, the numbers agent. You track what the team has "
            "done and what it's learning: which industries reply, which hooks "
            "fall flat, what the pipeline looks like. You are precise and "
            "honest -- you say 'not enough data yet' when that's the truth "
            "instead of inventing numbers. You rarely need web_search; you "
            "reason from what the team already knows. Keep replies under 130 "
            "words."
        ),
    },
}


# ── Per-agent memory ────────────────────────────────────────────────

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


def ask_agent(key: str, message: str, chat_history: list[dict] = None,
              session=None) -> dict:
    """Chat with one specialist agent. They remember, and they can act.

    Returns {agent, role, reply, used_web, learned, memory_count,
             tools_used, drafts_saved}.
    """
    spec = AGENTS.get((key or "").lower())
    if not spec:
        raise ValueError(f"Unknown agent: {key}")
    name = spec["name"]
    message = (message or "").strip() or "Introduce yourself and what you can help with."

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

    system = (f"{spec['persona']}\n\n"
              f"WHAT YOU ALREADY KNOW (your own memory):\n{memory_text}\n\n"
              f"Your tools: web_search (current facts), read_url (open a page "
              f"you found or were given), vault_query (search the team's own "
              f"notes -- use this before saying you don't know something about "
              f"our past outreach), propose_draft (write an email into the "
              f"user's review queue when they ask you to draft one). Call any "
              f"tool the moment you need it, then answer from what you got. "
              f"Never fabricate tool results.")

    contents = []
    for turn in (chat_history or [])[-6:]:
        role = "model" if turn.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": turn.get("content", "")}]})
    contents.append({"role": "user", "parts": [{"text": message}]})

    from agents.ai_engine import _get_client
    client = _get_client()
    from google.genai import types
    from agents.config import get_ai_model

    tool_decls = [{"function_declarations": [WEB_SEARCH_DECL, READ_URL_DECL,
                                              VAULT_QUERY_DECL, PROPOSE_DRAFT_DECL]}]

    used_web = False
    tools_used = []
    drafts_saved = 0
    search_text = ""
    reply = ""
    last_err = None
    try:
        for _ in range(MAX_TOOL_ROUNDS + 1):
            response = client.models.generate_content(
                model=get_ai_model(),
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    tools=tool_decls,
                    temperature=0.4,
                ),
            )
            part = None
            model_content = None
            if response.candidates and response.candidates[0].content:
                model_content = response.candidates[0].content
                parts = model_content.parts
                part = parts[0] if parts else None

            fname = None
            fargs = {}
            if part and hasattr(part, "function_call") and part.function_call:
                fname = part.function_call.name
                fargs = dict(part.function_call.args or {})

            if fname == "web_search":
                query = fargs.get("query", message)
                search_text = web_search(query) or "(no results found for that)"
                used_web = True
                tools_used.append("web_search")
                contents.append(model_content)
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(function_response=types.FunctionResponse(
                        name="web_search", response={"result": search_text}))],
                ))
                continue

            if fname == "read_url":
                page_text = read_url(fargs.get("url", "")) or "(could not read that URL)"
                tools_used.append("read_url")
                used_web = True
                contents.append(model_content)
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(function_response=types.FunctionResponse(
                        name="read_url", response={"result": page_text}))],
                ))
                continue

            if fname == "vault_query":
                vault_text = vault_query(fargs.get("question", ""),
                                         fargs.get("area", ""))
                tools_used.append("vault_query")
                contents.append(model_content)
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(function_response=types.FunctionResponse(
                        name="vault_query", response={"result": vault_text}))],
                ))
                continue

            if fname == "propose_draft":
                res = propose_draft(
                    fargs.get("business_name", ""), fargs.get("to", ""),
                    fargs.get("subject", ""), fargs.get("body", ""),
                    session=session, agent_key=key)
                tools_used.append("propose_draft")
                if res.get("saved"):
                    drafts_saved += 1
                contents.append(model_content)
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(function_response=types.FunctionResponse(
                        name="propose_draft", response={"result": res}))],
                ))
                continue

            if fname:
                # Unknown tool name: feed an error back so the model can
                # recover instead of dead-ending the conversation.
                contents.append(model_content)
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(function_response=types.FunctionResponse(
                        name=fname,
                        response={"error": f"tool '{fname}' is not available. Use "
                                            f"web_search, read_url, vault_query, or "
                                            f"propose_draft -- or just answer directly."}))],
                ))
                continue

            if part and hasattr(part, "text") and part.text:
                reply = part.text
            break
    except Exception as e:
        last_err = e

    if not reply:
        if search_text:
            # Search succeeded but the final answer didn't -- give the user
            # the raw findings instead of an error.
            reply = (f"{name} here. I searched the web before my thoughts got "
                     f"cut off -- here's what I found:\n{search_text[:600]}")
        elif last_err is not None:
            reply = f"{name} hit an error mid-thought ({type(last_err).__name__}). Try again."
        else:
            reply = f"{name} couldn't finish that lookup. Ask again?"

    learned = _learn_from_chat(key, message, reply, used_web)
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

    from agents import ai_engine
    if not ai_engine.is_available():
        out["errors"].append("no Gemini key -- team cannot think right now")
        return out

    # Mark this batch as handled so proactive notes stop nudging.
    try:
        _mark_batch_handled(targets)
    except Exception:
        pass

    for biz in targets[:max_research]:
        name = biz["name"]
        # ── Scout researches ──
        try:
            scout_out = ask_agent(
                "scout",
                f"Quickly research '{name}' (category: {biz.get('category', '?')}, "
                f"area: {biz.get('address', '?')}). Check your memory first -- only "
                f"use web_search if you need fresh facts. Reply with 2-3 concrete "
                f"facts: reputation, rating, and their biggest online gap.",
                session=session)
            scout_reply = scout_out["reply"]
        except Exception as e:
            out["errors"].append(f"scout/{name}: {type(e).__name__}")
            continue

        # ── Strategist writes the hook from Scout's findings ──
        try:
            strat_out = ask_agent(
                "strategist",
                f"Write ONE opening hook line (max 25 words) for a cold email to "
                f"'{name}'. Scout found: {scout_reply[:300]} Reply with only the "
                f"hook -- no preamble, no quotes.",
                session=session)
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
