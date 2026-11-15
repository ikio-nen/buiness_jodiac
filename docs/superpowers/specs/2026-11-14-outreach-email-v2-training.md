# Jodiac Agent Training — Sales-Outreach Emails (v2, 2026-11-14)

**Status**: TRAINING SPEC from Ikio's requirements (2026-11-14). Supersedes v1 generic starter draft.

---

## 1. Background & Context
During review of cold-outreach emails drafted by the agent for CAD licensing to training institutes (e.g. Arena Multimedia), Ikio established explicit requirements for all sales-outreach drafting.

Key directives:
- No generic template or 5-minute call default.
- Research first: cite the institution's specific courses, batches, website, or Google reviews.
- Issue-first opening (first 2 lines): `"I looked at [evidence]. That usually means [issue]."`.
- Single tied offer: `"We help training institutes get licensed AutoCAD seats at per-seat institute pricing, so [benefit]..."`.
- **Never say "keys"**: Say `"licensed AutoCAD seats"` / `"per-seat institute pricing"`. "Keys" reads as grey-market.
- Configurable WhatsApp CTA: Reply to email, WhatsApp (`+91 6296 142368`), or schedule a short meet when free.
- Sender: Real name, default `Ikio` (never `"The Team"`).
- Target length: ~90–110 words.

---

## 2. Before / After Training Pair

### BEFORE (What NOT to do)
```text
Subject: AutoCAD keys for Animation & Multimedia Classes student batches

Running job-oriented design and technical courses often hits a roadblock when scaling software seats for every new student batch. Full retail license pricing simply doesn't fit standard course margins.

We supply cost-effective AutoCAD keys designed specifically for training institutes like yours. Our per-seat licensing scales effortlessly as you add new batches, ensuring your students have licensed software from day one without hurting your bottom line.

How fast could Animation & Multimedia Classes start a new CAD batch with per-seat licensing?

Let's connect for a quick 5-minute chat this week.

Best regards,
The Team
```
*Problems*: Grey-market "keys", generic "training institutes like yours", no researched evidence, default 5-minute call CTA, "The Team" sign-off.

---

### AFTER (Corrected Arena Example — Follows v2 Rules)
```text
Subject: AutoCAD seats for your next batch at Arena?

Hi team,

I looked at Arena's design and multimedia courses in Kolkata. Running batches where students need drafting software usually means full retail pricing eats into the batch margin when every desk needs a seat from day one.

We help training institutes get licensed AutoCAD seats at per-seat institute pricing, so a new batch can start with every student covered without retail costs eating the course margin.

You can reply to this email, or message me on WhatsApp at +91 6296 142368. If you would rather meet, we can schedule a short meet when you are free — just tell me a time that works for you.

Best regards,
Ikio
```

---

## 3. Implementation In Codebase
- `agents/config.py`: `get_whatsapp_number()`, `set_whatsapp_number()`, `get_sender_name()` (default `Ikio`).
- `agents/icp.py`: Product line `licensed AutoCAD seats`.
- `agents/ai_design.py`: `AIEmailDesigner._draft_email` prompt updated with v2 rules, WhatsApp CTA, and Ikio sign-off.
- `agents/medium.py`: `MediumAgent._draft_email` template and hooks aligned with v2 rules.
- `agents/mailer.py`: Empty recipient validation and `Ikio` default sender.
- `agents/ai/prompts/draft_email.md`: Version header bumped to `<!-- version: 2 -->`.
