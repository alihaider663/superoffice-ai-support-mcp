"""Deterministic incident correlation and investigation timeline runtime."""

from platform_core.errors import DomainValidationError
from platform_investigation.interfaces import IncidentCorrelator
from platform_investigation.models import (
    CorrelationGroup,
    CorrelationReference,
    EvidenceAggregationResult,
    InvestigationTimeline,
    TimelineEvent,
)
from platform_observability.logging import get_logger

logger = get_logger(__name__)


class IncidentCorrelationEngine(IncidentCorrelator):
    """Deterministic, pure synchronous incident correlation and timeline engine.

    Enforces:
    - Pure in-memory transformation over EvidenceAggregationResult.
    - Lightweight TimelineEvent projection (preserves metadata, omits data payload).
    - Stable chronological event sorting (timestamp ASC; stable aggregate order on tie).
    - Explicit, typed CorrelationReference matching (exact namespace + value equality).
    - Non-transitive correlation grouping (no multi-hop cluster merging).
    - Distinct-evidence threshold: CorrelationGroup created only when >= 2 distinct items share ref.
    - Deterministic group ordering by first appearance of reference in aggregate evidence order.
    - Complete input immutability (input models are never mutated).
    """

    def build_timeline(
        self,
        aggregation_result: EvidenceAggregationResult,
    ) -> InvestigationTimeline:
        """Build a deterministic timeline and correlation groups from aggregated evidence."""
        if not isinstance(aggregation_result, EvidenceAggregationResult):
            raise DomainValidationError(
                "aggregation_result must be an instance of EvidenceAggregationResult.",
                field_name="aggregation_result",
            )
        inv_id = aggregation_result.investigation_id
        if not inv_id or not inv_id.strip():
            raise DomainValidationError(
                "aggregation_result.investigation_id cannot be empty.",
                field_name="investigation_id",
            )

        evidence = aggregation_result.evidence

        # 1. Project evidence items into lightweight TimelineEvent representations
        events: list[TimelineEvent] = [
            TimelineEvent(
                evidence_id=ev.evidence_id,
                source_type=ev.source_type,
                timestamp=ev.timestamp,
                title=ev.title,
                correlation_references=ev.correlation_references,
                tags=ev.tags,
            )
            for ev in evidence
        ]

        # 2. Sort chronologically (timestamp ASC).
        # Python's Timsort is stable; equal timestamps preserve original aggregate sequence order.
        sorted_events = sorted(events, key=lambda e: e.timestamp)

        # 3. Index correlation references across evidence items
        # Uses internal immutable key (namespace, value) for indexing.
        # Dict preserves insertion order (first appearance of reference in aggregate order).
        # Distinct evidence IDs are tracked defensively to ensure true cardinality.
        ref_index: dict[tuple[str, str], tuple[CorrelationReference, list[str], set[str]]] = {}

        for ev in evidence:
            for ref in ev.correlation_references:
                key = (ref.namespace, ref.value)
                if key not in ref_index:
                    ref_index[key] = (ref, [], set())
                _, ids_list, ids_set = ref_index[key]
                if ev.evidence_id not in ids_set:
                    ids_set.add(ev.evidence_id)
                    ids_list.append(ev.evidence_id)

        # 4. Filter for correlation groups meeting the >= 2 distinct evidence items threshold
        groups: list[CorrelationGroup] = [
            CorrelationGroup(
                correlation_reference=ref,
                evidence_ids=tuple(ids_list),
            )
            for ref, ids_list, _ in ref_index.values()
            if len(ids_list) >= 2
        ]

        timeline = InvestigationTimeline(
            investigation_id=inv_id.strip(),
            events=tuple(sorted_events),
            correlation_groups=tuple(groups),
        )

        logger.info(
            "Investigation timeline constructed",
            investigation_id=timeline.investigation_id,
            evidence_count=len(evidence),
            timeline_event_count=timeline.total_events,
            correlation_group_count=timeline.total_groups,
        )
        return timeline
