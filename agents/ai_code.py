#!/usr/bin/env python3
"""AI Code agent — uses Gemini to generate and modify code.

Handles tasks like: code review, refactoring suggestions, script generation,
bug fixes, and code explanations. Falls back gracefully when AI is unavailable.
"""
import json
from typing import Any

from .base import BaseAgent, Complexity, Task


class AICodeAgent(BaseAgent):
    """AI-powered agent for code generation and analysis tasks."""

    def __init__(self):
        super().__init__(model="gemini-ai")
        self.supported_tasks = {
            "ai_review_code", "ai_generate_script",
            "ai_refactor", "ai_explain_code",
            "ai_fix_bug", "ai_generate_html_snippet",
        }

    @property
    def agent_id(self) -> str:
        return "ai_code"

    @property
    def max_complexity(self) -> Complexity:
        return Complexity.HEAVY

    def _execute(self, task: Task) -> Any:
        from . import ai_engine
        if not ai_engine.is_available():
            return {"error": "Gemini API key not configured. Go to [S] Setup to add it.",
                    "ai_powered": False}
        handlers = {
            "ai_review_code":         self._review_code,
            "ai_generate_script":     self._generate_script,
            "ai_refactor":            self._refactor,
            "ai_explain_code":        self._explain_code,
            "ai_fix_bug":             self._fix_bug,
            "ai_generate_html_snippet": self._generate_html_snippet,
        }
        handler = handlers.get(task.name)
        if handler is None:
            raise ValueError(f"AICodeAgent has no handler for '{task.name}'")
        return handler(task.payload, task.context)

    # ── Code Review ────────────────────────────────────────────────────

    def _review_code(self, payload: dict, ctx: dict) -> dict:
        from . import ai_engine
        code = payload.get("code", "")
        language = payload.get("language", "python")

        prompt = f"""Review this {language} code. Be concise and specific.

```{language}
{code}
```

Return ONLY JSON:
{{"issues": [{{"severity": "high/medium/low", "line": "description", "fix": "suggestion"}}],
  "summary": "one-line overall assessment",
  "score": 0-10}}"""

        result = ai_engine.generate_json(prompt)
        if result and "issues" in result:
            result["ai_powered"] = True
            return result
        return {"error": "AI generation failed", "ai_powered": False}

    # ── Script Generation ──────────────────────────────────────────────

    def _generate_script(self, payload: dict, ctx: dict) -> dict:
        from . import ai_engine
        description = payload.get("description", "")
        language = payload.get("language", "python")
        requirements = payload.get("requirements", "")

        prompt = f"""Write a {language} script for: {description}

{f'Requirements: {requirements}' if requirements else ''}

Return ONLY JSON:
{{"code": "the complete script", "filename": "suggested_filename.ext",
  "explanation": "brief explanation of what it does"}}"""

        result = ai_engine.generate_json(prompt)
        if result and "code" in result:
            result["ai_powered"] = True
            return result
        return {"error": "AI generation failed", "ai_powered": False}

    # ── Refactoring ────────────────────────────────────────────────────

    def _refactor(self, payload: dict, ctx: dict) -> dict:
        from . import ai_engine
        code = payload.get("code", "")
        goal = payload.get("goal", "improve readability and performance")
        language = payload.get("language", "python")

        prompt = f"""Refactor this {language} code. Goal: {goal}

```{language}
{code}
```

Return ONLY JSON:
{{"refactored_code": "...", "changes": ["change 1", "change 2"],
  "improvements": "brief explanation"}}"""

        result = ai_engine.generate_json(prompt)
        if result and "refactored_code" in result:
            result["ai_powered"] = True
            return result
        return {"error": "AI generation failed", "ai_powered": False}

    # ── Code Explanation ───────────────────────────────────────────────

    def _explain_code(self, payload: dict, ctx: dict) -> dict:
        from . import ai_engine
        code = payload.get("code", "")
        language = payload.get("language", "python")

        prompt = f"""Explain this {language} code line by line for a beginner.

```{language}
{code}
```

Return ONLY JSON:
{{"summary": "high-level summary",
  "steps": [{{"line": "what that section does"}}],
  "key_concepts": ["concept 1", "concept 2"]}}"""

        result = ai_engine.generate_json(prompt)
        if result and "summary" in result:
            result["ai_powered"] = True
            return result
        return {"error": "AI generation failed", "ai_powered": False}

    # ── Bug Fix ────────────────────────────────────────────────────────

    def _fix_bug(self, payload: dict, ctx: dict) -> dict:
        from . import ai_engine
        code = payload.get("code", "")
        error = payload.get("error", "")
        language = payload.get("language", "python")

        prompt = f"""Fix the bug in this {language} code.

```{language}
{code}
```

Error: {error}

Return ONLY JSON:
{{"fixed_code": "...", "explanation": "what was wrong and how you fixed it",
  "prevention": "how to avoid this in the future"}}"""

        result = ai_engine.generate_json(prompt)
        if result and "fixed_code" in result:
            result["ai_powered"] = True
            return result
        return {"error": "AI generation failed", "ai_powered": False}

    # ── HTML Snippet ───────────────────────────────────────────────────

    def _generate_html_snippet(self, payload: dict, ctx: dict) -> dict:
        from . import ai_engine
        description = payload.get("description", "")
        style = payload.get("style", "modern, clean")

        prompt = f"""Generate an HTML+CSS snippet for: {description}
Style: {style}
Output ONLY the HTML code (no explanation)."""

        html = ai_engine.generate(
            prompt=prompt,
            system="You are an expert frontend developer. Generate clean, modern HTML/CSS.",
            temperature=0.4,
        )
        if html:
            html = html.strip()
            if html.startswith("```"):
                lines = html.split("\n")
                lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                html = "\n".join(lines)
            return {"html": html, "ai_powered": True}
        return {"error": "AI generation failed", "ai_powered": False}
