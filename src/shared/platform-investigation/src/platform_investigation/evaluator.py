"""Deterministic hypothesis evaluation runtime."""

from platform_core.errors import DomainValidationError
from platform_investigation.interfaces import HypothesisEvaluator
from platform_investigation.models import (
    EvidenceAggregationResult,
    Hypothesis,
    HypothesisEvaluationOutcome,
    HypothesisEvaluationResult,
)
from platform_observability.logging import get_logger

logger = get_logger(__name__)


class HypothesisEvaluatorEngine(HypothesisEvaluator):
    """Deterministic, pure synchronous hypothesis evaluation engine.

    Enforces:
    - Pure in-memory transformation (zero I/O, zero clock dependency).
    - Preservation of Hypothesis.status (lifecycle state unchanged).
    - Preservation of Hypothesis.confidence (zero mathematical scoring/weighting).
    - Preservation of DiagnosticEvidence.confidence_score (no re-scoring).
    - Non-overlap: S ∩ R == ∅ (fails closed with safe error if same evidence supports and refutes).
    - No duplicate support IDs or refute IDs (fails closed with safe error).
    - Referential integrity: all referenced evidence IDs must exist in evidence inventory.
    - Outcome derivation:
        - len(S) == 0 and len(R) == 0 -> UNEVALUATED
        - len(S) > 0 and len(R) == 0 -> SUPPORTED
        - len(S) == 0 and len(R) > 0 -> REFUTED
        - len(S) > 0 and len(R) > 0 -> INCONCLUSIVE
    - Complete input immutability (input models are never mutated).
    - Safe error messages (no raw IDs or customer data in error strings).
    """

    def evaluate(
        self,
        hypothesis: Hypothesis,
        evidence: EvidenceAggregationResult,
    ) -> HypothesisEvaluationResult:
        """Evaluate a single hypothesis against explicit evidence bindings."""
        if not isinstance(hypothesis, Hypothesis):
            raise DomainValidationError(
                "hypothesis must be an instance of Hypothesis.",
                field_name="hypothesis",
            )
        if not isinstance(evidence, EvidenceAggregationResult):
            raise DomainValidationError(
                "evidence must be an instance of EvidenceAggregationResult.",
                field_name="evidence",
            )
        if not hypothesis.hypothesis_id or not hypothesis.hypothesis_id.strip():
            raise DomainValidationError(
                "hypothesis.hypothesis_id cannot be empty.",
                field_name="hypothesis_id",
            )

        supporting_ids = hypothesis.supporting_evidence_ids
        refuting_ids = hypothesis.refuting_evidence_ids

        # 1. Validate no duplicate support IDs
        if len(supporting_ids) != len(set(supporting_ids)):
            raise DomainValidationError(
                "Hypothesis contains duplicate supporting evidence references.",
                field_name="supporting_evidence_ids",
            )

        # 2. Validate no duplicate refute IDs
        if len(refuting_ids) != len(set(refuting_ids)):
            raise DomainValidationError(
                "Hypothesis contains duplicate refuting evidence references.",
                field_name="refuting_evidence_ids",
            )

        # 3. Validate disjointness: S ∩ R == ∅
        support_set = set(supporting_ids)
        refute_set = set(refuting_ids)
        if not support_set.isdisjoint(refute_set):
            raise DomainValidationError(
                "Hypothesis contains conflicting support and refutation references.",
                field_name="evidence_references",
            )

        # 4. Referential integrity: check all referenced IDs exist in evidence inventory
        available_evidence_ids = {ev.evidence_id for ev in evidence.evidence}
        all_referenced_ids = support_set | refute_set
        if not all_referenced_ids.issubset(available_evidence_ids):
            raise DomainValidationError(
                "Hypothesis references evidence not present in the supplied evidence inventory.",
                field_name="evidence_references",
            )

        # 5. Derive deterministic evaluation outcome
        has_support = len(supporting_ids) > 0
        has_refute = len(refuting_ids) > 0

        if not has_support and not has_refute:
            outcome = HypothesisEvaluationOutcome.UNEVALUATED
        elif has_support and not has_refute:
            outcome = HypothesisEvaluationOutcome.SUPPORTED
        elif not has_support and has_refute:
            outcome = HypothesisEvaluationOutcome.REFUTED
        else:
            outcome = HypothesisEvaluationOutcome.INCONCLUSIVE

        logger.info(
            "Hypothesis evaluated",
            supporting_count=len(supporting_ids),
            refuting_count=len(refuting_ids),
            outcome=outcome.value,
        )

        return HypothesisEvaluationResult(
            hypothesis_id=hypothesis.hypothesis_id.strip(),
            outcome=outcome,
        )
