# JODIAC (JARVIS)

Production-ready local intelligence and automated business outreach assistant with a retro Ghibli pixel-art office interface.

## AI Configuration

JODIAC uses a streamlined, two-tier AI setup:
1. **Primary AI**: Google Gemini (`GEMINI_API_KEY`, defaulting to `gemini-3.5-flash-lite`).
2. **Secondary / Alternative AI**: OpenCode or Vercel AI provider (OpenAI-compatible endpoint configured via `AI_PROVIDER=opencode` or `vercel`, `AI_PROVIDER_KEY`, `AI_PROVIDER_BASE_URL`, and `AI_PROVIDER_MODEL`).
3. **Template Fallback**: When offline or unkeyed, intelligent template fallbacks keep workflows moving without failures or errors.

Third-party providers without keys are silently skipped with zero network overhead.

## Services & APIs

* **Required / Primary Services**:
  * `GEMINI_API_KEY`: Core AI reasoning and drafting.
  * `GMAIL_USER` & `GMAIL_APP_PASSWORD`: SMTP email dispatch.
  * `EXA_API_KEY`: Neural web search and market research.
  * `DRY_RUN`: Set to `1` or `true` for safe local testing without touching real network sockets.
* **Optional Services**:
  * Alternative Email: Resend (`RESEND_API_KEY`), Brevo (`BREVO_API_KEY`).
  * Alternative Search: Tavily (`TAVILY_API_KEY`), Geoapify (`GEOAPIFY_API_KEY`), Reacher (`REACHER_URL`).
  * Contact Enrichment: Hunter.io (`HUNTER_API_KEY`), Apollo (`APOLLO_KEY`), Apify (`APIFY_TOKEN`), Outscraper (`OUTSCRAPER_KEY`).

## Quick Start

1. Copy `.env.example` to `.env` and fill in your keys.
2. Launch using `jarvis.bat` or run:
   ```bash
   python -m agents.web.server
   ```
3. Open `http://127.0.0.1:8765` in your browser.

