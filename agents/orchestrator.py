#!/usr/bin/env python3
"""Orchestrator — routes tasks to the best-fit agent.

The orchestrator is the brain of the multi-agent system:
  1. Receives a task (or batch of tasks)
  2. Assigns the right complexity level
  3. Routes to the cheapest agent that can handle it
  4. Collects results, handles retries, and reports stats

Usage:
    from agents.orchestrator import Orchestrator

    orch = Orchestrator()
    result = orch.run("classify_text", {"text": "Joe's Pizza"})
    results = orch.run_batch([Task(...), Task(...)])
"""

import time
import uuid
from typing import Any

from .base import BaseAgent, Complexity, Task, TaskResult
from .lightweight import LightweightAgent
from .medium import MediumAgent
from .heavy import HeavyAgent


# Default complexity mapping — orchestrator can auto-assign
TASK_COMPLEXITY_MAP = {
    # Lightweight tasks
    "classify_text":       Complexity.LIGHT,
    "validate_email":      Complexity.LIGHT,
    "extract_keywords":    Complexity.LIGHT,
    "score_sentiment":     Complexity.LIGHT,
    "format_address":      Complexity.LIGHT,
    "parse_business_tags": Complexity.LIGHT,
    "summarise_counts":    Complexity.LIGHT,

    # Medium tasks
    "draft_email":         Complexity.MEDIUM,
    "enrich_with_hunter":  Complexity.MEDIUM,
    "score_lead":          Complexity.MEDIUM,
    "summarise_business":  Complexity.MEDIUM,
    "generate_subject":    Complexity.MEDIUM,
    "rank_leads":          Complexity.MEDIUM,
    "extract_icebreaker":  Complexity.MEDIUM,

    # Heavy tasks
    "generate_website":       Complexity.HEAVY,
    "deep_analysis":          Complexity.HEAVY,
    "generate_full_report":   Complexity.HEAVY,

    # AI-powered tasks
    "ai_generate_website":    Complexity.HEAVY,
    "ai_draft_email":         Complexity.HEAVY,
    "ai_generate_proposal":   Complexity.HEAVY,
    "ai_generate_pdf_content": Complexity.HEAVY,
    "ai_review_code":         Complexity.HEAVY,
    "ai_generate_script":     Complexity.HEAVY,
    "ai_refactor":            Complexity.HEAVY,
    "ai_explain_code":        Complexity.HEAVY,
    "ai_fix_bug":             Complexity.HEAVY,
    "ai_generate_html_snippet": Complexity.HEAVY,
}


class Orchestrator:
    """Central coordinator that routes tasks to agents.

    Automatically picks the cheapest agent that can handle each task's
    complexity. Keeps stats on throughput and latency.
    """

    def __init__(self, agents: list[BaseAgent] | None = None):
        if agents is not None:
            self.agents = agents
        else:
            self.agents = [LightweightAgent(), MediumAgent(), HeavyAgent()]
            # Add AI agents when Gemini is available
            try:
                from . import ai_engine
                if ai_engine.is_available():
                    from .ai_design import AIDesignAgent
                    from .ai_code import AICodeAgent
                    self.agents.insert(0, AICodeAgent())
                    self.agents.insert(0, AIDesignAgent())
            except Exception:
                pass
        # Sort by complexity so cheapest-first routing works
        self.agents.sort(key=lambda a: list(Complexity).index(a.max_complexity))

        self._history: list[TaskResult] = []

    # ------------------------------------------------------------------ #
    #  Routing                                                            #
    # ------------------------------------------------------------------ #

    def _route(self, task: Task) -> BaseAgent | None:
        """Find the cheapest agent that can handle this task."""
        for agent in self.agents:
            if agent.can_handle(task):
                return agent
        return None

    def _assign_complexity(self, task: Task) -> Task:
        """Auto-assign complexity if the task doesn't have one explicitly."""
        if task.complexity is None:
            task.complexity = TASK_COMPLEXITY_MAP.get(task.name, Complexity.MEDIUM)
        return task

    # ------------------------------------------------------------------ #
    #  Execution                                                          #
    # ------------------------------------------------------------------ #

    def run(self, task_name: str, payload: dict, context: dict | None = None,
            complexity: Complexity | None = None) -> TaskResult:
        """Run a single task. Auto-routes to the right agent.

        If an ai_* task finds no agent (AI not configured), automatically
        retries with the template equivalent (e.g. ai_draft_email -> draft_email).
        """
        task = Task(
            id=str(uuid.uuid4())[:8],
            name=task_name,
            complexity=complexity or TASK_COMPLEXITY_MAP.get(task_name, Complexity.MEDIUM),
            payload=payload,
            context=context or {},
        )
        result = self.run_task(task)

        # AI fallback: if ai_* task failed, try template equivalent
        if not result.success and task_name.startswith("ai_"):
            fallback_name = task_name[3:]  # strip 'ai_' prefix
            if fallback_name in TASK_COMPLEXITY_MAP:
                fallback_task = Task(
                    id=str(uuid.uuid4())[:8],
                    name=fallback_name,
                    complexity=TASK_COMPLEXITY_MAP[fallback_name],
                    payload=payload,
                    context=context or {},
                )
                result = self.run_task(fallback_task)

        return result

    def run_task(self, task: Task) -> TaskResult:
        """Run a pre-built Task object."""
        task = self._assign_complexity(task)
        agent = self._route(task)

        if agent is None:
            result = TaskResult(
                task_id=task.id, success=False,
                error=f"No agent can handle task '{task.name}' at complexity '{task.complexity.value}'",
            )
            self._history.append(result)
            return result

        result = agent.handle(task)
        self._history.append(result)
        return result

    def run_batch(self, tasks: list[Task], parallel: bool = False) -> list[TaskResult]:
        """Run a batch of tasks, routing each independently.

        Args:
            tasks:     List of Task objects
            parallel:  (Future: run concurrently — currently sequential)
        """
        results = []
        for task in tasks:
            results.append(self.run_task(task))
        return results

    # ------------------------------------------------------------------ #
    #  Stats                                                              #
    # ------------------------------------------------------------------ #

    @property
    def stats(self) -> dict:
        """Aggregate stats across all agents and history."""
        total = len(self._history)
        success = sum(1 for r in self._history if r.success)
        total_ms = sum(r.duration_ms for r in self._history)
        agent_usage = {}
        for r in self._history:
            agent_usage[r.agent_id] = agent_usage.get(r.agent_id, 0) + 1

        return {
            "total_tasks": total,
            "success": success,
            "failed": total - success,
            "success_rate": round(success / total * 100, 1) if total else 0,
            "total_ms": round(total_ms, 1),
            "avg_ms": round(total_ms / total, 1) if total else 0,
            "agent_usage": agent_usage,
            "agents": [a.stats for a in self.agents],
        }
