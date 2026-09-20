"""Gemini service seam — one module owns every Gemini call.

Consumers import `service` from here and call typed capability methods.
No consumer imports the Gemini SDK, a prompt string, or an API key.
See docs: ARCHITECTURE.md §1-§5 (Gemini Service Seam).
"""

from agents.ai.service import GeminiService, service

__all__ = ["GeminiService", "service"]
