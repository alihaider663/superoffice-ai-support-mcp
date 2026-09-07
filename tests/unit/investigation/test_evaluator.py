"""Unit tests for HypothesisEvaluatorEngine and evaluation models."""

import pytest

from platform_core.errors import DomainValidationError
from platform_investigation.evaluator import HypothesisEvaluatorEngine
from platform_investigation.interfaces import HypothesisEvaluator
from platform_investigation.models import (
    DiagnosticEvidence,
    EvidenceAggregationResult,
    EvidenceSourceType,
    Hypothesis,
    HypothesisEvaluationOutcome,
    HypothesisEvaluationResult,
    HypothesisStatus,
    SourceCollectionResult,
    SourceCollectionStatus,
)


def _make_evidence(
    source_type: EvidenceSourceType,
    evidence_id: str,
    title: str = "Test Evidence",
    confidence: float = 0.9,
    data: dict[str, object] | None = None,
) -> DiagnosticEvidence:
    return DiagnosticEvidence(
        evidence_id=evidence_id,
        source_type=source_type,
        title=title,
        confidence_score=confidence,
        data=data or {"raw_key": "raw_val"},
    )


def _make_aggregation_result(
    investigation_id: str,
    evidence: tuple[DiagnosticEvidence, ...],
    other_outcomes: tuple[SourceCollectionResult, ...] = (),
) -> EvidenceAggregationResult:
    outcomes: list[SourceCollectionResult] = []
    sources_seen: list[EvidenceSourceType] = []
    source_to_evidence: dict[EvidenceSourceType, list[DiagnosticEvidence]] = {}

    for ev in evidence:
        if ev.source_type not in source_to_evidence:
            sources_seen.append(ev.source_type)
            source_to_evidence[ev.source_type] = []
        source_to_evidence[ev.source_type].append(ev)

    for st in sources_seen:
        outcomes.append(
            SourceCollectionResult(
                source_type=st,
                status=SourceCollectionStatus.SUCCESS,
                evidence=tuple(source_to_evidence[st]),
            )
        )

    if not outcomes and not other_outcomes:
        outcomes.append(
            SourceCollectionResult(
                source_type=EvidenceSourceType.SUPEROFFICE_CRM,
                status=SourceCollectionStatus.SUCCESS,
                evidence=(),
            )
        )

    return EvidenceAggregationResult(
        investigation_id=investigation_id,
        correlation_key="test-correlation-key",
        source_outcomes=(*outcomes, *other_outcomes),
    )


# =========================================================================
# Protocol & Model Tests
# =========================================================================


def test_engine_implements_protocol() -> None:
    """HypothesisEvaluatorEngine implements HypothesisEvaluator protocol."""
    engine = HypothesisEvaluatorEngine()
    assert isinstance(engine, HypothesisEvaluator)


def test_evaluation_result_model() -> None:
    """HypothesisEvaluationResult correctly records target ID and outcome."""
    result = HypothesisEvaluationResult(
        hypothesis_id="hyp-100",
        outcome=HypothesisEvaluationOutcome.SUPPORTED,
    )
    assert result.hypothesis_id == "hyp-100"
    assert result.outcome == HypothesisEvaluationOutcome.SUPPORTED


# =========================================================================
# Deterministic Outcome Semantics Tests
# =========================================================================


def test_evaluate_unevaluated_when_no_evidence_relationships() -> None:
    """Hypothesis with no supporting or refuting evidence evaluates to UNEVALUATED."""
    ev = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-1")
    agg = _make_aggregation_result("inv-1", (ev,))
    hyp = Hypothesis(
        description="Database connection pool starvation",
        supporting_evidence_ids=(),
        refuting_evidence_ids=(),
    )
    engine = HypothesisEvaluatorEngine()

    result = engine.evaluate(hyp, agg)

    assert result.hypothesis_id == hyp.hypothesis_id
    assert result.outcome == HypothesisEvaluationOutcome.UNEVALUATED


def test_evaluate_supported_when_only_supporting_evidence_exists() -> None:
    """Hypothesis with supporting evidence and zero refuting evidence evaluates to SUPPORTED."""
    ev1 = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-1")
    ev2 = _make_evidence(EvidenceSourceType.MSSQL_DIAGNOSTICS, "ev-2")
    agg = _make_aggregation_result("inv-1", (ev1, ev2))
    hyp = Hypothesis(
        description="Deadlock on Task table",
        supporting_evidence_ids=("ev-1", "ev-2"),
        refuting_evidence_ids=(),
    )
    engine = HypothesisEvaluatorEngine()

    result = engine.evaluate(hyp, agg)

    assert result.outcome == HypothesisEvaluationOutcome.SUPPORTED


def test_evaluate_refuted_when_only_refuting_evidence_exists() -> None:
    """Hypothesis with refuting evidence and zero supporting evidence evaluates to REFUTED."""
    ev1 = _make_evidence(EvidenceSourceType.APPLICATION_LOGS, "ev-log")
    agg = _make_aggregation_result("inv-1", (ev1,))
    hyp = Hypothesis(
        description="Authentication service outage",
        supporting_evidence_ids=(),
        refuting_evidence_ids=("ev-log",),
    )
    engine = HypothesisEvaluatorEngine()

    result = engine.evaluate(hyp, agg)

    assert result.outcome == HypothesisEvaluationOutcome.REFUTED


def test_evaluate_inconclusive_when_both_support_and_refute_exist() -> None:
    """Hypothesis with distinct supporting and refuting evidence evaluates to INCONCLUSIVE."""
    ev_supp = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-supp")
    ev_ref = _make_evidence(EvidenceSourceType.MSSQL_DIAGNOSTICS, "ev-ref")
    agg = _make_aggregation_result("inv-1", (ev_supp, ev_ref))
    hyp = Hypothesis(
        description="Memory pressure causing slow queries",
        supporting_evidence_ids=("ev-supp",),
        refuting_evidence_ids=("ev-ref",),
    )
    engine = HypothesisEvaluatorEngine()

    result = engine.evaluate(hyp, agg)

    assert result.outcome == HypothesisEvaluationOutcome.INCONCLUSIVE


def test_mixed_evidence_counts_do_not_use_majority_rule() -> None:
    """Mixed evidence evaluates to INCONCLUSIVE regardless of support vs refute counts."""
    ev_s1 = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-s1")
    ev_s2 = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-s2")
    ev_s3 = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-s3")
    ev_r1 = _make_evidence(EvidenceSourceType.MSSQL_DIAGNOSTICS, "ev-r1")
    ev_r2 = _make_evidence(EvidenceSourceType.MSSQL_DIAGNOSTICS, "ev-r2")
    ev_r3 = _make_evidence(EvidenceSourceType.MSSQL_DIAGNOSTICS, "ev-r3")

    agg = _make_aggregation_result("inv-1", (ev_s1, ev_s2, ev_s3, ev_r1, ev_r2, ev_r3))
    engine = HypothesisEvaluatorEngine()

    # Case 1: 3 support, 1 refute -> INCONCLUSIVE (not SUPPORTED)
    hyp_majority_support = Hypothesis(
        description="Hypothesis with majority support",
        supporting_evidence_ids=("ev-s1", "ev-s2", "ev-s3"),
        refuting_evidence_ids=("ev-r1",),
    )
    res1 = engine.evaluate(hyp_majority_support, agg)
    assert res1.outcome == HypothesisEvaluationOutcome.INCONCLUSIVE

    # Case 2: 1 support, 3 refute -> INCONCLUSIVE (not REFUTED)
    hyp_majority_refute = Hypothesis(
        description="Hypothesis with majority refutation",
        supporting_evidence_ids=("ev-s1",),
        refuting_evidence_ids=("ev-r1", "ev-r2", "ev-r3"),
    )
    res2 = engine.evaluate(hyp_majority_refute, agg)
    assert res2.outcome == HypothesisEvaluationOutcome.INCONCLUSIVE


# =========================================================================
# Referential Integrity & Validation Tests
# =========================================================================


def test_rejects_overlapping_support_and_refute_references() -> None:
    """Fails closed when the same evidence ID appears in both support and refute sets."""
    ev = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-conflict")
    agg = _make_aggregation_result("inv-1", (ev,))
    hyp = Hypothesis(
        description="Contradictory hypothesis",
        supporting_evidence_ids=("ev-conflict",),
        refuting_evidence_ids=("ev-conflict",),
    )
    engine = HypothesisEvaluatorEngine()

    with pytest.raises(DomainValidationError) as exc_info:
        engine.evaluate(hyp, agg)

    err_str = str(exc_info.value)
    assert "Hypothesis contains conflicting support and refutation references." in err_str
    assert "ev-conflict" not in err_str


def test_rejects_duplicate_supporting_evidence_ids() -> None:
    """Fails closed when supporting_evidence_ids contains duplicate IDs."""
    ev = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-dup")
    agg = _make_aggregation_result("inv-1", (ev,))
    hyp = Hypothesis(
        description="Duplicate support hypothesis",
        supporting_evidence_ids=("ev-dup", "ev-dup"),
        refuting_evidence_ids=(),
    )
    engine = HypothesisEvaluatorEngine()

    with pytest.raises(DomainValidationError) as exc_info:
        engine.evaluate(hyp, agg)

    err_str = str(exc_info.value)
    assert "Hypothesis contains duplicate supporting evidence references." in err_str
    assert "ev-dup" not in err_str


def test_rejects_duplicate_refuting_evidence_ids() -> None:
    """Fails closed when refuting_evidence_ids contains duplicate IDs."""
    ev = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-dup-r")
    agg = _make_aggregation_result("inv-1", (ev,))
    hyp = Hypothesis(
        description="Duplicate refute hypothesis",
        supporting_evidence_ids=(),
        refuting_evidence_ids=("ev-dup-r", "ev-dup-r"),
    )
    engine = HypothesisEvaluatorEngine()

    with pytest.raises(DomainValidationError) as exc_info:
        engine.evaluate(hyp, agg)

    err_str = str(exc_info.value)
    assert "Hypothesis contains duplicate refuting evidence references." in err_str
    assert "ev-dup-r" not in err_str


def test_rejects_unknown_evidence_ids_with_safe_error_message() -> None:
    """Fails closed on unknown evidence references without leaking IDs in error message."""
    ev = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-known")
    agg = _make_aggregation_result("inv-1", (ev,))
    sensitive_fake_id = "SECRET-EVIDENCE-ID-98765"
    hyp = Hypothesis(
        description="Unknown reference hypothesis",
        supporting_evidence_ids=(sensitive_fake_id,),
        refuting_evidence_ids=(),
    )
    engine = HypothesisEvaluatorEngine()

    with pytest.raises(DomainValidationError) as exc_info:
        engine.evaluate(hyp, agg)

    err_str = str(exc_info.value)
    msg = "Hypothesis references evidence not present in the supplied evidence inventory."
    assert msg in err_str
    assert sensitive_fake_id not in err_str


def test_input_type_and_id_validation() -> None:
    """Evaluator rejects invalid input types and empty hypothesis_id."""
    engine = HypothesisEvaluatorEngine()
    ev = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-1")
    agg = _make_aggregation_result("inv-1", (ev,))
    hyp = Hypothesis(description="Valid")

    with pytest.raises(DomainValidationError):
        engine.evaluate("not_a_hypothesis", agg)  # type: ignore[arg-type]

    with pytest.raises(DomainValidationError):
        engine.evaluate(hyp, "not_an_aggregation_result")  # type: ignore[arg-type]

    bad_hyp = hyp.model_copy(update={"hypothesis_id": ""})
    with pytest.raises(DomainValidationError):
        engine.evaluate(bad_hyp, agg)


# =========================================================================
# Lifecycle & Confidence Preservation Tests
# =========================================================================


def test_hypothesis_status_and_lifecycle_separation() -> None:
    """Evaluating a hypothesis produces an outcome without mutating Hypothesis.status."""
    ev = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-1")
    agg = _make_aggregation_result("inv-1", (ev,))
    hyp = Hypothesis(
        status=HypothesisStatus.PROPOSED,
        description="Lifecycle separation test",
        supporting_evidence_ids=("ev-1",),
    )
    engine = HypothesisEvaluatorEngine()

    result = engine.evaluate(hyp, agg)

    # Result outcome is SUPPORTED
    assert result.outcome == HypothesisEvaluationOutcome.SUPPORTED

    # Original Hypothesis lifecycle status remains strictly PROPOSED (not CONFIRMED)
    assert hyp.status == HypothesisStatus.PROPOSED


def test_hypothesis_confidence_preserved_unchanged() -> None:
    """Evaluator preserves Hypothesis.confidence without applying score adjustments."""
    ev = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-1", confidence=1.0)
    agg = _make_aggregation_result("inv-1", (ev,))
    hyp = Hypothesis(
        confidence=0.73,
        description="Confidence preservation test",
        supporting_evidence_ids=("ev-1",),
    )
    engine = HypothesisEvaluatorEngine()

    result = engine.evaluate(hyp, agg)

    assert result.outcome == HypothesisEvaluationOutcome.SUPPORTED
    assert hyp.confidence == 0.73  # Untouched


def test_diagnostic_evidence_confidence_score_preserved() -> None:
    """DiagnosticEvidence confidence_score is never altered during evaluation."""
    ev = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-1", confidence=0.88)
    agg = _make_aggregation_result("inv-1", (ev,))
    hyp = Hypothesis(
        description="Evidence confidence preservation test",
        supporting_evidence_ids=("ev-1",),
    )
    engine = HypothesisEvaluatorEngine()

    engine.evaluate(hyp, agg)

    assert ev.confidence_score == 0.88


def test_source_failures_and_zero_evidence_not_treated_as_refutation() -> None:
    """Unavailable/failed sources in aggregation result do not create false refutations."""
    outcome_blocked = SourceCollectionResult(
        source_type=EvidenceSourceType.MSSQL_DIAGNOSTICS,
        status=SourceCollectionStatus.BLOCKED,
        evidence=(),
        error_code="PHASE_2B_3_BLOCKED_SCHEMA",
    )
    outcome_failed = SourceCollectionResult(
        source_type=EvidenceSourceType.KNOWLEDGE_BASE,
        status=SourceCollectionStatus.FAILED,
        evidence=(),
        error_code="SOURCE_EXECUTION_FAILED",
    )
    agg = _make_aggregation_result(
        "inv-part",
        evidence=(),
        other_outcomes=(outcome_blocked, outcome_failed),
    )
    hyp = Hypothesis(description="No relationships")
    engine = HypothesisEvaluatorEngine()

    result = engine.evaluate(hyp, agg)

    # Empty relationships with failed sources evaluates to UNEVALUATED (not REFUTED)
    assert result.outcome == HypothesisEvaluationOutcome.UNEVALUATED


def test_repeated_evaluation_is_deterministic() -> None:
    """Repeated evaluation of the same inputs yields 100% equal results."""
    ev = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-1")
    agg = _make_aggregation_result("inv-1", (ev,))
    hyp = Hypothesis(
        description="Deterministic evaluation",
        supporting_evidence_ids=("ev-1",),
    )
    engine = HypothesisEvaluatorEngine()

    run1 = engine.evaluate(hyp, agg)
    run2 = engine.evaluate(hyp, agg)

    assert run1 == run2


def test_inputs_are_immutable() -> None:
    """Evaluator does not mutate input Hypothesis or EvidenceAggregationResult."""
    ev = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-1", data={"key": "val"})
    agg = _make_aggregation_result("inv-1", (ev,))
    hyp = Hypothesis(
        description="Immutability test",
        supporting_evidence_ids=("ev-1",),
    )
    engine = HypothesisEvaluatorEngine()

    engine.evaluate(hyp, agg)

    assert hyp.supporting_evidence_ids == ("ev-1",)
    assert hyp.refuting_evidence_ids == ()
    assert agg.evidence[0].data == {"key": "val"}
