# Session Wizard + Persistent Memory + Business Research + Email Review

**Date:** 2026-09-03
**Status:** Draft — awaiting user review
**Scope:** 4 interconnected features that transform JARVIS from a tool into an intelligent assistant

---

## Problem

JARVIS currently:
- Asks for a project name but doesn't learn what you sell or who you target
- Has no memory across sessions — you repeat yourself every time
- Drafts generic emails without researching the actual business
- Sends all emails at once with no per-business review or editing
- Has no way to attach files to specific businesses

## Goal

Make JARVIS feel like a personal assistant who:
- Knows your business and remembers your style
- Researches each business before drafting (Google reviews, what they're missing)
- Lets you review, edit, and personalize each email before sending
- Attaches different files to different businesses

---

## Feature 1: Session Wizard

### What
When creating a new project (`[1]`), JARVIS runs a 4-step wizard instead of just asking for a name.

### Flow
```
  New Project Setup
  ~~~~~~~~~~~~~~~~~

  1. Project name: Bandel AutoCAD Outreach
  2. What are we selling? AutoCAD product keys with official licenses
  3. Who are we targeting? Educational centers, training institutes
  4. How should emails sound? (professional/friendly/casual): professional

  Profile saved! Ready to search.
```

### Behavior
- Step 1 (name) is required
- Steps 2-4 are optional — Enter skips, uses main memory defaults
- If main memory already has a profile, skip steps 2-4 entirely and just ask for project name
- Profile is saved to session folder as `profile.json`
- Main memory is updated if user provides new info

### Storage
**Session `profile.json`:**
```json
{
  "project_name": "Bandel AutoCAD Outreach",
  "product": "AutoCAD product keys with official licenses",
  "target_customers": "educational centers, training institutes",
  "email_tone": "professional",
  "created_at": "2026-09-03T12:00:00"
}
```

**Main memory (`config.json` `business_profile`):**
```json
{
  "company_name": "Zyphr",
  "product": "AutoCAD product keys with official licenses",
  "target_customers": "educational centers, training institutes",
  "value_proposition": "Official licensed AutoCAD keys at competitive prices",
  "sender_name": "Zyphr Team",
  "email_tone": "professional",
  "communication_style": "friendly but professional, focus on value"
}
```

### Files Touched
- `agents/jarvis.py` — `_ensure_session()` runs wizard instead of just asking name
- `agents/config.py` — `get_business_profile()` / `set_business_profile()` already exist, add `email_tone` and `communication_style`

---

## Feature 2: Persistent Memory

### What
JARVIS remembers across sessions:
- Your business profile (what you sell, who you target)
- Your email style preferences (tone, what works, what doesn't)
- Learning data from past outreach (which hooks worked, which got rejected)
- Industry knowledge (what works for education vs food vs retail)

### How It Works
- **Main memory** lives in `config.json` — survives forever
- **Learning data** lives in `knowledge_base/` — grows with every session
- **Session memory** lives in session folders — per-project context
- When a new session starts, it inherits main memory + learning data
- During the session, JARVIS learns and updates both session and main memory

### What Gets Remembered
| Data | Where | Lifetime |
|------|-------|----------|
| Business profile | `config.json` | Forever |
| Email tone preference | `config.json` | Forever |
| Communication style | `config.json` | Forever |
| Industry knowledge | `knowledge_base/industry_research.json` | Forever |
| Email performance | `knowledge_base/email_performance.json` | Forever |
| Business patterns | `knowledge_base/business_patterns.json` | Forever |
| Session-specific data | `sessions/<id>/profile.json` | Per session |

### Files Touched
- `agents/config.py` — add `email_tone`, `communication_style` fields
- `agents/learn.py` — already handles persistent learning
- `agents/jarvis.py` — session creation reads main memory, wizard pre-fills from it

---

## Feature 3: Business Research

### What
After selecting businesses, before drafting, JARVIS researches each one using web scraping and AI analysis.

### Flow
```
  [RESEARCH] Don Bosco School...
    Type: Education (school, grades 1-12)
    Rating: 4.2/5 (156 reviews)
    Strengths: Strong academics, good infrastructure
    Gaps: No online admission, no parent portal
    Email hook: "I noticed your reviews praise your facilities but
      parents want online updates — a parent portal could help"

  [RESEARCH] Bandel Medical Hall...
    Type: Retail (pharmacy)
    Rating: 3.8/5 (43 reviews)
    Strengths: Wide product range, good location
    Gaps: No website, no online ordering
    Email hook: "Customers mention wanting to check medicine availability
      online — a website with inventory could drive more visits"
```

### How It Works
1. **Scrape Google Maps** — use Scrapling to fetch reviews, ratings, business type
2. **Analyze with Gemini** — extract: what they do well, what they're missing, improvement suggestions
3. **Store insights** — save to session data as `research/<business_name>.json`
4. **Inject into email** — each draft includes a personalized "improvement suggestion"

### Research Output Per Business
```json
{
  "name": "Don Bosco School",
  "type": "Education - School",
  "rating": 4.2,
  "review_count": 156,
  "strengths": ["Strong academics", "Good infrastructure"],
  "gaps": ["No online admission", "No parent portal"],
  "email_hook": "I noticed your reviews praise your facilities but parents want online updates",
  "improvement_suggestion": "A parent portal with real-time updates would address the #1 parent concern"
}
```

### Files Touched
- `agents/business_research.py` — **NEW** — scrapes Google Maps, analyzes with Gemini
- `agents/workflows.py` — `draft_and_pdf_workflow()` calls research before drafting
- `agents/ai_design.py` — email prompt includes research insights
- `agents/medium.py` — template emails include research hooks

---

## Feature 4: Email Review & Attachments

### What
After drafting, JARVIS shows each email one by one. You can:
- Review the subject and body
- Edit any part (subject, body, greeting)
- Attach a file specific to that business
- Approve or skip

### Flow
```
  Email Review
  ~~~~~~~~~~~~

  Business 1: Don Bosco School (education)
  ─────────────────────────────────────────
  To: info@donbosco.edu
  Subject: Help Don Bosco parents stay connected with a parent portal
  Body:
    Dear Principal,

    I noticed your Google reviews praise your facilities but parents
    want online updates. A parent portal with real-time attendance,
    grades, and announcements would address the #1 parent concern.

    We offer AutoCAD product keys with official licenses at competitive
    prices...

  Attachment: [none] (type path to attach, or Enter to skip)

  [A]pprove  [E]dit  [S]kip  [AT]tach file
  > A

  Business 2: Bandel Medical Hall (shop)
  ─────────────────────────────────────────
  To: info@medical.com
  Subject: Help customers check medicine availability online
  ...

  [A]pprove  [E]dit  [S]kip  [AT]tach file
  > AT
  Attachment path: F:\pharmacy-brochure.pdf
  Attached: F:\pharmacy-brochure.pdf

  [A]pprove  [E]dit  [S]kip  [AT]tach file
  > A

  Summary: 2 approved, 0 skipped, 1 attached
```

### Edit Mode
When you press `[E]`, JARVIS shows the current text and lets you rewrite:
```
  Edit: (current text shown, type new version or Enter to keep)
  Subject [current]: > Help Don Bosco go digital
  Body (type new, blank line to finish, or Enter to keep current):
  > I visited your school last week and was impressed by your campus.
  > I think a digital parent portal would be the perfect next step...
  >
  Body updated.
```

- Subject: single line, Enter to submit
- Body: multi-line, blank line (Enter on empty line) to submit
- Enter immediately (empty input) = keep current text

### Attachment Handling
- Attachments are stored per-business in session data
- When sending, the mailer attaches the specified file
- If no attachment specified, email is sent without one

### Storage
**Session `attachments.json`:**
```json
{
  "Don Bosco School": "F:/brochure.pdf",
  "Bandel Medical Hall": "F:/pharmacy-pricing.pdf"
}
```

### Files Touched
- `agents/workflows.py` — new `review_and_edit_workflow()` function
- `agents/jarvis.py` — new review step between drafting and sending
- `agents/mailer.py` — `send_email()` accepts `attachment_path` parameter
- `agents/ui.py` — `show_email_review()` display function

---

## Data Flow

```
[1] New Project
  → Wizard asks: name, product, target, tone
  → Saves to config.json (main memory) + session/profile.json

[4] Search Businesses
  → Overpass API → businesses list
  → Learning system records categories + patterns

[6] Select Businesses
  → User picks which ones

[NEW] Research Businesses
  → Scrapling scrapes Google Maps per business
  → Gemini analyzes reviews, finds gaps
  → Stores research/<name>.json per business

[7] Draft Emails
  → AI/template uses: business profile + industry context + research insights
  → Each email has personalized hook based on real reviews

[NEW] Review & Edit Each Email
  → Show one by one: subject, body, attachment
  → User: approve, edit, attach file, or skip
  → Stores approved drafts + attachment paths

[8] Send
  → Sends only approved emails
  → Attaches specified files
  → Records success/failure in learning system
```

---

## Testing Strategy

1. **Wizard test** — create session, verify profile saved correctly
2. **Memory test** — create session 2, verify main memory persists
3. **Research test** — select a business, verify research output
4. **Email with research** — draft email, verify it includes research insights
5. **Review flow** — approve/edit/skip/attach, verify correct behavior
6. **Attachment test** — attach file, verify it's sent with email
7. **End-to-end** — full flow: wizard → search → select → research → draft → review → send

---

## Out of Scope

- Parallel research (researching all businesses simultaneously)
- Auto-send without review (always requires explicit approval)
- Editing sent emails (not possible with SMTP)
- Multiple attachment formats (PDF only for now)

---

## Open Questions

None — design is complete and approved by user.
