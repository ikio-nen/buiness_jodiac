"""Multi-agent AI architecture for the BizFinder pipeline.

Five tiers of agents, each covering a different capability:

    Lightweight  ->  rule-based, fast, free  (classify, validate, format)
    Medium       ->  templates + heuristics   (email drafts, enrichment, scoring)
    Heavy        ->  full generation           (websites, proposals, reports)
    AI Design    ->  Gemini-powered generation  (websites, emails, proposals)
    AI Code      ->  Gemini-powered code tasks  (review, refactor, generate)

The Orchestrator routes tasks to the cheapest agent that can handle them.
AI agents take priority when Gemini API is configured.
"""

from .base import BaseAgent, Complexity, Task, TaskResult
from .lightweight import LightweightAgent
from .medium import MediumAgent
from .heavy import HeavyAgent
from .orchestrator import Orchestrator, TASK_COMPLEXITY_MAP
from .learn import get_kb, get_learning_summary, get_learning_dashboard

__all__ = [
    "BaseAgent", "Complexity", "Task", "TaskResult",
    "LightweightAgent", "MediumAgent", "HeavyAgent",
    "Orchestrator", "TASK_COMPLEXITY_MAP",
    "AIDesignAgent", "AICodeAgent", "ai_engine",
    "get_kb", "get_learning_summary", "get_learning_dashboard",
]
