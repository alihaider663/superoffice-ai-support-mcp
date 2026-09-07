"""Deterministic PII scrubbing, secret redaction, and recursive output sanitization."""

import re
from typing import Any

from platform_security.interfaces import OutputSanitizer, PIIFilter
from platform_security.models import PIIRedactionResult

# Common sensitive dictionary keys that must always be masked
SENSITIVE_KEY_PATTERNS = {
    "password",
    "pwd",
    "secret",
    "client_secret",
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "auth_token",
    "jwt",
    "authorization",
    "private_key",
    "privatekey",
    "db_password",
    "database_password",
    "service_key",
}

# Compiled regex patterns for deterministic text redaction
_RE_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    re.MULTILINE,
)
_RE_JWT = re.compile(r"\beyJ[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}\b")
_RE_BEARER_TOKEN = re.compile(
    r"\bBearer\s+([A-Za-z0-9\-_.~+/]+=*)\b",
    re.IGNORECASE,
)
_RE_API_KEY = re.compile(
    r"\b(?:sk|pk|api|key|ghp|gho)_[A-Za-z0-9_\-]{16,}\b",
    re.IGNORECASE,
)
_RE_CREDIT_CARD = re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b")
_RE_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_RE_NORDIC_ID = re.compile(r"\b\d{6}[- ]\d{5}\b")
_RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_RE_PHONE = re.compile(r"(?:\+\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?){2,4}\d{2,4}\b")
_RE_INLINE_SECRET = re.compile(
    r"(?i)\b(password|secret|pwd|api_key|token)\s*[:=]\s*['\"]?([^\s'\";,]{3,})['\"]?"
)


class RegexPIIFilter(PIIFilter):
    """Deterministic regex-based PII and secret scanner."""

    def _redact_patterns(self, text: str) -> tuple[str, int, set[str]]:
        """Apply sequential regex replacements for sensitive patterns."""
        categories: set[str] = set()
        count = 0
        current = text

        rules: list[tuple[re.Pattern[str], str, str]] = [
            (_RE_PRIVATE_KEY, "[REDACTED_PRIVATE_KEY]", "private_key"),
            (_RE_JWT, "[REDACTED_JWT]", "jwt"),
            (_RE_BEARER_TOKEN, "Bearer [REDACTED_TOKEN]", "bearer_token"),
            (_RE_API_KEY, "[REDACTED_API_KEY]", "api_key"),
            (_RE_CREDIT_CARD, "[REDACTED_CARD]", "credit_card"),
            (_RE_SSN, "[REDACTED_SSN]", "national_id"),
            (_RE_NORDIC_ID, "[REDACTED_NATIONAL_ID]", "national_id"),
            (_RE_EMAIL, "[REDACTED_EMAIL]", "email"),
        ]

        for pattern, replacement, category in rules:
            matches = list(pattern.finditer(current))
            if matches:
                count += len(matches)
                categories.add(category)
                current = pattern.sub(replacement, current)

        inline_matches = list(_RE_INLINE_SECRET.finditer(current))
        if inline_matches:
            count += len(inline_matches)
            categories.add("inline_secret")
            current = _RE_INLINE_SECRET.sub(r"\1=[REDACTED_SECRET]", current)

        phone_matches = [
            m for m in _RE_PHONE.finditer(current) if sum(c.isdigit() for c in m.group(0)) >= 7
        ]
        if phone_matches:
            count += len(phone_matches)
            categories.add("phone_number")
            for m in reversed(phone_matches):
                start, end = m.span()
                current = current[:start] + "[REDACTED_PHONE]" + current[end:]

        return current, count, categories

    def redact(self, text: str) -> PIIRedactionResult:
        """Scan input string and replace sensitive PII/secrets with redaction tokens."""
        if not text:
            return PIIRedactionResult(
                sanitized_text="",
                redactions_count=0,
                redacted_categories=(),
            )

        sanitized_text, count, categories = self._redact_patterns(text)

        return PIIRedactionResult(
            sanitized_text=sanitized_text,
            redactions_count=count,
            redacted_categories=tuple(sorted(categories)),
        )


class RecursiveOutputSanitizer(OutputSanitizer):
    """Deep inspection and sanitization engine for arbitrary nested JSON data structures."""

    def __init__(self, pii_filter: PIIFilter | None = None) -> None:
        self.pii_filter = pii_filter or RegexPIIFilter()

    def sanitize(self, payload: Any) -> Any:
        """Deeply traverse nested payloads, masking sensitive dictionary keys and string PII."""
        if payload is None or isinstance(payload, (int, float, bool)):
            return payload

        if isinstance(payload, str):
            return self.pii_filter.redact(payload).sanitized_text

        if isinstance(payload, dict):
            sanitized_dict: dict[str, Any] = {}
            for k, v in payload.items():
                str_key = str(k)
                norm_key = str_key.lower().replace("-", "_").strip()
                if norm_key in SENSITIVE_KEY_PATTERNS or any(
                    norm_key.endswith(f"_{s}") for s in SENSITIVE_KEY_PATTERNS
                ):
                    sanitized_dict[str_key] = "[REDACTED_SECRET]"
                else:
                    sanitized_dict[str_key] = self.sanitize(v)
            return sanitized_dict

        if isinstance(payload, (list, tuple)):
            sanitized_seq = [self.sanitize(item) for item in payload]
            return tuple(sanitized_seq) if isinstance(payload, tuple) else sanitized_seq

        if hasattr(payload, "model_dump") and callable(payload.model_dump):
            return self.sanitize(payload.model_dump())

        return self.pii_filter.redact(str(payload)).sanitized_text
