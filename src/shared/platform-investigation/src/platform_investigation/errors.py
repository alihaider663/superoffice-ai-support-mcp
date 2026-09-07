"""Standard hierarchical exceptions for the Investigation Layer."""

from typing import Any

from platform_core.errors import PlatformError


class InvestigationError(PlatformError):
    """Base exception for all investigation state machine and diagnostic orchestration errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "INVESTIGATION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, error_code=error_code, details=details)


class InvestigationNotFoundError(InvestigationError):
    """Raised when an investigation plan cannot be found by its identifier."""

    def __init__(self, plan_id: str) -> None:
        super().__init__(
            f"Investigation plan with identifier '{plan_id}' was not found.",
            error_code="INVESTIGATION_NOT_FOUND",
            details={"plan_id": plan_id},
        )
        self.plan_id = plan_id


class InvalidInvestigationStateError(InvestigationError):
    """Raised when an operation is invalid for the investigation's current lifecycle state."""

    def __init__(self, plan_id: str, current_status: str, message: str) -> None:
        msg = f"Cannot operate on investigation '{plan_id}' in state '{current_status}': {message}"
        super().__init__(
            msg,
            error_code="INVALID_INVESTIGATION_STATE",
            details={"plan_id": plan_id, "current_status": current_status},
        )
        self.plan_id = plan_id
        self.current_status = current_status


class StepLimitExceededError(InvestigationError):
    """Raised when an investigation exceeds its configured maximum step ceiling."""

    def __init__(self, plan_id: str, max_steps: int) -> None:
        super().__init__(
            f"Investigation plan '{plan_id}' has reached its maximum step limit of {max_steps}.",
            error_code="STEP_LIMIT_EXCEEDED",
            details={"plan_id": plan_id, "max_steps": max_steps},
        )
        self.plan_id = plan_id
        self.max_steps = max_steps


class HypothesisNotFoundError(InvestigationError):
    """Raised when a specified hypothesis ID does not exist in the target investigation plan."""

    def __init__(self, plan_id: str, hypothesis_id: str) -> None:
        super().__init__(
            f"Hypothesis '{hypothesis_id}' not found in investigation plan '{plan_id}'.",
            error_code="HYPOTHESIS_NOT_FOUND",
            details={"plan_id": plan_id, "hypothesis_id": hypothesis_id},
        )
        self.plan_id = plan_id
        self.hypothesis_id = hypothesis_id


class DuplicateEvidenceIdError(InvestigationError):
    """Raised when the same evidence identifier is emitted multiple times in an aggregation pass."""

    def __init__(self, evidence_id: str) -> None:
        super().__init__(
            f"Duplicate evidence identifier '{evidence_id}' detected during aggregation.",
            error_code="DUPLICATE_EVIDENCE_ID",
            details={"evidence_id": evidence_id},
        )
        self.evidence_id = evidence_id


class EvidenceProvenanceMismatchError(InvestigationError):
    """Raised when an evidence item's source_type does not match its declaring collector outcome."""

    def __init__(self, expected_source: str, actual_source: str, evidence_id: str) -> None:
        msg = (
            f"Evidence item '{evidence_id}' has source_type '{actual_source}' "
            f"which does not match collector source_type '{expected_source}'."
        )
        super().__init__(
            msg,
            error_code="EVIDENCE_PROVENANCE_MISMATCH",
            details={
                "expected_source": expected_source,
                "actual_source": actual_source,
                "evidence_id": evidence_id,
            },
        )
        self.expected_source = expected_source
        self.actual_source = actual_source
        self.evidence_id = evidence_id
