"""Secret detection and PII redaction security boundary for knowledge ingestion (Gate 7D.5B)."""

import re
from dataclasses import dataclass
from typing import Final

from kb_mcp.contracts.constants import MAX_REDACTABLE_PII_OCCURRENCES
from kb_mcp.contracts.ingestion import AdmissionReasonCode

# ============================================================================
# Safe Documentation Placeholder Heuristics
# ============================================================================

_RE_PLACEHOLDER_TAG: Final[re.Pattern[str]] = re.compile(r"^<[A-Za-z0-9_ -]+>$")
_RE_PLACEHOLDER_VAR: Final[re.Pattern[str]] = re.compile(
    r"^\$\{[A-Za-z0-9_]+\}$|^\{\{[A-Za-z0-9_]+\}\}$"
)
_RE_PLACEHOLDER_PREFIX: Final[re.Pattern[str]] = re.compile(
    r"^(?:YOUR|MY|SAMPLE|EXAMPLE|DUMMY|TEST|FAKE|DEFAULT)_[A-Za-z0-9_]+$",
    re.IGNORECASE,
)
_SAFE_PLACEHOLDER_WORDS: Final[set[str]] = {
    "example-token",
    "example_token",
    "sample-token",
    "sample_token",
    "replace_me",
    "replaceme",
    "change_me",
    "changeme",
    "placeholder",
    "dummy",
    "fake",
    "password",
    "secret",
    "token",
    "none",
    "null",
    "undefined",
    "todo",
    "sample",
    "xxx",
    "xxxx",
    "...",
}


def is_safe_placeholder(value: str) -> bool:
    """Return True if the extracted secret candidate is a synthetic documentation placeholder."""
    cleaned = value.strip().strip("'\"")
    if not cleaned:
        return True
    lower = cleaned.lower()
    if lower in _SAFE_PLACEHOLDER_WORDS:
        return True
    if _RE_PLACEHOLDER_TAG.match(cleaned):
        return True
    if _RE_PLACEHOLDER_VAR.match(cleaned):
        return True
    return bool(_RE_PLACEHOLDER_PREFIX.match(cleaned))


# ============================================================================
# Secret Detection Regex Patterns
# ============================================================================

# PEM Private Keys (any variant)
_RE_PEM_PRIVATE_KEY: Final[re.Pattern[str]] = re.compile(
    r"-----BEGIN\s+(?:[A-Za-z0-9_-]+\s+)?PRIVATE\s+KEY-----",
    re.IGNORECASE,
)

# JWT: 3 base64url segments starting with eyJ
_RE_JWT: Final[re.Pattern[str]] = re.compile(
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)

# Bearer token
_RE_BEARER: Final[re.Pattern[str]] = re.compile(
    r"\bBearer\s+([A-Za-z0-9\-_.~+/]{12,}=*)\b",
    re.IGNORECASE,
)

# Credential-bearing URI / DSN
_RE_CREDENTIAL_URI: Final[re.Pattern[str]] = re.compile(
    r"\b[a-zA-Z][a-zA-Z0-9+.-]*://([^:\s@]+):([^@\s]+)@"
)

# Connection string password assignments
_RE_CONN_STRING_PWD: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:password|pwd)\s*=\s*([^;\s'\"]+)"
)

# Code / config secret assignment with : or = separator
_RE_SECRET_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(password|passwd|pwd|api_key|apikey|client_secret|access_token|secret)\s*[:=]\s*['\"]?([^\s'\";,]+)['\"]?"
)

# Secret assignment with whitespace separator (where safely recognized)
_RE_SECRET_WHITESPACE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(password|passwd|pwd|api_key|apikey|client_secret|access_token|secret)\s+['\"]?([^\s'\";,]+)['\"]?"
)

# Known API key / token prefixes
_RE_API_KEY_PREFIX: Final[re.Pattern[str]] = re.compile(
    r"\b(?:sk|pk|ghp|gho|ghu|ghs|glpat|xoxb|xoxp)_[A-Za-z0-9_\-]{16,}\b",
    re.IGNORECASE,
)


def is_substantive_secret_token(value: str) -> bool:
    """Return True if candidate token in whitespace context represents a substantive secret."""
    cleaned = value.strip().strip("'\"")
    if not cleaned or is_safe_placeholder(cleaned):
        return False
    if _RE_API_KEY_PREFIX.search(cleaned):
        return True
    has_alpha = any(c.isalpha() for c in cleaned)
    has_digit = any(c.isdigit() for c in cleaned)
    if has_alpha and has_digit and len(cleaned) >= 8:
        return True
    special_chars = set("!@#$%^&*()_+-=[]{}|;:,.<>?")
    if any(c in special_chars for c in cleaned) and len(cleaned) >= 8:
        return True
    return len(cleaned) >= 16


# ============================================================================
# PII Detection Regex Patterns
# ============================================================================

# Email address
_RE_EMAIL: Final[re.Pattern[str]] = re.compile(
    r"\b([A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,}))\b"
)

# Exempt documentation email domains
_EXEMPT_EMAIL_DOMAINS: Final[set[str]] = {
    "example.com",
    "example.org",
    "example.net",
}

# Phone numbers (at least 7 digits, bounded separators)
_RE_PHONE: Final[re.Pattern[str]] = re.compile(
    r"(?:\+\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?){2,4}\d{2,4}\b"
)

# US SSN
_RE_SSN: Final[re.Pattern[str]] = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# Nordic National ID
_RE_NORDIC_ID: Final[re.Pattern[str]] = re.compile(r"\b\d{6}[- ]\d{5}\b")

# Strongly labelled personal IDs
_RE_LABELLED_ID: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b("
    r"personal[_\s]?(?:id|identity)(?:[_\s]?number)?"
    r"|national[_\s]?(?:id|identity)(?:[_\s]?number)?"
    r"|identity[_\s]?number"
    r"|customer[_\s]?(?:id[_\s]?number|personal[_\s]?id)"
    r"|passport[_\s]?(?:no|number)"
    r"|ssn"
    r")\s*[:=]\s*([A-Za-z0-9-]+)\b"
)

# Date pattern to exclude false positive phones (e.g. 2026-09-08)
_RE_DATE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ============================================================================
# Sanitization Outcome Models
# ============================================================================


@dataclass(frozen=True)
class SanitizationOutcome:
    """Outcome of secret and PII sanitization pass."""

    is_admissible: bool
    sanitized_text: str = ""
    pii_count: int = 0
    reason_code: AdmissionReasonCode | None = None
    message: str = ""


class KnowledgeSanitizer:
    """Security boundary scanner that rejects real secrets and redacts incidental PII."""

    def contains_secret(self, text: str) -> bool:
        """Scan text for real credentials or secrets; returns True if detected."""
        if not text:
            return False

        return (
            self._has_private_key_or_jwt(text)
            or self._has_unmasked_token_or_credential(text)
            or self._has_secret_assignment(text)
        )

    def _has_private_key_or_jwt(self, text: str) -> bool:
        """Check for PEM private keys, JWTs, or explicit API key prefixes."""
        if _RE_PEM_PRIVATE_KEY.search(text):
            return True
        if _RE_JWT.search(text):
            return True
        return bool(_RE_API_KEY_PREFIX.search(text))

    def _has_unmasked_token_or_credential(self, text: str) -> bool:
        """Check for unmasked bearer tokens, credential URIs, or connection strings."""
        for match in _RE_BEARER.finditer(text):
            if not is_safe_placeholder(match.group(1)):
                return True

        for match in _RE_CREDENTIAL_URI.finditer(text):
            if not is_safe_placeholder(match.group(2)):
                return True

        for match in _RE_CONN_STRING_PWD.finditer(text):
            if not is_safe_placeholder(match.group(1)):
                return True

        return False

    def _has_secret_assignment(self, text: str) -> bool:
        """Check for code or configuration secret assignments."""
        for match in _RE_SECRET_ASSIGNMENT.finditer(text):
            if not is_safe_placeholder(match.group(2)):
                return True

        for match in _RE_SECRET_WHITESPACE.finditer(text):
            if is_substantive_secret_token(match.group(2)):
                return True

        return False

    def contains_pii(self, text: str) -> bool:
        """Scan text for PII (email, phone, national ID); returns True if non-exempt PII exists."""
        if not text:
            return False

        # Check emails (accounting for documentation exemptions)
        for match in _RE_EMAIL.finditer(text):
            domain = match.group(2).lower()
            if not self._is_exempt_domain(domain):
                return True

        # Check personal IDs
        if _RE_SSN.search(text) or _RE_NORDIC_ID.search(text) or _RE_LABELLED_ID.search(text):
            return True

        # Check phone numbers
        for match in _RE_PHONE.finditer(text):
            val = match.group(0)
            if self._is_real_phone(val):
                return True

        return False

    def _is_exempt_domain(self, domain: str) -> bool:
        """Return True if the domain is an exempt documentation domain."""
        return domain in _EXEMPT_EMAIL_DOMAINS or any(
            domain.endswith(f".{exempt}") for exempt in _EXEMPT_EMAIL_DOMAINS
        )

    def _is_real_phone(self, text: str) -> bool:
        """Validate if matching string is an apparent phone number rather than a date or version."""
        stripped = text.strip()
        if _RE_DATE.match(stripped):
            return False
        digits = [c for c in stripped if c.isdigit()]
        if len(digits) < 7 or len(digits) > 15:
            return False
        # If it looks like a dotted version (e.g. 10.2.1.0), skip
        return not (
            stripped.count(".") >= 2 and all(part.isdigit() for part in stripped.split("."))
        )

    def sanitize_free_text(self, text: str) -> tuple[str, int, AdmissionReasonCode | None, str]:
        """Scan and sanitize free-text string.

        Enforces:
        1. Secret check -> fails closed if secret found.
        2. Bounded PII redaction -> replaces with placeholders.
        3. Mass-PII check -> fails closed if total findings > 10.

        Returns: (sanitized_text, pii_count, reason_code, message)
        """
        if not text:
            return "", 0, None, ""

        # Step 1: Secret detection (Fail-closed)
        if self.contains_secret(text):
            return (
                "",
                0,
                AdmissionReasonCode.SECRET_DETECTED,
                "Secret or credential detected in text content.",
            )

        # Step 2: PII Redaction
        pii_count = 0
        current = text

        # Redact non-exempt emails
        def replace_email(match: re.Match[str]) -> str:
            nonlocal pii_count
            domain = match.group(2).lower()
            if self._is_exempt_domain(domain):
                return match.group(0)
            pii_count += 1
            return "<EMAIL_REDACTED>"

        current = _RE_EMAIL.sub(replace_email, current)

        # Redact SSN
        ssn_matches = list(_RE_SSN.finditer(current))
        if ssn_matches:
            pii_count += len(ssn_matches)
            current = _RE_SSN.sub("<ID_REDACTED>", current)

        # Redact Nordic ID
        nordic_matches = list(_RE_NORDIC_ID.finditer(current))
        if nordic_matches:
            pii_count += len(nordic_matches)
            current = _RE_NORDIC_ID.sub("<ID_REDACTED>", current)

        # Redact Labelled IDs
        def replace_labelled_id(match: re.Match[str]) -> str:
            nonlocal pii_count
            pii_count += 1
            prefix = match.group(0)[: match.start(2) - match.start(0)]
            return f"{prefix}<ID_REDACTED>"

        current = _RE_LABELLED_ID.sub(replace_labelled_id, current)

        # Redact Phone numbers (in reverse order to preserve indices)
        phone_matches = [m for m in _RE_PHONE.finditer(current) if self._is_real_phone(m.group(0))]
        if phone_matches:
            pii_count += len(phone_matches)
            for m in reversed(phone_matches):
                start, end = m.span()
                current = current[:start] + "<PHONE_REDACTED>" + current[end:]

        # Step 3: Mass PII threshold check
        if pii_count > MAX_REDACTABLE_PII_OCCURRENCES:
            return (
                "",
                pii_count,
                AdmissionReasonCode.PII_DETECTED,
                (
                    f"Mass PII detected: {pii_count} occurrences exceeds maximum allowed "
                    f"limit of {MAX_REDACTABLE_PII_OCCURRENCES}."
                ),
            )

        return current, pii_count, None, ""

    def check_identity_field(
        self,
        value: str | None,
        _field_name: str = "",
    ) -> AdmissionReasonCode | None:
        """Validate that an identity/provenance field contains neither secrets nor PII.

        Identity fields cannot be redacted; any secret or PII presence rejects the source.
        """
        if not value:
            return None

        if self.contains_secret(value):
            return AdmissionReasonCode.SECRET_DETECTED

        if self.contains_pii(value):
            return AdmissionReasonCode.PII_DETECTED

        return None
