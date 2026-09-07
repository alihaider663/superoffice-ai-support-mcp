"""Unit tests for IncidentCorrelationEngine and timeline domain models."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from platform_core.errors import DomainValidationError
from platform_investigation.interfaces import IncidentCorrelator
from platform_investigation.models import (
    CorrelationGroup,
    CorrelationReference,
    DiagnosticEvidence,
    EvidenceAggregationResult,
    EvidenceSourceType,
    SourceCollectionResult,
    SourceCollectionStatus,
)
from platform_investigation.timeline import IncidentCorrelationEngine


def _make_evidence(
    source_type: EvidenceSourceType,
    evidence_id: str,
    title: str = "Test Evidence",
    *,
    timestamp: datetime | None = None,
    confidence: float = 0.9,
    correlation_refs: tuple[CorrelationReference, ...] = (),
    data: dict[str, object] | None = None,
    tags: tuple[str, ...] = ("diag",),
) -> DiagnosticEvidence:
    return DiagnosticEvidence(
        evidence_id=evidence_id,
        source_type=source_type,
        title=title,
        timestamp=timestamp or datetime.now(UTC),
        confidence_score=confidence,
        data=data or {"raw_key": "raw_val"},
        tags=tags,
        correlation_references=correlation_refs,
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
# Model & Contract Tests
# =========================================================================


def test_correlation_reference_validation() -> None:
    """CorrelationReference requires non-empty, non-whitespace-padded namespace and value."""
    ref = CorrelationReference(namespace="ticket", value="10209")
    assert ref.namespace == "ticket"
    assert ref.value == "10209"

    # Empty
    with pytest.raises(ValidationError):
        CorrelationReference(namespace="", value="10209")
    with pytest.raises(ValidationError):
        CorrelationReference(namespace="ticket", value="")

    # Whitespace-only
    with pytest.raises(ValidationError):
        CorrelationReference(namespace="   ", value="10209")
    with pytest.raises(ValidationError):
        CorrelationReference(namespace="ticket", value="   ")

    # Leading/trailing whitespace rejected
    with pytest.raises(ValidationError):
        CorrelationReference(namespace=" ticket", value="10209")
    with pytest.raises(ValidationError):
        CorrelationReference(namespace="ticket ", value="10209")
    with pytest.raises(ValidationError):
        CorrelationReference(namespace="ticket", value=" 10209")
    with pytest.raises(ValidationError):
        CorrelationReference(namespace="ticket", value="10209 ")


def test_diagnostic_evidence_correlation_references_default_and_uniqueness() -> None:
    """DiagnosticEvidence defaults correlation_references to empty and rejects duplicates."""
    ev = DiagnosticEvidence(
        source_type=EvidenceSourceType.SUPEROFFICE_CRM,
        title="Sample",
    )
    assert ev.correlation_references == ()

    ref1 = CorrelationReference(namespace="ticket", value="10209")
    ref2 = CorrelationReference(namespace="trace", value="req-1")

    # Multiple distinct references accepted
    ev_multi = DiagnosticEvidence(
        source_type=EvidenceSourceType.SUPEROFFICE_CRM,
        title="Multi",
        correlation_references=(ref1, ref2),
    )
    assert len(ev_multi.correlation_references) == 2

    # Duplicate exact references rejected with safe message exposing zero values
    sensitive_ref = CorrelationReference(
        namespace="internal_system",
        value="SECRET-CORRELATION-KEY-12345",
    )
    with pytest.raises(ValidationError) as exc_info:
        DiagnosticEvidence(
            source_type=EvidenceSourceType.SUPEROFFICE_CRM,
            title="Duplicate",
            correlation_references=(sensitive_ref, sensitive_ref),
        )

    err_str = str(exc_info.value)
    assert "DiagnosticEvidence contains a duplicate correlation reference." in err_str
    assert "SECRET-CORRELATION-KEY-12345" not in err_str
    assert "internal_system" not in err_str


def test_diagnostic_evidence_allows_same_value_in_different_namespaces() -> None:
    """DiagnosticEvidence accepts same value when namespaces differ."""
    ref_ticket = CorrelationReference(namespace="ticket", value="100")
    ref_spid = CorrelationReference(namespace="spid", value="100")

    ev = DiagnosticEvidence(
        source_type=EvidenceSourceType.SUPEROFFICE_CRM,
        title="Diff Namespaces",
        correlation_references=(ref_ticket, ref_spid),
    )
    assert len(ev.correlation_references) == 2


def test_correlation_group_cardinality_and_distinct_evidence_ids() -> None:
    """CorrelationGroup rejects groups with fewer than 2 items or duplicate evidence IDs."""
    ref = CorrelationReference(namespace="trace", value="req-1")

    # Valid with >= 2 distinct items
    group = CorrelationGroup(correlation_reference=ref, evidence_ids=("ev-1", "ev-2"))
    assert group.total_evidence == 2

    # Invalid with 1 item
    with pytest.raises(ValidationError):
        CorrelationGroup(correlation_reference=ref, evidence_ids=("ev-1",))

    # Invalid with 0 items
    with pytest.raises(ValidationError):
        CorrelationGroup(correlation_reference=ref, evidence_ids=())

    # Invalid with duplicate evidence IDs
    with pytest.raises(ValidationError):
        CorrelationGroup(correlation_reference=ref, evidence_ids=("ev-1", "ev-1"))


def test_engine_implements_protocol() -> None:
    """IncidentCorrelationEngine implements IncidentCorrelator protocol."""
    engine = IncidentCorrelationEngine()
    assert isinstance(engine, IncidentCorrelator)


# =========================================================================
# Timeline Construction & Ordering Tests
# =========================================================================


def test_build_timeline_zero_evidence() -> None:
    """Empty aggregation result yields empty timeline with zero events and groups."""
    agg = _make_aggregation_result("inv-empty", ())
    engine = IncidentCorrelationEngine()

    timeline = engine.build_timeline(agg)

    assert timeline.investigation_id == "inv-empty"
    assert timeline.total_events == 0
    assert timeline.total_groups == 0
    assert timeline.events == ()
    assert timeline.correlation_groups == ()


def test_build_timeline_single_evidence_item_no_group() -> None:
    """Single evidence item produces a TimelineEvent but no CorrelationGroup (threshold < 2)."""
    ref = CorrelationReference(namespace="ticket", value="100")
    t0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
    ev = _make_evidence(
        EvidenceSourceType.SUPEROFFICE_CRM,
        "ev-single",
        "Single Observation",
        timestamp=t0,
        correlation_refs=(ref,),
    )

    agg = _make_aggregation_result("inv-1", (ev,))
    engine = IncidentCorrelationEngine()

    timeline = engine.build_timeline(agg)

    assert timeline.total_events == 1
    assert timeline.total_groups == 0  # Below group threshold
    event = timeline.events[0]
    assert event.evidence_id == "ev-single"
    assert event.source_type == EvidenceSourceType.SUPEROFFICE_CRM
    assert event.timestamp == t0
    assert event.title == "Single Observation"
    assert event.correlation_references == (ref,)


def test_build_timeline_chronological_ordering() -> None:
    """Evidence items with out-of-order timestamps are sorted chronologically ascending."""
    t0 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=5)
    t2 = t0 + timedelta(minutes=10)

    # Input in scrambled temporal order (t2, t0, t1)
    ev_late = _make_evidence(EvidenceSourceType.MSSQL_DIAGNOSTICS, "ev-late", timestamp=t2)
    ev_early = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-early", timestamp=t0)
    ev_mid = _make_evidence(EvidenceSourceType.APPLICATION_LOGS, "ev-mid", timestamp=t1)

    agg = _make_aggregation_result("inv-sort", (ev_late, ev_early, ev_mid))
    engine = IncidentCorrelationEngine()

    timeline = engine.build_timeline(agg)

    assert [e.evidence_id for e in timeline.events] == ["ev-early", "ev-mid", "ev-late"]
    assert [e.timestamp for e in timeline.events] == [t0, t1, t2]


def test_build_timeline_identical_timestamp_preserves_aggregate_input_order() -> None:
    """Evidence items with identical timestamps preserve stable aggregate sequence order."""
    t_same = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)

    ev_a = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-A", timestamp=t_same)
    ev_b = _make_evidence(EvidenceSourceType.MSSQL_DIAGNOSTICS, "ev-B", timestamp=t_same)
    ev_c = _make_evidence(EvidenceSourceType.KNOWLEDGE_BASE, "ev-C", timestamp=t_same)

    agg = _make_aggregation_result("inv-tie", (ev_a, ev_b, ev_c))
    engine = IncidentCorrelationEngine()

    timeline = engine.build_timeline(agg)

    assert [e.evidence_id for e in timeline.events] == ["ev-A", "ev-B", "ev-C"]


# =========================================================================
# Explicit Correlation Grouping Tests
# =========================================================================


def test_build_timeline_correlation_grouping_with_threshold() -> None:
    """Exact correlation references shared by >= 2 items form groups in first-seen order."""
    ref_ticket = CorrelationReference(namespace="ticket", value="10209")
    ref_session = CorrelationReference(namespace="session", value="sess-xyz")
    ref_single = CorrelationReference(namespace="unique", value="only-one")

    ev1 = _make_evidence(
        EvidenceSourceType.SUPEROFFICE_CRM,
        "ev-1",
        correlation_refs=(ref_ticket, ref_session),
    )
    ev2 = _make_evidence(
        EvidenceSourceType.MSSQL_DIAGNOSTICS,
        "ev-2",
        correlation_refs=(ref_ticket, ref_single),
    )
    ev3 = _make_evidence(
        EvidenceSourceType.APPLICATION_LOGS,
        "ev-3",
        correlation_refs=(ref_session,),
    )

    agg = _make_aggregation_result("inv-groups", (ev1, ev2, ev3))
    engine = IncidentCorrelationEngine()

    timeline = engine.build_timeline(agg)

    assert timeline.total_events == 3
    assert timeline.total_groups == 2

    # Group 1: ref_ticket (first seen on ev1)
    g1 = timeline.correlation_groups[0]
    assert g1.correlation_reference == ref_ticket
    assert g1.evidence_ids == ("ev-1", "ev-2")

    # Group 2: ref_session (first seen on ev1)
    g2 = timeline.correlation_groups[1]
    assert g2.correlation_reference == ref_session
    assert g2.evidence_ids == ("ev-1", "ev-3")


def test_correlation_namespace_isolation() -> None:
    """References with identical values but different namespaces are strictly isolated."""
    ref_ticket = CorrelationReference(namespace="ticket", value="100")
    ref_spid = CorrelationReference(namespace="spid", value="100")

    ev1 = _make_evidence(
        EvidenceSourceType.SUPEROFFICE_CRM,
        "ev-1",
        correlation_refs=(ref_ticket,),
    )
    ev2 = _make_evidence(
        EvidenceSourceType.MSSQL_DIAGNOSTICS,
        "ev-2",
        correlation_refs=(ref_spid,),
    )
    ev3 = _make_evidence(
        EvidenceSourceType.MSSQL_DIAGNOSTICS,
        "ev-3",
        correlation_refs=(ref_spid,),
    )

    agg = _make_aggregation_result("inv-ns", (ev1, ev2, ev3))
    engine = IncidentCorrelationEngine()

    timeline = engine.build_timeline(agg)

    # ref_ticket only has 1 item -> no group
    # ref_spid has 2 items -> 1 group
    assert timeline.total_groups == 1
    assert timeline.correlation_groups[0].correlation_reference == ref_spid
    assert timeline.correlation_groups[0].evidence_ids == ("ev-2", "ev-3")


def test_no_transitive_clustering() -> None:
    """Transitive references (A-B via X, B-C via Y) are kept in distinct groups and not merged."""
    ref_x = CorrelationReference(namespace="key", value="X")
    ref_y = CorrelationReference(namespace="key", value="Y")

    ev_a = _make_evidence(
        EvidenceSourceType.SUPEROFFICE_CRM,
        "ev-A",
        correlation_refs=(ref_x,),
    )
    ev_b = _make_evidence(
        EvidenceSourceType.MSSQL_DIAGNOSTICS,
        "ev-B",
        correlation_refs=(ref_x, ref_y),
    )
    ev_c = _make_evidence(
        EvidenceSourceType.APPLICATION_LOGS,
        "ev-C",
        correlation_refs=(ref_y,),
    )

    agg = _make_aggregation_result("inv-notrans", (ev_a, ev_b, ev_c))
    engine = IncidentCorrelationEngine()

    timeline = engine.build_timeline(agg)

    assert timeline.total_groups == 2
    assert timeline.correlation_groups[0].correlation_reference == ref_x
    assert timeline.correlation_groups[0].evidence_ids == ("ev-A", "ev-B")

    assert timeline.correlation_groups[1].correlation_reference == ref_y
    assert timeline.correlation_groups[1].evidence_ids == ("ev-B", "ev-C")


def test_uncorrelated_evidence_remains_in_timeline() -> None:
    """Evidence without correlation references appears in timeline events without error."""
    ev_corr = _make_evidence(
        EvidenceSourceType.SUPEROFFICE_CRM,
        "ev-corr-1",
        correlation_refs=(CorrelationReference(namespace="t", value="1"),),
    )
    ev_corr2 = _make_evidence(
        EvidenceSourceType.SUPEROFFICE_CRM,
        "ev-corr-2",
        correlation_refs=(CorrelationReference(namespace="t", value="1"),),
    )
    ev_bare = _make_evidence(
        EvidenceSourceType.KNOWLEDGE_BASE,
        "ev-bare",
        correlation_refs=(),
    )

    agg = _make_aggregation_result("inv-uncorr", (ev_corr, ev_corr2, ev_bare))
    engine = IncidentCorrelationEngine()

    timeline = engine.build_timeline(agg)

    assert timeline.total_events == 3
    assert timeline.total_groups == 1
    assert "ev-bare" in [e.evidence_id for e in timeline.events]


# =========================================================================
# Determinism & Immutability Tests
# =========================================================================


def test_repeated_execution_is_exactly_deterministic() -> None:
    """Repeated timeline generation over identical input produces 100% equal output."""
    t0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
    ref = CorrelationReference(namespace="ticket", value="999")
    ev1 = _make_evidence(
        EvidenceSourceType.SUPEROFFICE_CRM,
        "ev-1",
        timestamp=t0,
        correlation_refs=(ref,),
    )
    ev2 = _make_evidence(
        EvidenceSourceType.MSSQL_DIAGNOSTICS,
        "ev-2",
        timestamp=t0,
        correlation_refs=(ref,),
    )

    agg = _make_aggregation_result("inv-det", (ev1, ev2))
    engine = IncidentCorrelationEngine()

    run1 = engine.build_timeline(agg)
    run2 = engine.build_timeline(agg)

    assert run1 == run2


def test_input_evidence_and_confidence_unmodified() -> None:
    """Engine does not mutate input EvidenceAggregationResult or modify confidence scores."""
    ref = CorrelationReference(namespace="ticket", value="500")
    ev = _make_evidence(
        EvidenceSourceType.SUPEROFFICE_CRM,
        "ev-orig",
        confidence=0.75,
        correlation_refs=(ref,),
        data={"sensitive": "dont_inspect"},
    )
    agg = _make_aggregation_result("inv-immut", (ev,))
    engine = IncidentCorrelationEngine()

    timeline = engine.build_timeline(agg)

    # Input object attributes unchanged
    assert ev.confidence_score == 0.75
    assert ev.data == {"sensitive": "dont_inspect"}
    assert agg.investigation_id == "inv-immut"
    assert len(timeline.events) == 1


def test_source_failures_do_not_become_timeline_events() -> None:
    """Blocked/failed source outcomes in aggregation result do not create events or groups."""
    ev_real = _make_evidence(EvidenceSourceType.SUPEROFFICE_CRM, "ev-real")
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
        evidence=(ev_real,),
        other_outcomes=(outcome_blocked, outcome_failed),
    )
    engine = IncidentCorrelationEngine()

    timeline = engine.build_timeline(agg)

    assert timeline.total_events == 1
    assert timeline.events[0].evidence_id == "ev-real"
    assert timeline.total_groups == 0


def test_build_timeline_validates_input_type_and_id() -> None:
    """build_timeline rejects non-EvidenceAggregationResult and empty investigation_id."""
    engine = IncidentCorrelationEngine()

    with pytest.raises(DomainValidationError):
        engine.build_timeline("not_an_aggregation_result")  # type: ignore[arg-type]

    bad_agg = EvidenceAggregationResult(
        investigation_id="",
        correlation_key="valid-key",
        source_outcomes=(),
    )
    with pytest.raises(DomainValidationError):
        engine.build_timeline(bad_agg)
