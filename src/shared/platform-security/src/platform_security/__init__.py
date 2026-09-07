"""Platform Security package providing security contracts, authorization gates, and sanitization."""

from platform_core.errors import AuthenticationError, AuthorizationError, SecurityError
from platform_security.interfaces import (
    AttachmentPolicy,
    Authenticator,
    Authorizer,
    OutputSanitizer,
    PIIFilter,
    PolicyEngine,
)
from platform_security.jwt import JwtAuthenticator
from platform_security.models import (
    AttachmentMetadata,
    AuthorizationDecision,
    PIIRedactionResult,
    SecurityContext,
)
from platform_security.rate_limiting import (
    RateLimitPolicy,
    SlidingWindowRateLimiter,
    format_rate_limit_key,
)
from platform_security.rbac import (
    RbacPolicySchema,
    ToolPermissionRule,
    YamlPolicyEngine,
)
from platform_security.sanitization import (
    RecursiveOutputSanitizer,
    RegexPIIFilter,
)

__all__ = [
    "AttachmentMetadata",
    "AttachmentPolicy",
    "AuthenticationError",
    "Authenticator",
    "AuthorizationDecision",
    "AuthorizationError",
    "Authorizer",
    "JwtAuthenticator",
    "OutputSanitizer",
    "PIIFilter",
    "PIIRedactionResult",
    "PolicyEngine",
    "RateLimitPolicy",
    "RbacPolicySchema",
    "RecursiveOutputSanitizer",
    "RegexPIIFilter",
    "SecurityContext",
    "SecurityError",
    "SlidingWindowRateLimiter",
    "ToolPermissionRule",
    "YamlPolicyEngine",
    "format_rate_limit_key",
]
