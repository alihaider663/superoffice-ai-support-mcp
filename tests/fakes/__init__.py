"""Deterministic in-memory test fakes for offline contract testing."""

from tests.fakes.fake_diagnostic_repository import FakeDiagnosticRepository
from tests.fakes.fake_gateway_dispatcher import FakeGatewayDispatcher
from tests.fakes.fake_knowledge_repository import FakeKnowledgeRepository
from tests.fakes.fake_log_search_client import FakeLogSearchClient
from tests.fakes.fake_superoffice_client import FakeSuperOfficeClient

__all__ = [
    "FakeDiagnosticRepository",
    "FakeGatewayDispatcher",
    "FakeKnowledgeRepository",
    "FakeLogSearchClient",
    "FakeSuperOfficeClient",
]
