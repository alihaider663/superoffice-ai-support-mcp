"""Global pytest configuration and shared offline test fixtures."""

import pytest

from platform_core.models import PrincipalIdentity
from platform_security.models import SecurityContext


@pytest.fixture
def sample_principal() -> PrincipalIdentity:
    """Fixture providing a standard test principal."""
    return PrincipalIdentity(
        user_id="test-agent-001",
        role="SupportEngineer_L2",
        scopes=("read:tickets", "read:logs", "read:kb"),
    )


@pytest.fixture
def sample_security_context(sample_principal: PrincipalIdentity) -> SecurityContext:
    """Fixture providing an authenticated security context."""
    return SecurityContext(
        principal=sample_principal,
        token_id="test-token-uuid-12345",
        is_authenticated=True,
    )
