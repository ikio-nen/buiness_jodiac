"""GeminiService — the one seam every consumer calls (ARCH §4).

Rules enforced here, not in callers:
- typed in / typed out (schemas.py), never free-form dicts
- every capability has a fallback; a Gemini outage never blocks the pipeline
- no method takes a raw prompt string — new behavior is a new capability
- every call is logged (capability, prompt version, business id, path taken)
- score_fit / summarize_profile are memoized per business (cache.py)
"""

import json

from agents.ai import cache as biz_cache
from agents.ai import fallbacks, prompts, usage_log
from agents.ai import gemini_client
from agents.ai.gemini_client import VERSION as CLIENT_VERSION
from agents.ai.gemini_client import available, generate_json
from agents.ai.schemas import (
    Business, BusinessProfile, ContactCandidate, EmailDraft,
    FitScore, QueryExpansion, ReplyIntent, ToolTurn,
)


def _bid(b: Business) -> str:
    return biz_cache.business_id(b.model_dump(exclude={"snippets"}))


class GeminiService:
    """Seven capabilities. Consumers import the shared ``service``."""

    # ── P0: lead fit scoring ────────────────────────────────────────
    def score_fit(self, business: Business) -> FitScore:
        bid = _bid(business)
        cached = biz_cache.get("score_fit", bid)
        if cached:
            return cached
        result = self._score_fit_impl(business, bid)
        biz_cache.put("score_fit", bid, result)
        return result

    def _score_fit_impl(self, business: Business, bid: str) -> FitScore:
        version, body = prompts.load("score_fit")
        if not available():
            out = fallbacks.score_fit(business)
            usage_log.record("score_fit", version, bid, used_gemini=False,
                             notes="no gemini key")
            return out
        snippet = " | ".join(business.snippets)[:500]
        prompt = f"{body}\n\nBUSINESS: {json.dumps(business.model_dump(exclude_none=True), ensure_ascii=True)}\nSNIPPETS: {snippet}"
        raw = generate_json(prompt)
        # The deterministic ICP verdict stays the floor: the AI pass may only
        # add a rationale. One judge owns the verdict (the double-judge lesson).
        base = fallbacks.score_fit(business)
        if raw.get("rationale"):
            usage_log.record("score_fit", version, bid, used_gemini=True)
            return base.model_copy(update={"rationale": str(raw["rationale"])[:200]})
        usage_log.record("score_fit", version, bid, used_gemini=False,
                         notes="unparseable AI response")
        return base

    # ── P0: business profile summarization ─────────────────────────
    def summarize_profile(self, business: Business) -> BusinessProfile:
        bid = _bid(business)
        cached = biz_cache.get("summarize_profile", bid)
        if cached:
            return cached
        version, body = prompts.load("summarize_profile")
        result: BusinessProfile
        if available() and business.snippets:
            snippet = "\n".join(business.snippets)[:1500]
            prompt = (f"{body}\n\nBUSINESS: {business.name} ({business.category})\n"
                      f"SNIPPETS:\n{snippet}")
            raw = generate_json(prompt)
            if raw.get("industry") or raw.get("hook") or raw.get("pain_point"):
                result = BusinessProfile(
                    industry=str(raw.get("industry") or business.category or "unknown"),
                    size_signal=str(raw.get("size_signal") or "unknown"),
                    pain_point=str(raw.get("pain_point") or "unknown"),
                    hook=str(raw.get("hook") or "unknown"),
                    summary=str(raw.get("summary") or "")[:300],
                    source="gemini",
                )
                usage_log.record("summarize_profile", version, bid, used_gemini=True)
            else:
                result = fallbacks.summarize_profile(business)
                usage_log.record("summarize_profile", version, bid, used_gemini=False,
                                 notes="unparseable AI response")
        else:
            result = fallbacks.summarize_profile(business)
            usage_log.record("summarize_profile", version, bid, used_gemini=False,
                             notes="no key or no snippets")
        biz_cache.put("summarize_profile", bid, result)
        return result

    # ── P0: personalized email drafting (formalized existing path) ──
    def draft_email(self, payload: dict, ctx: dict) -> EmailDraft:
        """Delegate to the migrated ai_design prompt — same behavior, one seam.

        ``payload``/``ctx`` are the same dicts the workflow already passes to
        the drafting agent; the typed models wrap the result.
        """
        version, _ = prompts.load("draft_email")
        from agents.ai_design import AIEmailDesigner
        designer = AIEmailDesigner()
        try:
            raw = designer._draft_email(payload, ctx)
        except Exception as e:
            usage_log.record("draft_email", version,
                             str(payload.get("business_name", ""))[:40],
                             ok=False, used_gemini=False, notes=str(e)[:120])
            return fallbacks.draft_email(
                BusinessProfile(industry=payload.get("category", "")),
                ContactCandidate(name=payload.get("contact_name", "")),
                product=payload.get("product", "what we sell"),
                tone=str(ctx.get("tone", "professional")))
        usage_log.record("draft_email", version,
                         str(payload.get("business_name", ""))[:40],
                         used_gemini=bool(raw.get("ai_powered")))
        return EmailDraft(
            subject=raw.get("subject", ""), body=raw.get("body", ""),
            greeting=raw.get("greeting", ""), hook=raw.get("hook", ""),
            ai_powered=bool(raw.get("ai_powered")), source="gemini",
        )

    # ── P1: reply intent classification ─────────────────────────────
    def classify_reply(self, reply_text: str, thread_context: str | None = None) -> ReplyIntent:
        version, body = prompts.load("classify_reply")
        if not available():
            usage_log.record("classify_reply", version, used_gemini=False,
                             notes="no gemini key")
            return fallbacks.classify_reply(reply_text)
        prompt = f"{body}\n\nTHREAD CONTEXT: {thread_context or 'none'}\nREPLY: {reply_text[:2000]}"
        raw = generate_json(prompt)
        if raw.get("intent"):
            usage_log.record("classify_reply", version, used_gemini=True)
            return ReplyIntent(
                intent=str(raw["intent"]),
                next_action=str(raw.get("next_action", "")),
                confidence=float(raw.get("confidence", 0.7)),
                source="gemini")
        usage_log.record("classify_reply", version, used_gemini=False,
                         notes="unparseable AI response")
        return fallbacks.classify_reply(reply_text)

    # ── P1: search query expansion ──────────────────────────────────
    def expand_query(self, seed_query: str, learnings: list[str] | None = None) -> QueryExpansion:
        version, body = prompts.load("expand_query")
        if not available():
            usage_log.record("expand_query", version, used_gemini=False,
                             notes="no gemini key")
            return fallbacks.expand_query(seed_query)
        prompt = (f"{body}\n\nSEED QUERY: {seed_query}\n"
                  f"LEARNED SO FAR:\n" + "\n".join(learnings or [])[:1200])
        raw = generate_json(prompt)
        queries = raw.get("queries")
        if isinstance(queries, list) and queries:
            usage_log.record("expand_query", version, used_gemini=True)
            return QueryExpansion(
                queries=[str(q) for q in queries if str(q).strip()][:5],
                rationale=str(raw.get("rationale", "")), source="gemini")
        usage_log.record("expand_query", version, used_gemini=False,
                         notes="unparseable AI response")
        return fallbacks.expand_query(seed_query)

    # ── P2: contact extraction from raw pages ───────────────────────
    def extract_contact(self, page_text: str) -> list[ContactCandidate]:
        version, body = prompts.load("extract_contact")
        if not available():
            usage_log.record("extract_contact", version, used_gemini=False,
                             notes="no gemini key")
            return fallbacks.extract_contact(page_text)
        prompt = f"{body}\n\nPAGE TEXT:\n{page_text[:3000]}"
        raw = generate_json(prompt)
        people = raw.get("candidates")
        if isinstance(people, list):
            out = [ContactCandidate(
                name=str(p.get("name", "")), title=str(p.get("title", "")),
                email=str(p.get("email", "")),
                confidence=float(p.get("confidence", 0.5)), source="gemini")
                for p in people if isinstance(p, dict)][:8]
            usage_log.record("extract_contact", version, used_gemini=True)
            return out
        usage_log.record("extract_contact", version, used_gemini=False,
                         notes="unparseable AI response")
        return fallbacks.extract_contact(page_text)

    # ── Tool-using conversation (intent parsing, specialist agents) ──
    def converse(self, capability: str, *, contents: list, system: str = "",
                 tools: list | None = None, temperature: float = 0.3,
                 max_rounds: int = 1, execute=None) -> ToolTurn:
        """Run a tool-using turn through the seam, logged as a capability.

        This is the transport-shaped capability: the caller owns *what* to ask
        (its system instruction, its tool declarations, its tool executor
        policy) and the seam owns the wire — SDK, key, model, retry/quota
        policy and the call/result protocol. A consumer that needs the Gemini
        SDK to reach the model is the smell this method exists to remove.

        ``execute=None`` returns the model's function calls unexecuted; with an
        executor the seam completes the tool loop before returning.
        """
        turn = gemini_client.converse(
            contents=contents, system=system, tools=tools,
            temperature=temperature, max_rounds=max_rounds, execute=execute)
        if turn.error:
            notes = turn.error_type or "call failed"
        elif not turn.calls and not turn.text:
            notes = "empty response"
        else:
            notes = ""
        usage_log.record(capability, CLIENT_VERSION, "",
                         ok=not turn.error, used_gemini=turn.available and not turn.error,
                         notes=notes)
        return turn


service = GeminiService()
