# JARVIS Chat Notes — 14 Sep 2026 (00:50 IST)

Live session via Web UI (http://localhost:8765), captured by Buffy while in progress.
Server: `E:\python.exe -m agents.web.server`, PID 18820.

## Session summary

- User searched for prospective AutoCAD key customers (educational) in **Kolkata**.
- JARVIS ran the search pipeline: found **14 businesses, 8 without a website**.
- User asked to find emails and draft an email for each — email lookup was
  still running at time of capture.

## Transcript

**YOU:** search buiness near me that will be good customers for my autocad keys
**JARVIS:** Could you please tell me your location (city, town, or area) so I can search for businesses near you?

**YOU:** kolkata
**JARVIS:** Searching for: educational centers engineering colleges training institutes that teach AutoCAD in Kolkata...
**JARVIS:** Running search pipeline (query, verify, scrape, enrich)...
**JARVIS:** Found 14 businesses, 8 without website
  [filter] Filtered 322 -> 14 for "educational centers engineering colleges training institutes that teach AutoCAD":
    hard tags dropped 135 (33 hospital, 30 restaurant, 17 bank, 12 fast_food, 10 clinic)
    AI dropped 46 other, 16 government, 12 school, 8 ticket, 8 supermarket
  Maps fallback found emails for 0 and phones for 0 — Google did not surface contact info;
  WhatsApp messaging will need another source.
  Phone/WhatsApp list saved: F:\jodiac\agent_output\reports\phones_for_whatsapp_20260914_005019.csv

  [AGENT TEAM]
  - Scout on SCC - Physics and Chemistry Building: couldn't find a distinct standalone entity; SCC typically... | Hook: Balancing rigorous undergraduate research with high-volume lab scheduling in a shared science facility — streamlining equipment workflows.
  - Scout on Duff Building: couldn't find a distinct standalone entity as a college facility... | Hook: Balancing intensive daily facility operations with high foot traffic in a multi-use academic building — streamlining resource scheduling.
  - Analyst: batch targeted two campus facilities with custom hooks; third prospect unresearched. Next move: run a vault query on si... (truncated)

  [AGENT CHECK-IN]
  - [!!] Follow-up for Bandel St. John's High School is 11 days overdue.
  - [i] Agent team hasn't reviewed 5 new prospects (SCC - Physics and Chemistry Building,
    Duff Building, Indian Institute Of Social Welfare And Business Management + 2 more)
    — say 'team act' to put them on it.

**SEARCH RESULTS** (top 8 shown, all "NO" website):

| # | Name | Category |
|---|------|----------|
| 1 | SCC - Physics and Chemistry Building | college |
| 2 | Duff Building | college |
| 3 | Indian Institute Of Social Welfare And Business Management | educational_institution |
| 4 | Surendranath Group of College | educational_institution |
| 5 | Bangabhashi College | college |
| 6 | University of Calcutta, Rajabazar Science College Campus | university |
| 7 | All India Institute of Hygeine and Public Health | educational_institution |
| 8 | University of Calcutta, College Street Campus | university |

Total: 14 found — 8 without site, 6 with site.

**YOU:** do they have emails search and draft a email for eacb one
**JARVIS:** Looking up email addresses...
**JARVIS:** Looking up email addresses...
**JARVIS:** Maps fallback: found emails for 0/8, phones for 0/8 — nothing found
  (Google did not surface contact info for any of them)

*(captured at 00:52 IST — nothing further arrived in the UI)*

## Status / diagnosis (01:05 IST)

- Currency check: through 01:22 the chat was verified unchanged — UI snapshot
  identical to the capture, 0 new rows in the chat DB after message id 81, and
  no `email_drafts.json` exists in session `20260913_221658`.
- Last DB-logged action: `enrich` completed 00:51:56 (message id 81).
- The draft phase (`research_batch` → `draft_and_pdf_workflow` in
  agents/action_dispatch.py `_handle_draft`) never logged or wrote a file after that:
  - No new brain files after 00:50 (the two existing ones are from the Scout agent
    team during search, not from research).
  - server_stderr.log proves the hang point: the last logged activity anywhere is
    the 8 Google "contact phone" fetches at 00:51:56 (the enrich step). Zero
    research/scrape fetches were ever attempted after that — so the draft step is
    hung BEFORE the first scrape. This points at the pre-scrape AI path (context
    building / ai_engine.generate, which has no per-call timeout), not web-scraping.
- Side finding: `phones_for_whatsapp_20260914_005019.csv` was written but is EMPTY (0 bytes),
  consistent with "Maps fallback found emails for 0/8, phones for 0/8".

## Resolution (01:28 IST) — not a hang: the draft step was never started

- Re-verified frozen through 01:22 (0 new DB rows, no new fetches). Then the real
  cause emerged: the last DB row shows the user's message ("do they have emails
  search and draft a email for eacb one") was parsed as ONE action — `enrich`
  (the email/phone lookup) only. JARVIS takes one action per message, so the
  "draft a email for each" half was dropped by the parser. After enrich finished
  at 00:51:56 the server was simply idle — it looked like a hang but nothing was
  stuck. The pre-scrape-AI theory was wrong.
- Proof: running the draft step directly via `dispatch(DRAFT)` completed in ~90s
  (01:31–01:33): 8/8 emails drafted, 0 errors, AI used 15 calls, `research.json`
  and `email_drafts.json` written. One transient Gemini 429 (rate limit) hit and
  the retry handled it. None of the 8 prospects has an email address, so drafts
  have no `to:` — they're ready for manual follow-up, not for `send`.

## Open items

- Draft step: DONE at 01:33 (8 drafts). Sending blocked on missing email
  addresses — needs a contact source (Hunter/domain search or manual lookup).
- Root-cause fix (code): DONE at 04:05 — parser now chains multi-part
  messages (enrich→draft runs both steps from one message), verified live
  with the original failing message; contact-finder also hunts college
  domains for emails (Duff Building → hailey@duff.com).
- Overdue follow-up: Bandel St. John's High School (11 days) — flagged by agent check-in.
- 5 new prospects not yet reviewed by agent team ('team act').
- Contact finder misses most Kolkata colleges (name-based domain probing
  can't guess caluniv.ac.in-style domains) — 7/8 drafts still have no `to:`;
  needs a better site-discovery step or manual lookup.
