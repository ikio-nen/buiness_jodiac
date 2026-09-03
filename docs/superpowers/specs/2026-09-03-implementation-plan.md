# Implementation Plan: Session Wizard + Memory + Research + Review

**Date:** 2026-09-03
**Depends on:** Spec at `2026-09-03-session-wizard-memory-review-design.md`

---

## Architecture: Who Owns What

```
┌─────────────────────────────────────────────────────┐
│  jarvis.py (orchestrator, ~400 lines)               │
│  - Menu loop + dispatch                             │
│  - Calls workflows, shows UI, reads/writes session  │
│  - NO business logic, NO rendering details           │
├─────────────────────────────────────────────────────┤
│  ui.py (rendering, ~500 lines)                      │
│  - All display functions                            │
│  - Input prompts                                    │
│  - NEW: wizard display, email review display         │
├─────────────────────────────────────────────────────┤
│  session.py (state, ~120 lines)                     │
│  - Create/load/save/clear                           │
│  - Profile management (session-level)               │
│  - Attachment tracking                              │
├─────────────────────────────────────────────────────┤
│  workflows.py (pure logic, ~500 lines)              │
│  - Search, enrich, draft, send, sync                │
│  - NEW: research_workflow, review_workflow           │
│  - NO UI calls, NO session imports                  │
├─────────────────────────────────────────────────────┤
│  config.py (persistent state, ~160 lines)           │
│  - Business profile (forever)                       │
│  - Email tone, communication style                  │
│  - API keys                                        │
└─────────────────────────────────────────────────────┘
```

**State ownership rules:**
- `config.json` owns: business profile, email tone, API keys — survives forever
- `session/profile.json` owns: project-specific overrides — per session
- `session/attachments.json` owns: file paths per business — per session
- `knowledge_base/*.json` owns: learning data — grows forever
- Workflows read state, never mutate session or config directly
- Jarvis mediates: reads config, writes session, calls workflows

---

## Pass 1: Session Wizard

**Goal:** New project creation asks name, product, target, tone instead of just a name.

### Files Changed

| File | Change |
|------|--------|
| `agents/session.py` | Add `create_with_wizard()`, `save_profile()`, `load_profile()`, `get_effective_profile()` |
| `agents/config.py` | Add `get_email_tone()`, `set_email_tone()`, `get_communication_style()`, `set_communication_style()` |
| `agents/ui.py` | Add `show_wizard_step()`, `show_wizard_summary()` |
| `agents/jarvis.py` | Replace `_ensure_session()` with wizard flow |

### session.py additions

```python
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
    self.save_data(profile, "profile.json")

def load_profile(self) -> dict:
    return self.load_data("profile.json")

def get_effective_profile(self) -> dict:
    """Session profile + main memory defaults."""
    from agents.config import get_business_profile
    main = get_business_profile()
    session_profile = self.load_profile()
    # Session overrides main, main provides defaults
    return {**main, **{k: v for k, v in session_profile.items() if v}}
```

### config.py additions

```python
def get_email_tone() -> str:
    return load_config().get("business_profile", {}).get("email_tone", "professional")

def set_email_tone(tone: str):
    cfg = load_config()
    cfg.setdefault("business_profile", {})["email_tone"] = tone
    save_config(cfg)

def get_communication_style() -> str:
    return load_config().get("business_profile", {}).get("communication_style", "")

def set_communication_style(style: str):
    cfg = load_config()
    cfg.setdefault("business_profile", {})["communication_style"] = style
    save_config(cfg)
```

### jarvis.py change

Replace `_ensure_session()`:

```python
def _ensure_session():
    if session.active:
        return
    name = prompt("Project name: ")
    profile = get_business_profile()
    if profile.get("product"):
        # Main memory exists — just ask name
        session.create(name)
        success(f"Session started: {session.id}")
        return
    # First time — run wizard
    product = prompt("What are we selling? [skip]: ")
    target = prompt("Who are we targeting? [skip]: ")
    tone = prompt("Email tone (professional/friendly/casual) [professional]: ")
    session.create_with_wizard(name, product, target, tone)
    # Update main memory if user provided info
    if product:
        set_business_profile({
            **profile,
            "product": product,
            "target_customers": target or profile.get("target_customers", ""),
            "email_tone": tone or "professional",
        })
    success(f"Session started: {session.id}")
```

### Dependency
None — pure additive. Can be done first.

---

## Pass 2: Persistent Memory

**Goal:** New sessions inherit main memory. Learning data persists and grows.

### Files Changed

| File | Change |
|------|--------|
| `agents/session.py` | `get_effective_profile()` already returns merged profile (Pass 1) |
| `agents/config.py` | Already has `get_business_profile()` / `set_business_profile()` |
| `agents/workflows.py` | `draft_and_pdf_workflow()` reads effective profile instead of just sender_name |
| `agents/jarvis.py` | Chat mode uses effective profile for context |

### workflows.py change

In `draft_and_pdf_workflow()`, replace:
```python
sender_name = get_sender_name()
```
With:
```python
# Read effective profile (session + main memory)
from agents.session import Session
# ... pass profile as parameter instead of just sender_name
```

Actually, the cleaner approach: pass the profile as a parameter from jarvis.py, not import session inside workflows.

### jarvis.py change

Where workflows are called, pass the effective profile:
```python
profile = session.get_effective_profile()
result = draft_and_pdf_workflow(selected, profile)
```

### Dependency
Pass 1 must be done first (session.get_effective_profile exists).

---

## Pass 3: Business Research

**Goal:** After selecting businesses, research each one before drafting.

### Files Changed

| File | Change |
|------|--------|
| `agents/business_research.py` | **NEW** — `research_business()`, `research_batch()` |
| `agents/workflows.py` | `draft_and_pdf_workflow()` calls research before drafting |
| `agents/ui.py` | `show_research_results()` display function |
| `agents/jarvis.py` | Adds research step between selection and drafting |

### business_research.py (new file)

```python
"""Research businesses using web scraping + Gemini analysis."""
from agents.business_enricher import scrape_business
from agents.industry_learner import get_or_research_industry
from agents import ai_engine

def research_business(business: dict) -> dict:
    """Research a single business. Returns insights dict."""
    name = business.get("name", "")
    category = business.get("category", "")

    # 1. Scrape Google Maps for reviews
    scraped = scrape_business(business)

    # 2. Get industry context
    industry = get_or_research_industry(category)

    # 3. Analyze with Gemini (if available)
    if ai_engine.is_available():
        insights = _analyze_with_ai(name, category, scraped, industry)
    else:
        insights = _analyze_basic(name, category, scraped, industry)

    return {
        "name": name,
        "category": category,
        "rating": scraped.get("rating", 0),
        "review_count": scraped.get("review_count", 0),
        "strengths": insights.get("strengths", []),
        "gaps": insights.get("gaps", []),
        "email_hook": insights.get("email_hook", ""),
        "improvement_suggestion": insights.get("improvement_suggestion", ""),
    }

def research_batch(businesses: list[dict]) -> list[dict]:
    """Research multiple businesses. Returns list of insights."""
    results = []
    for biz in businesses:
        try:
            result = research_business(biz)
            results.append(result)
        except Exception:
            results.append({"name": biz.get("name", "?"), "error": "research failed"})
    return results

def _analyze_with_ai(name, category, scraped, industry):
    """Use Gemini to analyze business and find improvement opportunities."""
    prompt = f"""Analyze this business for cold outreach:
Name: {name}
Category: {category}
Industry context: {industry.get('description', '')}
Reviews: {scraped.get('reviews', [])[:5]}
Rating: {scraped.get('rating', 'unknown')}

Return JSON with: strengths, gaps, email_hook, improvement_suggestion"""
    return ai_engine.generate_json(prompt)

def _analyze_basic(name, category, scraped, industry):
    """Fallback analysis without AI."""
    return {
        "strengths": [f"Established {category} business"],
        "gaps": industry.get("pain_points", ["No website"])[:2],
        "email_hook": f"I noticed {name} could benefit from a stronger online presence",
        "improvement_suggestion": industry.get("outreach_approach", ""),
    }
```

### workflows.py change

In `draft_and_pdf_workflow()`, add research step:
```python
def draft_and_pdf_workflow(businesses, profile, do_research=True):
    # ... existing code ...
    if do_research:
        from agents.business_research import research_batch
        research = research_batch(businesses)
        # Pass research insights to AI/template agents
    # ... draft with research context ...
```

### Dependency
Pass 2 must be done first (workflows receive profile parameter).

---

## Pass 4: Email Review & Attachments

**Goal:** Between drafting and sending, show each email for review/edit/attach.

### Files Changed

| File | Change |
|------|--------|
| `agents/ui.py` | Add `show_email_review()`, `show_review_summary()` |
| `agents/session.py` | Add `save_attachments()`, `load_attachments()` |
| `agents/mailer.py` | `send_email()` accepts `attachment_path` parameter |
| `agents/workflows.py` | Add `review_and_edit_workflow()`, `send_approved_workflow()` |
| `agents/jarvis.py` | Adds review step between drafting and sending |

### ui.py additions

```python
def show_email_review(business: dict, draft: dict, index: int, total: int):
    """Show one email for review."""
    print()
    section_header(f"Email Review ({index}/{total})")
    p(f"  Business: {C.BOLD}{business.get('name', '?')}{C.RESET} ({business.get('category', '')})")
    p(f"  To: {draft.get('to', 'not set')}")
    p(f"  Subject: {C.BOLD}{draft.get('subject', '')}{C.RESET}")
    print()
    p("  Body:")
    for line in draft.get("body", "").split("\n"):
        p(f"    {line}")
    print()
    p("  [A]pprove  [E]dit  [S]kip  [AT]tach file")

def show_review_summary(approved: int, skipped: int, attached: int):
    print()
    p(f"  {C.GREEN}Summary: {approved} approved, {skipped} skipped, {attached} attached{C.RESET}")
```

### mailer.py change

```python
def send_email(to, subject, body, pdf_path="", sender_name="The Team",
               attachment_path="") -> dict:
    # ... existing code ...
    # Also attach user-specified file
    if attachment_path and Path(attachment_path).exists():
        with open(attachment_path, "rb") as f:
            attach = MIMEApplication(f.read())
            filename = Path(attachment_path).name
            attach.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(attach)
```

### workflows.py addition

```python
def review_and_edit_workflow(drafts: list[dict]) -> list[dict]:
    """Interactive review of drafts. Returns approved drafts with attachments."""
    approved = []
    for i, draft in enumerate(drafts):
        show_email_review(draft["business"], draft, i + 1, len(drafts))
        action = prompt("  > ").strip().upper()

        if action == "A":
            draft["approved"] = True
            approved.append(draft)
        elif action == "E":
            # Edit mode
            new_subject = prompt(f"  Subject [{draft['subject'][:40]}]: ")
            if new_subject:
                draft["subject"] = new_subject
            # Body editing...
            draft["approved"] = True
            approved.append(draft)
        elif action == "AT":
            path = prompt("  Attachment path: ")
            if path:
                draft["attachment"] = path
            draft["approved"] = True
            approved.append(draft)
        # S = skip (don't add to approved)

    return approved
```

### jarvis.py change

In `_run_quick_outreach()`, after drafting, add review step:

```python
    # ... after drafting ...
    step_header(4, 5, "Review & Edit Emails")
    approved_drafts = review_and_edit_workflow(drafts)

    step_header(5, 5, "Sending")
    send_result = send_emails_workflow(approved_drafts, sender)
```

### Dependency
Pass 3 must be done first (drafts include research insights).

---

## Implementation Order

```
Pass 1: Session Wizard          (no dependencies)
    ↓
Pass 2: Persistent Memory       (depends on Pass 1)
    ↓
Pass 3: Business Research       (depends on Pass 2)
    ↓
Pass 4: Email Review            (depends on Pass 3)
```

Each pass is independently testable and deployable. If any pass is cut, the previous ones still work.

---

## Estimated Line Changes

| Pass | New Lines | Modified Lines | Files |
|------|-----------|---------------|-------|
| 1. Wizard | ~80 | ~30 | session.py, config.py, ui.py, jarvis.py |
| 2. Memory | ~20 | ~40 | workflows.py, jarvis.py |
| 3. Research | ~120 | ~30 | business_research.py (new), workflows.py, ui.py, jarvis.py |
| 4. Review | ~100 | ~50 | ui.py, session.py, mailer.py, workflows.py, jarvis.py |
| **Total** | **~320** | **~150** | **8 files** |

---

## Verification

After each pass, run:
```bash
E:\python.exe -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['agents/session.py','agents/config.py','agents/ui.py','agents/jarvis.py','agents/workflows.py','agents/business_research.py','agents/mailer.py']]"
```

Then run the full playtest to confirm no regressions.
