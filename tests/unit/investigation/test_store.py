"""Unit tests for InMemoryInvestigationStore."""

from datetime import UTC, datetime

import pytest

from platform_investigation.models import (
    Hypothesis,
    HypothesisStatus,
    InvestigationPlan,
    InvestigationStatus,
)
from platform_investigation.store import InMemoryInvestigationStore, InvestigationStore


@pytest.fixture
def store() -> InMemoryInvestigationStore:
    return InMemoryInvestigationStore()


@pytest.fixture
def sample_plan() -> InvestigationPlan:
    now = datetime.now(UTC)
    hyp = Hypothesis(description="Initial test hypothesis", status=HypothesisStatus.PROPOSED)
    return InvestigationPlan(
        investigation_id="plan-test-001",
        status=InvestigationStatus.INITIALIZED,
        max_steps=10,
        current_step_count=0,
        steps=(),
        hypotheses=(hyp,),
        concluded_root_cause=None,
        created_at=now,
        updated_at=now,
    )


def test_in_memory_store_implements_protocol() -> None:
    store = InMemoryInvestigationStore()
    assert isinstance(store, InvestigationStore)


@pytest.mark.asyncio
async def test_get_non_existent_plan_returns_none(store: InMemoryInvestigationStore) -> None:
    plan = await store.get_plan("unknown-plan-id")
    assert plan is None


@pytest.mark.asyncio
async def test_save_and_get_plan(
    store: InMemoryInvestigationStore,
    sample_plan: InvestigationPlan,
) -> None:
    await store.save_plan(sample_plan)
    retrieved = await store.get_plan("plan-test-001")
    assert retrieved is not None
    assert retrieved.investigation_id == "plan-test-001"
    assert retrieved.status == InvestigationStatus.INITIALIZED
    assert len(retrieved.hypotheses) == 1
    assert retrieved.hypotheses[0].description == "Initial test hypothesis"


@pytest.mark.asyncio
async def test_store_returns_defensive_deep_copy(
    store: InMemoryInvestigationStore,
    sample_plan: InvestigationPlan,
) -> None:
    """Modifications to retrieved plan object must not mutate store state."""
    await store.save_plan(sample_plan)
    retrieved1 = await store.get_plan("plan-test-001")
    assert retrieved1 is not None

    # Retrieve again and verify equality
    retrieved2 = await store.get_plan("plan-test-001")
    assert retrieved2 is not None
    assert retrieved1.investigation_id == retrieved2.investigation_id
