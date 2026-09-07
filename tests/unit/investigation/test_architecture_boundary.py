"""Architecture boundary regression tests for platform-investigation package."""

from pathlib import Path

import platform_investigation


def test_platform_investigation_has_no_forbidden_server_imports() -> None:
    """platform-investigation must not import server runtimes or external database libs."""
    forbidden_modules = [
        "so_mcp",
        "diag_mcp",
        "kb_mcp",
        "infra_mcp",
        "platform_gateway",
        "sqlalchemy",
        "aioodbc",
        "supabase",
    ]

    # Inspect all python files under platform-investigation
    investigation_pkg_dir = (
        Path(__file__).parents[3]
        / "src"
        / "shared"
        / "platform-investigation"
        / "src"
        / "platform_investigation"
    )
    assert investigation_pkg_dir.exists(), f"Directory not found: {investigation_pkg_dir}"

    for py_file in investigation_pkg_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for forbidden in forbidden_modules:
            assert f"import {forbidden}" not in content, (
                f"Forbidden import '{forbidden}' found in {py_file.name}"
            )
            assert f"from {forbidden}" not in content, (
                f"Forbidden from-import '{forbidden}' found in {py_file.name}"
            )


def test_platform_investigation_public_exports() -> None:
    """Verify platform_investigation package exports expected public symbols cleanly."""
    expected_symbols = [
        "DiagnosticEvidence",
        "EvidenceSourceType",
        "Hypothesis",
        "HypothesisStatus",
        "InvestigationPlan",
        "InvestigationStatus",
        "InvestigationStep",
        "LogInvestigationResult",
        "EvidenceCollector",
        "DiagnosticLogCollector",
        "InvestigationOrchestrator",
        "InvestigationOrchestratorEngine",
        "InvestigationStore",
        "InMemoryInvestigationStore",
        "InvestigationError",
        "InvestigationNotFoundError",
        "InvalidInvestigationStateError",
        "StepLimitExceededError",
        "HypothesisNotFoundError",
        "SourceCollectionStatus",
        "SourceCollectionResult",
        "EvidenceAggregationResult",
        "OutcomeAwareEvidenceCollector",
        "EvidenceAggregator",
        "EvidenceAggregatorEngine",
        "DuplicateEvidenceIdError",
        "EvidenceProvenanceMismatchError",
        "CorrelationReference",
        "TimelineEvent",
        "CorrelationGroup",
        "InvestigationTimeline",
        "IncidentCorrelator",
        "IncidentCorrelationEngine",
        "HypothesisEvaluationOutcome",
        "HypothesisEvaluationResult",
        "HypothesisEvaluator",
        "HypothesisEvaluatorEngine",
    ]

    for symbol in expected_symbols:
        assert hasattr(platform_investigation, symbol), (
            f"Symbol '{symbol}' not exported from platform_investigation"
        )


def test_aggregator_does_not_depend_on_or_mutate_orchestrator() -> None:
    """EvidenceAggregatorEngine must not import or call InvestigationOrchestrator state machine."""
    aggregator_file = (
        Path(__file__).parents[3]
        / "src"
        / "shared"
        / "platform-investigation"
        / "src"
        / "platform_investigation"
        / "aggregator.py"
    )
    content = aggregator_file.read_text(encoding="utf-8")
    assert "import orchestrator" not in content
    assert "from platform_investigation.orchestrator" not in content
    assert "advance_step" not in content
    assert "create_plan" not in content
    assert "conclude_investigation" not in content


def test_timeline_engine_does_not_depend_on_or_mutate_orchestrator() -> None:
    """IncidentCorrelationEngine must not import or call InvestigationOrchestrator state machine."""
    timeline_file = (
        Path(__file__).parents[3]
        / "src"
        / "shared"
        / "platform-investigation"
        / "src"
        / "platform_investigation"
        / "timeline.py"
    )
    content = timeline_file.read_text(encoding="utf-8")
    assert "import orchestrator" not in content
    assert "from platform_investigation.orchestrator" not in content
    assert "advance_step" not in content
    assert "create_plan" not in content
    assert "conclude_investigation" not in content


def test_evaluator_engine_does_not_depend_on_or_mutate_orchestrator() -> None:
    """HypothesisEvaluatorEngine must not import or call InvestigationOrchestrator state machine."""
    evaluator_file = (
        Path(__file__).parents[3]
        / "src"
        / "shared"
        / "platform-investigation"
        / "src"
        / "platform_investigation"
        / "evaluator.py"
    )
    content = evaluator_file.read_text(encoding="utf-8")
    assert "import orchestrator" not in content
    assert "from platform_investigation.orchestrator" not in content
    assert "advance_step" not in content
    assert "create_plan" not in content
    assert "conclude_investigation" not in content
