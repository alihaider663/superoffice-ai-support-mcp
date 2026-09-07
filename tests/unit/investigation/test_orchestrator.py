"""Unit tests for InvestigationOrchestratorEngine state machine and step bounding."""

import asyncio

import pytest

from platform_core.errors import DomainValidationError
from platform_investigation.errors import (
    HypothesisNotFoundError,
    InvalidInvestigationStateError,
    InvestigationNotFoundError,
    StepLimitExceededError,
)
from platform_investigation.interfaces import InvestigationOrchestrator
from platform_investigation.models import (
    Hypothesis,
    HypothesisStatus,
    InvestigationStatus,
)
from platform_investigation.orchestrator import InvestigationOrchestratorEngine
from platform_investigation.store import InMemoryInvestigationStore


@pytest.fixture
def orchestrator() -> InvestigationOrchestratorEngine:
    return InvestigationOrchestratorEngine(store=InMemoryInvestigationStore())


def test_orchestrator_implements_protocol() -> None:
    engine = InvestigationOrchestratorEngine()
    assert isinstance(engine, InvestigationOrchestrator)


# =========================================================================
# Plan Creation Tests
# =========================================================================


@pytest.mark.asyncio
async def test_create_plan_default_parameters_and_model_confidence(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """create_plan initializes a valid InvestigationPlan using model-owned defaults."""
    plan = await orchestrator.create_plan(initial_hypothesis="Database connection pool starvation")

    assert plan.investigation_id is not None
    assert plan.status == InvestigationStatus.INITIALIZED
    assert plan.max_steps == 10
    assert plan.current_step_count == 0
    assert len(plan.steps) == 0
    assert len(plan.hypotheses) == 1
    assert plan.hypotheses[0].description == "Database connection pool starvation"
    assert plan.hypotheses[0].status == HypothesisStatus.PROPOSED
    # Model-owned default confidence must be preserved without orchestrator overrides
    assert plan.hypotheses[0].confidence == Hypothesis(description="dummy").confidence
    assert plan.concluded_root_cause is None
    assert plan.created_at is not None
    assert plan.updated_at is not None


@pytest.mark.asyncio
async def test_create_plan_custom_step_bounds(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """create_plan accepts custom max_steps within 1..25 range."""
    plan_min = await orchestrator.create_plan(initial_hypothesis="Hypothesis min", max_steps=1)
    assert plan_min.max_steps == 1

    plan_max = await orchestrator.create_plan(initial_hypothesis="Hypothesis max", max_steps=25)
    assert plan_max.max_steps == 25


@pytest.mark.asyncio
async def test_create_plan_validates_empty_hypothesis(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """create_plan rejects empty or whitespace hypothesis string."""
    with pytest.raises(DomainValidationError) as exc_info:
        await orchestrator.create_plan(initial_hypothesis="")
    assert "cannot be empty" in str(exc_info.value)

    with pytest.raises(DomainValidationError) as exc_info2:
        await orchestrator.create_plan(initial_hypothesis="   ")
    assert "cannot be empty" in str(exc_info2.value)


@pytest.mark.asyncio
async def test_create_plan_validates_out_of_range_max_steps(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """create_plan rejects max_steps outside 1..25."""
    with pytest.raises(DomainValidationError):
        await orchestrator.create_plan(initial_hypothesis="Test", max_steps=0)

    with pytest.raises(DomainValidationError):
        await orchestrator.create_plan(initial_hypothesis="Test", max_steps=26)


# =========================================================================
# Plan Retrieval Tests (Concrete Helper)
# =========================================================================


@pytest.mark.asyncio
async def test_get_plan_existing_and_unknown(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """get_plan returns existing plan or raises InvestigationNotFoundError."""
    created = await orchestrator.create_plan(initial_hypothesis="Auth failure")
    retrieved = await orchestrator.get_plan(created.investigation_id)
    assert retrieved.investigation_id == created.investigation_id

    with pytest.raises(InvestigationNotFoundError) as exc_info:
        await orchestrator.get_plan("non-existent-plan-id")
    assert "non-existent-plan-id" in str(exc_info.value)
    assert exc_info.value.error_code == "INVESTIGATION_NOT_FOUND"


# =========================================================================
# Step Progression Tests
# =========================================================================


@pytest.mark.asyncio
async def test_advance_step_increments_count_and_appends_step(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """advance_step increments count, sets status to IN_PROGRESS, and stores step details."""
    plan = await orchestrator.create_plan(initial_hypothesis="High CPU usage")

    # Step 1
    updated1 = await orchestrator.advance_step(
        plan_id=plan.investigation_id,
        action_taken="Queried sys.dm_exec_requests",
        summary="Found 3 blocking sessions",
        severity="WARNING",
        correlation_keys=["ticket:10209", "spid:54"],
        collected_evidence_ids=["ev-001", "ev-002"],
    )

    assert updated1.status == InvestigationStatus.IN_PROGRESS
    assert updated1.current_step_count == 1
    assert len(updated1.steps) == 1
    step1 = updated1.steps[0]
    assert step1.step_number == 1
    assert step1.action_taken == "Queried sys.dm_exec_requests"
    assert step1.summary == "Found 3 blocking sessions"
    assert step1.severity == "WARNING"
    assert step1.correlation_keys == ("ticket:10209", "spid:54")
    assert step1.collected_evidence_ids == ("ev-001", "ev-002")

    # Step 2
    updated2 = await orchestrator.advance_step(
        plan_id=plan.investigation_id,
        action_taken="Checked lock escalation",
        summary="Confirmed table lock on Ticket table",
    )
    assert updated2.current_step_count == 2
    assert len(updated2.steps) == 2
    assert updated2.steps[1].step_number == 2


@pytest.mark.asyncio
async def test_advance_step_unknown_plan_raises_error(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """advance_step on unknown plan raises InvestigationNotFoundError."""
    with pytest.raises(InvestigationNotFoundError):
        await orchestrator.advance_step("unknown-plan-999")


@pytest.mark.asyncio
async def test_advance_step_updates_and_adds_hypotheses(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """advance_step replaces existing hypothesis by ID or appends new hypothesis."""
    plan = await orchestrator.create_plan(initial_hypothesis="Hypothesis A")
    initial_hyp_id = plan.hypotheses[0].hypothesis_id

    # Update existing hypothesis with specific confidence
    updated_hyp_a = Hypothesis(
        hypothesis_id=initial_hyp_id,
        description="Hypothesis A (Refined)",
        status=HypothesisStatus.PROPOSED,
        confidence=0.85,
        supporting_evidence_ids=("ev-01",),
    )
    plan_after_h1 = await orchestrator.advance_step(
        plan_id=plan.investigation_id,
        hypothesis=updated_hyp_a,
    )
    assert len(plan_after_h1.hypotheses) == 1
    assert plan_after_h1.hypotheses[0].description == "Hypothesis A (Refined)"
    assert plan_after_h1.hypotheses[0].confidence == 0.85

    # Append new hypothesis
    new_hyp_b = Hypothesis(
        description="Hypothesis B (Secondary root cause)",
        status=HypothesisStatus.PROPOSED,
        confidence=0.4,
    )
    plan_after_h2 = await orchestrator.advance_step(
        plan_id=plan.investigation_id,
        hypothesis=new_hyp_b,
    )
    assert len(plan_after_h2.hypotheses) == 2
    assert plan_after_h2.hypotheses[1].description == "Hypothesis B (Secondary root cause)"


# =========================================================================
# Step Limit Boundary & Terminal State Tests
# =========================================================================


@pytest.mark.asyncio
async def test_step_limit_boundary_exact_ceiling(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """Plan allows exactly max_steps, and transitions to STEP_LIMIT_EXCEEDED on step N+1."""
    plan = await orchestrator.create_plan(initial_hypothesis="Test ceiling", max_steps=3)

    # Steps 1, 2, 3 should all succeed
    p1 = await orchestrator.advance_step(plan.investigation_id, summary="Step 1")
    assert p1.current_step_count == 1
    assert p1.status == InvestigationStatus.IN_PROGRESS

    p2 = await orchestrator.advance_step(plan.investigation_id, summary="Step 2")
    assert p2.current_step_count == 2

    p3 = await orchestrator.advance_step(plan.investigation_id, summary="Step 3")
    assert p3.current_step_count == 3
    assert len(p3.steps) == 3

    # Attempting Step 4 must fail with StepLimitExceededError and set STEP_LIMIT_EXCEEDED
    with pytest.raises(StepLimitExceededError) as exc_info:
        await orchestrator.advance_step(plan.investigation_id, summary="Step 4 (excess)")

    assert exc_info.value.max_steps == 3
    assert exc_info.value.error_code == "STEP_LIMIT_EXCEEDED"

    # Verify plan state in store
    final_plan = await orchestrator.get_plan(plan.investigation_id)
    assert final_plan.status == InvestigationStatus.STEP_LIMIT_EXCEEDED
    assert final_plan.current_step_count == 3
    assert len(final_plan.steps) == 3


@pytest.mark.asyncio
async def test_step_limit_boundary_single_step_plan(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """Plan with max_steps=1 allows exactly 1 step, and rejects step 2."""
    plan = await orchestrator.create_plan(initial_hypothesis="Single step plan", max_steps=1)

    p1 = await orchestrator.advance_step(plan.investigation_id, summary="Step 1")
    assert p1.current_step_count == 1

    with pytest.raises(StepLimitExceededError):
        await orchestrator.advance_step(plan.investigation_id, summary="Step 2")

    stored = await orchestrator.get_plan(plan.investigation_id)
    assert stored.status == InvestigationStatus.STEP_LIMIT_EXCEEDED
    assert stored.current_step_count == 1


@pytest.mark.asyncio
async def test_cannot_advance_concluded_investigation(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """Advancing an already concluded investigation raises InvalidInvestigationStateError."""
    plan = await orchestrator.create_plan(initial_hypothesis="Root cause test")
    hyp_id = plan.hypotheses[0].hypothesis_id

    await orchestrator.advance_step(plan.investigation_id, summary="Diagnostic step")
    await orchestrator.conclude_investigation(plan.investigation_id, final_hypothesis_id=hyp_id)

    with pytest.raises(InvalidInvestigationStateError) as exc_info:
        await orchestrator.advance_step(plan.investigation_id, summary="Post-conclusion step")

    assert "terminal status 'concluded'" in str(exc_info.value)
    assert exc_info.value.current_status == "concluded"


@pytest.mark.asyncio
async def test_cannot_advance_aborted_investigation(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """Advancing an aborted investigation raises InvalidInvestigationStateError."""
    plan = await orchestrator.create_plan(initial_hypothesis="Abort test")
    await orchestrator.abort_investigation(plan.investigation_id, reason="User cancelled")

    with pytest.raises(InvalidInvestigationStateError) as exc_info:
        await orchestrator.advance_step(plan.investigation_id, summary="Post-abort step")

    assert "terminal status 'aborted'" in str(exc_info.value)


# =========================================================================
# Conclusion & Abort Tests (Confidence Preservation)
# =========================================================================


@pytest.mark.asyncio
async def test_conclude_investigation_preserves_existing_confidence(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """conclude_investigation sets CONFIRMED status without forcing confidence to 1.0."""
    plan = await orchestrator.create_plan(initial_hypothesis="Deadlock on Task table")
    hyp_id = plan.hypotheses[0].hypothesis_id

    # Update hypothesis with specific confidence 0.85 during investigation
    refined_hyp = Hypothesis(
        hypothesis_id=hyp_id,
        description="Deadlock on Task table (Evaluated)",
        status=HypothesisStatus.PROPOSED,
        confidence=0.85,
    )
    await orchestrator.advance_step(plan.investigation_id, hypothesis=refined_hyp)

    concluded = await orchestrator.conclude_investigation(
        plan_id=plan.investigation_id,
        final_hypothesis_id=hyp_id,
    )

    assert concluded.status == InvestigationStatus.CONCLUDED
    assert concluded.concluded_root_cause == "Deadlock on Task table (Evaluated)"
    assert len(concluded.hypotheses) == 1
    assert concluded.hypotheses[0].status == HypothesisStatus.CONFIRMED
    # Must preserve caller/model confidence (0.85) rather than forcing 1.0
    assert concluded.hypotheses[0].confidence == 0.85


@pytest.mark.asyncio
async def test_conclude_step_limit_exceeded_plan_preserves_confidence(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """A plan in STEP_LIMIT_EXCEEDED may be concluded, preserving existing confidence."""
    plan = await orchestrator.create_plan(initial_hypothesis="Ceiling conclusion", max_steps=1)
    hyp_id = plan.hypotheses[0].hypothesis_id

    await orchestrator.advance_step(plan.investigation_id, summary="Step 1")

    # Attempt excess step to trigger STEP_LIMIT_EXCEEDED
    with pytest.raises(StepLimitExceededError):
        await orchestrator.advance_step(plan.investigation_id, summary="Step 2 (excess)")

    stored = await orchestrator.get_plan(plan.investigation_id)
    assert stored.status == InvestigationStatus.STEP_LIMIT_EXCEEDED

    # Conclude without taking additional steps
    concluded = await orchestrator.conclude_investigation(
        plan_id=plan.investigation_id,
        final_hypothesis_id=hyp_id,
    )
    assert concluded.status == InvestigationStatus.CONCLUDED
    assert concluded.hypotheses[0].status == HypothesisStatus.CONFIRMED
    assert concluded.hypotheses[0].confidence == 0.5  # Model default preserved


@pytest.mark.asyncio
async def test_conclude_investigation_unknown_plan_raises_error(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """conclude_investigation on unknown plan raises InvestigationNotFoundError."""
    with pytest.raises(InvestigationNotFoundError):
        await orchestrator.conclude_investigation("unknown-plan-999", "hyp-123")


@pytest.mark.asyncio
async def test_conclude_investigation_unknown_hypothesis_raises_error(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """conclude_investigation with non-existent hypothesis ID raises HypothesisNotFoundError."""
    plan = await orchestrator.create_plan(initial_hypothesis="Initial hypothesis")

    with pytest.raises(HypothesisNotFoundError) as exc_info:
        await orchestrator.conclude_investigation(
            plan_id=plan.investigation_id,
            final_hypothesis_id="non-existent-hyp-id",
        )
    assert "non-existent-hyp-id" in str(exc_info.value)
    assert exc_info.value.error_code == "HYPOTHESIS_NOT_FOUND"


@pytest.mark.asyncio
async def test_cannot_conclude_already_concluded_investigation(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """Calling conclude_investigation twice raises InvalidInvestigationStateError."""
    plan = await orchestrator.create_plan(initial_hypothesis="Double conclusion test")
    hyp_id = plan.hypotheses[0].hypothesis_id

    await orchestrator.conclude_investigation(plan.investigation_id, final_hypothesis_id=hyp_id)

    with pytest.raises(InvalidInvestigationStateError):
        await orchestrator.conclude_investigation(plan.investigation_id, final_hypothesis_id=hyp_id)


@pytest.mark.asyncio
async def test_cannot_conclude_aborted_investigation(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """Concluding an aborted investigation raises InvalidInvestigationStateError."""
    plan = await orchestrator.create_plan(initial_hypothesis="Abort then conclude")
    hyp_id = plan.hypotheses[0].hypothesis_id

    await orchestrator.abort_investigation(plan.investigation_id, reason="Operator aborted")

    with pytest.raises(InvalidInvestigationStateError):
        await orchestrator.conclude_investigation(plan.investigation_id, final_hypothesis_id=hyp_id)


@pytest.mark.asyncio
async def test_abort_investigation_unknown_plan_raises_error(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """abort_investigation on unknown plan raises InvestigationNotFoundError."""
    with pytest.raises(InvestigationNotFoundError):
        await orchestrator.abort_investigation("unknown-plan-999")


@pytest.mark.asyncio
async def test_cannot_abort_already_concluded_or_aborted_investigation(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """Aborting a concluded or already aborted plan raises InvalidInvestigationStateError."""
    plan = await orchestrator.create_plan(initial_hypothesis="Abort edge case")
    hyp_id = plan.hypotheses[0].hypothesis_id

    await orchestrator.conclude_investigation(plan.investigation_id, final_hypothesis_id=hyp_id)

    with pytest.raises(InvalidInvestigationStateError):
        await orchestrator.abort_investigation(plan.investigation_id)


# =========================================================================
# Concurrency Safety Tests
# =========================================================================


@pytest.mark.asyncio
async def test_concurrent_advance_steps_maintain_monotonic_ordering(
    orchestrator: InvestigationOrchestratorEngine,
) -> None:
    """10 concurrent advance_step calls on same plan record unique, sequential step numbers."""
    plan = await orchestrator.create_plan(initial_hypothesis="Concurrent test", max_steps=10)

    async def _advance(idx: int) -> None:
        await orchestrator.advance_step(
            plan_id=plan.investigation_id,
            summary=f"Concurrent step {idx}",
        )

    tasks = [_advance(i) for i in range(10)]
    await asyncio.gather(*tasks)

    final_plan = await orchestrator.get_plan(plan.investigation_id)
    assert final_plan.current_step_count == 10
    assert len(final_plan.steps) == 10

    # Verify step numbers 1..10 are strictly present without duplicates
    step_numbers = [s.step_number for s in final_plan.steps]
    assert sorted(step_numbers) == list(range(1, 11))


# =========================================================================
# Error Serialization Tests
# =========================================================================


def test_investigation_error_serialization() -> None:
    """Investigation errors conform to PlatformError structured dictionary contract."""
    err = InvalidInvestigationStateError("plan-123", "concluded", "Cannot modify.")
    data = err.to_dict()
    assert data["error"] == "INVALID_INVESTIGATION_STATE"
    assert data["error_code"] == "INVALID_INVESTIGATION_STATE"
    assert "Cannot operate" in data["message"]
    assert data["details"]["plan_id"] == "plan-123"
    assert data["details"]["current_status"] == "concluded"

    sanitized = err.to_sanitized_dict()
    assert sanitized == data
