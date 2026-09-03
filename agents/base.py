#!/usr/bin/env python3
"""Base agent classes and task complexity definitions.

Every agent inherits from BaseAgent. Tasks carry a complexity level so the
orchestrator can route them to the cheapest agent that can handle them.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import time
import traceback


class Complexity(Enum):
    """Task complexity tiers – higher = more capable (and expensive) agent."""
    LIGHT = "light"       # classification, formatting, simple look-ups
    MEDIUM = "medium"     # email drafting, enrichment, summarisation
    HEAVY = "heavy"       # website generation, deep analysis, multi-step reasoning


@dataclass
class Task:
    """A unit of work routed to an agent."""
    id: str
    name: str
    complexity: Complexity
    payload: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    def __repr__(self):
        return f"Task({self.id}, {self.name}, {self.complexity.value})"


@dataclass
class TaskResult:
    """Structured result returned by an agent."""
    task_id: str
    success: bool
    output: Any = None
    error: str = ""
    agent_id: str = ""
    duration_ms: float = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        if self.success:
            return f"OK {self.task_id} completed in {self.duration_ms:.0f}ms"
        return f"FAIL {self.task_id} failed: {self.error}"


class BaseAgent(ABC):
    """Abstract base for all agents.

    Subclasses MUST implement:
        - agent_id        (property)  unique name
        - max_complexity  (property)  highest Complexity this agent handles
        - _execute(task)             the actual work

    Subclasses SHOULD set supported_tasks to a set of task names.
    """

    def __init__(self, model: str = "", api_key: str = ""):
        self.model = model
        self.api_key = api_key
        self._task_count = 0
        self.supported_tasks: set[str] = set()

    # -- identity --

    @property
    @abstractmethod
    def agent_id(self) -> str: ...

    @property
    @abstractmethod
    def max_complexity(self) -> Complexity: ...

    def can_handle(self, task: Task) -> bool:
        """Return True if this agent can handle this specific task."""
        levels = [Complexity.LIGHT, Complexity.MEDIUM, Complexity.HEAVY]
        complexity_ok = levels.index(task.complexity) <= levels.index(self.max_complexity)
        if not complexity_ok:
            return False
        # If supported_tasks is declared, also check task name
        if self.supported_tasks:
            return task.name in self.supported_tasks
        return True

    # -- execution --

    def handle(self, task: Task) -> TaskResult:
        """Public entry point – wraps _execute with timing & error handling."""
        if not self.can_handle(task):
            return TaskResult(
                task_id=task.id, success=False,
                error=f"{self.agent_id} cannot handle complexity {task.complexity.value}",
                agent_id=self.agent_id,
            )

        start = time.time()
        try:
            output = self._execute(task)
            duration = (time.time() - start) * 1000
            self._task_count += 1
            return TaskResult(
                task_id=task.id, success=True, output=output,
                agent_id=self.agent_id, duration_ms=duration,
            )
        except Exception as exc:
            duration = (time.time() - start) * 1000
            return TaskResult(
                task_id=task.id, success=False,
                error=f"{type(exc).__name__}: {exc}",
                agent_id=self.agent_id, duration_ms=duration,
            )

    @abstractmethod
    def _execute(self, task: Task) -> Any:
        """Implement the actual work. Raise on failure."""
        ...

    # -- stats --

    @property
    def stats(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "max_complexity": self.max_complexity.value,
            "supported_tasks": sorted(self.supported_tasks),
            "tasks_completed": self._task_count,
            "model": self.model,
        }
