"""Unit tests for RegexPIIFilter and RecursiveOutputSanitizer."""

import pytest

from platform_security.sanitization import (
    RecursiveOutputSanitizer,
    RegexPIIFilter,
)


@pytest.fixture
def pii_filter() -> RegexPIIFilter:
    return RegexPIIFilter()


@pytest.fixture
def sanitizer() -> RecursiveOutputSanitizer:
    return RecursiveOutputSanitizer()


def test_regex_pii_filter_empty_and_safe_text(pii_filter: RegexPIIFilter) -> None:
    res_empty = pii_filter.redact("")
    assert res_empty.sanitized_text == ""
    assert res_empty.redactions_count == 0

    safe_text = "Ticket #12345: Database index scan slow on table ticket_log. Status: OPEN."
    res_safe = pii_filter.redact(safe_text)
    assert res_safe.sanitized_text == safe_text
    assert res_safe.redactions_count == 0
    assert res_safe.redacted_categories == ()


def test_regex_pii_filter_redacts_private_keys(pii_filter: RegexPIIFilter) -> None:
    text = (
        "Server config loaded. Private key:\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA0Y1+5v678...\n"
        "-----END RSA PRIVATE KEY-----\n"
        "Process started."
    )
    result = pii_filter.redact(text)
    assert "-----BEGIN RSA PRIVATE KEY-----" not in result.sanitized_text
    assert "[REDACTED_PRIVATE_KEY]" in result.sanitized_text
    assert "private_key" in result.redacted_categories
    assert result.redactions_count >= 1


def test_regex_pii_filter_redacts_jwt_and_bearer_tokens(pii_filter: RegexPIIFilter) -> None:
    jwt_token = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    text = f"User authenticated with Bearer {jwt_token}. Query executed."
    result = pii_filter.redact(text)
    assert jwt_token not in result.sanitized_text
    assert (
        "Bearer [REDACTED_TOKEN]" in result.sanitized_text
        or "[REDACTED_JWT]" in result.sanitized_text
    )
    assert result.redactions_count >= 1


def test_regex_pii_filter_redacts_api_keys(pii_filter: RegexPIIFilter) -> None:
    text = (
        "Connecting with OpenAI key sk-1234567890abcdef1234567890 "
        "and github token ghp_1234567890abcdef123456."
    )
    result = pii_filter.redact(text)
    assert "sk-1234567890abcdef1234567890" not in result.sanitized_text
    assert "ghp_1234567890abcdef123456" not in result.sanitized_text
    assert "[REDACTED_API_KEY]" in result.sanitized_text
    assert "api_key" in result.redacted_categories


def test_regex_pii_filter_redacts_credit_cards(pii_filter: RegexPIIFilter) -> None:
    text = "Payment failed for card 4111-2222-3333-4444 and 5500 0000 1111 2222."
    result = pii_filter.redact(text)
    assert "4111-2222-3333-4444" not in result.sanitized_text
    assert "5500 0000 1111 2222" not in result.sanitized_text
    assert "[REDACTED_CARD]" in result.sanitized_text
    assert "credit_card" in result.redacted_categories


def test_regex_pii_filter_redacts_national_ids(pii_filter: RegexPIIFilter) -> None:
    text = "Customer SSN is 123-45-6789 and Nordic CPR is 123456-12345."
    result = pii_filter.redact(text)
    assert "123-45-6789" not in result.sanitized_text
    assert "123456-12345" not in result.sanitized_text
    assert "[REDACTED_SSN]" in result.sanitized_text
    assert "[REDACTED_NATIONAL_ID]" in result.sanitized_text
    assert "national_id" in result.redacted_categories


def test_regex_pii_filter_redacts_emails(pii_filter: RegexPIIFilter) -> None:
    text = "Contact customer at john.doe@example.com or support@superoffice.internal."
    result = pii_filter.redact(text)
    assert "john.doe@example.com" not in result.sanitized_text
    assert "[REDACTED_EMAIL]" in result.sanitized_text
    assert "email" in result.redacted_categories


def test_regex_pii_filter_redacts_phone_numbers(pii_filter: RegexPIIFilter) -> None:
    text = "Customer called from +47 22 33 44 55 and fallback +1 (555) 123-4567."
    result = pii_filter.redact(text)
    assert "+47 22 33 44 55" not in result.sanitized_text
    assert "+1 (555) 123-4567" not in result.sanitized_text
    assert "[REDACTED_PHONE]" in result.sanitized_text
    assert "phone_number" in result.redacted_categories


def test_recursive_output_sanitizer_masks_sensitive_dict_keys(
    sanitizer: RecursiveOutputSanitizer,
) -> None:
    payload = {
        "user": "support_agent_1",
        "password": "SuperSecretPassword123!",
        "db_password": "AnotherSecretPassword!",
        "api_key": "some_api_key_value",
        "nested": {
            "client_secret": "xyz_secret",
            "token": "token_abc",
        },
    }
    sanitized = sanitizer.sanitize(payload)
    assert sanitized["user"] == "support_agent_1"
    assert sanitized["password"] == "[REDACTED_SECRET]"
    assert sanitized["db_password"] == "[REDACTED_SECRET]"
    assert sanitized["api_key"] == "[REDACTED_SECRET]"
    assert sanitized["nested"]["client_secret"] == "[REDACTED_SECRET]"
    assert sanitized["nested"]["token"] == "[REDACTED_SECRET]"


def test_recursive_output_sanitizer_deep_nested_structures(
    sanitizer: RecursiveOutputSanitizer,
) -> None:
    payload = {
        "status": "SUCCESS",
        "records": [
            {
                "id": 101,
                "message": "User alice@corp.com updated ticket with phone +47 99 88 77 66",
            },
            {
                "id": 102,
                "message": "System note: safe message with no PII.",
            },
        ],
        "tuple_data": ("secret_user@domain.com", 42, True),
    }
    sanitized = sanitizer.sanitize(payload)
    assert "alice@corp.com" not in sanitized["records"][0]["message"]
    assert "[REDACTED_EMAIL]" in sanitized["records"][0]["message"]
    assert "[REDACTED_PHONE]" in sanitized["records"][0]["message"]
    assert sanitized["records"][1]["message"] == "System note: safe message with no PII."
    assert sanitized["tuple_data"][0] == "[REDACTED_EMAIL]"
    assert sanitized["tuple_data"][1] == 42
    assert sanitized["tuple_data"][2] is True
