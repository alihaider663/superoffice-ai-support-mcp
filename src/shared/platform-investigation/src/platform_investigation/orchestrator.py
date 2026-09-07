"""Concrete deterministic InvestigationOrchestrator state machine runtime."""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

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
    InvestigationPlan,
    InvestigationStatus,
    InvestigationStep,
)
from platform_investigation.store import InMemoryInvestigationStore, InvestigationStore
from platform_observability.logging import get_logger

logger = get_logger(__name__)


class InvestigationOrchestratorEngine(InvestigationOrchestrator):
    """Deterministic, step-bounded investigation state machine runtime.

    Enforces:
    - Bounded execution ceiling via max_steps validation (1 <= max_steps <= 25).
    - Immutable terminal state safety (CONCLUDED, ABORTED).
    - Strict step counting and monotonic step numbering without drift.
    - Hypothesis tracking and lifecycle confirmation on formal conclusion.
    - Safe plan storage via pluggable InvestigationStore abstraction.
    """

    def __init__(
        self,
        store: InvestigationStore | None = None,
        *,
        default_max_steps: int = 10,
    ) -> None:
        self._store = store or InMemoryInvestigationStore()
        self._default_max_steps = default_max_steps
        self._lock = asyncio.Lock()

    async def create_plan(
        self,
        initial_hypothesis: str,
        max_steps: int | None = None,
    ) -> InvestigationPlan:
        """Create and initialize a new step-bounded diagnostic investigation plan."""
        if not initial_hypothesis or not initial_hypothesis.strip():
            raise DomainValidationError(
                "Initial hypothesis description cannot be empty.",
                field_name="initial_hypothesis",
            )

        steps_limit = max_steps if max_steps is not None else self._default_max_steps
        if not (1 <= steps_limit <= 25):
            raise DomainValidationError(
                f"max_steps must be between 1 and 25 (received {steps_limit}).",
                field_name="max_steps",
            )

        now = datetime.now(UTC)
        initial_hyp = Hypothesis(
            description=initial_hypothesis.strip(),
            status=HypothesisStatus.PROPOSED,
        )

        plan = InvestigationPlan(
            investigation_id=str(uuid4()),
            status=InvestigationStatus.INITIALIZED,
            max_steps=steps_limit,
            current_step_count=0,
            steps=(),
            hypotheses=(initial_hyp,),
            concluded_root_cause=None,
            created_at=now,
            updated_at=now,
        )

        await self._store.save_plan(plan)

        logger.info(
            "Investigation plan created",
            investigation_id=plan.investigation_id,
            max_steps=plan.max_steps,
            status=plan.status.value,
        )
        return plan

    async def get_plan(self, plan_id: str) -> InvestigationPlan:
        """Retrieve an existing investigation plan by its identifier (concrete engine helper)."""
        plan = await self._store.get_plan(plan_id)
        if plan is None:
            raise InvestigationNotFoundError(plan_id)
        return plan

    async def advance_step(
        self,
        plan_id: str,
        hypothesis: Hypothesis | None = None,
        *,
        action_taken: str = "Diagnostic step executed",
        summary: str = "Investigation step advanced",
        severity: str = "INFO",
        correlation_keys: Sequence[str] = (),
        collected_evidence_ids: Sequence[str] = (),
    ) -> InvestigationPlan:
        """Advance the diagnostic state machine, appending a step and validating bounds."""
        async with self._lock:
            plan = await self._store.get_plan(plan_id)
            if plan is None:
                raise InvestigationNotFoundError(plan_id)

            if plan.status in (InvestigationStatus.CONCLUDED, InvestigationStatus.ABORTED):
                raise InvalidInvestigationStateError(
                    plan_id=plan_id,
                    current_status=plan.status.value,
                    message=f"Cannot advance in terminal status '{plan.status.value}'.",
                )

            if plan.current_step_count >= plan.max_steps:
                if plan.status != InvestigationStatus.STEP_LIMIT_EXCEEDED:
                    plan = plan.model_copy(
                        update={
                            "status": InvestigationStatus.STEP_LIMIT_EXCEEDED,
                            "updated_at": datetime.now(UTC),
                        }
                    )
                    await self._store.save_plan(plan)
                raise StepLimitExceededError(plan_id=plan_id, max_steps=plan.max_steps)

            next_step_num = plan.current_step_count + 1

            new_step = InvestigationStep(
                step_number=next_step_num,
                action_taken=action_taken,
                summary=summary,
                severity=severity,
                correlation_keys=tuple(correlation_keys),
                collected_evidence_ids=tuple(collected_evidence_ids),
                timestamp=datetime.now(UTC),
            )

            updated_hypotheses: list[Hypothesis] = list(plan.hypotheses)
            if hypothesis is not None:
                replaced = False
                for idx, existing_hyp in enumerate(updated_hypotheses):
                    if existing_hyp.hypothesis_id == hypothesis.hypothesis_id:
                        updated_hypotheses[idx] = hypothesis
                        replaced = True
                        break
                if not replaced:
                    updated_hypotheses.append(hypothesis)

            now = datetime.now(UTC)
            updated_plan = plan.model_copy(
                update={
                    "status": InvestigationStatus.IN_PROGRESS,
                    "current_step_count": next_step_num,
                    "steps": (*plan.steps, new_step),
                    "hypotheses": tuple(updated_hypotheses),
                    "updated_at": now,
                }
            )

            await self._store.save_plan(updated_plan)

            logger.info(
                "Investigation step advanced",
                investigation_id=plan_id,
                step_number=next_step_num,
                max_steps=plan.max_steps,
                status=updated_plan.status.value,
            )
            return updated_plan

    async def conclude_investigation(
        self,
        plan_id: str,
        final_hypothesis_id: str,
    ) -> InvestigationPlan:
        """Conclude an investigation with a validated root-cause hypothesis."""
        async with self._lock:
            plan = await self._store.get_plan(plan_id)
            if plan is None:
                raise InvestigationNotFoundError(plan_id)

            if plan.status in (InvestigationStatus.CONCLUDED, InvestigationStatus.ABORTED):
                raise InvalidInvestigationStateError(
                    plan_id=plan_id,
                    current_status=plan.status.value,
                    message=f"Cannot conclude already in terminal status '{plan.status.value}'.",
                )

            matched_hyp: Hypothesis | None = None
            updated_hypotheses: list[Hypothesis] = []
            for hyp in plan.hypotheses:
                if hyp.hypothesis_id == final_hypothesis_id:
                    matched_hyp = hyp.model_copy(update={"status": HypothesisStatus.CONFIRMED})
                    updated_hypotheses.append(matched_hyp)
                else:
                    updated_hypotheses.append(hyp)

            if matched_hyp is None:
                raise HypothesisNotFoundError(plan_id=plan_id, hypothesis_id=final_hypothesis_id)

            now = datetime.now(UTC)
            concluded_plan = plan.model_copy(
                update={
                    "status": InvestigationStatus.CONCLUDED,
                    "hypotheses": tuple(updated_hypotheses),
                    "concluded_root_cause": matched_hyp.description,
                    "updated_at": now,
                }
            )

            await self._store.save_plan(concluded_plan)

            logger.info(
                "Investigation concluded successfully",
                investigation_id=plan_id,
                final_hypothesis_id=final_hypothesis_id,
                root_cause=matched_hyp.description,
            )
            return concluded_plan

    async def abort_investigation(
        self,
        plan_id: str,
        reason: str = "Investigation aborted by operator",
    ) -> InvestigationPlan:
        """Abort an active investigation (concrete engine helper)."""
        async with self._lock:
            plan = await self._store.get_plan(plan_id)
            if plan is None:
                raise InvestigationNotFoundError(plan_id)

            if plan.status in (InvestigationStatus.CONCLUDED, InvestigationStatus.ABORTED):
                raise InvalidInvestigationStateError(
                    plan_id=plan_id,
                    current_status=plan.status.value,
                    message=f"Cannot abort already in terminal status '{plan.status.value}'.",
                )

            now = datetime.now(UTC)
            aborted_plan = plan.model_copy(
                update={
                    "status": InvestigationStatus.ABORTED,
                    "concluded_root_cause": f"Aborted: {reason}",
                    "updated_at": now,
                }
            )

            await self._store.save_plan(aborted_plan)

            logger.info(
                "Investigation aborted",
                investigation_id=plan_id,
                reason=reason,
            )
            return aborted_plan
