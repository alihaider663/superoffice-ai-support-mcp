"""Investigation plan persistence protocols and in-memory store implementation."""

import asyncio
from typing import Protocol, runtime_checkable

from platform_investigation.models import InvestigationPlan


@runtime_checkable
class InvestigationStore(Protocol):
    """Protocol for persisting and retrieving InvestigationPlan state."""

    async def get_plan(self, plan_id: str) -> InvestigationPlan | None:
        """Retrieve an investigation plan by its identifier."""
        ...

    async def save_plan(self, plan: InvestigationPlan) -> None:
        """Persist or update an investigation plan."""
        ...


class InMemoryInvestigationStore:
    """Thread-safe and async-safe in-memory store for investigation state during local execution."""

    def __init__(self) -> None:
        self._plans: dict[str, InvestigationPlan] = {}
        self._lock = asyncio.Lock()

    async def get_plan(self, plan_id: str) -> InvestigationPlan | None:
        """Retrieve an investigation plan by its identifier."""
        async with self._lock:
            plan = self._plans.get(plan_id)
            return plan.model_copy(deep=True) if plan is not None else None

    async def save_plan(self, plan: InvestigationPlan) -> None:
        """Persist or update an investigation plan."""
        async with self._lock:
            self._plans[plan.investigation_id] = plan.model_copy(deep=True)
